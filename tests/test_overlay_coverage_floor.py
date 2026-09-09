"""Regression guard: real-data overlay match rates must not silently drop.

Runs the overlay-relevant part of the sica_core ingest against config.toml's
committed CSVs once (buildings + addresses + blocks + the three overlay
sources + boundaries — deliberately NOT membership, which needs a gitignored
raw export and isn't present in CI), then asserts each source's match rate
stays at or above a recorded floor. A parser regression that tanks recall
fails here instead of shipping a thinner map.

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
from sica_core.ingest.block_numbers import ingest_raw_block_numbers
from sica_core.ingest.blocks import ingest_blocks
from sica_core.ingest.merge import run_merge
from sica_core.ingest.overlays import run_overlay_match
from sica_core.ingest.raw_addresses import ingest_raw_addresses
from sica_core.ingest.raw_buildings import ingest_raw_buildings
from sica_core.ingest.raw_coops import ingest_raw_coops
from sica_core.ingest.raw_local_areas import ingest_raw_local_areas
from sica_core.ingest.raw_rezoning import ingest_raw_rezoning
from sica_core.ingest.raw_sro import ingest_raw_sro

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG = REPO_ROOT / "config.toml"

FLOORS = {"coop": 0.30, "sro": 0.20, "rezoning": 0.09}
MIN_TOTALS = {"coop": 100, "sro": 150, "rezoning": 300}


@pytest.fixture(scope="module")
def real_coverage(tmp_path_factory) -> dict:
    if not CONFIG.exists():
        pytest.skip("config.toml not present")
    config = load_ingest_config(str(CONFIG))
    required = [
        config.buildings,
        config.addresses,
        config.blocks,
        config.block_numbers,
        config.sro_housing,
        config.coops,
        config.rezoning_applications,
        config.local_area_boundary,
    ]
    for path in required:
        if not path or not (REPO_ROOT / path).exists():
            pytest.skip(f"source CSV missing: {path}")

    conn = get_connection(str(tmp_path_factory.mktemp("db") / "sica_core.db"))
    init_db(conn)
    ingest_raw_buildings(conn, config.buildings)
    ingest_raw_addresses(conn, config.addresses)
    ingest_blocks(conn, config.blocks, config.bbox)
    ingest_raw_block_numbers(conn, config.block_numbers)
    ingest_raw_sro(conn, config.sro_housing)
    ingest_raw_coops(conn, config.coops)
    ingest_raw_rezoning(conn, config.rezoning_applications)
    ingest_raw_local_areas(conn, config.local_area_boundary)
    run_merge(conn)
    run_overlay_match(conn)
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
