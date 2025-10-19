from __future__ import annotations
import argparse
import json
from pathlib import Path

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - only for <3.11
    tomllib = None

DEFAULT_BBOX = "-123.18,49.265,-123.10,49.295"
DEFAULT_OUT = "html/index.html"
DEFAULT_TILES = "cartodbpositron"
DEFAULT_SIDEBAR_WIDTH = 540
DEFAULT_STAGE = "frontend"
DEFAULT_DATA_DIR = ".preprocessed"
_REQUIRED_PATHS = ("buildings", "addresses", "blocks", "vtu")

def _load_config(path: str) -> dict[str, object]:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    suffix = config_path.suffix.lower()
    if suffix in {".toml", ".tml"}:
        if tomllib is None:
            raise RuntimeError("tomllib not available; upgrade to Python 3.11+ or use JSON config.")
        return tomllib.loads(config_path.read_text())
    if suffix == ".json":
        return json.loads(config_path.read_text())
    raise ValueError(f"Unsupported config format: {config_path.suffix}")

def _merge_config(args: argparse.Namespace, config: dict[str, object]) -> None:
    # Allow optional grouping inside the config (e.g. {"paths": {...}}).
    flat = {}
    if config:
        flat.update(config)
        for key in ("paths", "options"):
            section = config.get(key)
            if isinstance(section, dict):
                flat.update(section)

    defaults = {
        "out": DEFAULT_OUT,
        "bbox": DEFAULT_BBOX,
        "tiles": DEFAULT_TILES,
        "sidebar_width": DEFAULT_SIDEBAR_WIDTH,
        "stage": DEFAULT_STAGE,
        "data_dir": DEFAULT_DATA_DIR,
        "local_area": None,
    }

    for field in _REQUIRED_PATHS:
        if getattr(args, field) is None and field in flat:
            setattr(args, field, flat[field])
    for field, default in defaults.items():
        current = getattr(args, field)
        if current is None:
            value = flat.get(field, default)
            setattr(args, field, value)
    if not args.verbose and isinstance(flat.get("verbose"), bool):
        args.verbose = flat["verbose"]

    # Type coercion for numeric fields after merging
    if args.sidebar_width is not None:
        try:
            args.sidebar_width = int(args.sidebar_width)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"sidebar_width must be an integer (got {args.sidebar_width!r})") from exc

    # Normalize stage and data_dir
    stage = getattr(args, "stage", DEFAULT_STAGE)
    if isinstance(stage, str):
        args.stage = stage.lower()
    else:
        args.stage = DEFAULT_STAGE
    data_dir = getattr(args, "data_dir", DEFAULT_DATA_DIR)
    if data_dir is None:
        args.data_dir = DEFAULT_DATA_DIR
    else:
        args.data_dir = str(data_dir)

def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Build West End VTU map")
    ap.add_argument("--config", help="Optional TOML/JSON config file with argument defaults")
    ap.add_argument("--buildings", help="Buildings CSV")
    ap.add_argument("--addresses", help="Property addresses CSV (civic_number, std_street, geo_point_2d)")
    ap.add_argument("--blocks", help="Block outlines CSV (with 'geom' GeoJSON column)")
    ap.add_argument("--vtu", help="VTU members CSV (with address column)")
    ap.add_argument("--out", help=f"Output HTML (default: {DEFAULT_OUT})")
    ap.add_argument("--bbox", help=f"lon_min,lat_min,lon_max,lat_max (default: {DEFAULT_BBOX})")
    ap.add_argument("--tiles", help=f"Folium tile set (default: {DEFAULT_TILES})")
    ap.add_argument("--sidebar-width", type=int, help="Sidebar width in px (default: 540)")
    ap.add_argument("--stage", choices=["frontend","data","all"], default=None, help="Which stage to run: data preprocessing, frontend rendering, or both")
    ap.add_argument("--data-dir", default=None, help="Directory to read/write preprocessed data (default: .preprocessed)")
    ap.add_argument("--local-area", action="append", help="Optional local area(s) to include (repeat for multiple)")
    ap.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")

    args = ap.parse_args()

    if args.config:
        config = _load_config(args.config)
        _merge_config(args, config)
    else:
        # Apply defaults even without config
        _merge_config(args, {})

    if args.stage not in {"frontend", "data", "all"}:
        ap.error("stage must be one of: frontend, data, all")

    if args.local_area is None:
        parsed_areas = None
    elif isinstance(args.local_area, str):
        parsed_areas = [args.local_area]
    else:
        parsed_areas = [str(area) for area in args.local_area]
    args.local_area = parsed_areas

    missing = [field for field in _REQUIRED_PATHS if getattr(args, field) is None]
    if missing:
        ap.error(f"the following arguments are required (supply via CLI or config): {', '.join(missing)}")

    return args
