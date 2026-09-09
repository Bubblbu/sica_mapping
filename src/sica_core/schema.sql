-- ============================================================
-- REBUILDABLE — safe to DROP + recreate on every ingest run.
-- Derived from source CSVs; nothing here is hand-authored.
-- ============================================================

DROP TABLE IF EXISTS overlay_matches;
DROP TABLE IF EXISTS vtu_membership;
DROP TABLE IF EXISTS buildings;
DROP TABLE IF EXISTS landlords;
DROP TABLE IF EXISTS blocks;
DROP TABLE IF EXISTS raw_addresses;
DROP TABLE IF EXISTS raw_buildings;
DROP TABLE IF EXISTS raw_block_numbers;
DROP TABLE IF EXISTS raw_sro;
DROP TABLE IF EXISTS raw_coops;
DROP TABLE IF EXISTS raw_rezoning;
DROP TABLE IF EXISTS raw_local_areas;
DROP VIEW IF EXISTS block_stats;

CREATE TABLE raw_buildings (
    raw_building_id INTEGER PRIMARY KEY,
    local_area TEXT,
    address TEXT,
    secondary_addresses TEXT,  -- ";"-joined other civic addresses for this building; NULL on older buildings.csv vintages
    primary_address TEXT,
    is_primary_address INTEGER,
    n_pids INTEGER,
    pid TEXT,
    units INTEGER,
    year_built INTEGER,
    bsns_group TEXT,
    bsns_name TEXT,
    bsns_trade_name TEXT,
    bsns_type TEXT,
    value_land TEXT,        -- verbatim: source mixes plain numbers and "$..." strings; parse at merge time
    value_bldg TEXT,        -- verbatim, same reason
    bldg_land_ratio REAL,
    value_per_unit TEXT,
    zoning TEXT,
    name TEXT,
    management TEXT,
    n_issues INTEGER,
    issues_details TEXT,
    notes TEXT,
    prospect TEXT,
    ingested_at TEXT NOT NULL
);
CREATE INDEX idx_raw_buildings_address ON raw_buildings(address);
CREATE INDEX idx_raw_buildings_local_area ON raw_buildings(local_area);

CREATE TABLE raw_addresses (
    raw_address_id INTEGER PRIMARY KEY,
    civic_number TEXT,
    geo_local_area TEXT,
    geom TEXT,
    p_parcel_id TEXT,
    pcoord TEXT,
    site_id TEXT,
    std_street TEXT,
    geo_point_2d TEXT,      -- "lat, lon" verbatim
    ingested_at TEXT NOT NULL
);
CREATE INDEX idx_raw_addresses_street ON raw_addresses(std_street);
CREATE INDEX idx_raw_addresses_civic ON raw_addresses(civic_number);

-- Vancouver Open Data's "block-numbers" dataset: one point per city block,
-- carrying the City's own authoritative geo_local_area — used only to
-- resolve local_area for blocks with zero buildings (see export.py /
-- spatial.py's resolve_local_area_from_block_numbers).
CREATE TABLE raw_block_numbers (
    raw_block_number_id INTEGER PRIMARY KEY,
    label TEXT,
    geo_local_area TEXT,
    geom TEXT,
    geo_point_2d TEXT,      -- "lat, lon" verbatim
    ingested_at TEXT NOT NULL
);

-- SRO/SRA, co-op, and rezoning-application sources: raw storage, verbatim
-- from their CSVs (ingest/raw_sro.py, raw_coops.py, raw_rezoning.py). No
-- matching against buildings happens at load time — that's the job of
-- ingest/overlays.py (the merge step), which reads these rows and writes
-- overlay_matches. See docs/DATA_SOURCES.md for each source's (partially
-- unverified) origin.
CREATE TABLE raw_sro (
    raw_sro_id INTEGER PRIMARY KEY,
    source_id TEXT,            -- the source's own "ID" column
    address TEXT,
    building_name TEXT,
    secondary_address TEXT,
    area TEXT,
    latitude REAL,
    longitude REAL,
    owner TEXT,
    operator TEXT,
    operator_group TEXT,
    ownership_group TEXT,
    registered_rooms INTEGER,
    occupancy_status TEXT,
    match_method TEXT,        -- upstream address-matching flag from whoever combined the source lists; unrelated to our own matching
    ingested_at TEXT NOT NULL
);
CREATE INDEX idx_raw_sro_address ON raw_sro(address);

CREATE TABLE raw_coops (
    raw_coop_id INTEGER PRIMARY KEY,
    source_id TEXT,            -- the source's own "id" column
    title TEXT,
    city TEXT,
    region TEXT,
    neighbourhood TEXT,
    school_district TEXT,
    address TEXT,
    lat REAL,
    lon REAL,
    status TEXT,
    ownership_model TEXT,
    bedrooms_min REAL,
    bedrooms_max REAL,
    home_types TEXT,
    features TEXT,
    summary TEXT,
    featured_image TEXT,
    website TEXT,
    read_more_url TEXT,
    ingested_at TEXT NOT NULL
);
CREATE INDEX idx_raw_coops_address ON raw_coops(address);

CREATE TABLE raw_rezoning (
    raw_rezoning_id INTEGER PRIMARY KEY,
    source_id TEXT,            -- the source's own "ID" column (e.g. "RZ285"); NOT reliably unique per row
    name TEXT,
    status TEXT,
    category TEXT,
    status_detail TEXT,
    latitude REAL,
    longitude REAL,
    link TEXT,
    ingested_at TEXT NOT NULL
);

-- Vancouver's 22 official local-area boundary polygons (ingest/raw_local_areas.py).
-- ingest/overlays.py point-in-polygons an unmatched overlay record's lat/lon
-- against these to give it a local_area that lines up with the map's
-- neighbourhood filter checkboxes.
CREATE TABLE raw_local_areas (
    raw_local_area_id INTEGER PRIMARY KEY,
    name TEXT,
    geom TEXT,              -- GeoJSON polygon, verbatim
    geo_point_2d TEXT,      -- "lat, lon" verbatim
    ingested_at TEXT NOT NULL
);

CREATE TABLE blocks (
    block_id INTEGER PRIMARY KEY,
    geom TEXT NOT NULL,               -- GeoJSON polygon, verbatim
    in_west_end_bbox INTEGER NOT NULL DEFAULT 0,
    source_row_ids TEXT,
    ingested_at TEXT NOT NULL
);

CREATE TABLE landlords (
    landlord_id INTEGER PRIMARY KEY,
    display_name TEXT NOT NULL,       -- via clean_owner_label()
    owner_key TEXT NOT NULL,          -- via sanitize_owner()
    source_row_ids TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_landlords_owner_key ON landlords(owner_key);

CREATE TABLE buildings (
    building_id INTEGER PRIMARY KEY,
    addr_key TEXT NOT NULL UNIQUE,
    address TEXT NOT NULL,
    local_area TEXT,
    lat REAL,
    lon REAL,
    units INTEGER,
    year_built INTEGER,
    value_land NUMERIC,
    value_bldg NUMERIC,
    bldg_land_ratio REAL,
    n_issues INTEGER,
    landlord_id INTEGER REFERENCES landlords(landlord_id),
    block_id INTEGER REFERENCES blocks(block_id),
    source_row_ids TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_buildings_landlord ON buildings(landlord_id);
CREATE INDEX idx_buildings_block ON buildings(block_id);
CREATE INDEX idx_buildings_local_area ON buildings(local_area);

-- Result of ingest/overlays.py: one row per raw_sro/raw_coops/raw_rezoning
-- record, saying whether (and how) it matched a building. Fully derived —
-- dropped and rebuilt every run, same as the raw tables it's computed from.
--   building_id NULL          -> unmatched; becomes a standalone map marker
--   match_method 'address'    -> the source's own address/name keyed a building
--   match_method 'secondary_address' -> matched via raw_buildings.secondary_addresses
--   match_method 'unmatched'  -> no key hit (building_id is NULL)
CREATE TABLE overlay_matches (
    overlay_match_id INTEGER PRIMARY KEY,
    overlay_source TEXT NOT NULL CHECK (overlay_source IN ('sro','coop','rezoning')),
    raw_row_id INTEGER NOT NULL,   -- PK in the raw_<source> table named by overlay_source
    building_id INTEGER REFERENCES buildings(building_id),
    match_method TEXT NOT NULL CHECK (match_method IN ('address','secondary_address','unmatched')),
    match_key TEXT,                -- the addr_key (or rezoning name fragment key) used
    local_area TEXT,              -- point-in-polygon result, for unmatched markers
    created_at TEXT NOT NULL
);
CREATE INDEX idx_overlay_matches_source ON overlay_matches(overlay_source);
CREATE INDEX idx_overlay_matches_building ON overlay_matches(building_id);

-- Allow-listed columns only — see ingest/membership.py's ALLOWED_MEMBERSHIP_COLUMNS
-- (a later step). No name/email/phone/ethnicity/religion/donation data ever lands
-- here, even though the source NationBuilder export carries all of that.
-- Whole table is treated as non-public by default at export time (later step).
CREATE TABLE vtu_membership (
    membership_row_id INTEGER PRIMARY KEY,
    nationbuilder_id TEXT,
    addr_key TEXT,
    building_id INTEGER REFERENCES buildings(building_id),
    tag_list TEXT,
    updated_at TEXT,
    source_row_ids TEXT,
    ingested_at TEXT NOT NULL
);
CREATE INDEX idx_vtu_membership_addr_key ON vtu_membership(addr_key);
CREATE INDEX idx_vtu_membership_building ON vtu_membership(building_id);

-- Illustrative aggregate view — mirrors today's aggregate_blocks() shape.
-- Computed on read, never stored, so it can't go stale when a building changes.
CREATE VIEW block_stats AS
SELECT
    bl.block_id,
    COUNT(DISTINCT bd.building_id) AS buildings,
    COALESCE(SUM(bd.units), 0) AS total_units,
    COUNT(DISTINCT CASE WHEN vm.membership_row_id IS NOT NULL THEN bd.building_id END) AS member_buildings,
    COUNT(vm.membership_row_id) AS total_members
FROM blocks bl
LEFT JOIN buildings bd ON bd.block_id = bl.block_id
LEFT JOIN vtu_membership vm ON vm.building_id = bd.building_id
GROUP BY bl.block_id;

-- ============================================================
-- PERSISTENT — never dropped by rebuild. Hand-authored, irreplaceable.
-- Uses CREATE TABLE IF NOT EXISTS only. The ingest/rebuild routine must
-- never issue a DROP against anything in this section.
-- ============================================================

CREATE TABLE IF NOT EXISTS ownership_claims (
    claim_id INTEGER PRIMARY KEY,
    entity_a TEXT NOT NULL,
    entity_b TEXT NOT NULL,
    relationship TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_note TEXT,
    reported_by TEXT,
    date_reported TEXT,
    confidence TEXT NOT NULL DEFAULT 'unconfirmed' CHECK (confidence IN ('unconfirmed','confirmed')),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','retracted')),
    retracted_at TEXT,
    retracted_reason TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_claims_entity_a ON ownership_claims(entity_a);
CREATE INDEX IF NOT EXISTS idx_claims_entity_b ON ownership_claims(entity_b);
CREATE INDEX IF NOT EXISTS idx_claims_status ON ownership_claims(status);
