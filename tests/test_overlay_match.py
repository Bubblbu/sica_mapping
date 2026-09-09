"""run_overlay_match: matched/unmatched partition, secondary fallback, local_area."""

from __future__ import annotations


def _rows(conn, source):
    return conn.execute(
        "SELECT raw_row_id, building_id, match_method, match_key, local_area "
        "FROM overlay_matches WHERE overlay_source = ? ORDER BY raw_row_id",
        (source,),
    ).fetchall()


def test_coop_partition_and_secondary_fallback(overlay_db):
    rows = _rows(overlay_db, "coop")
    assert len(rows) == 3
    by_id = {r[0]: r for r in rows}

    # c1 -> b1, direct address
    assert by_id[1][1] == 1 and by_id[1][2] == "address"
    # c2 -> b3 via raw_buildings.secondary_addresses ("305 Pine St")
    assert by_id[2][1] == 3 and by_id[2][2] == "secondary_address"
    # c3 -> unmatched, local_area from point-in-polygon
    assert by_id[3][1] is None and by_id[3][2] == "unmatched"
    assert by_id[3][4] == "Downtown"


def test_sro_partition(overlay_db):
    rows = _rows(overlay_db, "sro")
    by_id = {r[0]: r for r in rows}
    assert by_id[1][1] == 2 and by_id[1][2] == "address"
    assert by_id[2][1] is None and by_id[2][2] == "unmatched"
    assert by_id[2][4] == "Downtown"


def test_rezoning_has_no_secondary_fallback(overlay_db):
    rows = _rows(overlay_db, "rezoning")
    by_id = {r[0]: r for r in rows}
    # r1 keys directly to b3
    assert by_id[1][1] == 3 and by_id[1][2] == "address"
    # r2 keys to "305 pine st" which is only a *secondary* address -> stays unmatched
    assert by_id[2][1] is None and by_id[2][2] == "unmatched"
    # r3 unmatched
    assert by_id[3][1] is None and by_id[3][2] == "unmatched"


def test_matched_rows_have_no_local_area(overlay_db):
    matched = overlay_db.execute(
        "SELECT COUNT(*) FROM overlay_matches WHERE building_id IS NOT NULL AND local_area IS NOT NULL"
    ).fetchone()[0]
    assert matched == 0


def test_rerun_is_idempotent(overlay_db):
    from sica_core.ingest.overlays import run_overlay_match

    before = overlay_db.execute("SELECT COUNT(*) FROM overlay_matches").fetchone()[0]
    run_overlay_match(overlay_db)
    after = overlay_db.execute("SELECT COUNT(*) FROM overlay_matches").fetchone()[0]
    assert before == after == 8
