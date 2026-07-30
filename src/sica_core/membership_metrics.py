"""Derives active-membership metrics from vtu_membership's allow-listed columns.

Forked from the parts of `src/sica_mapping/data/vtu.py` that only touch
`tag_list`/`updated_at` (everything else there reads columns this project
deliberately never ingests). Used by both the validation checkpoint and,
eventually, the real public/internal export.

"now" is an explicit parameter, not a bare `pd.Timestamp.utcnow()` call, so
two runs being compared (e.g. the checkpoint vs. a reference run) can't
disagree over a 365-day recency window crossed mid-comparison.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import timedelta

import pandas as pd

MEMBERSHIP_YEAR_RE = re.compile(r"membership-(\d{4})", re.IGNORECASE)
RECENT_ACTIVITY_WINDOW = timedelta(days=365)


def _extract_tags(raw: object) -> list[str]:
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


def prepare_membership_metrics(members_df: pd.DataFrame, now: pd.Timestamp) -> pd.DataFrame:
    df = members_df.copy()
    df["tags"] = df["tag_list"].apply(_extract_tags)
    df["has_member_tag"] = df["tags"].apply(
        lambda tags: any(t.lower() == "member" for t in tags)
    )
    df["latest_membership_year"] = df["tags"].apply(_latest_membership_year)
    df["updated_at_parsed"] = pd.to_datetime(
        df["updated_at"], errors="coerce", utc=True, format="ISO8601"
    )
    df["updated_recently"] = df["updated_at_parsed"].notna() & (
        now - df["updated_at_parsed"] <= RECENT_ACTIVITY_WINDOW
    )
    df["is_active_default"] = df["has_member_tag"] & (
        df["latest_membership_year"].isna()
        | (df["latest_membership_year"] >= now.year - 1)
        | df["updated_recently"]
    )
    return df


def compute_building_member_metrics(members_df: pd.DataFrame, now: pd.Timestamp) -> pd.DataFrame:
    """members_df: vtu_membership rows with a non-null building_id."""
    columns = ["building_id", "member_count", "member_count_all", "has_vtu_member", "members_payload"]
    if members_df.empty:
        return pd.DataFrame(columns=columns)

    metrics = prepare_membership_metrics(members_df, now)
    active_counts = (
        metrics[metrics["is_active_default"]].groupby("building_id").size().rename("member_count_active")
    )
    all_counts = metrics.groupby("building_id").size().rename("member_count_all")

    payload: dict[int, list[dict[str, object]]] = {}
    for building_id, group in metrics.groupby("building_id"):
        records = []
        for row in group.itertuples(index=False):
            updated_val = (
                row.updated_at_parsed.isoformat() if pd.notna(row.updated_at_parsed) else None
            )
            records.append(
                {
                    "tags": list(row.tags),
                    "updated_at": updated_val,
                    "has_member_tag": bool(row.has_member_tag),
                    "latest_membership_year": (
                        None
                        if pd.isna(row.latest_membership_year)
                        else int(row.latest_membership_year)
                    ),
                    "is_active_default": bool(row.is_active_default),
                }
            )
        payload[building_id] = records

    out = pd.concat([active_counts, all_counts], axis=1).reset_index()
    out["member_count_active"] = out["member_count_active"].fillna(0).astype(int)
    out["member_count_all"] = out["member_count_all"].fillna(0).astype(int)
    out["member_count"] = out["member_count_active"]
    out["has_vtu_member"] = out["member_count"] > 0
    out["members_payload"] = out["building_id"].map(payload)
    return out[columns]


def membership_filter_config(members_df: pd.DataFrame, now: pd.Timestamp) -> dict[str, object]:
    metrics = prepare_membership_metrics(members_df, now) if not members_df.empty else members_df
    if members_df.empty:
        year_counts: dict[int, int] = {}
        year_min = None
        year_max = None
        top_tags: list[dict[str, object]] = []
    else:
        year_series = metrics["latest_membership_year"].dropna().astype(int)
        if year_series.empty:
            year_counts = {}
            year_min = None
            year_max = None
        else:
            year_counts = (
                year_series.value_counts().sort_index(ascending=False).head(8).to_dict()
            )
            year_min = int(year_series.min())
            year_max = int(year_series.max())
        tag_counter: Counter[str] = Counter()
        for tags in metrics["tags"]:
            tag_counter.update(t for t in tags if "member" in t.lower())
        top_tags = [
            {"name": tag, "count": count} for tag, count in tag_counter.most_common(12)
        ]
    default_since = (now - RECENT_ACTIVITY_WINDOW).date().isoformat()
    return {
        "membership_years": year_counts,
        "top_tags": top_tags,
        "default_updated_since": default_since,
        "updated_year_min": year_min,
        "updated_year_max": year_max,
    }
