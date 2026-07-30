"""CSV loading helpers.

Forked from `src/sica_mapping/core/io.py` (see normalize.py's provenance note
for why this is a fork, not an import) minus `setup_logging`, which is a
sica_mapping-specific logging concern this package doesn't need.
"""

from __future__ import annotations

import pandas as pd


def read_any_csv(path: str) -> pd.DataFrame:
    """Read a CSV file, trying a few delimiter heuristics."""
    for kwargs in (dict(sep=None, engine="python"), dict(sep=";"), dict()):
        try:
            return pd.read_csv(path, **kwargs)
        except Exception:
            continue
    raise RuntimeError(f"Failed to read CSV: {path}")


def normalize_cols(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with normalised column names."""
    df = df.copy()

    def _clean(col: object) -> str:
        s = str(col).replace("﻿", "")
        return s.strip().lower().replace(" ", "_")

    df.columns = [_clean(c) for c in df.columns]
    return df


def require_columns(df: pd.DataFrame, cols: set[str], label: str) -> None:
    """Ensure the expected columns are available."""
    missing = set(cols) - set(df.columns)
    if missing:
        raise RuntimeError(f"{label} missing columns: {sorted(missing)}")
