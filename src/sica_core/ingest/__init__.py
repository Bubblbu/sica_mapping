"""Ingest orchestration: CSVs -> sica_core SQLite tables.

Order matters for FK dependencies: raw tables first, then the merge step
(which needs both raw_buildings and raw_addresses, and needs blocks for
point-in-polygon assignment), then membership last (needs buildings.addr_key
to resolve building_id).

Each stage's inserts are already scoped in their own transaction. If a stage
fails partway, nothing is silently left half-correct: every REBUILDABLE table
gets dropped and recreated by `init_db()` at the start of the next run, so
recovery is just "call init_db() again, then re-run ingest" — no rollback
machinery needed. `ownership_claims` is never written by ingest at all, so it
isn't at risk regardless.
"""

from __future__ import annotations

import argparse
import logging
import sqlite3

from ..config import load_ingest_config, IngestConfig
from ..db import get_connection, init_db
from .block_numbers import ingest_raw_block_numbers
from .blocks import ingest_blocks
from .membership import ingest_membership
from .merge import run_merge
from .overlays import run_overlay_match
from .raw_addresses import ingest_raw_addresses
from .raw_buildings import ingest_raw_buildings
from .raw_coops import ingest_raw_coops
from .raw_local_areas import ingest_raw_local_areas
from .raw_rezoning import ingest_raw_rezoning
from .raw_sro import ingest_raw_sro

logger = logging.getLogger("sica_core.ingest")


def run_ingest(conn: sqlite3.Connection, config: IngestConfig) -> dict[str, int]:
    counts: dict[str, int] = {}
    counts["raw_buildings"] = ingest_raw_buildings(conn, config.buildings)
    logger.info("raw_buildings: %d rows", counts["raw_buildings"])
    counts["raw_addresses"] = ingest_raw_addresses(conn, config.addresses)
    logger.info("raw_addresses: %d rows", counts["raw_addresses"])
    counts["blocks"] = ingest_blocks(conn, config.blocks, config.bbox)
    logger.info("blocks: %d rows", counts["blocks"])
    counts["raw_block_numbers"] = ingest_raw_block_numbers(conn, config.block_numbers)
    logger.info("raw_block_numbers: %d rows", counts["raw_block_numbers"])

    # Optional overlay sources — raw storage only here; matching against
    # buildings happens in run_overlay_match() below, after run_merge().
    if config.sro_housing:
        counts["raw_sro"] = ingest_raw_sro(conn, config.sro_housing)
        logger.info("raw_sro: %d rows", counts["raw_sro"])
    if config.coops:
        counts["raw_coops"] = ingest_raw_coops(conn, config.coops)
        logger.info("raw_coops: %d rows", counts["raw_coops"])
    if config.rezoning_applications:
        counts["raw_rezoning"] = ingest_raw_rezoning(conn, config.rezoning_applications)
        logger.info("raw_rezoning: %d rows", counts["raw_rezoning"])
    if config.local_area_boundary:
        counts["raw_local_areas"] = ingest_raw_local_areas(
            conn, config.local_area_boundary
        )
        logger.info("raw_local_areas: %d rows", counts["raw_local_areas"])

    counts["buildings"] = run_merge(conn)
    logger.info("buildings: %d rows", counts["buildings"])
    counts["vtu_membership"] = ingest_membership(conn, config.vtu_raw)
    logger.info("vtu_membership: %d rows", counts["vtu_membership"])

    # Match overlay records against buildings (needs buildings.addr_key /
    # building_id). No-op for any source not configured / not ingested above.
    counts["overlay_matches"] = run_overlay_match(conn)
    logger.info("overlay_matches: %d rows", counts["overlay_matches"])
    return counts


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(
        description="Ingest CSVs into sica_core's SQLite store"
    )
    parser.add_argument(
        "--config", required=True, help="TOML/JSON config with source paths"
    )
    args = parser.parse_args()

    config = load_ingest_config(args.config)
    conn = get_connection(config.db_path)
    init_db(conn)
    counts = run_ingest(conn, config)
    logger.info("Ingest complete: %s", counts)


if __name__ == "__main__":
    main()
