"""Connection and schema-loading helpers for the sica_core SQLite store."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def get_connection(path: str | Path) -> sqlite3.Connection:
    """Open a connection with foreign key enforcement turned on."""
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection, schema_path: str | Path = SCHEMA_PATH) -> None:
    """Load the schema.

    Safe to call repeatedly: every table except `ownership_claims` is dropped
    and recreated (schema.sql's REBUILDABLE section), while `ownership_claims`
    uses `CREATE TABLE IF NOT EXISTS` and is never touched by a rebuild.
    """
    sql = Path(schema_path).read_text(encoding="utf-8")
    with conn:
        conn.executescript(sql)
