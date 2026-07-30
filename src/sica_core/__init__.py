"""SQLite-backed data layer for SICA Mapping v2.

Lives alongside `sica_mapping` (the current, still-shipping v1 pipeline)
without depending on it. See CLAUDE.md for the v2 rebuild rationale.
"""

from __future__ import annotations

from .db import get_connection, init_db

__all__ = ["get_connection", "init_db"]
