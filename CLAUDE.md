# SICA Mapping v2 — Spec & Roadmap

*Living document. Update this as decisions change — it's meant to be edited, not archived.*

Last updated: 2026-09-09

---

## 1. Purpose & vision

SICA Mapping is being rebuilt from scratch to serve two goals at once:

1. **An internal organizing-intelligence tool** for VTU (Vancouver Tenants Union), combining public property/rental data with VTU's own membership data and — most importantly — manually-researched ownership intelligence gathered from tenants (e.g. "these two shell companies are secretly the same landlord").
2. **A proof-of-concept for funding** — the internal tool itself is the core pitch, not the public map. The public map (and possibly other public-facing views) are framed as a *service that could be offered to client organizations* (e.g. Toronto tenant unions currently in conversation), not the primary product.

The manually-curated ownership knowledge — built from tenant testimony and research — is the project's actual differentiator. Nobody else has it. The architecture below is built to protect and grow that asset first.

---

## 2. Product & org scope

| Decision | Answer | Rationale |
|---|---|---|
| Public vs. internal | **Both**, but as separate views/products (Q1) | Current site exposes exact VTU membership counts per building — sensitive to a landlord who finds the site. Public map = story/transparency layer; internal tool = organizing utility + funding pitch. |
| Single-org vs. multi-tenant | **Single-org (Vancouver/VTU) now, architected to generalize later** (Q2) | Toronto unions are already interested, but building real multi-tenancy (accounts, data isolation per org) now is premature infrastructure. Avoid hard-coding Vancouver-only assumptions into the schema (e.g. city/region stays a first-class field) so a second org isn't a rewrite. |
| Geographic scope for v1 | **West End pilot**, structured so scaling to all of Vancouver is "run the pipeline again," not a redesign (Q3) | Small, deep, accurate pilot is more convincing to funders than large and patchy. Matches the "narrow now, broaden later" instinct. |

---

## 3. Data model & pipeline (`sica_core`)

### Known data sources (Q4)
- **Vancouver Open Data platform** — addresses, shapefiles/boundary files, rental business licences.
- **City of Vancouver FOI records** — purpose-built rental inventory (address, year built, size, name). Periodic, public.
- **VTU NationBuilder exports** — membership data, manually anonymized by removing sensitive fields before use. Controlled internally, updated on VTU's own cadence.
- **Manual research / tenant reports** — common ownership across shell companies, identified through tenant testimony. Grows piecemeal, no external source — this is the project's core IP.
- **Third-party online sources** — e.g. CHF BC's co-op housing list. Scraped/pulled from another organization's own site, not the City or VTU.

See [`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md) for the full per-source catalog: origin, license/attribution, fetch method (scripted vs. manual), format quirks, and refresh cadence for every source above except manual research (which lives entirely in the `ownership_claims` model below).

### Storage engine (Q6)
**SQLite now, schema designed to be Postgres-compatible.** No infrastructure to run/pay for/secure while solo and pre-funding. Migrating to Postgres later (multi-user concurrency, hosted internal app) should be mechanical, not a rewrite — avoid SQLite-specific schema quirks.

### Claims model (Q5, elaborated)
The manually-curated layer (starting with **ownership claims**) is modeled as its own first-class, auditable table — **not** folded into the same table as scraped/open data. This protects hard-won manual research from being silently overwritten by data re-imports, and gives every assertion a traceable source.

**`ownership_claims` table (v1 scope):**

| field | purpose |
|---|---|
| `claim_id` | stable identifier |
| `entity_a`, `entity_b` | the two entities linked (e.g. landlord names/IDs) |
| `relationship` | e.g. `common_owner` |
| `source_type` | e.g. `tenant_report`, `manual_research`, `public_registry` |
| `source_note` | free text — who said what, context |
| `reported_by` | organizer identifier |
| `date_reported` | timestamp |
| `confidence` | e.g. `unconfirmed` / `confirmed` |
| `status` | `active` / `retracted` — claims are never deleted, only retracted, preserving history |

Built with an eye toward generalizing to a broader `claims` pattern later (building condition reports, renoviction incidents, organizing-campaign stage, rent-increase reports, tenant willingness-to-organize signals, corrections to public data) — **not built now**, but the schema shape (entity + relationship/attribute + value + source + confidence + status + timestamp) should stay compatible with that future.

### Lineage hook (Q8c)
Full data lineage tracking (tracing every derived value back to its exact source rows and transform step) is a real, valuable data-engineering capability — but a separate future project, not built now.

**What *is* built now (~1 hour of work):** every row in every table (raw and merged) gets a stable, permanent ID, and the build pipeline writes a `source_row_ids` field alongside each merged/derived output row, even though nothing reads or displays it yet. This means historical pipeline runs aren't lost if/when real lineage tooling gets built later.

### Data transparency (Q8b)
Raw source tables (Open Data extract, FOI list, NationBuilder export, ownership_claims) are kept as **separate browsable SQLite tables**, not collapsed into one merged dataframe early in the pipeline. No lineage tracing between them yet (see above) — just visibility into inputs alongside the merged/final view.

### Overlay sources (SRO/SRA, co-op, rezoning)

These three third-party datasets are ingested into `sica_core` as raw,
browsable tables (`raw_sro`, `raw_coops`, `raw_rezoning`) plus
`raw_local_areas` (the 22 official boundary polygons), then **matched in the
pipeline**, not at render time: `ingest/overlays.py::run_overlay_match` keys
each record against `buildings` (co-op/SRO by civic address with a
`secondary_addresses` fallback; rezoning by a parsed `name` fragment, no
fallback) and writes one row per record to `overlay_matches`
(`building_id` NULL = unmatched → standalone map marker). Match coverage per
source is logged and exported (`overlay_coverage.json`); a
fixture + real-data test guards against a keying regression silently
dropping recall.

`export.py` attaches the `is_coop`/`is_sro`/`is_rezoning` + detail columns
to every building row and writes `overlay_unmatched.json`. The old
render-time `src/sica_mapping/data/overlays.py::match_overlays` stays only
as the fallback for the pure-CSV `build_sica_map.py` path.

### Sensitivity model (Q11)
**Field-level flags, tagged incrementally, default-public.** Not every field classified up front (too much upfront work for the time budget) — instead, known-sensitive fields are flagged now (VTU membership counts/IDs, tenant names/identifying details in claim notes), everything else defaults to public, and new fields get flagged *at the moment they're added* if they touch tenant identity or membership. This is a discipline to maintain, not just a one-time setup.

### Export mechanism (Q12)
Two paths, sharing the same underlying "filter to public fields" logic in `sica_core`:
1. **Ad hoc export button** (in the internal app) — download a filtered CSV/JSON of whatever's currently in view, for sharing with e.g. a Toronto union or a funder.
2. **Automated public feed** — the same filter logic feeds the public map's build step directly (`sica_core` → filter to public fields → JSON → public site build reads it). Keeps the public map in sync with real data without manual copy-paste.

---

## 4. Internal tool

| Decision | Answer |
|---|---|
| Access scope | **Single-user (you) for now** (Q7) — read + write via forms, not raw SQL editing. Multi-user accounts deferred until there's an actual second organizer who needs it. |
| Tech | **Streamlit** (Q8) — fastest path to a working browse/edit tool in pure Python, fits existing skillset, no separate frontend to build. Not built for eventual multi-user use — that's a rewrite either way, deferred deliberately. |
| Data exploration | Raw source tables + merged/entity tables both browsable in-app (Q8b) — see "Data transparency" above. |
| Hosting | **Local only**, but config (file paths, secrets) not hardcoded to this machine, so deploying later is a config change, not a redesign (Q10). Given the data includes tenant-reported and membership information, "reachable over the internet" is a real risk not worth taking on before there's an actual second user and a real auth plan. |

---

## 5. Public map

| Decision | Answer |
|---|---|
| Rebuild scope | **Yes, rebuild** — driven by performance and architecture, not visual polish (Q13 revised). Current Folium-based map bakes thousands of marker objects directly into a static HTML file at build time; this is the likely performance ceiling at city scale. |
| Map rendering | **Hand-written Leaflet** (same visual library as now, no Folium), with marker clustering/canvas rendering for scale. Not vector tiles (MapLibre GL) yet — West End's few hundred buildings don't need that, but the data export is shaped so upgrading later, if the tool scales to full-city, is realistic (Q14). |
| Frontend tooling | **Vite + TypeScript, no framework** (Q15). Author's React experience (via Headstart, ~2016, pre-hooks) is real but rusty; relearning React well enough to use confidently is a bigger time cost right now than managing map/filter/table state sync by hand in TypeScript. Can migrate *to* a framework later once the JSON data contract is stable — the hard part (data) won't need to change. |
| Data flow | Python pipeline's job becomes: produce clean JSON/GeoJSON only. All rendering, filtering, and interactivity logic moves to the TypeScript frontend. |

---

## 6. Engineering practices

| Decision | Answer |
|---|---|
| Deployment/CI | **Deferred entirely** for now (Q17). Existing `.github/workflows/` pattern (push → build → GitHub Pages) can be revived later; not needed while nothing is meant to be shown externally yet. |
| Testing | **Targeted, not broad** (Q18). Automated tests specifically on: (1) the public/sensitive field-filtering logic, and (2) claims-merge logic — because silent regressions there are actively dangerous (data leak risk / corrupting the core IP asset). Everything else (address matching, block aggregation, rendering) gets sanity-checked by eyeballing output on the small West End dataset, not formal tests. |

---

## 7. MVP definition & milestone gate

**The West End "thin slice" (below) is an internal-only checkpoint — not to be shown to anyone external.**

The actual gate for showing this to anyone (Toronto union, funder, etc.) is:

> **A small, deep subset of West End buildings/landlords is fully populated and richly claimed** — not broad-but-thin coverage of all ~471 West End buildings. Pick cases you already know well (existing VTU organizing activity, already-pieced-together shell-company ownership) and make those airtight: accurate data, real ownership_claims, clear provenance. This is what proves the differentiator — "here's a building, here's who really owns it, here's how we know" — not raw coverage numbers.

**Secondary, opportunistic scope:** while researching a West End case, if a thread leads to a landlord's holdings elsewhere in Vancouver, capture that as an `ownership_claim` even if the linked building itself isn't fully researched/populated yet. This seeds future city-wide expansion cheaply, without competing for time against West End depth.

**Explicit risk to guard against:** the thin slice (Section 8 below) is easy to mistake for "done" once it's technically working. It isn't. The claims-layer milestone above is the real bar — don't let a working map-with-dots substitute for it, and don't let convenience-driven shortcuts (e.g. skipping the sensitivity-flag logic "for now") quietly become permanent.

---

## 8. Build sequencing

**Approach: thin vertical slice across all three layers first (internal checkpoint only), then deepen.**

Rationale: with real external interest already in motion (Toronto), having something end-to-end working soon is worth more than a perfectly sequenced build with nothing demoable for weeks. It also surfaces integration problems (e.g. "does the SQLite schema actually export cleanly into what the map needs?") early, rather than after each piece is built in isolation.

Risks to actively manage (see Section 7): the "good enough" trap, premature demoing before the claims layer exists, shortcuts becoming permanent, cross-stack context-switching cost, and showing rough/thin data before it's cleaned.

---

## 9. Task breakdown

### Phase 0 — Thin slice (internal checkpoint, not for external eyes)

**`sica_core` (data layer)**
- [ ] Set up SQLite schema: `landlords`, `buildings`, `units`, `vtu_membership` (basic fields only, no claims yet)
- [ ] Write ingest scripts for Open Data (addresses, shapefiles, business licences) — West End only
- [ ] Write ingest script for FOI purpose-built rental list — West End only
- [ ] Write ingest script for anonymized NationBuilder export
- [ ] Basic merge/dedup logic (landlord ↔ building ↔ address matching)
- [ ] Add `source_row_ids` field to merged output rows (the lineage hook — do this now, while writing the merge logic anyway)
- [ ] Basic public/sensitive field flags on known-sensitive fields (VTU membership counts/IDs)
- [ ] Basic export function: filter to public fields → JSON

**Internal app (Streamlit)**
- [ ] Local Streamlit app, reads SQLite directly
- [ ] Browse view: landlords, buildings, raw source tables (separate tabs)
- [ ] Basic filter/search
- [ ] Config (file paths etc.) externalized, not hardcoded — so future hosting is a config change

**Public map**
- [ ] Vite + TypeScript project scaffold
- [ ] Hand-written Leaflet map, loads from the JSON export
- [ ] Basic markers for West End buildings, no clustering needed yet at this scale
- [ ] Minimal table view alongside map (can mirror old sidebar table for now)

**Checkpoint:** confirm the full pipe works end to end — SQLite → export → map renders real West End data. This is *not* shown to anyone outside yourself.

### Phase 1 — Deepen toward the milestone gate

**`sica_core`**
- [ ] Build `ownership_claims` table per schema in Section 3
- [ ] Populate claims for the small, deep West End case set you already know well
- [ ] Opportunistically capture city-wide ownership claims surfaced during that research (unpolished, seed data only)
- [ ] Write targeted tests: sensitivity-filter logic, claims-merge logic
- [ ] Confirm public export correctly excludes sensitive fields (test-covered, not just eyeballed)

**Internal app**
- [ ] Add/edit form for `ownership_claims` (entity_a, entity_b, relationship, source_note, confidence, etc.)
- [ ] Retract (not delete) UI for claims
- [ ] Ad hoc export button (filtered CSV/JSON for sharing)

**Public map**
- [ ] Wire in claims-derived landlord clustering (grouping shell companies under a real owner where confirmed)
- [ ] Polish filters/sidebar to match or exceed current site's functionality (neighbourhood, assessed value, unit sliders)
- [ ] Marker clustering/canvas rendering if West End point count warrants it

**Milestone check:** does a small set of West End buildings/landlords tell a complete, accurate, well-sourced ownership story? If yes — this is the "ready to show externally" gate.

### Phase 2 — Not yet scoped (deliberately deferred)
- Deployment/CI automation (GitHub Actions → Pages, or scheduled rebuilds)
- Multi-user accounts for the internal app
- Vector tiles (MapLibre GL) — only if/when scaling past West End makes Leaflet performance a real problem
- Broader `claims` model generalization (building condition, renoviction, campaign stage, etc.)
- Full city-wide data population

---

## Open questions / not yet decided
*(add here as they come up)*

-