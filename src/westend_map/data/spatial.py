"""Spatial utilities used across the data pipeline."""

from __future__ import annotations

from typing import Tuple

import numpy as np
import pandas as pd
from shapely.geometry import Point
from shapely.strtree import STRtree

from ..core import require_columns, addr_key_from_freeform, clean_owner_label, normalize_street
from .geometry import parse_geom, poly_to_geojson


COLS = {
    "addresses_required": {"civic_number", "std_street", "geo_point_2d"},
    "buildings_required": {"local_area", "address"},
    "blocks_geom": "geom",
}

OWNER_CANDIDATES = [
    "bsns_group",
    "business_group",
    "owner_group",
    "owner",
    "ownership_group",
]


def prepare_addresses(addr_df: pd.DataFrame, parse_latlon_fn) -> pd.DataFrame:
    require_columns(addr_df, COLS["addresses_required"], "Addresses CSV")
    addr_df = addr_df.copy()
    addr_df[["lat", "lon"]] = addr_df["geo_point_2d"].apply(lambda s: pd.Series(parse_latlon_fn(s)))
    addr_df["street_norm"] = addr_df["std_street"].map(lambda s: normalize_street(s) if pd.notna(s) else None)
    addr_df["civic_number_int"] = pd.to_numeric(addr_df["civic_number"], errors="coerce")

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


def select_west_end_buildings(
    bldg_df: pd.DataFrame,
    addr_key_from_freeform_fn,
    allowed_areas: list[str] | None = None,
) -> tuple[pd.DataFrame, str]:
    require_columns(bldg_df, COLS["buildings_required"], "Buildings CSV")
    df = bldg_df.copy()
    df["local_area"] = df["local_area"].fillna("(Unknown)")
    if allowed_areas:
        allowed_norm = {area.strip().lower() for area in allowed_areas}
        df = df[df["local_area"].str.lower().isin(allowed_norm)].copy()
    df["addr_key"] = df["address"].apply(addr_key_from_freeform_fn)
    if "primary_address" in df.columns:
        df["addr_key_primary"] = df["primary_address"].apply(addr_key_from_freeform_fn)
        df["addr_key_primary"] = df["addr_key_primary"].fillna(df["addr_key"])
    else:
        df["addr_key_primary"] = df["addr_key"]

    owner_col = next((c for c in OWNER_CANDIDATES if c in df.columns), None)
    if owner_col is None:
        owner_col = next((c for c in df.columns if ("group" in c or "owner" in c)), None)
    if owner_col is None:
        owner_col = "bsns_group"
        df[owner_col] = "(Unknown)"
    return df, owner_col


def join_buildings_addresses(west: pd.DataFrame, addr_df: pd.DataFrame) -> pd.DataFrame:
    addr_df = addr_df.copy()
    area_cols = [col for col in addr_df.columns if "local_area" in col]
    addr_cols = ["addr_key", "lat", "lon", "street_norm", "civic_number_int"] + [
        col for col in area_cols if col not in {"lat", "lon"}
    ]
    addr_lookup = addr_df[addr_cols].drop_duplicates("addr_key")

    joined = west.merge(addr_lookup, on="addr_key", how="left")
    if "addr_key_primary" in joined.columns:
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
    area_candidates = [col for col in area_cols if col in joined.columns and col != "local_area"]
    if area_candidates:
        def _clean_area(val):
            if pd.isna(val):
                return None
            s = str(val).strip()
            return s or None

        area_values = joined[area_candidates].apply(
            lambda row: next((candidate for candidate in (_clean_area(row[col]) for col in area_candidates) if candidate), None),
            axis=1,
        )
        local_area_series = joined["local_area"].apply(_clean_area)
        mask_unknown = local_area_series.isna() | (local_area_series == "(Unknown)")
        joined.loc[mask_unknown, "local_area"] = area_values.where(mask_unknown, None)
        joined["local_area"] = joined["local_area"].apply(lambda v: _clean_area(v) or "(Unknown)")

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
                    idx_min = (numeric_candidates["civic_number_int"] - civic_val).abs().argsort().iloc[0]
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
    helper_cols_to_drop.extend([col for col in ("street_norm", "civic_number_int") if col in joined.columns])
    if helper_cols_to_drop:
        joined = joined.drop(columns=helper_cols_to_drop, errors="ignore")

    for col in ["units", "year_built", "value_land", "value_bldg", "bldg_land_ratio", "n_issues"]:
        if col not in joined.columns:
            joined[col] = np.nan
        joined[col] = pd.to_numeric(joined[col], errors="coerce")
    return joined


def deduplicate_buildings(df: pd.DataFrame, owner_col: str, sanitize_owner_fn) -> pd.DataFrame:
    def dedup_group(g: pd.DataFrame) -> pd.Series:
        addr = g["address"].mode().iloc[0] if not g["address"].mode().empty else g["address"].iloc[0]
        lat = g["lat"].dropna().iloc[0] if not g["lat"].dropna().empty else np.nan
        lon = g["lon"].dropna().iloc[0] if not g["lon"].dropna().empty else np.nan
        units = g["units"].max()
        yb = g["year_built"].median()
        n_issues = g["n_issues"].max() if "n_issues" in g.columns else np.nan
        members = int(g["member_count"].max())
        members_all = int(g["member_count_all"].max()) if "member_count_all" in g.columns else members
        val_land_series = g["value_land"].dropna() if "value_land" in g.columns else pd.Series(dtype=float)
        val_bldg_series = g["value_bldg"].dropna() if "value_bldg" in g.columns else pd.Series(dtype=float)
        ratio_series = g["bldg_land_ratio"].dropna() if "bldg_land_ratio" in g.columns else pd.Series(dtype=float)
        val_land = float(val_land_series.median()) if not val_land_series.empty else np.nan
        val_bldg = float(val_bldg_series.median()) if not val_bldg_series.empty else np.nan
        ratio = float(ratio_series.median()) if not ratio_series.empty else (
            float(val_bldg / val_land) if pd.notna(val_land) and val_land else np.nan
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
        share = float(np.minimum(members / units, 1.0)) if pd.notna(units) and units > 0 else 0.0
        payload = []
        if "members_payload" in g.columns:
            non_empty = g["members_payload"].dropna()
            if not non_empty.empty:
                for candidate in non_empty:
                    if isinstance(candidate, list) and candidate:
                        payload = candidate
                        break
        return pd.Series({
            "address": addr,
            "lat": lat,
            "lon": lon,
            "units": units,
            "year_built": yb,
            "n_issues": n_issues,
            "member_count": members,
            "has_vtu_member": bool(members > 0),
            "member_share_building": share,
            "owner_group": owner,
            "owner_key": sanitize_owner_fn(owner),
            "member_count_all": members_all,
            "members_payload": payload,
            "value_land": val_land,
            "value_bldg": val_bldg,
            "bldg_land_ratio": ratio,
            "local_area": local_area,
        })

    records = []
    for key, group in df.groupby("addr_key", sort=False):
        rec = dedup_group(group)
        rec["addr_key"] = key
        records.append(rec)
    out = pd.DataFrame(records)
    out["b_id"] = out.index
    return out.dropna(subset=["lat", "lon"]).copy()


def parse_blocks(blocks_raw: pd.DataFrame, bbox: tuple[float, float, float, float] | None) -> pd.DataFrame:
    if COLS["blocks_geom"] not in blocks_raw.columns:
        raise RuntimeError("Blocks CSV must have a 'geom' column with GeoJSON geometry.")
    blocks = blocks_raw.copy()
    blocks["geom_parsed"] = blocks["geom"].apply(parse_geom)
    blocks = blocks.dropna(subset=["geom_parsed"]).reset_index(drop=True)

    if bbox is None:
        subset = blocks.reset_index(drop=True)
    else:
        lon_min, lat_min, lon_max, lat_max = bbox

        def within_bbox(geom) -> bool:
            bx = geom.bounds
            return not (bx[2] < lon_min or bx[0] > lon_max or bx[3] < lat_min or bx[1] > lat_max)

        subset = blocks[blocks["geom_parsed"].apply(within_bbox)].reset_index(drop=True)
    subset["block_id"] = subset.index
    return subset


def aggregate_blocks(pts_df: pd.DataFrame, blocks_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    pts = pts_df.copy()
    pts["block_id"] = point_in_block_ids(pts, blocks_df)
    agg = pts.groupby("block_id", dropna=True).agg(
        buildings=("address", "count"),
        total_units=("units", "sum"),
        median_year_built=("year_built", "median"),
        member_buildings=("has_vtu_member", "sum"),
        total_members=("member_count", "sum"),
    ).reset_index()
    merged = blocks_df.merge(agg, on="block_id", how="left").fillna({
        "buildings": 0,
        "total_units": 0,
        "median_year_built": np.nan,
        "member_buildings": 0,
        "total_members": 0,
    })
    merged = merged.reset_index(drop=True)
    merged["member_share"] = np.where(
        merged["buildings"] > 0, merged["member_buildings"] / merged["buildings"], 0.0
    )
    return merged, pts


def blocks_feature_collection(blocks_merged: pd.DataFrame) -> dict:
    feats = []
    for _, r in blocks_merged.iterrows():
        gj = poly_to_geojson(r["geom_parsed"])
        if gj:
            feats.append({
                "type": "Feature",
                "geometry": gj,
                "properties": {
                    "block_id": int(r["block_id"]),
                    "buildings": int(r["buildings"]),
                    "total_units": int(r["total_units"]),
                    "median_year_built": None if pd.isna(r["median_year_built"]) else int(r["median_year_built"]),
                    "member_buildings": int(r["member_buildings"]),
                    "total_members": int(r["total_members"]),
                    "member_share": float(r["member_share"]),
                },
            })
    return {"type": "FeatureCollection", "features": feats}
def point_in_block_ids(pts_df: pd.DataFrame, blocks_df: pd.DataFrame) -> pd.Series:
    geoms = list(blocks_df["geom_parsed"])
    block_ids = blocks_df["block_id"].to_numpy()
    tree = STRtree(geoms)
    id_map = {id(g): block_ids[idx] for idx, g in enumerate(geoms)}

    def locate_block(lon: float, lat: float) -> float:
        if pd.isna(lat) or pd.isna(lon):
            return np.nan
        p = Point(lon, lat)
        candidates = tree.query(p)
        if candidates is None:
            return np.nan
        if isinstance(candidates, np.ndarray) and candidates.size and np.issubdtype(candidates.dtype, np.integer):
            for idx in candidates.astype(int).tolist():
                geom = geoms[int(idx)]
                if geom.contains(p) or geom.touches(p):
                    return block_ids[int(idx)]
            return np.nan
        try:
            iterable = list(candidates)
        except TypeError:
            iterable = [candidates]
        for cand in iterable:
            if cand is None:
                continue
            if isinstance(cand, (int, np.integer)):
                geom = geoms[int(cand)]
                if geom.contains(p) or geom.touches(p):
                    return block_ids[int(cand)]
                continue
            geom_id = id(cand)
            block_id = id_map.get(geom_id)
            if block_id is None:
                try:
                    idx = geoms.index(cand)
                except ValueError:
                    continue
                block_id = block_ids[int(idx)]
            if cand.contains(p) or cand.touches(p):
                return block_id
        return np.nan

    return pd.Series([locate_block(lo, la) for la, lo in zip(pts_df["lat"], pts_df["lon"])])
