"""Data pipeline orchestration for the West End map."""

from __future__ import annotations

import json
import math
import numbers
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from shapely.geometry import shape

from ..core import (
    read_any_csv,
    normalize_cols,
    parse_lat_lon,
    addr_key_from_freeform,
    sanitize_owner,
    ProgressReporter,
    logger,
)
from .spatial import (
    prepare_addresses,
    select_west_end_buildings,
    join_buildings_addresses,
    deduplicate_buildings,
    parse_blocks,
    aggregate_blocks,
)
from .tables import buildings_table, blocks_table, landlords_table
from .vtu import (
    prepare_membership_records,
    membership_records_by_address,
    membership_filter_config,
    compute_vtu_counts,
    attach_vtu_metrics,
)


PIPELINE_CACHE_FILES = {
    "points": "building_points.json",
    "blocks": "blocks.json",
    "filters": "filter_config.json",
}

BUILDING_METRICS = {
    "value_land": {
        "label": "Assessed land value",
        "format": "currency",
        "unit": "$",
        "type": "float",
        "step": 5000,
        "attr": "value-land",
        "bins": 24,
    },
    "value_bldg": {
        "label": "Assessed building value",
        "format": "currency",
        "unit": "$",
        "type": "float",
        "step": 5000,
        "attr": "value-bldg",
        "bins": 24,
    },
    "bldg_land_ratio": {
        "label": "Building / Land ratio",
        "format": "ratio",
        "type": "float",
        "step": 0.05,
        "decimals": 2,
        "attr": "value-ratio",
        "bins": 18,
    },
    "units": {
        "label": "Units",
        "format": "number",
        "type": "int",
        "step": 1,
        "attr": "units",
        "bins": 18,
        "force_log": True,
    },
}


def load_inputs(buildings_path: str, addresses_path: str, blocks_path: str, vtu_path: str):
    bldg_df = normalize_cols(read_any_csv(buildings_path))
    addr_df = normalize_cols(read_any_csv(addresses_path))
    blocks_raw = normalize_cols(read_any_csv(blocks_path))
    vtu_df = normalize_cols(read_any_csv(vtu_path))
    return bldg_df, addr_df, blocks_raw, vtu_df


def _summarize_metric(series: pd.Series, *, meta: dict) -> dict | None:
    data = series.dropna()
    if data.empty:
        return None
    data = data.astype(float)
    min_val = float(np.min(data))
    max_val = float(np.max(data))
    if not np.isfinite(min_val) or not np.isfinite(max_val):
        return None
    positive_min = None
    if np.any(data > 0):
        positive_min = float(np.min(data[data > 0]))
    span = max_val - min_val
    bins = meta.get("bins")
    if bins is None:
        bins = min(24, max(6, int(np.sqrt(len(data)))))
    use_log: bool = False
    can_use_log = positive_min is not None and positive_min > 0.0 and max_val > positive_min
    force_log = bool(meta.get("force_log"))
    if can_use_log:
        explicit = meta.get("use_log")
        if explicit is not None:
            use_log = bool(explicit)
        elif force_log:
            use_log = True
        elif meta.get("type") != "int":
            threshold = float(meta.get("log_threshold", 25.0))
            ratio = max_val / positive_min if positive_min else float("inf")
            use_log = meta.get("format") == "currency" or ratio >= threshold
    if force_log and not use_log and can_use_log:
        use_log = True
    if use_log:
        safe_min = max(positive_min if positive_min and positive_min > 0 else max_val, 1e-6)
        clipped = data.copy()
        non_positive_mask = clipped <= 0
        clipped[non_positive_mask] = safe_min
        log_data = np.log(clipped)
        counts, log_edges = np.histogram(log_data, bins=bins)
        edges = np.exp(log_edges)
        edges[0] = float(min_val if min_val < safe_min else safe_min)
        edges[-1] = float(max_val)
        if non_positive_mask.any():
            counts[0] += int(non_positive_mask.sum())
            edges[0] = float(min_val)
    else:
        counts, edges = np.histogram(data, bins=bins)
    max_count = int(counts.max()) if counts.size else 0
    bins_list = [
        {
            "start": float(edges[i]),
            "end": float(edges[i + 1]),
            "count": int(counts[i]),
        }
        for i in range(len(counts))
    ]
    if len(data) >= 20:
        suggested_min = float(np.percentile(data, 5))
        suggested_max = float(np.percentile(data, 95))
    else:
        suggested_min = min_val
        suggested_max = max_val
    suggested_min = max(min_val, min(suggested_min, max_val))
    suggested_max = min(max_val, max(suggested_max, min_val))
    if suggested_min >= suggested_max:
        suggested_min = min_val
        suggested_max = max_val
    step = meta.get("step")
    if step is None:
        if meta.get("type") == "int":
            step = 1
        else:
            step = span / 200 if span > 0 else max_val / 200 if max_val > 0 else 0.01
    if step == 0:
        step = 1 if meta.get("type") == "int" else 0.01
    decimals = meta.get("decimals")
    if decimals is None:
        decimals = 0 if meta.get("type") == "int" else 2
    attr = meta.get("attr") or meta.get("column", "").replace("_", "-")
    return {
        "label": meta.get("label", meta.get("column")),
        "min": float(min_val),
        "max": float(max_val),
        "suggested_min": float(suggested_min),
        "suggested_max": float(suggested_max),
        "step": float(step),
        "bins": bins_list,
        "max_count": max_count,
        "format": meta.get("format", "number"),
        "unit": meta.get("unit"),
        "type": meta.get("type", "float"),
        "decimals": int(decimals),
        "attr": attr,
        "min_positive": positive_min,
        "use_log": use_log,
    }


def build_building_metrics(pts_df: pd.DataFrame) -> dict[str, dict]:
    summaries: dict[str, dict] = {}
    for column, meta in BUILDING_METRICS.items():
        if column not in pts_df.columns:
            continue
        summary = _summarize_metric(pts_df[column], meta={"column": column, **meta})
        if summary:
            summaries[column] = summary
    return summaries


def _write_cache(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)


def _sanitize_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (np.ndarray, pd.Series, pd.Index)):
        return [_sanitize_value(v) for v in value.tolist()]
    if isinstance(value, (list, tuple, set)):
        return [_sanitize_value(v) for v in list(value)]
    if isinstance(value, dict):
        return {k: _sanitize_value(v) for k, v in value.items()}
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, numbers.Integral):
        return int(value)
    if isinstance(value, numbers.Real):
        if math.isnan(float(value)):
            return None
        return float(value)
    try:
        if pd.isna(value):  # type: ignore[arg-type]
            return None
    except TypeError:
        pass
    return value


def _sanitize_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{k: _sanitize_value(v) for k, v in record.items()} for record in records]


def write_cached_data(data: dict[str, Any], data_dir: Path) -> None:
    data_dir = Path(data_dir)
    logger.info("Writing preprocessed artifacts to %s", data_dir)

    pts_records = _sanitize_records(data["pts"].to_dict(orient="records"))
    _write_cache(data_dir / PIPELINE_CACHE_FILES["points"], pts_records)

    blocks_df = data["blocks"].copy()
    blocks_df["geom_geojson"] = blocks_df["geom_parsed"].apply(lambda geom: geom.__geo_interface__ if geom else None)
    blocks_records = _sanitize_records(blocks_df.drop(columns=["geom_parsed"], errors="ignore").to_dict(orient="records"))
    _write_cache(data_dir / PIPELINE_CACHE_FILES["blocks"], blocks_records)

    filter_cfg = _sanitize_value(data["filter_config"])
    _write_cache(data_dir / PIPELINE_CACHE_FILES["filters"], filter_cfg)


def load_cached_data(data_dir: Path) -> dict[str, Any]:
    data_dir = Path(data_dir)
    logger.info("Loading preprocessed artifacts from %s", data_dir)

    with (data_dir / PIPELINE_CACHE_FILES["points"]).open("r", encoding="utf-8") as handle:
        pts_records = json.load(handle)
    pts_df = pd.DataFrame(pts_records)
    if not pts_df.empty:
        pts_df = pts_df.convert_dtypes()
        if "local_area" not in pts_df.columns:
            pts_df["local_area"] = "(Unknown)"

    with (data_dir / PIPELINE_CACHE_FILES["blocks"]).open("r", encoding="utf-8") as handle:
        blocks_records = json.load(handle)
    blocks_df = pd.DataFrame(blocks_records)
    if not blocks_df.empty:
        blocks_df = blocks_df.convert_dtypes()
        if "geom_geojson" in blocks_df.columns and "geom_parsed" not in blocks_df.columns:
            blocks_df["geom_parsed"] = blocks_df["geom_geojson"].apply(lambda g: shape(g) if g else None)

    with (data_dir / PIPELINE_CACHE_FILES["filters"]).open("r", encoding="utf-8") as handle:
        filter_cfg = json.load(handle)

    return {
        "pts": pts_df,
        "blocks": blocks_df,
        "filter_config": filter_cfg,
    }


def cached_data_exists(data_dir: Path) -> bool:
    data_dir = Path(data_dir)
    return all((data_dir / filename).exists() for filename in PIPELINE_CACHE_FILES.values())


def run_data_pipeline(
    buildings_path: str,
    addresses_path: str,
    blocks_path: str,
    vtu_path: str,
    bbox: tuple[float, float, float, float],
    local_areas: list[str] | None = None,
) -> dict[str, Any]:
    logger.info("Starting data pipeline")
    progress_steps = 9
    with ProgressReporter(progress_steps, label="Data stage") as progress:
        bldg_df, addr_df, blocks_raw, vtu_df = load_inputs(buildings_path, addresses_path, blocks_path, vtu_path)
        progress.step("Loaded source tables")
        logger.info(
            "Loaded datasets — buildings: %d, addresses: %d, blocks: %d, membership rows: %d",
            len(bldg_df),
            len(addr_df),
            len(blocks_raw),
            len(vtu_df),
        )

        addr_df = prepare_addresses(addr_df, parse_lat_lon)
        progress.step("Prepared address coordinates")
        if local_areas:
            logger.info("Filtering to local areas: %s", local_areas)
        west, owner_col = select_west_end_buildings(bldg_df, addr_key_from_freeform, allowed_areas=local_areas)
        total_buildings_raw = len(west)
        unknown_local_areas = int((west["local_area"] == "(Unknown)").sum())
        if unknown_local_areas:
            percent_unknown = (unknown_local_areas / total_buildings_raw * 100.0) if total_buildings_raw else 0.0
            logger.warning(
                "Local area missing for %d of %d buildings (%.1f%%)",
                unknown_local_areas,
                total_buildings_raw,
                percent_unknown,
            )
        progress.step("Selected target buildings")

        joined = join_buildings_addresses(west, addr_df)
        total_joined = len(joined)
        matched_mask = joined["lat"].notna() & joined["lon"].notna()
        matched_count = int(matched_mask.sum())
        unmatched_count = total_joined - matched_count
        if total_joined:
            match_percent = matched_count / total_joined * 100.0
            logger.info(
                "Address match coverage: %d/%d (%.1f%%) buildings matched to coordinates; %d without coordinates",
                matched_count,
                total_joined,
                match_percent,
                unmatched_count,
            )
            if unmatched_count:
                sample_missing = joined.loc[~matched_mask, "address"].dropna().astype(str).head(10).tolist()
                logger.warning("Sample unmatched addresses (first %d): %s", len(sample_missing), sample_missing)
        else:
            logger.info("Address match coverage: no building records after filtering")
        progress.step("Matched buildings with addresses")

        members_df = prepare_membership_records(vtu_df)
        membership_payload = membership_records_by_address(members_df)
        active_counts = compute_vtu_counts(members_df, active_only=True)
        all_counts = compute_vtu_counts(members_df, active_only=False)
        joined["members_payload"] = joined["addr_key"].map(lambda key: membership_payload.get(key, []))
        joined = attach_vtu_metrics(joined, active_counts, all_counts)
        progress.step("Merged VTU membership metrics")

        pts_df = deduplicate_buildings(joined, owner_col, sanitize_owner)
        unique_joined_addresses = int(joined.loc[matched_mask, "addr_key"].nunique())
        dedup_collapsed = max(0, unique_joined_addresses - len(pts_df))
        logger.info(
            "Deduplicated to %d map points (%d duplicate address groups collapsed, %d unmatched dropped)",
            len(pts_df),
            dedup_collapsed,
            unmatched_count,
        )
        remaining_unknown_areas = int((pts_df["local_area"] == "(Unknown)").sum())
        progress.step("Deduplicated building points")
        logger.info(
            "Prepared %d building points (active members: %d, total members: %d, unknown local areas remaining: %d)",
            len(pts_df),
            int(pts_df["member_count"].sum()),
            int(pts_df["member_count_all"].sum()),
            remaining_unknown_areas,
        )

        valid_coords = pts_df.dropna(subset=["lat", "lon"])
        bounds = None
        if not valid_coords.empty:
            lat_min = float(valid_coords["lat"].min())
            lat_max = float(valid_coords["lat"].max())
            lon_min_points = float(valid_coords["lon"].min())
            lon_max_points = float(valid_coords["lon"].max())
            bounds = {
                "lat_min": lat_min,
                "lat_max": lat_max,
                "lon_min": lon_min_points,
                "lon_max": lon_max_points,
                "center_lat": float(valid_coords["lat"].mean()),
                "center_lon": float(valid_coords["lon"].mean()),
            }

        buffer = 0.001 if bounds else 0.0
        if bounds:
            dynamic_bbox = (
                bounds["lon_min"] - buffer,
                bounds["lat_min"] - buffer,
                bounds["lon_max"] + buffer,
                bounds["lat_max"] + buffer,
            )
            if bbox is None:
                blocks_bbox = dynamic_bbox
            else:
                lon_min_combined = min(bbox[0], dynamic_bbox[0])
                lat_min_combined = min(bbox[1], dynamic_bbox[1])
                lon_max_combined = max(bbox[2], dynamic_bbox[2])
                lat_max_combined = max(bbox[3], dynamic_bbox[3])
                blocks_bbox = (lon_min_combined, lat_min_combined, lon_max_combined, lat_max_combined)
        else:
            blocks_bbox = bbox

        blocks_subset = parse_blocks(blocks_raw, blocks_bbox)
        progress.step("Parsed block geometries")
        blocks_merged, pts_df = aggregate_blocks(pts_df, blocks_subset)
        progress.step("Aggregated block statistics")

        filter_cfg = membership_filter_config(members_df)
        building_metrics = build_building_metrics(pts_df)
        filter_cfg["building_metrics"] = building_metrics
        filter_cfg["building_metric_order"] = [key for key in BUILDING_METRICS if key in building_metrics]

        pts_with_area = pts_df.copy()
        pts_with_area["local_area"] = pts_with_area["local_area"].fillna("(Unknown)")
        pts_with_area["units"] = pts_with_area["units"].fillna(0)
        neighbourhood_counts = (
            pts_with_area["local_area"]
            .value_counts()  # type: ignore[arg-type]
            .sort_values(ascending=False)
        )
        neighbourhood_units = (
            pts_with_area.groupby("local_area")["units"].sum().sort_values(ascending=False)
        )
        filter_cfg["neighbourhoods"] = [
            {
                "name": area,
                "count": int(count),
                "units": int(round(neighbourhood_units.get(area, 0))),
            }
            for area, count in neighbourhood_counts.items()
        ]
        filter_cfg["bounds"] = bounds
        total_units = int(pd.to_numeric(pts_df["units"], errors="coerce").fillna(0).sum())
        total_vtu_buildings = int((pts_df["has_vtu_member"]).sum())
        filter_cfg["dataset_totals"] = {
            "buildings": int(len(pts_df)),
            "members": int(pts_df["member_count"].sum()),
            "units": total_units,
            "vtu_buildings": total_vtu_buildings,
        }
        filter_cfg["blocks_total_units_max"] = int(
            blocks_merged["total_units"].max()
        ) if not blocks_merged.empty else 0
        progress.step("Prepared filter metadata")
        progress.finish("Data stage complete")

    data_quality = {
        "buildings_total": int(total_buildings_raw),
        "local_area_unknown": int(unknown_local_areas),
        "address_match_total": int(total_joined),
        "address_match_with_coordinates": int(matched_count),
        "address_match_without_coordinates": int(unmatched_count),
        "address_unique_matched": int(unique_joined_addresses),
        "map_points": int(len(pts_df)),
        "duplicate_addresses_collapsed": int(dedup_collapsed),
        "local_area_unknown_after_enrichment": int(remaining_unknown_areas),
    }

    return {
        "pts": pts_df,
        "blocks": blocks_merged,
        "filter_config": filter_cfg,
        "metadata": {
            "bbox": bbox,
            "record_counts": {
                "buildings_raw": len(bldg_df),
                "addresses_raw": len(addr_df),
                "blocks_raw": len(blocks_raw),
                "members_raw": len(vtu_df),
            },
            "bounds": bounds,
            "data_quality": data_quality,
        },
    }
