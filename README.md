# SICA Mapping

SICA Mapping is a Python toolchain that assembles and serves an interactive folium map
for VTU (Vancouver Tenants Union) organizers. It ingests raw assessment, address, block
outline, and membership exports, enriches them with derived metrics, and renders an
HTML/JS dashboard under `www/` that can be deployed to any static host.

## Highlights

- Deterministic data pipeline that normalizes addresses, deduplicates buildings, and
  injects VTU membership metadata.
- Block-level aggregations with derived statistics (median year built, total units, VTU
  saturation).
- Folium-based visualization with two building layers (VTU vs non-VTU), colored markers,
  block choropleths, contextual sidebar, and JS wiring for interactivity.
- Configurable bounding boxes, tile sources, sidebar widths, and optional local-area
  filtering for quick experiments.
- Cached preprocessing artifacts for rapid iteration on the frontend without re-running
  expensive spatial joins.

## Repository Layout

| Path | Purpose |
| --- | --- |
| `build_sica_map.py` | CLI entry point that parses args and invokes the builder. |
| `config.toml` | Sample configuration enumerating preferred inputs and options. |
| `src/sica_mapping/core/` | Logging, IO, parsing, and normalization utilities. |
| `src/sica_mapping/data/` | The ETL pipeline, spatial helpers, VTU enrichments, HTML table builders. |
| `src/sica_mapping/frontend/` | Folium layout helpers and HTML/JS templates for the sidebar and legends. |
| `data/` | Local CSVs for buildings, addresses, blocks, and VTU members (not committed upstream). |
| `www/` | Generated static assets (`index.html`, marker metadata, filter configuration). |

## Requirements

- Python 3.12+
- `uv` (preferred) or `pip` for dependency management
- Geo/spatial dependencies: `folium`, `shapely`, `pandas`, `numpy`, `loguru`
- Input CSVs with the expected schemas (see below)

## Installation

Using [uv](https://github.com/astral-sh/uv):

```bash
uv sync
source .venv/bin/activate
```

Using pip:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

> Tip: `pip install -e .` uses `pyproject.toml` so the `sica_mapping` package can be
> imported anywhere within the repo.

## Input Data Expectations

The builder expects four CSV files. Their paths can be provided via CLI flags or in
`config.toml` under `[paths]`.

| Argument | Example file | Required columns |
| --- | --- | --- |
| `--buildings` | `data/buildings.csv` | At minimum `address`, `local_area`, `units`, `year_built`, `value_land`, `value_bldg`, VTU-friendly ownership columns such as `bsns_group`. |
| `--addresses` | `data/property_addresses.csv` | `civic_number`, `std_street`, and `geo_point_2d` (containing `"lat,lon"`). Optional `local_area_*` columns improve enrichment. |
| `--blocks` | `data/block-outlines.csv` | Polygon GeoJSON in a `geom` column and any block metadata you want surfaced in tables. |
| `--vtu` | `data/membership_full.csv` | Membership exports with an address column plus `tag_list`, `updated_at`, and any membership count fields. |

The pipeline normalizes column names to lowercase snake_case, but keeping the suggested
column names avoids surprises.

## Running the Map Builder

1. Ensure the virtual environment is activated.
2. Provide either CLI flags or a config file describing the inputs and rendering
   options.
3. Execute the `build_sica_map.py` script.

### Example commands

Run both preprocessing and frontend rendering using the sample config:

```bash
python build_sica_map.py --config config.toml --stage all
```

Only re-run the frontend, relying on cached `.preprocessed/` artifacts:

```bash
python build_sica_map.py --config config.toml --stage frontend
```

Restrict the dataset to one or more official local areas and write the output HTML into
`www/local-area.html`:

```bash
python build_sica_map.py \
  --config config.toml \
  --local-area "Downtown" \
  --local-area "West End" \
  --out www/local-area.html
```

### CLI Reference

| Option | Description |
| --- | --- |
| `--config PATH` | TOML/JSON file containing `paths` + `options`. Fields such as `bbox`, `out`, `tiles`, and `sidebar_width` can be overridden here. |
| `--buildings`, `--addresses`, `--blocks`, `--vtu` | Absolute or relative CSV paths. Required unless provided in the config. |
| `--bbox lon_min,lat_min,lon_max,lat_max` | Spatial filter applied to block geometries. Defaults to `-123.18,49.265,-123.10,49.295`. |
| `--tiles TILESET` | Any folium-compatible tile name. Defaults to `cartodbpositron`. |
| `--sidebar-width PX` | Sidebar width in pixels (affects legend offsets and layout). Default `540`. |
| `--stage {data,frontend,all}` | `data` writes `.preprocessed/`, `frontend` renders HTML using cached data, `all` performs both steps. |
| `--data-dir PATH` | Location for cached artifacts (default `.preprocessed`). Deleting this directory forces a fresh ETL run. |
| `--local-area NAME` | May be repeated. Filters the building dataset to the provided local areas before matching addresses. |
| `--verbose` | Enables verbose Loguru logging with progress meters. |

### Output

`build_map` ensures that `--out` paths are rooted under `www/`. Running the builder
produces:

- `www/<name>.html`: the folium map with embedded sidebar + filter scaffolding.
- `www/<name>_filter_config.json`: metadata powering the sidebar filter UI.
- `www/<name>_marker_metadata.json`: marker descriptors consumed by wiring JS.
- `www/<name>_building_records.json`: the table payload keyed by building IDs.

These four files can be deployed to any static host or served locally via `python -m
http.server` from the project root.

## Pipeline Stages ( `sica_mapping.data.pipeline` )

1. **Load & normalize** – `read_any_csv` coerces dtypes, `normalize_cols` lowercases
   headers.
2. **Address preparation** – `prepare_addresses` parses `geo_point_2d` into `lat/lon`,
   normalizes street names, and builds deterministic `addr_key` values for joins.
3. **Building filtering** – `select_west_end_buildings` narrows to the VTU study area,
   optionally by `--local-area`, while tracking owner labels.
4. **Address join and recovery** – `join_buildings_addresses` merges lat/lon, adopts
   primary address fallbacks, fills missing coordinates by matching on normalized
   streets, and harmonizes local area names.
5. **Membership enrichment** – `prepare_membership_records`, `membership_records_by_address`,
   and `attach_vtu_metrics` compute member counts, recency, and member share per
   building while annotating each marker with a payload of tag metadata.
6. **Deduplication** – Buildings sharing the same `addr_key` collapse to one map point,
   preserving the richest metadata across duplicates.
7. **Block aggregation** – `parse_blocks`, `point_in_block_ids`, and `aggregate_blocks`
   tag each building with a block ID, then compute block-level totals, VTU saturation,
   and medians.
8. **Filter & metric summaries** – `build_building_metrics` produces histograms for land
   value, building value, ratios, and units; neighbourhood counts, dataset totals, and
   map bounds are appended for the frontend.
9. **Caching** – When `--stage data` or `--stage all` runs, `.preprocessed/` receives
   sanitized JSON dumps of points, blocks, and filter config for later reuse.

Key data-quality stats (counts, deduplication numbers, unmatched addresses) are emitted
in the metadata block inside the cache, making it easy to vet ETL runs.

## Frontend Rendering ( `sica_mapping.build` + `frontend/` )

- `compute_vmax` inspects VTU member counts to set the color scale ceiling.
- `add_blocks_layer` shades block polygons by total units using a green gradient and
  optional popups listing aggregate metrics.
- `add_buildings_layers` splits VTU vs non-VTU markers into separate folium layers with
  plasma color scales, control toggles, and per-building popups.
- `tables.py` curates HTML rows for the sidebar tables (buildings, blocks, landlords),
  embedding `data-*` attributes for the JavaScript wiring.
- `templates/wiring.js` bootstraps the filter panel by fetching the three JSON payloads
  emitted alongside the HTML file.

Because the HTML, JS, and JSON assets are static, they can be published on GitHub Pages,
Netlify, or any other CDN without server-side code.

## Development Workflow

- Run `uv run python build_sica_map.py --config config.toml` during development to avoid
  manually activating the virtual environment.
- Use `--stage data` to refresh the `.preprocessed/` cache whenever any CSV input
  changes. Subsequent `--stage frontend` executions are fast and do not touch the data.
- Adjust folium styling in `src/sica_mapping/frontend/` and rerun the frontend stage to
  preview changes.
- When tweaking JS templates, remember to clear your browser cache or open the map in an
  incognito window so that updated assets load immediately.

## Deployment

1. Run `python build_sica_map.py --config config.toml --stage all`.
2. Commit or copy the four `www/index*` artifacts to your publishing repo.
3. If you need multiple filtered variants (e.g., per neighbourhood), re-run with
   different `--local-area` filters and output names to generate multiple HTML bundles.

Consider using GitHub Actions or another CI runner to trigger the build script whenever
new CSVs land in cloud storage, then push the resulting `www/` directory to the hosting
bucket.

## To-dos

### Mapping

- [ ] Add export feature
- [ ] Integrate more useful data sources
- [ ] Deep overhaul of tool for performance

### Overall

- [ ] Rethink deployment process
