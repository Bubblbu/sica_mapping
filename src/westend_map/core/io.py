"""IO helper utilities."""

from __future__ import annotations

import pandas as pd

from .logging import configure_logging, logger


def setup_logging(verbose: bool) -> None:
    """Initialise project logging."""
    configure_logging(verbose)


def read_any_csv(path: str) -> pd.DataFrame:
    """Read a CSV file, trying a few delimiter heuristics."""
    for kwargs in (dict(sep=None, engine="python"), dict(sep=";"), dict()):
        try:
            df = pd.read_csv(path, **kwargs)
            logger.debug("Loaded CSV %s with %s", path, kwargs)
            return df
        except Exception as exc:  # pragma: no cover - error handling is simple logging
            logger.debug("CSV read failed for %s with %s: %s", path, kwargs, exc)
    raise RuntimeError(f"Failed to read CSV: {path}")


def normalize_cols(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with normalised column names."""
    df = df.copy()

    def _clean(col: object) -> str:
        s = str(col).replace("\ufeff", "")
        return s.strip().lower().replace(" ", "_")

    df.columns = [_clean(c) for c in df.columns]
    return df


def require_columns(df: pd.DataFrame, cols: set[str], label: str) -> None:
    """Ensure the expected columns are available."""
    missing = set(cols) - set(df.columns)
    if missing:
        raise RuntimeError(f"{label} missing columns: {sorted(missing)}")
