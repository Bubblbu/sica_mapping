"""Ingest data/rezoning_applications.csv verbatim into raw_rezoning.

Raw storage only — no name-key matching against buildings happens here.
That logic stays in `src/sica_mapping/data/overlays.py::match_overlays()`.
See raw_sro.py's docstring for why this table exists regardless.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pandas as pd

from ..io import normalize_cols, read_any_csv

RENAME_MAP = {
    # The source's own ID (e.g. "RZ285"); distinct from raw_rezoning_id (our
    # PK). Note it is NOT reliably unique per row — a multi-site "umbrella"
    # application can cover two entirely different addresses as separate
    # rows (confirmed via a real duplicate-key collision, see overlays.py).
    "id": "source_id",
}

RAW_REZONING_COLUMNS = [
    "source_id",
    "name",
    "status",
    "category",
    "status_detail",
    "latitude",
    "longitude",
    "link",
]


def load_raw_rezoning_frame(path: str) -> pd.DataFrame:
    df = normalize_cols(read_any_csv(path))
    df = df.rename(columns=RENAME_MAP)

    unexpected = set(df.columns) - set(RAW_REZONING_COLUMNS)
    if unexpected:
        raise RuntimeError(
            f"rezoning_applications.csv has columns with no raw_rezoning mapping: {sorted(unexpected)}. "
            "Add them to RAW_REZONING_COLUMNS/schema.sql, don't drop silently."
        )

    for col in RAW_REZONING_COLUMNS:
        if col not in df.columns:
            df[col] = None
    return df[RAW_REZONING_COLUMNS]


def ingest_raw_rezoning(conn: sqlite3.Connection, path: str) -> int:
    df = load_raw_rezoning_frame(path)
    ingested_at = datetime.now(timezone.utc).isoformat()
    rows = [
        (*(None if pd.isna(v) else v for v in row), ingested_at)
        for row in df.itertuples(index=False)
    ]
    placeholders = ", ".join(["?"] * (len(RAW_REZONING_COLUMNS) + 1))
    columns_sql = ", ".join(RAW_REZONING_COLUMNS + ["ingested_at"])
    with conn:
        conn.executemany(
            f"INSERT INTO raw_rezoning ({columns_sql}) VALUES ({placeholders})",
            rows,
        )
    return len(rows)
