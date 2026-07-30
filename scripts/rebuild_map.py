#!/usr/bin/env python3
"""Rebuilds the live map straight from sica_core's SQLite store.

A drop-in replacement for the CSV-based `--stage data` step: ingests the
source CSVs into SQLite, exports the legacy `.preprocessed/*.json` cache
sica_mapping already reads, then hands off to the existing, unmodified
`build_sica_map.py --stage frontend` to render `www/index.html`.

Lives at the top level (like validate_migration.py), not inside
src/sica_core/, since it needs both packages — imports sica_core directly
and shells out to sica_mapping's CLI.

Usage: uv run python scripts/rebuild_map.py [--config config.toml]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from sica_core.config import load_ingest_config  # noqa: E402
from sica_core.db import get_connection, init_db  # noqa: E402
from sica_core.export import export_to_cache  # noqa: E402
from sica_core.ingest import run_ingest  # noqa: E402

# Matches sica_mapping.cli.DEFAULT_DATA_DIR — writing here makes this a
# drop-in replacement for the CSV pipeline's own cache, no extra wiring.
DATA_DIR = REPO_ROOT / ".preprocessed"


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

    print(f"Exporting to {DATA_DIR} ...")
    export_to_cache(conn, DATA_DIR)

    print("Rendering map via build_sica_map.py --stage frontend ...")
    subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "build_sica_map.py"),
            "--config", args.config,
            "--stage", "frontend",
            "--data-dir", str(DATA_DIR),
        ],
        cwd=REPO_ROOT,
        check=True,
    )
    print("Done — see www/index.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
