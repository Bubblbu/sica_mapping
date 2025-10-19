"""Helpers for working with VTU membership exports."""

from __future__ import annotations

import re
from collections import Counter
from datetime import timedelta

import numpy as np
import pandas as pd

from ..core import addr_key_from_freeform


MEMBERSHIP_YEAR_RE = re.compile(r"membership-(\d{4})", re.IGNORECASE)
RECENT_ACTIVITY_WINDOW = timedelta(days=365)


def _extract_tags(raw: str | float | None) -> list[str]:
    if not isinstance(raw, str):
        return []
    return [t.strip() for t in raw.split(",") if t.strip()]


def _latest_membership_year(tags: list[str]) -> int | None:
    years = []
    for tag in tags:
        match = MEMBERSHIP_YEAR_RE.search(tag)
        if match:
            years.append(int(match.group(1)))
    return max(years) if years else None


def prepare_membership_records(vtu_df: pd.DataFrame) -> pd.DataFrame:
    df = vtu_df.copy()
    addr_cols = [c for c in df.columns if "address" in c or c == "address"]
    addr_col = addr_cols[0] if addr_cols else df.columns[0]
    df["addr_key"] = df[addr_col].fillna("").apply(addr_key_from_freeform)
    df["tags"] = df.get("tag_list", pd.Series([None] * len(df))).apply(_extract_tags)
    df["has_member_tag"] = df["tags"].apply(lambda tags: any(t.lower() == "member" for t in tags))
    df["latest_membership_year"] = df["tags"].apply(_latest_membership_year)
    df["updated_at"] = pd.to_datetime(df.get("updated_at"), errors="coerce", utc=True, format="ISO8601")
    now = pd.Timestamp.utcnow()
    df["updated_recently"] = df["updated_at"].notna() & (now - df["updated_at"] <= RECENT_ACTIVITY_WINDOW)
    df["is_active_default"] = df["has_member_tag"] & (
        df["latest_membership_year"].isna()
        | (df["latest_membership_year"] >= now.year - 1)
        | df["updated_recently"]
    )
    return df


def membership_records_by_address(members_df: pd.DataFrame) -> dict[str, list[dict[str, object]]]:
    payload: dict[str, list[dict[str, object]]] = {}
    for addr_key, group in members_df.groupby("addr_key"):
        records = []
        for row in group.itertuples(index=False):
            updated_at = getattr(row, "updated_at", pd.NaT)
            updated_val = updated_at.isoformat() if isinstance(updated_at, pd.Timestamp) else None
            latest_year = getattr(row, "latest_membership_year", None)
            if pd.notna(latest_year):
                try:
                    latest_year = int(latest_year)
                except (TypeError, ValueError):
                    latest_year = None
            else:
                latest_year = None
            records.append({
                "tags": list(getattr(row, "tags", [])),
                "updated_at": updated_val,
                "has_member_tag": bool(getattr(row, "has_member_tag", False)),
                "latest_membership_year": latest_year,
                "is_active_default": bool(getattr(row, "is_active_default", False)),
            })
        payload[addr_key] = records
    return payload


def compute_vtu_counts(members_df: pd.DataFrame, *, active_only: bool = True) -> pd.DataFrame:
    df = members_df.copy()
    if active_only:
        df = df[df["is_active_default"]]
    member_count_col = next(
        (c for c in df.columns if "member" in c and ("count" in c or c.endswith("s"))),
        None,
    )
    if member_count_col and member_count_col in df.columns and pd.api.types.is_numeric_dtype(df[member_count_col]):
        counts = df.groupby("addr_key")[member_count_col].sum().rename(
            "member_count_active" if active_only else "member_count_all"
        ).reset_index()
    else:
        label = "member_count_active" if active_only else "member_count_all"
        counts = df.groupby("addr_key").size().rename(label).reset_index()
    return counts


def membership_filter_config(members_df: pd.DataFrame) -> dict[str, object]:
    year_series = members_df["latest_membership_year"].dropna().astype(int)
    if year_series.empty:
        year_counts: dict[int, int] = {}
        year_min = None
        year_max = None
    else:
        year_counts = year_series.value_counts().sort_index(ascending=False).head(8).to_dict()
        year_min = int(year_series.min())
        year_max = int(year_series.max())
    tag_counter: Counter[str] = Counter()
    for tags in members_df["tags"]:
        tag_counter.update(t for t in tags if "member" in t.lower())
    top_tags = [{"name": tag, "count": count} for tag, count in tag_counter.most_common(12)]
    default_since = (pd.Timestamp.utcnow() - RECENT_ACTIVITY_WINDOW).date().isoformat()
    return {
        "membership_years": year_counts,
        "top_tags": top_tags,
        "default_updated_since": default_since,
        "updated_year_min": year_min,
        "updated_year_max": year_max,
    }


def attach_vtu_metrics(
    joined: pd.DataFrame,
    active_counts: pd.DataFrame,
    all_counts: pd.DataFrame | None = None,
) -> pd.DataFrame:
    df = joined.merge(active_counts, on="addr_key", how="left")
    df["member_count_active"] = df["member_count_active"].fillna(0).astype(int)
    if all_counts is not None:
        df = df.merge(all_counts, on="addr_key", how="left")
        df["member_count_all"] = df["member_count_all"].fillna(df["member_count_active"]).astype(int)
    else:
        df["member_count_all"] = df["member_count_active"]
    df["member_count"] = df["member_count_active"]
    df["has_vtu_member"] = df["member_count"] > 0
    df["member_share_building"] = np.where(
        (df["units"] > 0) & (~df["units"].isna()),
        np.minimum(df["member_count"] / df["units"], 1.0),
        0.0,
    )
    return df
