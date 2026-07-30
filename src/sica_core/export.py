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
from shapely.strtree import STRtree

from .building_metrics import BUILDING_METRICS, _summarize_metric, build_building_metrics
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
            "latest_membership_year",
        ]
    ]


def resolve_local_area_from_block_numbers(
    blocks_merged: pd.DataFrame, block_numbers_df: pd.DataFrame
) -> pd.Series:
    """Fork of src/sica_mapping/data/spatial.py::resolve_local_area_from_block_numbers
    — see its docstring. Blocks with zero buildings have no local_area to take
    a mode from and default to "(Unknown)"; resolve those from Vancouver Open
    Data's "block-numbers" dataset instead — one point per city block,
    carrying the City's own authoritative geo_local_area. Primary: point-in-
    polygon (a block-numbers point almost always lands inside exactly one of
    our block polygons). Fallback: nearest block-numbers point by centroid
    distance, for the rare block with none landing inside it. Populated
    blocks keep their buildings-derived mode, untouched.
    """
    local_area = blocks_merged["local_area"].copy()
    unknown_mask = local_area == "(Unknown)"
    if not unknown_mask.any() or block_numbers_df.empty:
        return local_area

    bn = block_numbers_df.copy()
    bn["geom_parsed"] = bn["geom"].apply(parse_geom)
    bn = bn.dropna(subset=["geom_parsed", "geo_local_area"])
    if bn.empty:
        return local_area

    block_geoms = list(blocks_merged["geom_parsed"])
    block_ids = blocks_merged["block_id"].to_numpy()
    block_tree = STRtree(block_geoms)

    # Primary: point-in-polygon, one block-numbers point -> one of our blocks.
    matches: dict[int, list[str]] = {}
    for point, area in zip(bn["geom_parsed"], bn["geo_local_area"]):
        for idx in np.atleast_1d(block_tree.query(point)):
            geom = block_geoms[int(idx)]
            if geom.contains(point) or geom.touches(point):
                matches.setdefault(int(block_ids[int(idx)]), []).append(area)
                break
    resolved_by_block = {
        bid: pd.Series(areas).mode().iloc[0] for bid, areas in matches.items()
    }

    # Fallback: nearest block-numbers point by centroid distance, for blocks
    # that got zero points inside their polygon.
    point_tree = STRtree(bn["geom_parsed"].tolist())
    bn_areas = bn["geo_local_area"].to_numpy()
    centroids = blocks_merged["geom_parsed"].apply(
        lambda geom: geom.centroid if geom is not None else None
    )
    for idx in blocks_merged.index[unknown_mask]:
        bid = int(blocks_merged.at[idx, "block_id"])
        resolved = resolved_by_block.get(bid)
        if resolved is None:
            centroid = centroids.at[idx]
            if centroid is not None:
                nearest = point_tree.nearest(centroid)
                resolved = bn_areas[int(nearest)]
        if resolved:
            local_area.at[idx] = resolved
    return local_area


def assign_block_labels(blocks_merged: pd.DataFrame) -> pd.Series:
    """Fork of src/sica_mapping/data/spatial.py::assign_block_labels — see its
    docstring. Human-readable "{local_area}-{NN}" labels, reading-order
    (north-to-south, west-to-east) within each neighbourhood. Display-only;
    block_id remains the join/index key everywhere else.
    """
    centroids = blocks_merged["geom_parsed"].apply(
        lambda geom: geom.centroid if geom is not None else None
    )
    order_df = pd.DataFrame(
        {
            "local_area": blocks_merged["local_area"],
            "lat": centroids.apply(lambda c: c.y if c is not None else np.nan),
            "lon": centroids.apply(lambda c: c.x if c is not None else np.nan),
        },
        index=blocks_merged.index,
    )
    labels = pd.Series(index=blocks_merged.index, dtype=object)
    for area, group in order_df.groupby("local_area"):
        ordered = group.sort_values(["lat", "lon"], ascending=[False, True])
        for ordinal, idx in enumerate(ordered.index, start=1):
            labels.at[idx] = f"{area}-{ordinal:02d}"
    return labels


def reconstruct_blocks(conn: sqlite3.Connection, points_df: pd.DataFrame) -> pd.DataFrame:
    # Not bbox-filtered: buildings.csv is already city-wide (not West-End-scoped —
    # see merge.py's notes), so restricting blocks to the static config bbox left
    # most of the actual data — the whole eastside and south of the city — with no
    # block polygons at all.
    blocks_raw = pd.read_sql_query("SELECT block_id, geom FROM blocks", conn)
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
    local_area_by_block = (
        points_df.dropna(subset=["block_id"])
        .groupby("block_id")["local_area"]
        .agg(lambda s: s.mode().iloc[0] if not s.mode().empty else "(Unknown)")
        .rename("local_area")
    )
    agg = agg.merge(local_area_by_block, on="block_id", how="left")
    merged = blocks_raw.merge(agg, on="block_id", how="left").fillna(
        {
            "buildings": 0,
            "total_units": 0,
            "median_year_built": np.nan,
            "member_buildings": 0,
            "total_members": 0,
        }
    )
    merged["local_area"] = merged["local_area"].fillna("(Unknown)")
    merged["member_share"] = np.where(
        merged["buildings"] > 0, merged["member_buildings"] / merged["buildings"], 0.0
    )
    merged["geom_parsed"] = merged["geom"].apply(parse_geom)
    block_numbers_df = pd.read_sql_query(
        "SELECT geom, geo_local_area FROM raw_block_numbers", conn
    )
    merged["local_area"] = resolve_local_area_from_block_numbers(merged, block_numbers_df)
    merged["block_label"] = assign_block_labels(merged)
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

    # Rendered with the same dual-slider component as building_metrics, but kept
    # out of that dict so it doesn't also show up under the "Buildings" filter
    # section — it's rendered into its own container under "Membership" instead.
    cfg["membership_year_metric"] = _summarize_metric(
        pts["latest_membership_year"],
        meta={
            "label": "Membership year",
            "format": "number",
            "type": "int",
            "step": 1,
            "attr": "latest-membership-year",
            "bins": 12,
        },
    )

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
