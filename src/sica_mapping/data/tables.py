"""Table builders for the West End map UI."""

from __future__ import annotations

import numpy as np
import pandas as pd
from html import escape


def buildings_table(pts_df: pd.DataFrame) -> pd.DataFrame:
    tbl = pts_df[[
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
    ]].copy()
    tbl["member_share_pct"] = (tbl["member_share_building"] * 100).round(0).astype(int)
    return tbl.drop(columns=["member_share_building"]).sort_values(
        ["member_count", "units"], ascending=[False, False]
    )


def blocks_table(blocks_merged: pd.DataFrame) -> pd.DataFrame:
    tbl = blocks_merged.copy()
    tbl["median_year_built"] = tbl["median_year_built"].round().astype("Int64")
    tbl["share_pct"] = (tbl["member_share"] * 100).round(0).astype(int)
    return tbl[[
        "block_id",
        "buildings",
        "total_units",
        "median_year_built",
        "member_buildings",
        "total_members",
        "share_pct",
        "member_share",
    ]].sort_values("share_pct", ascending=False)


def landlords_table(pts_df: pd.DataFrame) -> pd.DataFrame:
    owners_df = pts_df.copy()
    owners_df["owner_group"] = owners_df["owner_group"].fillna("(Unknown)")
    owners_df["owner_key"] = owners_df["owner_key"].fillna("unknown")
    landlords = owners_df.groupby(["owner_group", "owner_key"]).agg(
        buildings=("address", "count"),
        total_units=("units", "sum"),
        member_buildings=("has_vtu_member", "sum"),
        total_members=("member_count", "sum"),
    ).reset_index()
    landlords["share_bldgs"] = np.where(
        landlords["buildings"] > 0,
        landlords["member_buildings"] / landlords["buildings"],
        0.0,
    )
    landlords["members_per_100_units"] = np.where(
        landlords["total_units"] > 0,
        landlords["total_members"] / landlords["total_units"] * 100.0,
        0.0,
    )
    landlords["share_pct"] = (landlords["share_bldgs"] * 100).round(0).astype(int)
    return landlords.sort_values(["total_units", "buildings"], ascending=[False, False])


def rows_buildings(df: pd.DataFrame) -> str:
    rows = []
    for r in df.itertuples(index=False):
        block_val = "" if pd.isna(r.block_id) else int(r.block_id)
        units_val = "" if pd.isna(r.units) else int(r.units)
        year_val = "" if pd.isna(r.year_built) else int(r.year_built)
        val_land = "" if pd.isna(r.value_land) else int(round(r.value_land))
        val_bldg = "" if pd.isna(r.value_bldg) else int(round(r.value_bldg))
        ratio_val = "" if pd.isna(r.bldg_land_ratio) else round(float(r.bldg_land_ratio), 3)
        member_total = int(r.member_count_all) if hasattr(r, "member_count_all") else int(r.member_count)
        bid = int(r.b_id)
        owner_key = escape(str(r.owner_key))
        local_area = "" if pd.isna(r.local_area) else str(r.local_area)
        search_terms = " ".join(
            str(val).lower()
            for val in (
                r.address,
                local_area,
                block_val,
                units_val,
                int(r.member_count),
                r.owner_group,
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
                f'data-member-total="{member_total}" data-search="{search_attr}">' \
                f'<td class="select-cell"><input type="checkbox" class="row-select" '
                f'data-type="building" data-target="{bid}"></td>'
                f'<td>{escape(str(r.address))}</td>'
                f'<td data-sort-value="{escape(local_area)}">{escape(local_area)}</td>'
                f'<td data-sort-value="{block_val}">{block_val}</td>'
                f'<td data-sort-value="{units_val}">{units_val}</td>'
                f'<td data-sort-value="{int(r.member_count)}">{int(r.member_count)}</td>'
                f'<td data-sort-value="{int(r.member_share_pct)}">{int(r.member_share_pct)}%</td>'
                f'<td>{escape(str(r.owner_group))}</td>'
                f'<td data-sort-value="{year_val}">{year_val}</td>'
                f'</tr>'
            )
        )
    return "\n".join(rows)


def rows_blocks(df: pd.DataFrame) -> str:
    rows = []
    for r in df.itertuples(index=False):
        block_id = int(r.block_id)
        year_val = "" if pd.isna(r.median_year_built) else int(r.median_year_built)
        rows.append(
            f'<tr data-block="{block_id}">'  # block
            f'<td class="select-cell"><input type="checkbox" class="row-select" '
            f'data-type="block" data-target="{block_id}"></td>'
            f'<td data-sort-value="{block_id}">{block_id}</td>'
            f'<td data-sort-value="{int(r.buildings)}">{int(r.buildings)}</td>'
            f'<td data-sort-value="{int(r.total_units)}">{int(r.total_units)}</td>'
            f'<td data-sort-value="{year_val}">{year_val}</td>'
            f'<td data-sort-value="{int(r.member_buildings)}">{int(r.member_buildings)}</td>'
            f'<td data-sort-value="{int(r.total_members)}">{int(r.total_members)}</td>'
            f'<td data-sort-value="{int(r.share_pct)}">{int(r.share_pct)}%</td>'
            f'</tr>'
        )
    return "\n".join(rows)


def rows_landlords(df: pd.DataFrame) -> str:
    rows = []
    for r in df.itertuples(index=False):
        owner_key = escape(str(r.owner_key))
        units_val = "" if pd.isna(r.total_units) else int(r.total_units)
        share_pct = int(round(r.share_bldgs * 100))
        per_100 = int(round(r.members_per_100_units))
        rows.append(
            f'<tr data-owner="{owner_key}">'  # owner
            f'<td class="select-cell"><input type="checkbox" class="row-select" '
            f'data-type="owner" data-target="{owner_key}"></td>'
            f'<td>{escape(str(r.owner_group))}</td>'
            f'<td data-sort-value="{int(r.buildings)}">{int(r.buildings)}</td>'
            f'<td data-sort-value="{units_val}">{units_val}</td>'
            f'<td data-sort-value="{int(r.member_buildings)}">{int(r.member_buildings)}</td>'
            f'<td data-sort-value="{int(r.total_members)}">{int(r.total_members)}</td>'
            f'<td data-sort-value="{share_pct}">{share_pct}%</td>'
            f'<td data-sort-value="{per_100}">{per_100}</td>'
            f'</tr>'
        )
    return "\n".join(rows)
