"""Exports sica_core's SQLite data into sica_mapping's legacy
`.preprocessed/*.json` cache shape, so the existing, unmodified Folium map
(`build_sica_map.py --stage frontend`) can render straight from SQLite
instead of the CSV pipeline.

This reproduces the same full data the current map already shows (including
VTU membership counts) — no public/sensitive field redaction here. That's a
separate, later piece of work for whenever an actual public-facing map
exists to feed; see CLAUDE.md's sensitivity-model notes.

No import from `sica_mapping` happens here (see `__init__.py`'s
dependency-free docstring): the tiny amount of `json.dump` boilerplate is
duplicated instead. `scripts/rebuild_map.py` is the piece that needs both
packages (it also shells out to `build_sica_map.py`), which is why it lives
at the top level, not inside this package.

Known, deliberate simplifications (not bugs):
- `reconstruct_blocks` filters to the static `in_west_end_bbox` flag computed
  at ingest time. v1 instead recomputes a *dynamic* buffered bbox every run
  (config bbox unioned with actual matched-building bounds, plus a small
  pad) — replicating that exactly isn't worth it. This produces a working,
  sensible map, just not byte-identical block counts to v1.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

from .building_metrics import BUILDING_METRICS, build_building_metrics
from .geometry import parse_geom
from .membership_metrics import compute_building_member_metrics, membership_filter_config


def reconstruct_points(conn: sqlite3.Connection, now: pd.Timestamp) -> pd.DataFrame:
    buildings = pd.read_sql_query("SELECT * FROM buildings", conn)
    landlords = pd.read_sql_query(
        "SELECT landlord_id, display_name, owner_key FROM landlords", conn
    )
    buildings = buildings.merge(landlords, on="landlord_id", how="left")
    buildings["display_name"] = buildings["display_name"].fillna("(Unknown)")
    buildings["owner_key"] = buildings["owner_key"].fillna("unknown")
    buildings = buildings.rename(
        columns={"building_id": "b_id", "display_name": "owner_group"}
    )

    members = pd.read_sql_query(
        "SELECT * FROM vtu_membership WHERE building_id IS NOT NULL", conn
    )
    metrics = compute_building_member_metrics(members, now).rename(
        columns={"building_id": "b_id"}
    )

    merged = buildings.merge(metrics, on="b_id", how="left")
    merged["member_count"] = merged["member_count"].fillna(0).astype(int)
    merged["member_count_all"] = merged["member_count_all"].fillna(0).astype(int)
    merged["has_vtu_member"] = merged["member_count"] > 0
    merged["members_payload"] = merged["members_payload"].apply(
        lambda v: v if isinstance(v, list) else []
    )
    merged["member_share_building"] = np.where(
        (merged["units"] > 0) & merged["units"].notna(),
        np.minimum(merged["member_count"] / merged["units"], 1.0),
        0.0,
    )

    return merged[
        [
            "addr_key", "address", "lat", "lon", "units", "year_built", "n_issues",
            "member_count", "has_vtu_member", "member_share_building", "owner_group",
            "owner_key", "member_count_all", "members_payload", "value_land",
            "value_bldg", "bldg_land_ratio", "local_area", "b_id", "block_id",
        ]
    ]


def reconstruct_blocks(conn: sqlite3.Connection, points_df: pd.DataFrame) -> pd.DataFrame:
    blocks_raw = pd.read_sql_query(
        "SELECT block_id, geom FROM blocks WHERE in_west_end_bbox = 1", conn
    )
    agg = (
        points_df.groupby("block_id", dropna=True)
        .agg(
            buildings=("address", "count"),
            total_units=("units", "sum"),
            median_year_built=("year_built", "median"),
            member_buildings=("has_vtu_member", "sum"),
            total_members=("member_count", "sum"),
        )
        .reset_index()
    )
    merged = blocks_raw.merge(agg, on="block_id", how="left").fillna(
        {
            "buildings": 0,
            "total_units": 0,
            "median_year_built": np.nan,
            "member_buildings": 0,
            "total_members": 0,
        }
    )
    merged["member_share"] = np.where(
        merged["buildings"] > 0, merged["member_buildings"] / merged["buildings"], 0.0
    )
    merged["geom_parsed"] = merged["geom"].apply(parse_geom)
    return merged.drop(columns=["geom"])


def reconstruct_filter_config(
    conn: sqlite3.Connection,
    points_df: pd.DataFrame,
    blocks_df: pd.DataFrame,
    now: pd.Timestamp,
) -> dict[str, object]:
    members = pd.read_sql_query(
        "SELECT * FROM vtu_membership WHERE building_id IS NOT NULL", conn
    )
    cfg = dict(membership_filter_config(members, now))

    pts = points_df.copy()
    pts["local_area"] = pts["local_area"].fillna("(Unknown)")
    pts["units"] = pts["units"].fillna(0)
    neighbourhood_counts = pts["local_area"].value_counts().sort_values(ascending=False)
    neighbourhood_units = pts.groupby("local_area")["units"].sum().sort_values(ascending=False)
    cfg["neighbourhoods"] = [
        {"name": area, "count": int(count), "units": int(round(neighbourhood_units.get(area, 0)))}
        for area, count in neighbourhood_counts.items()
    ]

    valid_coords = pts.dropna(subset=["lat", "lon"])
    bounds = None
    if not valid_coords.empty:
        bounds = {
            "lat_min": float(valid_coords["lat"].min()),
            "lat_max": float(valid_coords["lat"].max()),
            "lon_min": float(valid_coords["lon"].min()),
            "lon_max": float(valid_coords["lon"].max()),
            "center_lat": float(valid_coords["lat"].mean()),
            "center_lon": float(valid_coords["lon"].mean()),
        }
    cfg["bounds"] = bounds
    cfg["dataset_totals"] = {
        "buildings": int(len(pts)),
        "members": int(pts["member_count"].sum()),
        "units": int(pd.to_numeric(pts["units"], errors="coerce").fillna(0).sum()),
        "vtu_buildings": int(pts["has_vtu_member"].sum()),
    }

    building_metrics = build_building_metrics(pts)
    cfg["building_metrics"] = building_metrics
    cfg["building_metric_order"] = [
        key for key in BUILDING_METRICS if key in building_metrics
    ]

    cfg["blocks_total_units_max"] = (
        int(blocks_df["total_units"].max()) if not blocks_df.empty else 0
    )
    return cfg


def export_to_cache(
    conn: sqlite3.Connection, data_dir: str | Path, now: pd.Timestamp | None = None
) -> None:
    if now is None:
        now = pd.Timestamp.now(tz="UTC")
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    points_df = reconstruct_points(conn, now)
    blocks_df = reconstruct_blocks(conn, points_df)
    filter_cfg = reconstruct_filter_config(conn, points_df, blocks_df, now)

    points_records = json.loads(points_df.to_json(orient="records"))
    (data_dir / "building_points.json").write_text(
        json.dumps(points_records, indent=2), encoding="utf-8"
    )

    blocks_out = blocks_df.copy()
    blocks_out["geom_geojson"] = blocks_out["geom_parsed"].apply(
        lambda g: g.__geo_interface__ if g is not None else None
    )
    blocks_records = json.loads(
        blocks_out.drop(columns=["geom_parsed"]).to_json(orient="records")
    )
    (data_dir / "blocks.json").write_text(
        json.dumps(blocks_records, indent=2), encoding="utf-8"
    )

    (data_dir / "filter_config.json").write_text(
        json.dumps(filter_cfg, indent=2, default=str), encoding="utf-8"
    )
