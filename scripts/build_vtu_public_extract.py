#!/usr/bin/env python3
"""Builds the committed, address-aggregated VTU membership extract.

Reads the raw, un-anonymized local NationBuilder export
(data/membership_full.csv — gitignored, never committed; see
feedback_never_commit_raw_membership_csvs in the assistant's memory for why)
and writes data/vtu_membership_public.csv: one row per address with
member_count_active, member_count_all, and latest_membership_year only.

No per-member rows, tags, or timestamps ever reach the output — that would
let anyone tie a specific membership year/update time to one person's
address. The output resolution matches exactly what the built map already
shows on a building's marker (a count), never more, so it's safe to commit
and is what config.toml's `vtu` path should point at.

Usage: uv run python scripts/build_vtu_public_extract.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from sica_mapping.core import read_any_csv, normalize_cols  # noqa: E402
from sica_mapping.data import prepare_membership_records, compute_vtu_counts  # noqa: E402
from sica_mapping.data.vtu import compute_latest_membership_year  # noqa: E402

RAW_PATH = REPO_ROOT / "data" / "membership_full.csv"
OUT_PATH = REPO_ROOT / "data" / "vtu_membership_public.csv"


def main() -> int:
    if not RAW_PATH.exists():
        print(
            f"{RAW_PATH} not found. This raw NationBuilder export is gitignored "
            "and must be supplied locally (it is never committed) to regenerate "
            "the public extract.",
            file=sys.stderr,
        )
        return 1

    vtu_df = normalize_cols(read_any_csv(str(RAW_PATH)))
    members_df = prepare_membership_records(vtu_df)

    active = compute_vtu_counts(members_df, active_only=True)
    all_ = compute_vtu_counts(members_df, active_only=False)
    latest_year = compute_latest_membership_year(members_df)

    out = active.merge(all_, on="addr_key", how="outer").merge(
        latest_year, on="addr_key", how="outer"
    )
    out["member_count_active"] = out["member_count_active"].fillna(0).astype(int)
    out["member_count_all"] = (
        out["member_count_all"].fillna(out["member_count_active"]).astype(int)
    )
    out = out.sort_values("addr_key").reset_index(drop=True)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT_PATH, index=False)
    print(f"Wrote {len(out)} address-level rows to {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
