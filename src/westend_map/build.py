"""High-level orchestration of the map build process."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import folium
import pandas as pd
import numpy as np
from shapely.geometry import shape

from .core import setup_logging, logger
from .data import (
    run_data_pipeline,
    cached_data_exists,
    write_cached_data,
    load_cached_data,
    blocks_feature_collection,
    buildings_table,
    blocks_table,
    landlords_table,
    rows_buildings,
    rows_blocks,
    rows_landlords,
)
from .frontend import (
    compute_vmax,
    add_blocks_layer,
    add_buildings_layers,
    sidebar_html,
    wiring_js,
    legends_html,
)


def _ensure_output_path(path: Path) -> Path:
    original = Path(path)
    if original.is_absolute():
        target = Path("html") / original.name
    else:
        target = original if original.parts and original.parts[0] == "html" else Path("html") / original
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def _sanitise_record(record: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in record.items():
        if isinstance(value, (pd.Timestamp,)):
            cleaned[key] = value.isoformat()
        elif value is None:
            cleaned[key] = None
        elif isinstance(value, (np.generic,)):
            cleaned[key] = value.item()
        elif isinstance(value, float) and pd.isna(value):
            cleaned[key] = None
        else:
            cleaned[key] = value
    return cleaned


def build_map(args) -> None:
    setup_logging(args.verbose)
    lon_min, lat_min, lon_max, lat_max = map(float, args.bbox.split(","))
    bbox = (lon_min, lat_min, lon_max, lat_max)

    data_dir = Path(args.data_dir) if args.data_dir else None
    pipeline_data: dict[str, Any] | None = None

    local_areas = args.local_area if args.local_area else None

    if args.stage in {"data", "all"}:
        pipeline_data = run_data_pipeline(args.buildings, args.addresses, args.blocks, args.vtu, bbox, local_areas)
        if data_dir:
            write_cached_data(pipeline_data, data_dir)
        else:
            logger.warning("Data stage requested but no data directory specified; skipping cache write")
        if args.stage == "data":
            return

    if pipeline_data is None:
        if data_dir and cached_data_exists(data_dir):
            pipeline_data = load_cached_data(data_dir)
            if "blocks" in pipeline_data and "geom_geojson" in pipeline_data["blocks"].columns and "geom_parsed" not in pipeline_data["blocks"].columns:
                pipeline_data["blocks"]["geom_parsed"] = pipeline_data["blocks"]["geom_geojson"].apply(
                    lambda g: shape(g) if g else None
                )
        else:
            pipeline_data = run_data_pipeline(args.buildings, args.addresses, args.blocks, args.vtu, bbox, local_areas)
            if data_dir:
                write_cached_data(pipeline_data, data_dir)

    pts_df: pd.DataFrame = pipeline_data["pts"].copy()
    blocks_merged: pd.DataFrame = pipeline_data["blocks"].copy()
    if "geom_parsed" not in blocks_merged and "geom_geojson" in blocks_merged:
        blocks_merged["geom_parsed"] = blocks_merged["geom_geojson"].apply(lambda g: shape(g) if g else None)
    filter_cfg = pipeline_data["filter_config"]

    bounds_info = filter_cfg.get("bounds") if isinstance(filter_cfg, dict) else None
    center_lat = 49.286
    center_lon = -123.135
    zoom_start = 14
    lat_span = 0.0
    lon_span = 0.0
    if bounds_info:
        center_lat = float(bounds_info.get("center_lat", center_lat))
        center_lon = float(bounds_info.get("center_lon", center_lon))
        lat_min = float(bounds_info.get("lat_min", center_lat))
        lat_max = float(bounds_info.get("lat_max", center_lat))
        lon_min_bounds = float(bounds_info.get("lon_min", center_lon))
        lon_max_bounds = float(bounds_info.get("lon_max", center_lon))
        lat_span = lat_max - lat_min
        lon_span = lon_max_bounds - lon_min_bounds
    else:
        valid_coords = pts_df.dropna(subset=["lat", "lon"])
        if not valid_coords.empty:
            lat_min = float(valid_coords["lat"].min())
            lat_max = float(valid_coords["lat"].max())
            lon_min_bounds = float(valid_coords["lon"].min())
            lon_max_bounds = float(valid_coords["lon"].max())
            center_lat = float(valid_coords["lat"].mean())
            center_lon = float(valid_coords["lon"].mean())
            lat_span = lat_max - lat_min
            lon_span = lon_max_bounds - lon_min_bounds

    extent = max(abs(lat_span), abs(lon_span))
    if extent > 0.25:
        zoom_start = 10
    elif extent > 0.12:
        zoom_start = 11
    elif extent > 0.06:
        zoom_start = 12
    elif extent > 0.03:
        zoom_start = 13

    vmax = compute_vmax(pts_df)
    m = folium.Map(location=[center_lat, center_lon], zoom_start=zoom_start, tiles=args.tiles)
    fc = blocks_feature_collection(blocks_merged)
    blocks_geo = add_blocks_layer(m, fc)
    _layer_vtu, _layer_non, layer_vtu_name, layer_non_name, marker_metadata = add_buildings_layers(m, pts_df, vmax)

    if bounds_info and all(k in bounds_info for k in ("lat_min", "lon_min", "lat_max", "lon_max")):
        m.fit_bounds([[bounds_info["lat_min"], bounds_info["lon_min"]], [bounds_info["lat_max"], bounds_info["lon_max"]]])
    elif not pts_df.dropna(subset=["lat", "lon"]).empty:
        valid_coords = pts_df.dropna(subset=["lat", "lon"])
        m.fit_bounds([[float(valid_coords["lat"].min()), float(valid_coords["lon"].min())],
                      [float(valid_coords["lat"].max()), float(valid_coords["lon"].max())]])

    b_tbl = buildings_table(pts_df)
    k_tbl = blocks_table(blocks_merged)
    l_tbl = landlords_table(pts_df)
    m.get_root().html.add_child(folium.Element(
        sidebar_html(rows_buildings(b_tbl), rows_blocks(k_tbl), rows_landlords(l_tbl), args.sidebar_width)
    ))
    filter_config_json = json.dumps(filter_cfg)
    building_records_map: dict[str, dict[str, Any]] = {}
    for rec in b_tbl.to_dict(orient="records"):
        cleaned = _sanitise_record(rec)
        b_id = cleaned.get("b_id")
        if b_id is None:
            continue
        try:
            b_key = str(int(b_id))
        except (TypeError, ValueError):
            b_key = str(b_id)
        building_records_map[b_key] = cleaned

    building_records_payload = {
        "columns": [str(col) for col in b_tbl.columns],
        "records": building_records_map,
    }

    marker_metadata_json = json.dumps(marker_metadata)
    building_records_json = json.dumps(building_records_payload)
    m.get_root().html.add_child(folium.Element(
        wiring_js(
            blocks_geo.get_name(),
            layer_vtu_name,
            layer_non_name,
            filter_config_json,
            marker_metadata_json,
            building_records_json,
        )
    ))

    legends = legends_html(vmax, args.sidebar_width, filter_cfg)
    for legend in legends:
        m.get_root().html.add_child(folium.Element(legend))

    output_path = _ensure_output_path(Path(args.out))
    m.save(str(output_path))
    logger.info("Wrote %s", output_path)
