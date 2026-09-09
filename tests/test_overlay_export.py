"""export.py overlay helpers: building columns, unmatched records, coverage."""

from __future__ import annotations

from sica_core.export import (
    overlay_building_columns,
    overlay_coverage,
    overlay_unmatched_records,
)


def test_building_columns_shape_and_flags(overlay_db):
    df = overlay_building_columns(overlay_db).set_index("b_id")
    # b1 co-op, b2 SRO, b3 co-op (secondary) + rezoning
    assert bool(df.loc[1, "is_coop"]) and not bool(df.loc[1, "is_sro"])
    assert bool(df.loc[2, "is_sro"]) and not bool(df.loc[2, "is_coop"])
    assert bool(df.loc[3, "is_coop"]) and bool(df.loc[3, "is_rezoning"])
    assert df.loc[1, "coop_status"] == "Open"
    assert df.loc[2, "sro_owner"] == "Owner A"
    assert df.loc[3, "rezoning_status"] == "Approved"
    assert df.loc[3, "rezoning_status_group"] == "closed"  # "Approved" -> closed
    assert df.loc[1, "housing_type"] == "co-op"
    assert df.loc[2, "housing_type"] == "sro"


def test_unmatched_records_shape(overlay_db):
    recs = overlay_unmatched_records(overlay_db)
    by_source = {}
    for r in recs:
        by_source.setdefault(r["source"], []).append(r)
    assert len(by_source["coop"]) == 1
    assert len(by_source["sro"]) == 1
    assert len(by_source["rezoning"]) == 2

    coop = by_source["coop"][0]
    assert coop["synthetic_id"] == "coop-C3-3"
    assert (
        coop["housing_type"] == "coop"
    )  # quirk: unmatched co-op uses "coop", matched uses "co-op"
    assert coop["local_area"] == "Downtown"
    assert set(coop["popup_fields"]) == {
        "title",
        "status",
        "ownership_model",
        "read_more_url",
    }

    rez = next(
        r for r in by_source["rezoning"] if r["synthetic_id"] == "rezoning-RZ3-3"
    )
    assert rez["rezoning_status"] == "Refused"
    assert rez["rezoning_status_group"] == "open"


def test_coverage_numbers(overlay_db):
    cov = overlay_coverage(overlay_db)
    assert cov["coop"] == {
        "total": 3,
        "matched": 2,
        "address": 1,
        "secondary_address": 1,
        "unmatched": 1,
        "match_rate": round(2 / 3, 4),
    }
    assert cov["sro"]["matched"] == 1 and cov["sro"]["total"] == 2
    assert cov["rezoning"]["matched"] == 1 and cov["rezoning"]["total"] == 3
