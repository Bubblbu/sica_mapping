"""Ingest data/property_addresses.csv verbatim into raw_addresses."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pandas as pd

from ..io import normalize_cols, read_any_csv

RAW_ADDRESSES_COLUMNS = [
    "civic_number",
    "geo_local_area",
    "geom",
    "p_parcel_id",
    "pcoord",
    "site_id",
    "std_street",
    "geo_point_2d",
]


def load_raw_addresses_frame(path: str) -> pd.DataFrame:
    df = normalize_cols(read_any_csv(path))
    unexpected = set(df.columns) - set(RAW_ADDRESSES_COLUMNS)
    if unexpected:
        raise RuntimeError(
            f"property_addresses.csv has columns with no raw_addresses mapping: "
            f"{sorted(unexpected)}. Add them to RAW_ADDRESSES_COLUMNS/schema.sql, don't drop silently."
        )
    for col in RAW_ADDRESSES_COLUMNS:
        if col not in df.columns:
            df[col] = None
    return df[RAW_ADDRESSES_COLUMNS]


def ingest_raw_addresses(conn: sqlite3.Connection, path: str) -> int:
    df = load_raw_addresses_frame(path)
    ingested_at = datetime.now(timezone.utc).isoformat()
    rows = [
        (*(None if pd.isna(v) else v for v in row), ingested_at)
        for row in df.itertuples(index=False)
    ]
    placeholders = ", ".join(["?"] * (len(RAW_ADDRESSES_COLUMNS) + 1))
    columns_sql = ", ".join(RAW_ADDRESSES_COLUMNS + ["ingested_at"])
    with conn:
        conn.executemany(
            f"INSERT INTO raw_addresses ({columns_sql}) VALUES ({placeholders})",
            rows,
        )
    return len(rows)
