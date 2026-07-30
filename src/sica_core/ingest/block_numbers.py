"""Ingest data/block-numbers.csv verbatim into raw_block_numbers."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pandas as pd

from ..io import normalize_cols, read_any_csv

RAW_BLOCK_NUMBERS_COLUMNS = [
    "label",
    "geo_local_area",
    "geom",
    "geo_point_2d",
]


def load_raw_block_numbers_frame(path: str) -> pd.DataFrame:
    df = normalize_cols(read_any_csv(path))
    unexpected = set(df.columns) - set(RAW_BLOCK_NUMBERS_COLUMNS)
    if unexpected:
        raise RuntimeError(
            f"block-numbers.csv has columns with no raw_block_numbers mapping: "
            f"{sorted(unexpected)}. Add them to RAW_BLOCK_NUMBERS_COLUMNS/schema.sql, don't drop silently."
        )
    for col in RAW_BLOCK_NUMBERS_COLUMNS:
        if col not in df.columns:
            df[col] = None
    return df[RAW_BLOCK_NUMBERS_COLUMNS]


def ingest_raw_block_numbers(conn: sqlite3.Connection, path: str) -> int:
    df = load_raw_block_numbers_frame(path)
    ingested_at = datetime.now(timezone.utc).isoformat()
    rows = [
        (*(None if pd.isna(v) else v for v in row), ingested_at)
        for row in df.itertuples(index=False)
    ]
    placeholders = ", ".join(["?"] * (len(RAW_BLOCK_NUMBERS_COLUMNS) + 1))
    columns_sql = ", ".join(RAW_BLOCK_NUMBERS_COLUMNS + ["ingested_at"])
    with conn:
        conn.executemany(
            f"INSERT INTO raw_block_numbers ({columns_sql}) VALUES ({placeholders})",
            rows,
        )
    return len(rows)
