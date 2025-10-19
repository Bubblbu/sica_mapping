"""Utilities for normalising addresses, owners, and coordinates."""

from __future__ import annotations

import ast
import re
import unicodedata
from typing import Any, Tuple

import numpy as np
import pandas as pd


def normalize_street(s: str) -> str:
    s = str(s).strip().lower()
    s = re.sub(r"[.]", "", s)
    s = re.sub(r"\s+", " ", s)
    repl = {
        "street": "st",
        "avenue": "ave",
        "road": "rd",
        "drive": "dr",
        "boulevard": "blvd",
        "place": "pl",
        "court": "ct",
        "highway": "hwy",
        "av": "ave",
    }
    for k, v in repl.items():
        s = re.sub(rf"\b{k}\b", v, s)
    return s


def addr_key_from_freeform(addr: str) -> str:
    addr = str(addr).strip().lower()
    m = re.match(r"^(\d+)\s+(.+)$", addr)
    return f"{m.group(1)} {normalize_street(m.group(2))}" if m else normalize_street(addr)


def parse_lat_lon(s: Any) -> Tuple[float, float]:
    if pd.isna(s):  # type: ignore[arg-type]
        return (np.nan, np.nan)
    m = re.match(r"\s*([\-0-9.]+)\s*,\s*([\-0-9.]+)\s*$", str(s))
    return (float(m.group(1)), float(m.group(2))) if m else (np.nan, np.nan)


def clean_owner_label(name: Any) -> str:
    if pd.isna(name):
        return "(Unknown)"
    s = str(name).strip()
    if not s:
        return "(Unknown)"
    parsed = None
    if s.startswith("[") and s.endswith("]"):
        try:
            parsed = ast.literal_eval(s)
        except (ValueError, SyntaxError):
            parsed = None
    if parsed is None and s.startswith("(") and s.endswith(")"):
        try:
            parsed = ast.literal_eval(s)
        except (ValueError, SyntaxError):
            parsed = None
    if isinstance(parsed, (list, tuple, set)):
        cleaned = [str(item).strip().strip("'\"") for item in parsed if str(item).strip()]
        if cleaned:
            return ", ".join(cleaned)
        return "(Unknown)"
    if isinstance(parsed, str):
        s = parsed.strip()
    if s.startswith(("'", '"')) and s.endswith(("'", '"')) and len(s) >= 2:
        s = s[1:-1]
    stripped = s.strip()
    if stripped.startswith("[") and stripped.endswith("]") and "," not in stripped:
        stripped = stripped[1:-1].strip()
    return stripped or "(Unknown)"


def sanitize_owner(name: Any) -> str:
    if pd.isna(name) or str(name).strip() == "":
        return "unknown"
    s = str(name).lower()
    s = unicodedata.normalize('NFKD', s)
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "unknown"
