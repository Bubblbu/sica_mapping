"""Data processing helpers for the West End map."""

from .pipeline import (
    PIPELINE_CACHE_FILES,
    BUILDING_METRICS,
    build_building_metrics,
    run_data_pipeline,
    write_cached_data,
    load_cached_data,
    cached_data_exists,
)
from .spatial import (
    prepare_addresses,
    select_west_end_buildings,
    join_buildings_addresses,
    deduplicate_buildings,
    parse_blocks,
    aggregate_blocks,
    blocks_feature_collection,
    point_in_block_ids,
)
from .geometry import poly_to_geojson
from .tables import (
    buildings_table,
    blocks_table,
    landlords_table,
    rows_buildings,
    rows_blocks,
    rows_landlords,
)
from .vtu import (
    prepare_membership_records,
    membership_records_by_address,
    membership_filter_config,
    compute_vtu_counts,
    attach_vtu_metrics,
)

__all__ = [
    "PIPELINE_CACHE_FILES",
    "BUILDING_METRICS",
    "build_building_metrics",
    "run_data_pipeline",
    "write_cached_data",
    "load_cached_data",
    "cached_data_exists",
    "prepare_addresses",
    "select_west_end_buildings",
    "join_buildings_addresses",
    "deduplicate_buildings",
    "parse_blocks",
    "aggregate_blocks",
    "blocks_feature_collection",
    "poly_to_geojson",
    "point_in_block_ids",
    "buildings_table",
    "blocks_table",
    "landlords_table",
    "rows_buildings",
    "rows_blocks",
    "rows_landlords",
    "prepare_membership_records",
    "membership_records_by_address",
    "membership_filter_config",
    "compute_vtu_counts",
    "attach_vtu_metrics",
]
