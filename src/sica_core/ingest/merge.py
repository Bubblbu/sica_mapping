"""Merge raw_buildings + raw_addresses into buildings + landlords.

Ports the address-matching/dedup logic from `src/sica_mapping/data/spatial.py`
(select_west_end_buildings + join_buildings_addresses + deduplicate_buildings)
against data already sitting in SQLite, with two deliberate deviations from v1:

1. `_parse_money()` replaces a bare `pd.to_numeric(errors="coerce")` for
   value_land/value_bldg. The source mixes plain numbers with
   "$35,407,000.00"-style strings — 100% of West End rows use the latter
   format, and the naive cast silently nulls all of them in v1 today.
2. No `allowed_areas` filter, ever. `local_area` is kept as a plain column;
   scope-narrowing is deferred to query/export time, matching the fact that
   buildings.csv is already city-wide, not West-End-scoped.

Also assigns `block_id` (point-in-polygon against `blocks`, forked from
`point_in_block_ids`'s STRtree logic) and upserts `landlords` — neither of
which have a home anywhere else in the ingest sequence.
"""

from __future__ import annotations

import json
import math
import sqlite3
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from shapely.geometry import Point
from shapely.strtree import STRtree

from ..geometry import parse_geom
from ..normalize import (
    addr_key_from_freeform,
    clean_owner_label,
    normalize_street,
    parse_lat_lon,
    sanitize_owner,
)

OWNER_CANDIDATES = [
    "bsns_group",
    "business_group",
    "owner_group",
    "owner",
    "ownership_group",
]


def _parse_money(raw: object) -> float | None:
    """'$35,407,000.00' / '5343000' / '' / None -> float or None."""
    if raw is None:
        return None
    if isinstance(raw, float) and math.isnan(raw):
        return None
    s = str(raw).strip().replace("$", "").replace(",", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def load_raw_frames(conn: sqlite3.Connection) -> tuple[pd.DataFrame, pd.DataFrame]:
    raw_buildings = pd.read_sql_query("SELECT * FROM raw_buildings", conn)
    raw_addresses = pd.read_sql_query("SELECT * FROM raw_addresses", conn)
    return raw_buildings, raw_addresses


def _prepare_addresses(addr_df: pd.DataFrame) -> pd.DataFrame:
    addr_df = addr_df.copy()
    addr_df[["lat", "lon"]] = addr_df["geo_point_2d"].apply(
        lambda s: pd.Series(parse_lat_lon(s))
    )
    addr_df["street_norm"] = addr_df["std_street"].map(
        lambda s: normalize_street(s) if pd.notna(s) else None
    )
    addr_df["civic_number_int"] = pd.to_numeric(
        addr_df["civic_number"], errors="coerce"
    )

    def _addr_key(row: pd.Series) -> str:
        street = row.get("std_street")
        civic = row.get("civic_number_int")
        if street is None or (isinstance(street, float) and pd.isna(street)):
            return addr_key_from_freeform("")
        if pd.isna(civic):
            return addr_key_from_freeform(str(street))
        if float(civic).is_integer():
            civic_str = str(int(civic))
        else:
            civic_str = str(civic).rstrip("0").rstrip(".")
        return addr_key_from_freeform(f"{civic_str} {street}")

    addr_df["addr_key"] = addr_df.apply(_addr_key, axis=1)
    return addr_df


def _select_buildings(bldg_df: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    df = bldg_df.copy()
    df["local_area"] = df["local_area"].fillna("(Unknown)")
    df["addr_key"] = df["address"].apply(addr_key_from_freeform)
    if "primary_address" in df.columns:
        df["addr_key_primary"] = df["primary_address"].apply(addr_key_from_freeform)
        df["addr_key_primary"] = df["addr_key_primary"].fillna(df["addr_key"])
    else:
        df["addr_key_primary"] = df["addr_key"]

    owner_col = next((c for c in OWNER_CANDIDATES if c in df.columns), None)
    if owner_col is None:
        owner_col = next(
            (c for c in df.columns if ("group" in c or "owner" in c)), None
        )
    if owner_col is None:
        owner_col = "bsns_group"
        df[owner_col] = "(Unknown)"
    return df, owner_col


def _join_buildings_addresses(west: pd.DataFrame, addr_df: pd.DataFrame) -> pd.DataFrame:
    addr_df = addr_df.copy()
    area_cols = [col for col in addr_df.columns if "local_area" in col]
    addr_cols = ["addr_key", "lat", "lon", "street_norm", "civic_number_int"] + [
        col for col in area_cols if col not in {"lat", "lon"}
    ]
    addr_lookup = addr_df[addr_cols].drop_duplicates("addr_key")

    joined = west.merge(addr_lookup, on="addr_key", how="left")
    rename_map = {"addr_key": "addr_key_primary", "lat": "lat_primary", "lon": "lon_primary"}
    for col in area_cols:
        rename_map[col] = f"{col}_primary"
    alt_lookup = addr_lookup.rename(columns=rename_map)
    joined = joined.merge(alt_lookup, on="addr_key_primary", how="left")
    joined["lat"] = joined["lat"].fillna(joined.pop("lat_primary"))
    joined["lon"] = joined["lon"].fillna(joined.pop("lon_primary"))
    for col in area_cols:
        primary_col = f"{col}_primary"
        if primary_col in joined.columns:
            joined[col] = joined[col].fillna(joined.pop(primary_col))

    if "local_area" not in joined.columns:
        joined["local_area"] = "(Unknown)"
    area_candidates = [
        col for col in area_cols if col in joined.columns and col != "local_area"
    ]
    if area_candidates:

        def _clean_area(val):
            if pd.isna(val):
                return None
            s = str(val).strip()
            return s or None

        area_values = joined[area_candidates].apply(
            lambda row: next(
                (c for c in (_clean_area(row[col]) for col in area_candidates) if c),
                None,
            ),
            axis=1,
        )
        local_area_series = joined["local_area"].apply(_clean_area)
        mask_unknown = local_area_series.isna() | (local_area_series == "(Unknown)")
        joined.loc[mask_unknown, "local_area"] = area_values.where(mask_unknown, None)
        joined["local_area"] = joined["local_area"].apply(
            lambda v: _clean_area(v) or "(Unknown)"
        )

    missing_coords = joined["lat"].isna() | joined["lon"].isna()
    if missing_coords.any():
        addr_valid = addr_df.dropna(subset=["lat", "lon"])
        street_lookup: dict[str, pd.DataFrame] = {}
        if "street_norm" in addr_valid.columns:
            for street, group in addr_valid.groupby("street_norm"):
                street_lookup[street] = group

        for idx in joined[missing_coords].index:
            addr_text = joined.at[idx, "address"]
            key_norm = addr_key_from_freeform(addr_text)
            parts = key_norm.split(" ", 1)
            if len(parts) < 2:
                continue
            try:
                civic_val = float(parts[0])
            except ValueError:
                civic_val = None
            street_norm = parts[1]
            group = street_lookup.get(street_norm)
            if group is None or group.empty:
                continue
            candidates = group.dropna(subset=["lat", "lon"])
            if candidates.empty:
                continue
            choice = None
            if civic_val is not None and "civic_number_int" in candidates.columns:
                numeric_candidates = candidates.dropna(subset=["civic_number_int"])
                if not numeric_candidates.empty:
                    idx_min = (
                        (numeric_candidates["civic_number_int"] - civic_val)
                        .abs()
                        .argsort()
                        .iloc[0]
                    )
                    choice = numeric_candidates.iloc[idx_min]
            if choice is None:
                choice = candidates.iloc[0]
            joined.at[idx, "lat"] = choice["lat"]
            joined.at[idx, "lon"] = choice["lon"]
            if joined.at[idx, "local_area"] in {None, "", "(Unknown)"}:
                candidate_area = None
                for col in area_candidates:
                    if col in choice and pd.notna(choice[col]):
                        candidate_area = str(choice[col]).strip()
                        break
                if candidate_area:
                    joined.at[idx, "local_area"] = candidate_area

    helper_cols_to_drop = [col for col in area_candidates if col in joined.columns]
    helper_cols_to_drop.extend(
        [c for c in ("street_norm", "civic_number_int") if c in joined.columns]
    )
    if helper_cols_to_drop:
        joined = joined.drop(columns=helper_cols_to_drop, errors="ignore")

    joined["units"] = pd.to_numeric(joined.get("units"), errors="coerce")
    joined["year_built"] = pd.to_numeric(joined.get("year_built"), errors="coerce")
    joined["n_issues"] = pd.to_numeric(joined.get("n_issues"), errors="coerce")
    joined["bldg_land_ratio"] = pd.to_numeric(joined.get("bldg_land_ratio"), errors="coerce")
    joined["value_land"] = joined.get("value_land").apply(_parse_money)
    joined["value_bldg"] = joined.get("value_bldg").apply(_parse_money)
    return joined


def _deduplicate_buildings(df: pd.DataFrame, owner_col: str) -> pd.DataFrame:
    def dedup_group(g: pd.DataFrame) -> pd.Series:
        addr = g["address"].mode().iloc[0] if not g["address"].mode().empty else g["address"].iloc[0]
        lat = g["lat"].dropna().iloc[0] if not g["lat"].dropna().empty else None
        lon = g["lon"].dropna().iloc[0] if not g["lon"].dropna().empty else None
        units = g["units"].max()
        yb = g["year_built"].median()
        n_issues = g["n_issues"].max() if "n_issues" in g.columns else np.nan

        val_land_series = g["value_land"].dropna() if "value_land" in g.columns else pd.Series(dtype=float)
        val_bldg_series = g["value_bldg"].dropna() if "value_bldg" in g.columns else pd.Series(dtype=float)
        ratio_series = g["bldg_land_ratio"].dropna() if "bldg_land_ratio" in g.columns else pd.Series(dtype=float)
        val_land = float(val_land_series.median()) if not val_land_series.empty else None
        val_bldg = float(val_bldg_series.median()) if not val_bldg_series.empty else None
        ratio = (
            float(ratio_series.median())
            if not ratio_series.empty
            else (float(val_bldg / val_land) if val_land else None)
        )

        if owner_col in g.columns:
            owner_series = g[owner_col].dropna().apply(clean_owner_label)
        else:
            owner_series = pd.Series(dtype=str)
        if not owner_series.empty:
            mode_vals = owner_series.mode()
            owner = mode_vals.iloc[0] if not mode_vals.empty else owner_series.iloc[0]
        else:
            owner = "(Unknown)"
        owner = clean_owner_label(owner)

        areas = g["local_area"].dropna().astype(str) if "local_area" in g.columns else pd.Series(dtype=str)
        if not areas.empty:
            area_mode = areas.mode()
            local_area = area_mode.iloc[0] if not area_mode.empty else areas.iloc[0]
        else:
            local_area = "(Unknown)"

        source_ids = sorted({int(v) for v in g["raw_building_id"].dropna().tolist()})

        return pd.Series(
            {
                "address": addr,
                "lat": lat,
                "lon": lon,
                "units": None if pd.isna(units) else float(units),
                "year_built": None if pd.isna(yb) else float(yb),
                "n_issues": None if pd.isna(n_issues) else float(n_issues),
                "value_land": val_land,
                "value_bldg": val_bldg,
                "bldg_land_ratio": ratio,
                "owner_group": owner,
                "owner_key": sanitize_owner(owner),
                "local_area": local_area,
                "source_row_ids": source_ids,
            }
        )

    records = []
    for key, group in df.groupby("addr_key", sort=False):
        rec = dedup_group(group)
        rec["addr_key"] = key
        records.append(rec)
    out = pd.DataFrame(records)
    return out.dropna(subset=["lat", "lon"]).copy()


def merge_and_dedupe_buildings(
    raw_buildings: pd.DataFrame, raw_addresses: pd.DataFrame
) -> pd.DataFrame:
    addr_df = _prepare_addresses(raw_addresses)
    west, owner_col = _select_buildings(raw_buildings)
    joined = _join_buildings_addresses(west, addr_df)
    return _deduplicate_buildings(joined, owner_col)


def assign_blocks(buildings_df: pd.DataFrame, blocks_df: pd.DataFrame) -> pd.Series:
    """Fork of point_in_block_ids (STRtree). block_id per row, None if unmatched."""
    geoms = []
    block_ids = []
    for _, r in blocks_df.iterrows():
        geom = parse_geom(r["geom"])
        if geom is None:
            continue
        geoms.append(geom)
        block_ids.append(int(r["block_id"]))

    if not geoms:
        return pd.Series([None] * len(buildings_df), index=buildings_df.index)

    tree = STRtree(geoms)

    def locate(lon: float, lat: float) -> int | None:
        if pd.isna(lat) or pd.isna(lon):
            return None
        point = Point(lon, lat)
        for idx in np.atleast_1d(tree.query(point)):
            geom = geoms[int(idx)]
            if geom.contains(point) or geom.touches(point):
                return block_ids[int(idx)]
        return None

    return pd.Series(
        [locate(lo, la) for la, lo in zip(buildings_df["lat"], buildings_df["lon"])],
        index=buildings_df.index,
    )


def upsert_landlords(conn: sqlite3.Connection, buildings_df: pd.DataFrame) -> dict[str, int]:
    """One row per distinct owner_key, excluding 'unknown'. Returns owner_key -> landlord_id."""
    now = datetime.now(timezone.utc).isoformat()
    distinct = (
        buildings_df.loc[buildings_df["owner_key"] != "unknown", ["owner_key", "owner_group"]]
        .drop_duplicates("owner_key")
    )
    owner_key_to_id: dict[str, int] = {}
    with conn:
        for row in distinct.itertuples(index=False):
            cur = conn.execute(
                "INSERT INTO landlords (display_name, owner_key, source_row_ids, created_at, updated_at) "
                "VALUES (?, ?, NULL, ?, ?)",
                (row.owner_group, row.owner_key, now, now),
            )
            owner_key_to_id[row.owner_key] = cur.lastrowid
    return owner_key_to_id


def write_buildings(
    conn: sqlite3.Connection,
    buildings_df: pd.DataFrame,
    landlord_id_by_owner_key: dict[str, int],
    block_id_by_index: pd.Series,
) -> int:
    now = datetime.now(timezone.utc).isoformat()
    rows = []
    for idx, row in buildings_df.iterrows():
        landlord_id = landlord_id_by_owner_key.get(row["owner_key"])
        block_id = block_id_by_index.get(idx)
        rows.append(
            (
                row["addr_key"],
                row["address"],
                row["local_area"],
                row["lat"],
                row["lon"],
                row["units"],
                row["year_built"],
                row["value_land"],
                row["value_bldg"],
                row["bldg_land_ratio"],
                row["n_issues"],
                landlord_id,
                block_id,
                json.dumps(row["source_row_ids"]),
                now,
                now,
            )
        )
    with conn:
        conn.executemany(
            """
            INSERT INTO buildings (
                addr_key, address, local_area, lat, lon, units, year_built,
                value_land, value_bldg, bldg_land_ratio, n_issues,
                landlord_id, block_id, source_row_ids, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
    return len(rows)


def run_merge(conn: sqlite3.Connection) -> int:
    raw_buildings, raw_addresses = load_raw_frames(conn)
    buildings_df = merge_and_dedupe_buildings(raw_buildings, raw_addresses)

    blocks_df = pd.read_sql_query("SELECT block_id, geom FROM blocks", conn)
    block_id_by_index = assign_blocks(buildings_df, blocks_df)

    landlord_id_by_owner_key = upsert_landlords(conn, buildings_df)
    return write_buildings(conn, buildings_df, landlord_id_by_owner_key, block_id_by_index)
