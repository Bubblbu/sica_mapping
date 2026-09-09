"""Ingest data/sra_housing_combined.csv verbatim into raw_sro.

Raw storage only — no address-key matching against buildings happens here.
That logic (and its own reasons for existing independently — see its
docstring) stays in `src/sica_mapping/data/overlays.py::match_overlays()`,
which runs at map-render time against the CSV directly. This table exists
so the SRO/SRA source is actually browsable from sica_core's SQLite store
(CLAUDE.md Q8b), same as raw_buildings/raw_addresses.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pandas as pd

from ..io import normalize_cols, read_any_csv

# Raw CSV header -> raw_sro column, for the two that don't already match
# after normalize_cols() (lowercase + spaces->underscores).
RENAME_MAP = {
    "id": "source_id",  # the source's own ID; distinct from raw_sro_id (our PK)
    "#_registered_rooms": "registered_rooms",
}

RAW_SRO_COLUMNS = [
    "source_id",
    "address",
    "building_name",
    "secondary_address",
    "area",
    "latitude",
    "longitude",
    "owner",
    "operator",
    "operator_group",
    "ownership_group",
    "registered_rooms",
    "occupancy_status",
    "match_method",  # upstream address-matching flag from whoever combined the source lists; kept verbatim, unused here
]


def load_raw_sro_frame(path: str) -> pd.DataFrame:
    df = normalize_cols(read_any_csv(path))
    df = df.rename(columns=RENAME_MAP)

    unexpected = set(df.columns) - set(RAW_SRO_COLUMNS)
    if unexpected:
        raise RuntimeError(
            f"sra_housing_combined.csv has columns with no raw_sro mapping: {sorted(unexpected)}. "
            "Add them to RAW_SRO_COLUMNS/schema.sql, don't drop silently."
        )

    for col in RAW_SRO_COLUMNS:
        if col not in df.columns:
            df[col] = None
    return df[RAW_SRO_COLUMNS]


def ingest_raw_sro(conn: sqlite3.Connection, path: str) -> int:
    df = load_raw_sro_frame(path)
    ingested_at = datetime.now(timezone.utc).isoformat()
    rows = [
        (*(None if pd.isna(v) else v for v in row), ingested_at)
        for row in df.itertuples(index=False)
    ]
    placeholders = ", ".join(["?"] * (len(RAW_SRO_COLUMNS) + 1))
    columns_sql = ", ".join(RAW_SRO_COLUMNS + ["ingested_at"])
    with conn:
        conn.executemany(
            f"INSERT INTO raw_sro ({columns_sql}) VALUES ({placeholders})",
            rows,
        )
    return len(rows)
