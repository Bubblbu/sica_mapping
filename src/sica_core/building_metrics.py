"""Histogram-binning for the sidebar's value/units filter sliders.

Forked verbatim from `src/sica_mapping/data/pipeline.py`'s `BUILDING_METRICS`/
`_summarize_metric`/`build_building_metrics` (see normalize.py's provenance
note). Pure, no I/O — `wiring.js`'s `buildMetricControls()` silently omits
the filter section when `filter_config.json` lacks a `building_metrics` key,
so this needs to be a real, faithful port, not a "close enough" summary.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

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
    can_use_log = (
        positive_min is not None and positive_min > 0.0 and max_val > positive_min
    )
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
        safe_min = max(
            positive_min if positive_min and positive_min > 0 else max_val, 1e-6
        )
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
        {"start": float(edges[i]), "end": float(edges[i + 1]), "count": int(counts[i])}
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
