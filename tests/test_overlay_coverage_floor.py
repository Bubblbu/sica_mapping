"""Regression guard: real-data overlay match rates must not silently drop.

Runs the full sica_core ingest against config.toml's committed CSVs once, then
asserts each source's match rate stays at or above a recorded floor. A parser
regression that tanks recall fails here instead of shipping a thinner map.

Floors are set a few points below the rates observed on the 2026-09 data
(co-op 35%, SRO 24%, rezoning 11%) — tight enough to catch a real break,
loose enough to survive normal data drift. Raise them when a data/parser
improvement lifts the real numbers.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sica_core.config import load_ingest_config
from sica_core.db import get_connection, init_db
from sica_core.export import overlay_coverage
from sica_core.ingest import run_ingest

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG = REPO_ROOT / "config.toml"

FLOORS = {"coop": 0.30, "sro": 0.20, "rezoning": 0.09}
MIN_TOTALS = {"coop": 100, "sro": 150, "rezoning": 300}


@pytest.fixture(scope="module")
def real_coverage(tmp_path_factory) -> dict:
    if not CONFIG.exists():
        pytest.skip("config.toml not present")
    config = load_ingest_config(str(CONFIG))
    for path in (
        config.buildings,
        config.addresses,
        config.sro_housing,
        config.coops,
        config.rezoning_applications,
        config.local_area_boundary,
    ):
        if not path or not (REPO_ROOT / path).exists():
            pytest.skip(f"source CSV missing: {path}")
    config.db_path = str(tmp_path_factory.mktemp("db") / "sica_core.db")
    conn = get_connection(config.db_path)
    init_db(conn)
    run_ingest(conn, config)
    return overlay_coverage(conn)


@pytest.mark.parametrize("source", ["coop", "sro", "rezoning"])
def test_match_rate_above_floor(real_coverage, source):
    stats = real_coverage.get(source)
    assert stats is not None, f"no coverage recorded for {source}"
    assert stats["total"] >= MIN_TOTALS[source], (
        f"{source}: only {stats['total']} raw rows — source data may have shrunk"
    )
    assert stats["match_rate"] >= FLOORS[source], (
        f"{source} match rate {stats['match_rate']:.3f} fell below floor {FLOORS[source]:.2f} "
        f"({stats['matched']}/{stats['total']}) — likely a keying/parsing regression"
    )
