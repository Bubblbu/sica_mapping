"""Ingest data/local-area-boundary.csv verbatim into raw_local_areas.

Vancouver Open Data's 22 official local-area boundary polygons. Raw storage
only — the point-in-polygon lookup that resolves an unmatched overlay
record's `local_area` (see ingest/overlays.py) reads these rows straight
from SQLite rather than re-parsing the CSV. Previously only sica_mapping
consumed this file (src/sica_mapping/data/overlays.py); it becomes a
sica_core raw source so overlay matching can move into the pipeline.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pandas as pd

from ..io import normalize_cols, read_any_csv

RAW_LOCAL_AREAS_COLUMNS = [
    "name",
    "geom",  # GeoJSON polygon, verbatim
    "geo_point_2d",  # "lat, lon" verbatim
]


def load_raw_local_areas_frame(path: str) -> pd.DataFrame:
    df = normalize_cols(read_any_csv(path))
    unexpected = set(df.columns) - set(RAW_LOCAL_AREAS_COLUMNS)
    if unexpected:
        raise RuntimeError(
            f"local-area-boundary.csv has columns with no raw_local_areas mapping: "
            f"{sorted(unexpected)}. Add them to RAW_LOCAL_AREAS_COLUMNS/schema.sql, don't drop silently."
        )
    for col in RAW_LOCAL_AREAS_COLUMNS:
        if col not in df.columns:
            df[col] = None
    return df[RAW_LOCAL_AREAS_COLUMNS]


def ingest_raw_local_areas(conn: sqlite3.Connection, path: str) -> int:
    df = load_raw_local_areas_frame(path)
    ingested_at = datetime.now(timezone.utc).isoformat()
    rows = [
        (*(None if pd.isna(v) else v for v in row), ingested_at)
        for row in df.itertuples(index=False)
    ]
    placeholders = ", ".join(["?"] * (len(RAW_LOCAL_AREAS_COLUMNS) + 1))
    columns_sql = ", ".join(RAW_LOCAL_AREAS_COLUMNS + ["ingested_at"])
    with conn:
        conn.executemany(
            f"INSERT INTO raw_local_areas ({columns_sql}) VALUES ({placeholders})",
            rows,
        )
    return len(rows)
