"""Ingest data/coops_vancouver.csv (see scripts/fetch_coops.py) verbatim into raw_coops.

Raw storage only — no address-key matching against buildings happens here.
That logic stays in `src/sica_mapping/data/overlays.py::match_overlays()`.
See raw_sro.py's docstring for why this table exists regardless.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pandas as pd

from ..io import normalize_cols, read_any_csv

RENAME_MAP = {
    "id": "source_id",  # the source's own ID; distinct from raw_coop_id (our PK)
}

RAW_COOPS_COLUMNS = [
    "source_id",
    "title",
    "city",
    "region",
    "neighbourhood",
    "school_district",
    "address",
    "lat",
    "lon",
    "status",
    "ownership_model",
    "bedrooms_min",
    "bedrooms_max",
    "home_types",
    "features",
    "summary",
    "featured_image",
    "website",
    "read_more_url",
]


def load_raw_coops_frame(path: str) -> pd.DataFrame:
    df = normalize_cols(read_any_csv(path))
    df = df.rename(columns=RENAME_MAP)

    unexpected = set(df.columns) - set(RAW_COOPS_COLUMNS)
    if unexpected:
        raise RuntimeError(
            f"coops_vancouver.csv has columns with no raw_coops mapping: {sorted(unexpected)}. "
            "Add them to RAW_COOPS_COLUMNS/schema.sql, don't drop silently."
        )

    for col in RAW_COOPS_COLUMNS:
        if col not in df.columns:
            df[col] = None
    return df[RAW_COOPS_COLUMNS]


def ingest_raw_coops(conn: sqlite3.Connection, path: str) -> int:
    df = load_raw_coops_frame(path)
    ingested_at = datetime.now(timezone.utc).isoformat()
    rows = [
        (*(None if pd.isna(v) else v for v in row), ingested_at)
        for row in df.itertuples(index=False)
    ]
    placeholders = ", ".join(["?"] * (len(RAW_COOPS_COLUMNS) + 1))
    columns_sql = ", ".join(RAW_COOPS_COLUMNS + ["ingested_at"])
    with conn:
        conn.executemany(
            f"INSERT INTO raw_coops ({columns_sql}) VALUES ({placeholders})",
            rows,
        )
    return len(rows)
