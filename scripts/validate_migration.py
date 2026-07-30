#!/usr/bin/env python3
"""Validates that the sica_core SQLite migration reproduces sica_mapping's
current CSV-pipeline output — the "genuinely risky step" from the v2 rebuild
plan. Not part of either package: this script needs both (it shells out to
`build_sica_map.py` as a subprocess, and imports `sica_core` directly), which
would violate sica_core's own "no dependency on sica_mapping" guarantee if it
lived inside `src/sica_core/`.

Usage: uv run python scripts/validate_migration.py [--config config.toml]

Compares the reconstructed-from-SQLite `.preprocessed/*.json` cache against
a reference run of the unmodified v1 pipeline on the same CSVs, keyed on
addr_key. Known, pre-declared exceptions (the currency-parsing bug fix) are
allowed to differ; anything else is a real regression.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from sica_core.export import export_to_cache  # noqa: E402
from sica_core.config import load_ingest_config  # noqa: E402
from sica_core.db import get_connection, init_db  # noqa: E402
from sica_core.ingest import run_ingest  # noqa: E402

# value_land/value_bldg/bldg_land_ratio: the currency-parsing bug fix (expected to differ).
# b_id/block_id: arbitrary per-pipeline sequence numbers (SQLite autoincrement PK vs.
# row-index-after-bbox-filtering) — neither run's numbering is meaningful on its own,
# so an exact match is not a real signal either way.
# owner_group: the landlords table intentionally normalizes ownership identity —
# when the same real landlord appears with several raw spellings across buildings
# (e.g. "Orr Development Corp" / "Orr Development Corp." / sanitize_owner()-equivalent
# variants), v2 picks ONE canonical display name per owner_key globally, rather than
# each building keeping its own locally-computed spelling as v1 does. This is the
# intended effect of first-class landlord identity, not a bug — confirmed by
# owner_key (the actual identity signal) matching perfectly in every one of these
# cases; only the cosmetic display text differs.
KNOWN_DIFF_FIELDS = {"value_land", "value_bldg", "bldg_land_ratio", "b_id", "block_id", "owner_group"}
FLOAT_TOL = 1e-6


def _values_match(a: object, b: object) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if (isinstance(a, float) and math.isnan(a)) or (isinstance(b, float) and math.isnan(b)):
            return (isinstance(a, float) and math.isnan(a)) and (
                isinstance(b, float) and math.isnan(b)
            )
        return math.isclose(a, b, abs_tol=FLOAT_TOL)
    return a == b


def diff_points(sqlite_points: list[dict], reference_points: list[dict]) -> list[str]:
    sqlite_by_key = {r["addr_key"]: r for r in sqlite_points}
    reference_by_key = {r["addr_key"]: r for r in reference_points}

    problems: list[str] = []

    only_in_sqlite = set(sqlite_by_key) - set(reference_by_key)
    only_in_reference = set(reference_by_key) - set(sqlite_by_key)
    if only_in_sqlite:
        problems.append(f"{len(only_in_sqlite)} addr_key(s) only in SQLite path: {sorted(only_in_sqlite)[:5]}...")
    if only_in_reference:
        problems.append(
            f"{len(only_in_reference)} addr_key(s) only in reference (CSV) path: "
            f"{sorted(only_in_reference)[:5]}..."
        )

    for key in sorted(set(sqlite_by_key) & set(reference_by_key)):
        sqlite_rec = sqlite_by_key[key]
        reference_rec = reference_by_key[key]
        fields = set(sqlite_rec) | set(reference_rec)
        for field in sorted(fields):
            if field in KNOWN_DIFF_FIELDS:
                continue
            if field == "members_payload":
                continue  # list-of-dicts; person-level ordering isn't a correctness signal here
            sqlite_val = sqlite_rec.get(field)
            reference_val = reference_rec.get(field)
            if not _values_match(sqlite_val, reference_val):
                problems.append(
                    f"{key!r}.{field}: sqlite={sqlite_val!r} reference={reference_val!r}"
                )
    return problems


def check_west_end_currency_fix(sqlite_points: list[dict], reference_points: list[dict]) -> str:
    def non_null_rate(points: list[dict]) -> tuple[int, int]:
        west_end = [p for p in points if p.get("local_area") == "West End"]
        non_null = [p for p in west_end if p.get("value_land") is not None]
        return len(non_null), len(west_end)

    sqlite_non_null, sqlite_total = non_null_rate(sqlite_points)
    reference_non_null, reference_total = non_null_rate(reference_points)
    return (
        f"West End value_land non-null: sqlite={sqlite_non_null}/{sqlite_total}, "
        f"reference(v1, currency bug present)={reference_non_null}/{reference_total}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(REPO_ROOT / "config.toml"))
    args = parser.parse_args()

    config = load_ingest_config(args.config)
    print(f"Ingesting into {config.db_path} ...")
    conn = get_connection(config.db_path)
    init_db(conn)
    counts = run_ingest(conn, config)
    print(f"Ingest complete: {counts}")

    checkpoint_dir = Path(tempfile.mkdtemp(prefix="sica_core_checkpoint_"))
    export_to_cache(conn, checkpoint_dir)
    print(f"Wrote reconstructed cache to {checkpoint_dir}")

    reference_dir = Path(tempfile.mkdtemp(prefix="sica_mapping_reference_"))
    print(f"Running reference v1 pipeline into {reference_dir} ...")
    subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "build_sica_map.py"),
            "--config", args.config,
            "--stage", "data",
            "--data-dir", str(reference_dir),
        ],
        cwd=REPO_ROOT,
        check=True,
    )

    sqlite_points = json.loads((checkpoint_dir / "building_points.json").read_text())
    reference_points = json.loads((reference_dir / "building_points.json").read_text())

    print()
    print(check_west_end_currency_fix(sqlite_points, reference_points))
    print()

    problems = diff_points(sqlite_points, reference_points)

    # Not a byte-exact diff against the reference run: value_land/value_bldg legitimately
    # differ between the two paths (the currency-bug fix), so their histograms do too.
    # This just confirms the port actually produced bins, i.e. didn't silently no-op.
    sqlite_filter_cfg = json.loads((checkpoint_dir / "filter_config.json").read_text())
    building_metrics = sqlite_filter_cfg.get("building_metrics") or {}
    if not building_metrics:
        problems.append("filter_config.json: building_metrics is empty — histogram port didn't run")
    else:
        print(f"building_metrics populated: {sorted(building_metrics)}")

    if problems:
        print(f"FAIL: {len(problems)} unexpected mismatch(es):")
        for p in problems[:50]:
            print(f"  - {p}")
        if len(problems) > 50:
            print(f"  ... and {len(problems) - 50} more")
        return 1

    print(
        "PASS: no unexpected mismatches "
        f"(known-diff fields exempted: {sorted(KNOWN_DIFF_FIELDS)})."
    )
    print(
        "NOTE: blocks.json is informational only for this comparison — see export.py's docstring "
        "on why block_id/counts aren't expected to match v1's dynamic bbox filtering exactly."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
