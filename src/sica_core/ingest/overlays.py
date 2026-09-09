"""Match raw_sro / raw_coops / raw_rezoning records against buildings.

The merge step for overlay sources. Runs after run_merge() (needs
buildings.addr_key / building_id). Ported from
src/sica_mapping/data/overlays.py::match_overlays(), which did this at
map-render time against the CSVs directly — now it happens once, in the
pipeline, and the result is stored in overlay_matches for the export and
for browsing.

Per-source keying (unchanged from the sica_mapping version):
- co-op:    strip everything from the first "," in `address`, then addr_key
- SRO:      addr_key the `address` directly
- rezoning: strip from the first "(", split the rest on " and "/"&"/";",
            addr_key the first fragment. `name` is free text, not an address.

Co-op and SRO additionally get a secondary-address fallback: a record whose
key misses every building's own addr_key may still hit one of the
";"-joined civic addresses in raw_buildings.secondary_addresses. That
column is NULL on older buildings.csv vintages, in which case the fallback
index is empty and this is a plain no-op.

Unmatched records keep a `local_area` resolved by point-in-polygon against
raw_local_areas (the 22 official boundaries) — never the source's own
free-text area field, which doesn't line up with the map's neighbourhood
filters.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from datetime import datetime, timezone

from shapely.geometry import Point

from ..geometry import parse_geom
from ..normalize import addr_key_from_freeform

logger = logging.getLogger("sica_core.ingest")

_REZONING_NAME_SPLIT_RE = re.compile(r"\s+and\s+|\s*&\s*|;")


def _coop_addr_key(address: object) -> str:
    return addr_key_from_freeform(str(address).split(",")[0].strip())


def _sro_addr_key(address: object) -> str:
    return addr_key_from_freeform(str(address))


def _rezoning_addr_key(name: object) -> str:
    s = str(name).split("(")[0]
    s = _REZONING_NAME_SPLIT_RE.split(s, maxsplit=1)[0].strip()
    return addr_key_from_freeform(s)


# overlay_source -> (raw table, raw PK column, key source column, key fn, lat col, lon col, secondary fallback?)
_SOURCES = {
    "coop": ("raw_coops", "raw_coop_id", "address", _coop_addr_key, "lat", "lon", True),
    "sro": (
        "raw_sro",
        "raw_sro_id",
        "address",
        _sro_addr_key,
        "latitude",
        "longitude",
        True,
    ),
    "rezoning": (
        "raw_rezoning",
        "raw_rezoning_id",
        "name",
        _rezoning_addr_key,
        "latitude",
        "longitude",
        False,
    ),
}


def _table_has_rows(conn: sqlite3.Connection, name: str) -> bool:
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    if not exists:
        return False
    return conn.execute(f"SELECT 1 FROM {name} LIMIT 1").fetchone() is not None


def _load_secondary_index(conn: sqlite3.Connection) -> dict[str, str]:
    """{ addr_key(secondary address) -> addr_key(building's own address) }.

    Keyed the same way buildings.addr_key itself is derived
    (addr_key_from_freeform(raw_buildings.address); see ingest/merge.py), so
    a remapped key can be looked up directly against the buildings table.
    Empty dict when secondary_addresses is entirely NULL/blank.
    """
    rows = conn.execute(
        "SELECT address, secondary_addresses FROM raw_buildings "
        "WHERE secondary_addresses IS NOT NULL AND TRIM(secondary_addresses) <> ''"
    ).fetchall()
    index: dict[str, str] = {}
    for address, secs in rows:
        own_key = addr_key_from_freeform(address)
        if not own_key:
            continue
        for sec in str(secs).split(";"):
            sec = sec.strip()
            if not sec:
                continue
            sec_key = addr_key_from_freeform(sec)
            if sec_key:
                index.setdefault(sec_key, own_key)  # first building to claim it wins
    return index


def _load_boundary_polys(conn: sqlite3.Connection) -> list[tuple[str, object]]:
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='raw_local_areas'"
    ).fetchone()
    if not exists:
        return []
    polys: list[tuple[str, object]] = []
    for name, geom in conn.execute(
        "SELECT name, geom FROM raw_local_areas WHERE geom IS NOT NULL"
    ):
        poly = parse_geom(geom)
        if poly is not None and name:
            polys.append((str(name).strip(), poly))
    return polys


def _resolve_local_area(lat, lon, polys: list[tuple[str, object]]) -> str | None:
    if lat is None or lon is None or not polys:
        return None
    try:
        point = Point(float(lon), float(lat))
    except (TypeError, ValueError):
        return None
    for name, poly in polys:
        if poly.contains(point):
            return name
    return None


def run_overlay_match(conn: sqlite3.Connection) -> int:
    """(Re)build overlay_matches from whichever raw_<source> tables have rows.

    Returns the total number of overlay_matches rows written (matched +
    unmatched). A source with no raw rows is skipped entirely.
    """
    building_addr_keys: set[str] = set()
    addr_key_to_building: dict[str, int] = {}
    for bid, addr_key in conn.execute("SELECT building_id, addr_key FROM buildings"):
        building_addr_keys.add(addr_key)
        addr_key_to_building[addr_key] = bid

    secondary_index = _load_secondary_index(conn)
    if secondary_index:
        logger.info(
            "overlay match: %d secondary addresses available for co-op/SRO fallback",
            len(secondary_index),
        )
    boundary_polys = _load_boundary_polys(conn)

    now = datetime.now(timezone.utc).isoformat()
    all_records: list[tuple] = []

    for source, (
        raw_table,
        pk_col,
        key_col,
        key_fn,
        lat_col,
        lon_col,
        use_secondary,
    ) in _SOURCES.items():
        if not _table_has_rows(conn, raw_table):
            continue
        rows = conn.execute(
            f"SELECT {pk_col}, {key_col}, {lat_col}, {lon_col} FROM {raw_table}"
        ).fetchall()

        counts = {"address": 0, "secondary_address": 0, "unmatched": 0}
        for pk, key_src, lat, lon in rows:
            key = key_fn(key_src)
            building_id: int | None = None
            method = "unmatched"
            if key and key in building_addr_keys:
                building_id = addr_key_to_building.get(key)
                method = "address"
            elif use_secondary and key and key in secondary_index:
                remapped = secondary_index[key]
                building_id = addr_key_to_building.get(remapped)
                if building_id is not None:
                    key = remapped
                    method = "secondary_address"
            local_area = (
                _resolve_local_area(lat, lon, boundary_polys)
                if building_id is None
                else None
            )
            counts[method] += 1
            all_records.append(
                (source, pk, building_id, method, key or None, local_area, now)
            )

        matched = counts["address"] + counts["secondary_address"]
        logger.info(
            "overlay match [%s]: %d/%d matched (%.0f%%) — %d address, %d secondary, %d unmatched",
            source,
            matched,
            len(rows),
            100.0 * matched / len(rows) if rows else 0.0,
            counts["address"],
            counts["secondary_address"],
            counts["unmatched"],
        )

    with conn:
        conn.execute("DELETE FROM overlay_matches")
        if all_records:
            conn.executemany(
                "INSERT INTO overlay_matches "
                "(overlay_source, raw_row_id, building_id, match_method, match_key, local_area, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                all_records,
            )
    return len(all_records)
