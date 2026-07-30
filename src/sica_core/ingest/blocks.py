"""Ingest data/block-outlines.csv into blocks.

Every block row is kept — the bbox filter is recorded as `in_west_end_bbox`,
not used to drop rows, so the table stays fully browsable (see schema notes).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from ..geometry import parse_geom
from ..io import normalize_cols, read_any_csv


def ingest_blocks(
    conn: sqlite3.Connection,
    path: str,
    bbox: tuple[float, float, float, float],
) -> int:
    df = normalize_cols(read_any_csv(path))
    lon_min, lat_min, lon_max, lat_max = bbox
    ingested_at = datetime.now(timezone.utc).isoformat()

    rows = []
    for raw_geom in df["geom"]:
        geom = parse_geom(raw_geom)
        if geom is None:
            continue
        gb = geom.bounds
        in_bbox = not (
            gb[2] < lon_min or gb[0] > lon_max or gb[3] < lat_min or gb[1] > lat_max
        )
        rows.append((raw_geom, int(in_bbox), None, ingested_at))

    with conn:
        conn.executemany(
            "INSERT INTO blocks (geom, in_west_end_bbox, source_row_ids, ingested_at) "
            "VALUES (?, ?, ?, ?)",
            rows,
        )
    return len(rows)
