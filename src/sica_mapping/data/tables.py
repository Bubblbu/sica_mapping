"""Table builders for the West End map UI."""

from __future__ import annotations

import numpy as np
import pandas as pd
from html import escape


def buildings_table(pts_df: pd.DataFrame) -> pd.DataFrame:
    tbl = pts_df[
        [
            "b_id",
            "address",
            "local_area",
            "block_id",
            "units",
            "member_count",
            "member_share_building",
            "year_built",
            "owner_group",
            "owner_key",
            "member_count_all",
            "value_land",
            "value_bldg",
            "bldg_land_ratio",
            "has_vtu_member",
            "latest_membership_year",
            "housing_type",
            "rezoning_status",
            "rezoning_status_group",
        ]
    ].copy()
    tbl["member_share_pct"] = (tbl["member_share_building"] * 100).round(0).astype(int)
    tbl["source"] = "building"
    return tbl.drop(columns=["member_share_building"]).sort_values(
        ["member_count", "units"], ascending=[False, False]
    )


def _avg_units_per_bldg(total_units: pd.Series, buildings: pd.Series) -> pd.Series:
    return np.where(buildings > 0, total_units / buildings, 0.0).round(1)


def blocks_table(blocks_merged: pd.DataFrame) -> pd.DataFrame:
    tbl = blocks_merged.copy()
    tbl["median_year_built"] = tbl["median_year_built"].round().astype("Int64")
    tbl["avg_units_per_bldg"] = _avg_units_per_bldg(tbl["total_units"], tbl["buildings"])
    # Blocks with no buildings in this dataset fall back to "(Unknown)" (see
    # assign_block_labels); sort those last rather than first so a viewer sees
    # the actually-labeled, meaningful blocks before the empty-block bucket.
    tbl["_is_unknown"] = tbl["block_label"].str.startswith("(Unknown)")
    return tbl[
        [
            "block_id",
            "block_label",
            "local_area",
            "buildings",
            "total_units",
            "avg_units_per_bldg",
            "median_year_built",
            "member_buildings",
            "_is_unknown",
        ]
    ].sort_values(["_is_unknown", "block_label"], ascending=[True, True]).drop(
        columns=["_is_unknown"]
    )


def landlords_table(pts_df: pd.DataFrame) -> pd.DataFrame:
    owners_df = pts_df.copy()
    owners_df["owner_group"] = owners_df["owner_group"].fillna("(Unknown)")
    owners_df["owner_key"] = owners_df["owner_key"].fillna("unknown")
    landlords = (
        owners_df.groupby(["owner_group", "owner_key"])
        .agg(
            buildings=("address", "count"),
            total_units=("units", "sum"),
            member_buildings=("has_vtu_member", "sum"),
        )
        .reset_index()
    )
    landlords["avg_units_per_bldg"] = _avg_units_per_bldg(
        landlords["total_units"], landlords["buildings"]
    )
    return landlords.sort_values(["total_units", "buildings"], ascending=[False, False])


def neighbourhoods_table(pts_df: pd.DataFrame) -> pd.DataFrame:
    df = pts_df.copy()
    df["local_area"] = df["local_area"].fillna("(Unknown)")
    tbl = (
        df.groupby("local_area")
        .agg(
            buildings=("address", "count"),
            total_units=("units", "sum"),
            member_buildings=("has_vtu_member", "sum"),
        )
        .reset_index()
    )
    tbl["avg_units_per_bldg"] = _avg_units_per_bldg(tbl["total_units"], tbl["buildings"])
    return tbl.sort_values(["total_units", "buildings"], ascending=[False, False])


def rows_buildings(df: pd.DataFrame) -> str:
    rows = []
    for r in df.itertuples(index=False):
        block_val = "" if pd.isna(r.block_id) else int(r.block_id)
        units_val = "" if pd.isna(r.units) else int(r.units)
        year_val = "" if pd.isna(r.year_built) else int(r.year_built)
        has_vtu_val = 1 if bool(r.has_vtu_member) else 0
        membership_year_val = (
            "" if pd.isna(r.latest_membership_year) else int(r.latest_membership_year)
        )
        val_land = "" if pd.isna(r.value_land) else int(round(r.value_land))
        val_bldg = "" if pd.isna(r.value_bldg) else int(round(r.value_bldg))
        ratio_val = (
            "" if pd.isna(r.bldg_land_ratio) else round(float(r.bldg_land_ratio), 3)
        )
        member_total = (
            int(r.member_count_all)
            if hasattr(r, "member_count_all")
            else int(r.member_count)
        )
        bid = int(r.b_id)
        owner_key = escape(str(r.owner_key))
        local_area = "" if pd.isna(r.local_area) else str(r.local_area)
        housing_type = "" if pd.isna(r.housing_type) else str(r.housing_type)
        rezoning_status = "" if pd.isna(r.rezoning_status) else str(r.rezoning_status)
        rezoning_status_group = (
            "" if pd.isna(r.rezoning_status_group) else str(r.rezoning_status_group)
        )
        search_terms = " ".join(
            str(val).lower()
            for val in (
                r.address,
                local_area,
                block_val,
                units_val,
                int(r.member_count),
                r.owner_group,
                housing_type,
                rezoning_status,
            )
            if val not in ("", None)
        )
        search_attr = escape(search_terms)
        rows.append(
            (
                f'<tr data-bid="{bid}" data-owner="{owner_key}" data-block="{block_val}" '
                f'data-area="{escape(local_area)}" '
                f'data-value-land="{val_land}" data-value-bldg="{val_bldg}" '
                f'data-value-ratio="{ratio_val}" data-units="{units_val}" '
                f'data-year-built="{year_val}" '
                f'data-has-vtu-member="{has_vtu_val}" '
                f'data-latest-membership-year="{membership_year_val}" '
                f'data-member-total="{member_total}" data-search="{search_attr}" '
                f'data-source="building" data-synthetic="0" '
                f'data-housing-type="{escape(housing_type)}" '
                f'data-rezoning-status="{escape(rezoning_status)}" '
                f'data-rezoning-status-group="{escape(rezoning_status_group)}">'
                f'<td class="select-cell"><input type="checkbox" class="row-select" '
                f'data-type="building" data-target="{bid}"></td>'
                f"<td>{escape(str(r.address))}</td>"
                f'<td data-sort-value="{escape(local_area)}">{escape(local_area)}</td>'
                f'<td data-sort-value="{block_val}">{block_val}</td>'
                f'<td data-sort-value="{units_val}">{units_val}</td>'
                f'<td data-sort-value="{int(r.member_count)}">{int(r.member_count)}</td>'
                f'<td data-sort-value="{int(r.member_share_pct)}">{int(r.member_share_pct)}%</td>'
                f"<td>{escape(str(r.owner_group))}</td>"
                f'<td data-sort-value="{year_val}">{year_val}</td>'
                f'<td data-sort-value="{escape(housing_type)}">{escape(housing_type)}</td>'
                f'<td data-sort-value="{escape(rezoning_status)}">{escape(rezoning_status)}</td>'
                f"</tr>"
            )
        )
    return "\n".join(rows)


def rows_synthetic(records: list[dict]) -> str:
    """Unmatched SRO/co-op/rezoning records rendered as Buildings-table rows,
    flagged by source, with real-building-only fields left blank. See
    data.overlays.match_overlays for how these records are produced.
    """
    rows = []
    for rec in records:
        sid = escape(str(rec["synthetic_id"]))
        source = escape(str(rec.get("source") or ""))
        local_area = str(rec.get("local_area") or "")
        address = str(rec.get("address") or "")
        housing_type = str(rec.get("housing_type") or "")
        rezoning_status = str(rec.get("rezoning_status") or "")
        rezoning_status_group = str(rec.get("rezoning_status_group") or "")
        search_terms = " ".join(
            str(val).lower()
            for val in (address, local_area, source)
            if val not in ("", None)
        )
        rows.append(
            (
                f'<tr data-bid="{sid}" data-owner="" data-block="" '
                f'data-area="{escape(local_area)}" '
                f'data-value-land="" data-value-bldg="" data-value-ratio="" '
                f'data-units="" data-year-built="" data-has-vtu-member="0" '
                f'data-latest-membership-year="" data-member-total="0" '
                f'data-search="{escape(search_terms)}" '
                f'data-source="{source}" data-synthetic="1" '
                f'data-housing-type="{escape(housing_type)}" '
                f'data-rezoning-status="{escape(rezoning_status)}" '
                f'data-rezoning-status-group="{escape(rezoning_status_group)}">'
                f'<td class="select-cell"><input type="checkbox" class="row-select" '
                f'data-type="building" data-target="{sid}"></td>'
                f"<td>{escape(address)} <em>(unmatched {source})</em></td>"
                f'<td data-sort-value="{escape(local_area)}">{escape(local_area)}</td>'
                f"<td></td><td></td><td></td><td></td><td></td><td></td>"
                f'<td data-sort-value="{escape(housing_type)}">{escape(housing_type)}</td>'
                f'<td data-sort-value="{escape(rezoning_status)}">{escape(rezoning_status)}</td>'
                f"</tr>"
            )
        )
    return "\n".join(rows)


def rows_blocks(df: pd.DataFrame) -> str:
    rows = []
    for r in df.itertuples(index=False):
        block_id = int(r.block_id)
        block_label = escape(str(r.block_label))
        local_area = "" if pd.isna(r.local_area) else str(r.local_area)
        year_val = "" if pd.isna(r.median_year_built) else int(r.median_year_built)
        avg_units = float(r.avg_units_per_bldg)
        rows.append(
            f'<tr data-block="{block_id}" data-area="{escape(local_area)}" '
            f'data-bldgs="{int(r.buildings)}" data-units="{int(r.total_units)}" '
            f'data-vtu-bldgs="{int(r.member_buildings)}">'  # block
            f'<td class="select-cell"><input type="checkbox" class="row-select" '
            f'data-type="block" data-target="{block_id}"></td>'
            f'<td data-sort-value="{block_label}">{block_label}</td>'
            f'<td data-sort-value="{int(r.buildings)}">{int(r.buildings)}</td>'
            f'<td data-sort-value="{int(r.total_units)}">{int(r.total_units)}</td>'
            f'<td data-sort-value="{avg_units}">{avg_units:.1f}</td>'
            f'<td data-sort-value="{year_val}">{year_val}</td>'
            f'<td data-sort-value="{int(r.member_buildings)}">{int(r.member_buildings)}</td>'
            f"</tr>"
        )
    return "\n".join(rows)


def rows_landlords(df: pd.DataFrame) -> str:
    rows = []
    for r in df.itertuples(index=False):
        owner_key = escape(str(r.owner_key))
        units_val = "" if pd.isna(r.total_units) else int(r.total_units)
        avg_units = float(r.avg_units_per_bldg)
        rows.append(
            f'<tr data-owner="{owner_key}" '
            f'data-bldgs="{int(r.buildings)}" data-units="{units_val if units_val != "" else 0}" '
            f'data-vtu-bldgs="{int(r.member_buildings)}">'  # owner
            f'<td class="select-cell"><input type="checkbox" class="row-select" '
            f'data-type="owner" data-target="{owner_key}"></td>'
            f"<td>{escape(str(r.owner_group))}</td>"
            f'<td data-sort-value="{int(r.buildings)}">{int(r.buildings)}</td>'
            f'<td data-sort-value="{units_val}">{units_val}</td>'
            f'<td data-sort-value="{avg_units}">{avg_units:.1f}</td>'
            f'<td data-sort-value="{int(r.member_buildings)}">{int(r.member_buildings)}</td>'
            f"</tr>"
        )
    return "\n".join(rows)


def rows_neighbourhoods(df: pd.DataFrame) -> str:
    rows = []
    for r in df.itertuples(index=False):
        local_area = escape(str(r.local_area))
        units_val = "" if pd.isna(r.total_units) else int(r.total_units)
        avg_units = float(r.avg_units_per_bldg)
        rows.append(
            f'<tr data-area="{local_area}" '
            f'data-bldgs="{int(r.buildings)}" data-units="{units_val if units_val != "" else 0}" '
            f'data-vtu-bldgs="{int(r.member_buildings)}">'  # neighbourhood
            f'<td class="select-cell"><input type="checkbox" class="row-select" '
            f'data-type="neighbourhood" data-target="{local_area}"></td>'
            f"<td>{local_area}</td>"
            f'<td data-sort-value="{int(r.buildings)}">{int(r.buildings)}</td>'
            f'<td data-sort-value="{units_val}">{units_val}</td>'
            f'<td data-sort-value="{avg_units}">{avg_units:.1f}</td>'
            f'<td data-sort-value="{int(r.member_buildings)}">{int(r.member_buildings)}</td>'
            f"</tr>"
        )
    return "\n".join(rows)
