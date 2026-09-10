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
    local_area_boundaries_feature_collection,
    match_overlays,
    buildings_table,
    blocks_table,
    landlords_table,
    neighbourhoods_table,
    rows_buildings,
    rows_blocks,
    rows_landlords,
    rows_neighbourhoods,
    rows_synthetic,
)
from .frontend import (
    add_blocks_layer,
    add_buildings_layers,
    add_neighbourhoods_layer,
    add_unmatched_overlay_layers,
    sidebar_html,
    wiring_js,
    legends_html,
)


# Named keyless basemaps. CARTO retired unauthenticated access to its
# positron/voyager raster tiles, so `cartodbpositron` now renders an
# "add an API key" placeholder. `esri-gray` is the closest drop-in that
# needs no key — Esri's Light Gray Canvas (attribution only), with the
# matching reference layer for street/place labels so it reads like
# positron rather than a blank grey sheet.
_ESRI_CANVAS = "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas"
_ESRI_GRAY_ATTR = (
    "Tiles © Esri — Esri, HERE, Garmin, © OpenStreetMap contributors"
)
_BASEMAPS: dict[str, dict[str, str]] = {
    "esri-gray": {
        "tiles": f"{_ESRI_CANVAS}/World_Light_Gray_Base/MapServer/tile/{{z}}/{{y}}/{{x}}",
        "attr": _ESRI_GRAY_ATTR,
        "labels": f"{_ESRI_CANVAS}/World_Light_Gray_Reference/MapServer/tile/{{z}}/{{y}}/{{x}}",
    },
    "esri-gray-plain": {  # same, without the street/place label layer
        "tiles": f"{_ESRI_CANVAS}/World_Light_Gray_Base/MapServer/tile/{{z}}/{{y}}/{{x}}",
        "attr": _ESRI_GRAY_ATTR,
    },
}


def _resolve_basemap(
    name: str | None, attr_override: str | None
) -> dict[str, str | None]:
    """Turn a `--tiles` value into folium.Map kwargs.

    - a key in _BASEMAPS  -> that preset (attr_override wins if given)
    - a raw tile URL      -> passed through; an attribution is required
    - anything else        -> a folium built-in name ("OpenStreetMap", ...),
                              folium supplies the attribution itself
    """
    preset = _BASEMAPS.get(name or "")
    if preset:
        attr = attr_override or preset["attr"]
        return {
            "tiles": preset["tiles"],
            "attr": attr,
            "labels": preset.get("labels"),
            "labels_attr": attr,
        }
    if name and name.startswith(("http://", "https://")):
        if not attr_override:
            raise ValueError(
                "a raw tile URL in --tiles / [options].tiles needs an attribution "
                "(--attr or [options].attr)"
            )
        return {"tiles": name, "attr": attr_override, "labels": None, "labels_attr": None}
    return {"tiles": name, "attr": attr_override, "labels": None, "labels_attr": None}


def _ensure_output_path(path: Path) -> Path:
    original = Path(path)
    if original.is_absolute():
        target = Path("www") / original.name
    else:
        target = (
            original
            if original.parts and original.parts[0] == "www"
            else Path("www") / original
        )
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
        pipeline_data = run_data_pipeline(
            args.buildings,
            args.addresses,
            args.blocks,
            args.block_numbers,
            args.vtu,
            bbox,
            local_areas,
        )
        if data_dir:
            write_cached_data(pipeline_data, data_dir)
        else:
            logger.warning(
                "Data stage requested but no data directory specified; skipping cache write"
            )
        if args.stage == "data":
            return

    if pipeline_data is None:
        if data_dir and cached_data_exists(data_dir):
            pipeline_data = load_cached_data(data_dir)
            if (
                "blocks" in pipeline_data
                and "geom_geojson" in pipeline_data["blocks"].columns
                and "geom_parsed" not in pipeline_data["blocks"].columns
            ):
                pipeline_data["blocks"]["geom_parsed"] = pipeline_data["blocks"][
                    "geom_geojson"
                ].apply(lambda g: shape(g) if g else None)
        else:
            pipeline_data = run_data_pipeline(
                args.buildings,
                args.addresses,
                args.blocks,
                args.block_numbers,
                args.vtu,
                bbox,
                local_areas,
            )
            if data_dir:
                write_cached_data(pipeline_data, data_dir)

    pts_df: pd.DataFrame = pipeline_data["pts"].copy()
    blocks_merged: pd.DataFrame = pipeline_data["blocks"].copy()
    if "geom_parsed" not in blocks_merged and "geom_geojson" in blocks_merged:
        blocks_merged["geom_parsed"] = blocks_merged["geom_geojson"].apply(
            lambda g: shape(g) if g else None
        )
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

    basemap = _resolve_basemap(args.tiles, getattr(args, "attr", None))
    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=zoom_start,
        tiles=basemap["tiles"],
        attr=basemap["attr"],
        prefer_canvas=True,
    )
    # Street/place labels for the grey basemaps — added before the data
    # layers so markers and choropleths sit on top of it, like positron.
    if basemap["labels"]:
        folium.TileLayer(
            basemap["labels"],
            attr=basemap["labels_attr"],
            name="labels",
            overlay=True,
            control=False,
        ).add_to(m)
    # local_area_boundary_fc loads before match_overlays() — needed for its
    # point-in-polygon local-area lookup for unmatched overlay records — and
    # match_overlays() enriches pts_df before anything downstream (marker
    # rendering, table building) reads housing_type/rezoning_* columns.
    neighbourhoods_fc = local_area_boundaries_feature_collection(args.local_area_boundary)
    overlay_result = match_overlays(
        pts_df,
        coops_path=getattr(args, "coops", None),
        sro_path=getattr(args, "sro_housing", None),
        rezoning_path=getattr(args, "rezoning_applications", None),
        local_area_boundary_fc=neighbourhoods_fc,
    )
    pts_df = overlay_result.pts_df

    fc = blocks_feature_collection(blocks_merged)
    blocks_geo = add_blocks_layer(m, fc)
    neighbourhoods_geo = add_neighbourhoods_layer(m, neighbourhoods_fc)
    # Unmatched overlay markers are added to the SAME shared canvas
    # (prefer_canvas=True) as buildings, and canvas z-order is just
    # insertion order — so this needs to run BEFORE add_buildings_layers(),
    # not after, or every unmatched marker paints (and steals clicks) on
    # top of every building marker. wiring.js's sendBuildingsToFront() is
    # the runtime backstop for when a checkbox toggle re-inserts buildings
    # anyway (see its docstring for why that alone isn't enough).
    _unmatched_layers, _unmatched_layer_names, unmatched_marker_metadata = (
        add_unmatched_overlay_layers(m, overlay_result.unmatched_records)
    )
    _layer_vtu, _layer_non, layer_vtu_name, layer_non_name, marker_metadata = (
        add_buildings_layers(m, pts_df)
    )
    marker_metadata.extend(unmatched_marker_metadata)

    if bounds_info and all(
        k in bounds_info for k in ("lat_min", "lon_min", "lat_max", "lon_max")
    ):
        m.fit_bounds(
            [
                [bounds_info["lat_min"], bounds_info["lon_min"]],
                [bounds_info["lat_max"], bounds_info["lon_max"]],
            ]
        )
    elif not pts_df.dropna(subset=["lat", "lon"]).empty:
        valid_coords = pts_df.dropna(subset=["lat", "lon"])
        m.fit_bounds(
            [
                [float(valid_coords["lat"].min()), float(valid_coords["lon"].min())],
                [float(valid_coords["lat"].max()), float(valid_coords["lon"].max())],
            ]
        )

    b_tbl = buildings_table(pts_df)
    k_tbl = blocks_table(blocks_merged)
    l_tbl = landlords_table(pts_df)
    n_tbl = neighbourhoods_table(pts_df)
    buildings_rows_html = (
        rows_buildings(b_tbl) + "\n" + rows_synthetic(overlay_result.unmatched_records)
    )
    m.get_root().html.add_child(
        folium.Element(
            sidebar_html(
                buildings_rows_html,
                rows_blocks(k_tbl),
                rows_landlords(l_tbl),
                rows_neighbourhoods(n_tbl),
                args.sidebar_width,
            )
        )
    )
    output_path = _ensure_output_path(Path(args.out))
    output_dir = output_path.parent
    asset_base = output_path.stem or "index"

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

    for rec in overlay_result.unmatched_records:
        building_records_map[str(rec["synthetic_id"])] = _sanitise_record(
            {
                "b_id": rec["synthetic_id"],
                "address": rec.get("address"),
                "local_area": rec.get("local_area"),
                "housing_type": rec.get("housing_type"),
                "rezoning_status": rec.get("rezoning_status"),
                "source": rec.get("source"),
            }
        )

    building_records_payload = {
        "columns": [str(col) for col in b_tbl.columns],
        "records": building_records_map,
    }

    filter_config_name = f"{asset_base}_filter_config.json"
    marker_metadata_name = f"{asset_base}_marker_metadata.json"
    building_records_name = f"{asset_base}_building_records.json"

    (output_dir / filter_config_name).write_text(
        json.dumps(filter_cfg, separators=(",", ":")),
        encoding="utf-8",
    )
    (output_dir / marker_metadata_name).write_text(
        json.dumps(marker_metadata, separators=(",", ":")),
        encoding="utf-8",
    )
    (output_dir / building_records_name).write_text(
        json.dumps(building_records_payload, separators=(",", ":")),
        encoding="utf-8",
    )

    m.get_root().html.add_child(
        folium.Element(
            wiring_js(
                blocks_geo.get_name(),
                layer_vtu_name,
                layer_non_name,
                neighbourhoods_geo.get_name(),
                filter_config_name,
                marker_metadata_name,
                building_records_name,
            )
        )
    )

    legends = legends_html(args.sidebar_width, filter_cfg)
    for legend in legends:
        m.get_root().html.add_child(folium.Element(legend))

    m.save(str(output_path))
    logger.info("Wrote %s", output_path)
