"""Shared fixtures for sica_core overlay tests.

Builds a tiny in-memory-ish SQLite DB with the real schema.sql, a handful of
buildings, and a few overlay raw rows exercising every match path (direct
address, secondary-address fallback, unmatched + point-in-polygon local_area).
"""

from __future__ import annotations

import sqlite3

import pytest

from sica_core.db import init_db
from sica_core.ingest.overlays import run_overlay_match
from sica_core.normalize import addr_key_from_freeform

# One big rectangle over Vancouver-ish coords; every unmatched test point sits
# inside it so local_area resolves to "Downtown".
_DOWNTOWN_POLY = (
    '{"type":"Polygon","coordinates":[[[-123.30,49.20],[-123.00,49.20],'
    "[-123.00,49.40],[-123.30,49.40],[-123.30,49.20]]]}"
)
_INSIDE = (49.28, -123.11)  # (lat, lon) inside _DOWNTOWN_POLY


def _k(addr: str) -> str:
    return addr_key_from_freeform(addr)


@pytest.fixture
def overlay_db(tmp_path) -> sqlite3.Connection:
    conn = sqlite3.connect(tmp_path / "t.db")
    conn.execute("PRAGMA foreign_keys = ON")
    init_db(conn)

    now = "2026-01-01T00:00:00+00:00"
    buildings = [
        # building_id, addr_key, address, local_area
        (1, _k("100 Main St"), "100 Main St", "Downtown"),
        (2, _k("200 Oak Ave"), "200 Oak Ave", "Kitsilano"),
        (3, _k("300 Pine St"), "300 Pine St", "West End"),
    ]
    conn.executemany(
        "INSERT INTO buildings (building_id, addr_key, address, local_area, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [(bid, ak, ad, la, now, now) for bid, ak, ad, la in buildings],
    )
    # b3 has two secondary addresses; "305 Pine St" is the one overlays should
    # fall back through.
    conn.execute(
        "INSERT INTO raw_buildings (raw_building_id, address, secondary_addresses, ingested_at) "
        "VALUES (3, '300 Pine St', '305 Pine St; 50 Side Ln', ?)",
        (now,),
    )

    conn.execute(
        "INSERT INTO raw_local_areas (name, geom, geo_point_2d, ingested_at) VALUES (?, ?, ?, ?)",
        ("Downtown", _DOWNTOWN_POLY, "49.28, -123.11", now),
    )

    lat, lon = _INSIDE
    conn.executemany(
        "INSERT INTO raw_coops (raw_coop_id, source_id, address, lat, lon, status, ownership_model, "
        "title, read_more_url, ingested_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            # c1 -> b1 by direct address (note the trailing city/prov/postal to strip)
            (
                1,
                "C1",
                "100 Main St, Vancouver, BC V6A 1A1",
                lat,
                lon,
                "Open",
                "Non-profit",
                "Main Co-op",
                "http://x/1",
                now,
            ),
            # c2 -> b3 via secondary address "305 Pine St"
            (
                2,
                "C2",
                "305 Pine St, Vancouver, BC",
                lat,
                lon,
                "Waitlist",
                "Leasehold",
                "Pine Co-op",
                "http://x/2",
                now,
            ),
            # c3 -> unmatched, local_area from point-in-polygon
            (
                3,
                "C3",
                "999 Nowhere Rd, Vancouver, BC",
                lat,
                lon,
                "Closed",
                "Strata",
                "Ghost Co-op",
                "http://x/3",
                now,
            ),
        ],
    )
    conn.executemany(
        "INSERT INTO raw_sro (raw_sro_id, source_id, address, latitude, longitude, owner, operator, "
        "occupancy_status, registered_rooms, ingested_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                1,
                "S1",
                "200 Oak Ave",
                lat,
                lon,
                "Owner A",
                "Operator A",
                "Open",
                42,
                now,
            ),
            (
                2,
                "S2",
                "777 Ghost St",
                lat,
                lon,
                "Owner B",
                "Operator B",
                "Closed",
                7,
                now,
            ),
        ],
    )
    conn.executemany(
        "INSERT INTO raw_rezoning (raw_rezoning_id, source_id, name, status, category, status_detail, "
        "latitude, longitude, link, ingested_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            # r1 -> b3 by direct address
            (
                1,
                "RZ1",
                "300 Pine St (Big Tower)",
                "Approved",
                "Residential",
                "Approved by Council",
                lat,
                lon,
                "http://rz/1",
                now,
            ),
            # r2 keys to "305 pine st" but rezoning has NO secondary fallback -> unmatched
            (
                2,
                "RZ2",
                "305 Pine St and 307 Pine St (Assembly)",
                "Rezoning",
                "Mixed",
                "In stream",
                lat,
                lon,
                "http://rz/2",
                now,
            ),
            # r3 -> unmatched
            (
                3,
                "RZ3",
                "123-125 Elsewhere Blvd (Church)",
                "Refused",
                "Institutional",
                "Refused",
                lat,
                lon,
                "http://rz/3",
                now,
            ),
        ],
    )
    conn.commit()

    run_overlay_match(conn)
    return conn
