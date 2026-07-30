"""Ingest data/buildings.csv verbatim into raw_buildings.

value_land/value_bldg are kept as TEXT — the source mixes plain numbers with
"$35,407,000.00"-style strings (100% of West End rows use the latter format);
parsing happens at merge time (see ingest/merge.py::_parse_money), not here.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pandas as pd

from ..io import normalize_cols, read_any_csv

# Raw CSV header -> raw_buildings column, for the handful that don't already
# match after normalize_cols() (lowercase + spaces->underscores).
RENAME_MAP = {
    "address_is_primary?": "is_primary_address",
    "prospect?": "prospect",
}

# Intentionally not persisted:
# - unnamed:_0: a row-number artifact from however this CSV was exported, not sourced data.
# - vtu_members / westend_inbox / vtu_main_inbox / vtu_building: a one-off artifact from
#   manually merging buildings.csv with a small organizing-status tracking sheet for a
#   handful of buildings, not a recurring data source. Organizing-status tracking belongs
#   in a dedicated organizer view (its own table, fed on its own cadence) later — not four
#   ad hoc columns bolted onto raw_buildings now.
IGNORED_COLUMNS = {
    "unnamed:_0",
    "vtu_members",
    "westend_inbox",
    "vtu_main_inbox",
    "vtu_building",
}

RAW_BUILDINGS_COLUMNS = [
    "local_area",
    "address",
    "primary_address",
    "is_primary_address",
    "n_pids",
    "pid",
    "units",
    "year_built",
    "bsns_group",
    "bsns_name",
    "bsns_trade_name",
    "bsns_type",
    "value_land",
    "value_bldg",
    "bldg_land_ratio",
    "value_per_unit",
    "zoning",
    "name",
    "management",
    "n_issues",
    "issues_details",
    "notes",
    "prospect",
]


def load_raw_buildings_frame(path: str) -> pd.DataFrame:
    df = normalize_cols(read_any_csv(path))
    df = df.rename(columns=RENAME_MAP)
    df = df.drop(columns=[c for c in IGNORED_COLUMNS if c in df.columns])

    unexpected = set(df.columns) - set(RAW_BUILDINGS_COLUMNS)
    if unexpected:
        raise RuntimeError(
            f"buildings.csv has columns with no raw_buildings mapping: {sorted(unexpected)}. "
            "Add them to RAW_BUILDINGS_COLUMNS/schema.sql or IGNORED_COLUMNS, don't drop silently."
        )

    # See CLAUDE.md / schema design notes: the source mixes plain numbers and
    # currency-formatted strings in these two columns. If a fresh export ever
    # arrives fully numeric, that's a meaningful change worth knowing about
    # explicitly rather than silently accepting either shape.
    for col in ("value_land", "value_bldg"):
        if col in df.columns and df[col].dtype != object:
            raise RuntimeError(
                f"buildings.csv '{col}' column is no longer string-typed "
                f"(dtype={df[col].dtype}) — verify it's still safe to store verbatim as TEXT."
            )

    for col in RAW_BUILDINGS_COLUMNS:
        if col not in df.columns:
            df[col] = None
    return df[RAW_BUILDINGS_COLUMNS]


def ingest_raw_buildings(conn: sqlite3.Connection, path: str) -> int:
    df = load_raw_buildings_frame(path)
    ingested_at = datetime.now(timezone.utc).isoformat()
    rows = [
        (*(None if pd.isna(v) else v for v in row), ingested_at)
        for row in df.itertuples(index=False)
    ]
    placeholders = ", ".join(["?"] * (len(RAW_BUILDINGS_COLUMNS) + 1))
    columns_sql = ", ".join(RAW_BUILDINGS_COLUMNS + ["ingested_at"])
    with conn:
        conn.executemany(
            f"INSERT INTO raw_buildings ({columns_sql}) VALUES ({placeholders})",
            rows,
        )
    return len(rows)
