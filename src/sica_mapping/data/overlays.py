"""Match SRO/SRA, co-op, and rezoning-application datasets against buildings.

Runs after the main buildings pipeline (`pts_df` must already carry `addr_key`,
`lat`/`lon`) and before `add_buildings_layers`/`buildings_table`. For each
optional source CSV, splits rows into "matched" (joins onto an existing
building by address) and "unmatched" (kept as its own standalone record, see
`OverlayResult.unmatched_records`).

Matching is address-key only (`core.normalization.addr_key_from_freeform`), no
lat/lon proximity fallback — a deliberate precision-over-recall choice. Each
source needs different preprocessing before it produces a clean key:

- Co-ops: `address` is "123 Foo St, Vancouver, BC V1V 1V1" — strip everything
  from the first comma before keying.
- SRO/SRA: `address` is already a clean single-line address ("210 Abbott
  St.") — key directly. Note the CSV's own `match_method` column (an
  upstream address-matching flag baked into the source data) is unrelated to
  our own matching here and is intentionally not used to filter rows.
- Rezoning: `name` is free text, not an address ("2165-2195 and 2205-2291 W
  45th Av (Dunbar Ryerson United Church)") — strip from the first "(", split
  the remainder on " and "/"&"/";", and key the first fragment. Best-effort:
  most rezoning applications (churches, single-family lots, commercial,
  multi-lot assemblies) don't correspond to any row in buildings.csv at all,
  regardless of parsing quality.

Measured match rates against buildings.csv (5,112 rows, citywide): co-ops
42/117 (36%), SRO/SRA 41/171 (24%), rezoning ~43/377 (11%).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
from shapely.geometry import Point, shape

from ..core import addr_key_from_freeform, logger, normalize_cols, read_any_csv


def rezoning_status_group(status: str) -> str:
    """"closed" once approved, "open" for anything still in progress (Rezoning/Upcoming)."""
    return "closed" if str(status).strip().lower() == "approved" else "open"


@dataclass
class OverlayResult:
    pts_df: pd.DataFrame
    unmatched_records: list[dict] = field(default_factory=list)


def _clean(val) -> str:
    if val is None:
        return ""
    if isinstance(val, float) and pd.isna(val):
        return ""
    s = str(val).strip()
    return "" if s.lower() == "nan" else s


def _load_optional_csv(path: str | None, label: str) -> pd.DataFrame | None:
    if not path:
        return None
    if not Path(path).exists():
        logger.warning("%s CSV not found, skipping overlay: %s", label, path)
        return None
    return normalize_cols(read_any_csv(path))


def _build_boundary_polys(local_area_boundary_fc: dict) -> list[tuple[str, object]]:
    polys = []
    for feat in (local_area_boundary_fc or {}).get("features") or []:
        props = feat.get("properties") or {}
        name = str(props.get("name") or "").strip()
        geom = feat.get("geometry")
        if not geom or not name:
            continue
        try:
            polys.append((name, shape(geom)))
        except Exception:
            continue
    return polys


def _resolve_local_area(lat, lon, boundary_polys: list[tuple[str, object]]) -> str:
    """Point-in-polygon lookup against the 22 official local-area boundaries.

    Deliberately not trusting each source's own free-text area field (e.g.
    SRO's "Area" is a DTES-style composite label, not one of the 22 official
    local areas the sidebar's neighbourhood checkboxes are built from) — an
    unmatched marker needs a local_area that actually lines up with those
    checkboxes to be filterable correctly.
    """
    if lat is None or lon is None or pd.isna(lat) or pd.isna(lon):
        return ""
    point = Point(float(lon), float(lat))
    for name, poly in boundary_polys:
        if poly.contains(point):
            return name
    return ""


def _coop_addr_key(address) -> str:
    street_part = str(address).split(",")[0].strip()
    return addr_key_from_freeform(street_part)


def _sro_addr_key(address) -> str:
    return addr_key_from_freeform(address)


_REZONING_NAME_SPLIT_RE = re.compile(r"\s+and\s+|\s*&\s*|;")


def _rezoning_addr_key(name) -> str:
    s = str(name).split("(")[0]
    s = _REZONING_NAME_SPLIT_RE.split(s, maxsplit=1)[0].strip()
    return addr_key_from_freeform(s)


def match_overlays(
    pts_df: pd.DataFrame,
    coops_path: str | None,
    sro_path: str | None,
    rezoning_path: str | None,
    local_area_boundary_fc: dict,
) -> OverlayResult:
    df = pts_df.copy()
    addr_keys = set(df["addr_key"])
    boundary_polys = _build_boundary_polys(local_area_boundary_fc)
    unmatched_records: list[dict] = []

    # Defaults for every new column, so downstream code (add_buildings_layers,
    # buildings_table) never needs to branch on a column being absent.
    df["is_coop"] = False
    df["coop_status"] = ""
    df["coop_ownership_model"] = ""
    df["is_sro"] = False
    df["sro_owner"] = ""
    df["sro_operator"] = ""
    df["sro_operator_group"] = ""
    df["sro_ownership_group"] = ""
    df["sro_occupancy_status"] = ""
    df["sro_registered_rooms"] = ""
    df["is_rezoning"] = False
    df["rezoning_status"] = ""
    df["rezoning_status_group"] = ""
    df["rezoning_category"] = ""
    df["rezoning_status_detail"] = ""
    df["rezoning_link"] = ""

    # ---- Co-ops ----
    coops = _load_optional_csv(coops_path, "Co-op housing")
    if coops is not None:
        coops = coops.copy()
        coops["addr_key"] = coops["address"].apply(_coop_addr_key)
        matched_mask = coops["addr_key"].isin(addr_keys)
        matched = coops[matched_mask].drop_duplicates("addr_key")
        unmatched = coops[~matched_mask]
        logger.info(
            "Co-ops: %d/%d matched an existing building", len(matched), len(coops)
        )

        if not matched.empty:
            lookup = matched.set_index("addr_key")
            hit = df["addr_key"].isin(lookup.index)
            df.loc[hit, "is_coop"] = True
            df.loc[hit, "coop_status"] = (
                df.loc[hit, "addr_key"].map(lookup["status"]).apply(_clean)
            )
            df.loc[hit, "coop_ownership_model"] = (
                df.loc[hit, "addr_key"].map(lookup["ownership_model"]).apply(_clean)
            )

        for idx, row in unmatched.iterrows():
            lat, lon = row.get("lat"), row.get("lon")
            unmatched_records.append(
                {
                    # Suffixed with the row's own CSV index, not just its "id"
                    # column, since that's assumed unique per-record but isn't
                    # guaranteed to be (confirmed true for co-ops; kept
                    # consistent across all three sources defensively).
                    "synthetic_id": f"coop-{row.get('id')}-{idx}",
                    "source": "coop",
                    "lat": lat,
                    "lon": lon,
                    "address": _clean(row.get("address")),
                    "local_area": _resolve_local_area(lat, lon, boundary_polys),
                    "housing_type": "coop",
                    "rezoning_status": "",
                    "rezoning_status_group": "",
                    "popup_fields": {
                        "title": _clean(row.get("title")),
                        "status": _clean(row.get("status")),
                        "ownership_model": _clean(row.get("ownership_model")),
                        "read_more_url": _clean(row.get("read_more_url")),
                    },
                }
            )

    # ---- SRO/SRA housing ----
    sro = _load_optional_csv(sro_path, "SRO/SRA housing")
    if sro is not None:
        sro = sro.copy()
        sro["addr_key"] = sro["address"].apply(_sro_addr_key)
        matched_mask = sro["addr_key"].isin(addr_keys)
        matched = sro[matched_mask].drop_duplicates("addr_key")
        unmatched = sro[~matched_mask]
        logger.info(
            "SRO/SRA: %d/%d matched an existing building", len(matched), len(sro)
        )

        if not matched.empty:
            lookup = matched.set_index("addr_key")
            hit = df["addr_key"].isin(lookup.index)
            df.loc[hit, "is_sro"] = True
            field_map = {
                "owner": "sro_owner",
                "operator": "sro_operator",
                "operator_group": "sro_operator_group",
                "ownership_group": "sro_ownership_group",
                "occupancy_status": "sro_occupancy_status",
                "#_registered_rooms": "sro_registered_rooms",
            }
            for src_col, dst_col in field_map.items():
                if src_col in lookup.columns:
                    df.loc[hit, dst_col] = (
                        df.loc[hit, "addr_key"].map(lookup[src_col]).apply(_clean)
                    )

        for idx, row in unmatched.iterrows():
            lat, lon = row.get("latitude"), row.get("longitude")
            unmatched_records.append(
                {
                    "synthetic_id": f"sro-{row.get('id')}-{idx}",
                    "source": "sro",
                    "lat": lat,
                    "lon": lon,
                    "address": _clean(row.get("address")),
                    "local_area": _resolve_local_area(lat, lon, boundary_polys),
                    "housing_type": "sro",
                    "rezoning_status": "",
                    "rezoning_status_group": "",
                    "popup_fields": {
                        "building_name": _clean(row.get("building_name")),
                        "secondary_address": _clean(row.get("secondary_address")),
                        "owner": _clean(row.get("owner")),
                        "operator": _clean(row.get("operator")),
                        "operator_group": _clean(row.get("operator_group")),
                        "ownership_group": _clean(row.get("ownership_group")),
                        "registered_rooms": _clean(row.get("#_registered_rooms")),
                        "occupancy_status": _clean(row.get("occupancy_status")),
                    },
                }
            )

    # ---- Rezoning applications ----
    rezoning = _load_optional_csv(rezoning_path, "Rezoning applications")
    if rezoning is not None:
        rezoning = rezoning.copy()
        rezoning["addr_key"] = rezoning["name"].apply(_rezoning_addr_key)
        matched_mask = rezoning["addr_key"].isin(addr_keys)
        matched = rezoning[matched_mask].drop_duplicates("addr_key")
        unmatched = rezoning[~matched_mask]
        logger.info(
            "Rezoning applications: %d/%d matched an existing building",
            len(matched),
            len(rezoning),
        )

        if not matched.empty:
            lookup = matched.set_index("addr_key")
            hit = df["addr_key"].isin(lookup.index)
            df.loc[hit, "is_rezoning"] = True
            df.loc[hit, "rezoning_status"] = (
                df.loc[hit, "addr_key"].map(lookup["status"]).apply(_clean)
            )
            df.loc[hit, "rezoning_status_group"] = df.loc[hit, "rezoning_status"].apply(
                rezoning_status_group
            )
            df.loc[hit, "rezoning_category"] = (
                df.loc[hit, "addr_key"].map(lookup["category"]).apply(_clean)
            )
            df.loc[hit, "rezoning_status_detail"] = (
                df.loc[hit, "addr_key"].map(lookup["status_detail"]).apply(_clean)
            )
            df.loc[hit, "rezoning_link"] = (
                df.loc[hit, "addr_key"].map(lookup["link"]).apply(_clean)
            )

        for idx, row in unmatched.iterrows():
            lat, lon = row.get("latitude"), row.get("longitude")
            status = _clean(row.get("status"))
            unmatched_records.append(
                {
                    # rezoning_applications.csv's own ID is NOT reliably
                    # unique per row — e.g. RZ285 covers two entirely
                    # different addresses/lat-lons as separate rows (a
                    # multi-site umbrella application) — confirmed via a
                    # real duplicate-key collision during testing.
                    "synthetic_id": f"rezoning-{row.get('id')}-{idx}",
                    "source": "rezoning",
                    "lat": lat,
                    "lon": lon,
                    "address": _clean(row.get("name")),
                    "local_area": _resolve_local_area(lat, lon, boundary_polys),
                    "housing_type": "",
                    "rezoning_status": status,
                    "rezoning_status_group": rezoning_status_group(status),
                    "popup_fields": {
                        "name": _clean(row.get("name")),
                        "status": status,
                        "category": _clean(row.get("category")),
                        "status_detail": _clean(row.get("status_detail")),
                        "link": _clean(row.get("link")),
                    },
                }
            )

    df["housing_type"] = np.where(
        df["is_coop"] & df["is_sro"],
        "co-op, sro",
        np.where(df["is_coop"], "co-op", np.where(df["is_sro"], "sro", "")),
    )

    return OverlayResult(pts_df=df, unmatched_records=unmatched_records)
