# Data Sources

*Reference catalog. Update whenever a source is added, re-fetched, or its details change — see [Adding a new source](#adding-a-new-source) at the bottom.*

Last updated: 2026-08-05

---

## Scope

This document catalogs **acquisition** — how each external dataset gets from its
origin into a file under `data/`, and what's known about that origin (license,
format, cadence, quirks). It stops there.

- What happens *after* acquisition — parsing a `data/*.csv` into `sica_core`'s
  SQLite tables — is covered by the code itself: one `ingest/raw_<source>.py`
  module per source under `src/sica_core/ingest/`, each with an explicit
  column allow-list. That pattern is the target for new sources going
  forward; this doc doesn't re-describe it.
- **Manually-curated data** (tenant reports, common-ownership research) is not
  an acquisition source and isn't cataloged here — see
  [Manual curation](#manual-curation) below for where it actually lives.
- This doc is the detailed per-source reference. `CLAUDE.md` Section 3 stays
  the short decisions/roadmap summary and links here.

## Conventions

- **Retain originals.** Where a source arrives as a document (FOI PDF/
  spreadsheet, a scraped page) rather than a clean CSV, the as-received file
  is kept under `data/sources/<source_name>/`, separate from the processed
  CSV the pipelines actually read (which keeps its existing path in `data/`
  unchanged — this is additive, not a reorg).
- **Script vs. manual.** A source gets a `scripts/fetch_<source>.py` (see
  `fetch_coops.py` for the pattern: documented, replayable offline via a
  `--html-file`-style flag) if it's expected to be re-pulled periodically.
  A stable, official one-off pull (a City Open Data export, an FOI response)
  is fine as a documented manual procedure — write out the exact steps in
  that source's entry instead.
- **No in-place hand edits.** Once a CSV is retained as "this is what the
  source gave us," don't hand-edit it directly (e.g. in LibreOffice) — that
  silently blurs source data with manual correction and breaks the retained
  original as a source of truth. Fix problems upstream (re-derive from the
  retained original) or record the correction as a dated note in that
  source's entry.
- **TODO markers** below are real gaps, not rhetorical — facts only you have
  (FOI reference numbers, exact portal URLs) that weren't recoverable from
  the repo. Fill them in as you get a chance; they're not blocking anything.

---

## Summary

| Source | Category | Last fetched | Refresh cadence | Consumed by |
|---|---|---|---|---|
| [`buildings.csv`](#buildingscsv) | Open Data + hand-added fields ⚠️ | TODO | Ad hoc | `sica_mapping`, `sica_core` |
| [`property_addresses.csv`](#property_addressescsv) | Open Data portal | TODO | Ad hoc | `sica_mapping`, `sica_core` |
| [`block-outlines.csv`](#block-outlinescsv) | Open Data portal | TODO | Ad hoc | `sica_mapping`, `sica_core` |
| [`block-numbers.csv`](#block-numberscsv) | Open Data portal | TODO | Ad hoc | `sica_mapping`, `sica_core` |
| [`local-area-boundary.csv`](#local-area-boundarycsv) | Open Data portal | TODO | Rare (stable boundaries) | `sica_mapping` |
| [`sra_housing_combined.csv`](#sra_housing_combinedcsv) | FOI? — unverified ⚠️ | 2026-07-30 (file date) | TODO | `sica_mapping` |
| [`rezoning_applications.csv`](#rezoning_applicationscsv) | FOI? — unverified ⚠️ | 2026-07-30 (file date) | TODO | `sica_mapping` |
| [`coops_vancouver.csv`](#coops_vancouvercsv) | Third-party online | 2026-08-04 | Periodic (re-run script) | `sica_mapping` |
| [`membership_full.csv`](#membership_fullcsv) | Internal / organizational | TODO | VTU's own cadence | `sica_core` |
| [`vtu_membership_public.csv`](#vtu_membership_publiccsv) | Derived (generated locally, committed) | TODO | Regenerate after each `membership_full.csv` refresh | `sica_mapping` |
| [`vtu_members.csv`](#vtu_memberscsv) | Internal / organizational — likely orphaned ⚠️ | — | — | none found |

⚠️ = flagged for your attention, see that source's entry.

---

## Open Data portal

Sources pulled from the City of Vancouver's Open Data platform
(opendata.vancouver.ca). Currently all manual downloads — no fetch script
exists yet for any of them. Column names like `geo_point_2d`, `geom`,
`geo_local_area` are the portal's own naming convention, visible directly in
the raw CSVs.

### `buildings.csv`

- **What it is:** the core building/landlord table — address, unit count,
  year built, assessed land/building value, zoning, plus City rental
  business-licence fields (`bsns_group`, `bsns_name`, `bsns_trade_name`,
  `bsns_type`).
- **⚠️ Not a pure Open Data pull.** Several columns in this file —
  `management`, `n_issues`, `issues_details`, `notes`, `prospect` — read as
  hand-added/curated, not sourced from the portal
  (`src/sica_core/ingest/raw_buildings.py` keeps them verbatim but they have
  no Open Data equivalent). `raw_buildings.py` already strips four other
  columns — `vtu_members`, `westend_inbox`, `vtu_main_inbox`, `vtu_building`
  — as "a one-off artifact from manually merging buildings.csv with a small
  organizing-status tracking sheet." The five kept columns above look like
  the same kind of thing, just not yet flagged. Worth deciding: are these
  hand-added columns actually part of this "Open Data" source at all, or do
  they belong in their own tracked manual layer (arguably close to the
  future `ownership_claims`/organizer-view model in `CLAUDE.md`)? TODO:
  your call.
- **Origin:** TODO — exact dataset URL/export. Likely the portal's rental
  business licence dataset, joined with something producing land/building
  values (BC Assessment data via the portal, or a separate export) —
  unconfirmed.
- **License/attribution:** TODO — Vancouver Open Data's default license
  (Open Government Licence – Vancouver) likely applies; confirm and note any
  attribution requirement once the exact dataset is identified.
- **Geographic scope:** appears pre-filtered to West End already in this
  file (or filtered downstream — TODO confirm which).
- **Access method:** manual download from the portal (steps TODO).
- **Format/known quirks:** `value_land`/`value_bldg` are `TEXT`, not
  numeric — 100% of West End rows use `"$35,407,000.00"`-style formatting.
  A prior version of the pipeline's bare `pd.to_numeric(errors="coerce")`
  silently nulled every West End row on this; fixed in
  `sica_core/ingest/merge.py::_parse_money()`. If a fresh export ever
  arrives fully numeric, `raw_buildings.py` raises rather than silently
  accepting the new shape.
- **Output location:** `data/buildings.csv`.
- **Consumed by:** `sica_mapping` (`config.toml` → `buildings`), `sica_core`
  (`ingest/raw_buildings.py`).
- **Refresh cadence:** ad hoc / not tracked historically. TODO: decide one.

### `property_addresses.csv`

- **What it is:** civic addresses with lat/lon and local-area tagging —
  used to geocode buildings and recover missing coordinates.
- **Origin:** TODO — exact dataset URL (columns `civic_number`,
  `geo_local_area`, `geom`, `p_parcel_id`, `pcoord`, `site_id`,
  `std_street`, `geo_point_2d` strongly suggest the portal's "Property
  Addresses" dataset; URL unconfirmed).
- **License/attribution:** TODO.
- **Geographic scope:** citywide (filtered to West End downstream by the
  pipelines, not in the file itself).
- **Access method:** manual download (steps TODO).
- **Format/known quirks:** `geo_point_2d` holds `"lat,lon"` as a single
  string, parsed downstream. `sica_core/ingest/raw_addresses.py` raises on
  any column not in its allow-list rather than silently dropping it.
- **Output location:** `data/property_addresses.csv`.
- **Consumed by:** `sica_mapping` (`config.toml` → `addresses`), `sica_core`
  (`ingest/raw_addresses.py`).
- **Refresh cadence:** ad hoc / not tracked historically. TODO: decide one.

### `block-outlines.csv`

- **What it is:** polygon geometry for city blocks, used for block-level
  choropleth aggregation (unit totals, VTU saturation, median year built).
- **Origin:** TODO — exact dataset URL/name.
- **License/attribution:** TODO.
- **Geographic scope:** citywide; `sica_core/ingest/blocks.py` keeps every
  row and records a `in_west_end_bbox` flag rather than dropping rows
  outside the pilot bbox, so the table stays fully browsable.
- **Access method:** manual download (steps TODO).
- **Format/known quirks:** polygon geometry lives in a `geom` column,
  parsed via `sica_core/geometry.py::parse_geom`.
- **Output location:** `data/block-outlines.csv`.
- **Consumed by:** `sica_mapping` (`config.toml` → `blocks`), `sica_core`
  (`ingest/blocks.py`).
- **Refresh cadence:** ad hoc / not tracked historically. TODO: decide one.

### `block-numbers.csv`

- **What it is:** point locations with a `label` and `geo_local_area`, used
  to resolve which of the 22 official local areas a block/building falls
  in (point-in-polygon primary, nearest-centroid fallback).
- **Origin:** confirmed to be Vancouver Open Data's "block-numbers" dataset
  by name (`src/sica_mapping/data/spatial.py` docstring cites it directly);
  exact URL still TODO.
- **License/attribution:** TODO.
- **Geographic scope:** citywide.
- **Access method:** manual download (steps TODO).
- **Format/known quirks:** none noted beyond standard portal column naming
  (`geom`, `geo_point_2d`). `sica_core/ingest/block_numbers.py` raises on
  unexpected columns.
- **Output location:** `data/block-numbers.csv`.
- **Consumed by:** `sica_mapping` (`spatial.py::resolve_local_area_from_block_numbers`),
  `sica_core` (`ingest/block_numbers.py`).
- **Refresh cadence:** rare — local area/block boundaries change
  infrequently. Re-pull only if the City revises them.

### `local-area-boundary.csv`

- **What it is:** the 22 official Vancouver local-area boundary polygons,
  used to assign a `local_area` to overlay records (co-ops, SRO/SRA,
  rezoning applications) that don't already carry one that matches the
  sidebar's neighbourhood checkboxes.
- **Origin:** TODO — exact dataset URL/name (likely the portal's "Local
  Area Boundary" dataset).
- **License/attribution:** TODO.
- **Geographic scope:** citywide, all 22 local areas.
- **Access method:** manual download (steps TODO).
- **Format/known quirks:** GeoJSON-style `FeatureCollection`, `properties.name`
  used as the area label. `src/sica_mapping/data/overlays.py` deliberately
  does *not* trust each overlay source's own free-text area field (e.g. the
  SRO CSV's "Area" is a DTES-style composite label) — always resolves via
  point-in-polygon against this file instead.
- **Output location:** `data/local-area-boundary.csv`.
- **Consumed by:** `sica_mapping` only (`overlays.py`) — not yet ingested
  into `sica_core`.
- **Refresh cadence:** rare — official boundaries change infrequently.

---

## FOI records

**⚠️ Category unverified.** Both files below were assumed to be FOI
responses (per `CLAUDE.md`'s "City of Vancouver FOI records" source type),
but nothing in the repo actually confirms that:

- `rezoning_applications.csv`'s `Link` column points to Wayback
  Machine/archive-it.org captures of individual `rezoning.vancouver.ca`
  application pages — consistent with **manually compiling this by browsing
  archived web pages**, not a formal FOI request.
- `sra_housing_combined.csv`'s own `match_method` column (values like
  `"address"`) suggests it's already a **merge of at least two source
  lists** by address — possibly assembled by a third party (an advocacy
  group's SRO hotel registry is a plausible candidate) rather than a direct
  FOI response.

TODO: confirm the actual origin of each and re-file it under the correct
category (most likely "Third-party online" for one or both) once confirmed.
Sections kept here for now since that's the best guess available.

### `sra_housing_combined.csv`

- **What it is:** SRO/SRA (single-room-occupancy) hotel inventory — owner,
  operator, operator group, ownership group, registered room count,
  occupancy status.
- **Origin:** TODO (see category warning above) — request date, reference
  number if FOI; source URL/organization if not.
- **License/attribution:** TODO.
- **Geographic scope:** DTES/Chinatown/Gastown/Strathcona-concentrated (per
  the file's own `Area` field), not West End.
- **Access method:** TODO — no script; unclear if this can even be
  re-fetched the same way twice (a merged/combined file may not have a
  single re-runnable source).
- **Format/known quirks:** the file's own `match_method` column is an
  upstream address-matching flag from whoever combined the source lists —
  unrelated to and not used by this project's own address-key matching in
  `src/sica_mapping/data/overlays.py`.
- **Provenance/original retained:** **not yet** — no original document is
  currently kept. Per the retain-originals convention above, the source
  document(s) this was combined from should be saved under
  `data/sources/sra_housing/` going forward, with a note on how the merge
  was done. TODO once the origin is confirmed.
- **Output location:** `data/sra_housing_combined.csv`.
- **Consumed by:** `sica_mapping` only (`overlays.py`) — 41/171 rows (24%)
  match an existing building by address; the rest surface as standalone
  unmatched markers.
- **Refresh cadence:** TODO.

### `rezoning_applications.csv`

- **What it is:** rezoning application records — status (open/approved),
  category, status detail, and a link to the application's page.
- **Origin:** TODO (see category warning above) — likely compiled from
  `rezoning.vancouver.ca` (live and/or Wayback-archived), possibly
  alongside or instead of a formal FOI response.
- **License/attribution:** TODO.
- **Geographic scope:** citywide.
- **Access method:** TODO — if compiled from archived web pages by hand,
  document the actual steps (which archive snapshots, what was pulled from
  each) rather than leaving it as "FOI."
- **Format/known quirks:** `id` (e.g. `RZ285`) is **not** reliably unique
  per row — a multi-site "umbrella" application can cover two entirely
  different addresses/lat-lons as separate rows with the same `id`
  (confirmed via a real duplicate-key collision during testing — see
  `overlays.py`). `name` is free text, not a clean address (e.g.
  `"2165-2195 and 2205-2291 W 45th Av (Dunbar Ryerson United Church)"`) —
  parsed by stripping from the first `(`, then splitting on
  `" and "`/`"&"`/`";"` and keying the first fragment. Most rezoning
  applications (churches, single-family lots, commercial, multi-lot
  assemblies) don't correspond to any row in `buildings.csv` at all,
  regardless of parsing quality — ~43/377 (11%) match.
- **Provenance/original retained:** **not yet** — TODO, same as above.
- **Output location:** `data/rezoning_applications.csv`.
- **Consumed by:** `sica_mapping` only (`overlays.py`), split into
  open/closed status groups.
- **Refresh cadence:** TODO.

---

## Third-party online

Data pulled from an external organization's own website or public dataset —
not the City's Open Data portal, not FOI, not VTU's own systems.

### `coops_vancouver.csv`

- **What it is:** CHF BC's ("Co-operative Housing Federation of BC")
  province-wide co-op housing directory, filtered to Vancouver — address,
  coordinates, waitlist status, ownership model, bedroom range, home type,
  accessibility/seniors/pets/RGI features, source links.
- **Origin:** [chf.bc.ca/find-a-co-op](https://www.chf.bc.ca/find-a-co-op/) —
  the page embeds its entire dataset as inline JSON in a
  `<script class="coop-explorer__data">` tag; no separate API call needed.
- **License/attribution:** TODO — confirm CHF BC's terms of use for reuse
  of this data, and what attribution (if any) is expected before this
  reaches the public map.
- **Geographic scope:** filtered to CHF's own `location.city == "Vancouver"`
  field (city-wide, not clipped to West End or any block/bbox geometry —
  deliberately, since this isn't scoped to the pilot).
- **Access method:** **scripted** — `scripts/fetch_coops.py`. Supports
  `--html-file` for an offline replay against a previously-saved page, and
  `--city`/`--out` overrides. This is the reference example for how a
  scripted source should be documented.
- **Format/known quirks:** the page blocks bare-looking scripted requests —
  the script sends a normal browser `User-Agent` to get a plain 200. Filter
  matches on `"Vancouver"` exactly; if CHF ever changes the field to e.g.
  `"City of Vancouver"`, the script's `normalize_coops()` raises rather than
  silently returning zero rows.
- **Provenance/original retained:** not currently — the fetched HTML is not
  saved, only the derived CSV. Per the retain-originals convention, future
  re-runs could optionally save the fetched HTML under
  `data/sources/coops_chf_bc/<date>.html` for exact replay/audit later;
  not done yet (TODO, low priority given the script re-fetches live data
  cleanly).
- **Output location:** `data/coops_vancouver.csv`.
- **Consumed by:** `sica_mapping` only (`overlays.py`) — 42/117 rows (36%)
  match an existing building by address; the rest surface as standalone
  unmatched markers. Not yet ingested into `sica_core`.
- **Refresh cadence:** periodic, re-run by hand
  (`python scripts/fetch_coops.py`) when a refresh is wanted. 117 co-ops as
  of 2026-08-04 (287 province-wide).

---

## Internal / organizational

VTU's own data, not pulled from any public source. The one category here
that's genuinely sensitive — see `CLAUDE.md` Section 3's sensitivity model
rather than this doc for how field-level access is handled.

### `membership_full.csv`

- **What it is:** VTU's NationBuilder membership export — 154 columns
  (emails, phone, ethnicity, religion, donation history, marital status,
  and more), of which only `nationbuilder_id`, `primary_address1`,
  `tag_list`, and `updated_at` are ever read.
- **Origin:** VTU's NationBuilder account, exported by VTU on its own
  cadence. Not a public pull — controlled internally.
- **License/attribution:** N/A (internal data) — but see sensitivity note
  below regarding what may ever be exported publicly.
- **⚠️ Sensitivity:** this is the one source containing directly
  identifying/sensitive tenant data. `sica_core/ingest/membership.py`
  enforces an explicit column allow-list at the CSV-read layer itself
  (`pd.read_csv(usecols=...)`), so the other ~150 columns never become an
  in-memory column, let alone a database row. The address column is
  hardcoded to `primary_address1` rather than found via substring search —
  a reordered NationBuilder export could otherwise silently start reading a
  different address-like column (`address_address1`, `billing_address1`,
  `mailing_address1`, `work_address1`, `user_submitted_address1` all exist)
  with no error. See `CLAUDE.md` Section 3 ("Sensitivity model") for the
  broader field-level flagging approach this feeds into.
- **Access method:** manual export from NationBuilder by VTU; not
  scriptable from this project's side.
- **Output location:** `data/Nationbuilder/membership_full.csv` — that whole
  directory is gitignored (`data/Nationbuilder/*`) and never committed; this
  file only ever exists on someone's local machine.
- **Consumed by:** `sica_core` (`ingest/membership.py`) directly, via
  config.toml's `vtu_raw` path. `sica_mapping` no longer reads this file at
  all — it reads the derived `vtu_membership_public.csv` below instead. That
  split (2026-09-09) is what fixes the leak this section used to warn about:
  the raw export used to be committed and consumed directly by the public
  map build.
- **Refresh cadence:** VTU's own cadence — TODO: confirm how often VTU
  re-exports and whether there's a standing arrangement for this. Whenever
  it's refreshed, re-run `scripts/build_vtu_public_extract.py` to regenerate
  `vtu_membership_public.csv` from it.

### `vtu_membership_public.csv`

- **What it is:** the public, address-level aggregate derived from
  `membership_full.csv` — one row per address with `addr_key`,
  `member_count_active`, `member_count_all`, and `latest_membership_year`
  only. No per-member rows, tags, or timestamps.
- **Origin:** generated locally by `scripts/build_vtu_public_extract.py`
  (reads config's `vtu_raw` path, writes config's `vtu` path) — not fetched
  from anywhere; regenerate it after every `membership_full.csv` refresh.
- **License/attribution:** N/A (derived internal data), but safe to commit
  and safe to feed the public build — the resolution matches exactly what a
  building's public marker already shows (a count), never more.
- **Access method:** `uv run python scripts/build_vtu_public_extract.py`.
- **Output location:** `data/vtu_membership_public.csv` (committed).
- **Consumed by:** `sica_mapping` (`data/pipeline.py`), via config.toml's
  `vtu` path.
- **Refresh cadence:** tied to `membership_full.csv`'s refresh cadence, not
  independent.

### `vtu_members.csv`

- **⚠️ Likely orphaned.** 566 rows, only 3 columns
  (`nationbuilder_id`, `primary_address1`, `address`) — looks like an older,
  already-narrowed export that predates `membership_full.csv`. No code in
  either `sica_mapping` or `sica_core` references this file by name
  (confirmed via repo-wide search); neither `config.toml` path (`vtu` or
  `vtu_raw`) points at it.
- **Output location:** `data/Nationbuilder/vtu_members.csv` — gitignored
  alongside `membership_full.csv`.
- **Recommendation:** confirm it's genuinely unused, then either delete it
  or keep it as a dated historical snapshot rather than leaving it sitting
  next to the live input looking like one.

---

## Manual curation

Not cataloged here — manually-curated ownership intelligence (tenant
reports, common-ownership research) is modeled as its own first-class,
auditable table (`ownership_claims`), not a file with a URL or a fetch
cadence. See `CLAUDE.md` Section 3 ("Claims model") for the full schema and
rationale.

---

## Adding a new source

1. Pick a category: Open Data portal / FOI records / Third-party online /
   Internal-organizational. If it doesn't fit any of these, it's probably
   manual curation instead — see above, don't add it here.
2. Decide script vs. manual (see [Conventions](#conventions)). If scripted,
   base it on `scripts/fetch_coops.py`'s shape: documented source URL,
   offline-replayable, fails loudly on unexpected shape rather than
   silently returning something wrong or empty.
3. If it arrives as a document (PDF, spreadsheet, saved HTML) rather than a
   clean CSV, save the original under `data/sources/<source_name>/` and
   note how it was turned into the CSV the pipeline actually reads.
4. Add a row to the [Summary](#summary) table.
5. Add a detail section with these fields: **What it is**, **Origin**,
   **License/attribution**, **Geographic scope**, **Access method**,
   **Format/known quirks**, **Provenance/original retained** (if
   applicable), **Output location**, **Consumed by**, **Refresh cadence**.
6. If it lands in `data/` as a plain CSV meant for `sica_core`, add a
   corresponding `ingest/raw_<source>.py` module following the existing
   pattern (explicit column allow-list, raise on unexpected columns) — see
   [Scope](#scope) above for why that's not re-described in this doc.
