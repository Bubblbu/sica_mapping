#!/usr/bin/env python3
"""Builds the committed, address-aggregated VTU membership extract.

Reads the raw, un-anonymized local NationBuilder export (config's `vtu_raw`
path, e.g. data/Nationbuilder/membership_full.csv — gitignored, never
committed; see feedback_never_commit_raw_membership_csvs in the assistant's
memory for why) and writes the address-level aggregate to config's `vtu`
path (data/vtu_membership_public.csv): one row per address with
member_count_active, member_count_all, and latest_membership_year only.

No per-member rows, tags, or timestamps ever reach the output — that would
let anyone tie a specific membership year/update time to one person's
address. The output resolution matches exactly what the built map already
shows on a building's marker (a count), never more, so it's safe to commit.

Both paths are read from config.toml rather than hardcoded here, so this
script and sica_mapping's build (which reads the same `vtu` key) can't
silently drift apart the way they did once already.

Usage: uv run python scripts/build_vtu_public_extract.py [--config config.toml]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - only for <3.11
    tomllib = None

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from sica_mapping.core import read_any_csv, normalize_cols  # noqa: E402
from sica_mapping.data import prepare_membership_records, compute_vtu_counts  # noqa: E402
from sica_mapping.data.vtu import compute_latest_membership_year  # noqa: E402


def _load_paths(config_path: Path) -> tuple[Path, Path]:
    if tomllib is None:
        raise RuntimeError("tomllib not available; upgrade to Python 3.11+.")
    raw = tomllib.loads(config_path.read_text())
    paths = raw.get("paths", {})
    try:
        raw_path = paths["vtu_raw"]
        out_path = paths["vtu"]
    except KeyError as exc:
        raise ValueError(f"{config_path} is missing paths.{exc.args[0]}") from exc
    return REPO_ROOT / raw_path, REPO_ROOT / out_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(REPO_ROOT / "config.toml"))
    args = parser.parse_args()

    raw_path, out_path = _load_paths(Path(args.config))

    if not raw_path.exists():
        print(
            f"{raw_path} not found. This raw NationBuilder export is gitignored "
            "and must be supplied locally (it is never committed) to regenerate "
            "the public extract.",
            file=sys.stderr,
        )
        return 1

    vtu_df = normalize_cols(read_any_csv(str(raw_path)))
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

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_path, index=False)
    print(f"Wrote {len(out)} address-level rows to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
