"""Config loading for sica_core ingest.

Forked from `src/sica_mapping/cli.py`'s `_load_config`/`_merge_config` (see
normalize.py's provenance note) and trimmed to what ingest actually needs:
the same four source CSV paths already used by `config.toml`, plus the
sica_core database path.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - only for <3.11
    tomllib = None

DEFAULT_DB_PATH = "data/sica_core.db"
DEFAULT_BBOX = "-123.18,49.265,-123.10,49.295"
_REQUIRED_PATHS = ("buildings", "addresses", "blocks", "block_numbers", "vtu")


@dataclass
class IngestConfig:
    buildings: str
    addresses: str
    blocks: str
    block_numbers: str
    vtu: str
    db_path: str = DEFAULT_DB_PATH
    bbox: tuple[float, float, float, float] = (-123.18, 49.265, -123.10, 49.295)


def _load_raw(path: str) -> dict[str, object]:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    suffix = config_path.suffix.lower()
    if suffix in {".toml", ".tml"}:
        if tomllib is None:
            raise RuntimeError(
                "tomllib not available; upgrade to Python 3.11+ or use JSON config."
            )
        return tomllib.loads(config_path.read_text())
    if suffix == ".json":
        return json.loads(config_path.read_text())
    raise ValueError(f"Unsupported config format: {config_path.suffix}")


def load_ingest_config(path: str) -> IngestConfig:
    raw = _load_raw(path)
    flat: dict[str, object] = dict(raw)
    for key in ("paths", "options"):
        section = raw.get(key)
        if isinstance(section, dict):
            flat.update(section)

    missing = [field for field in _REQUIRED_PATHS if field not in flat]
    if missing:
        raise ValueError(f"config missing required paths: {', '.join(missing)}")

    bbox_str = str(flat.get("bbox", DEFAULT_BBOX))
    bbox = tuple(float(v) for v in bbox_str.split(","))

    return IngestConfig(
        buildings=str(flat["buildings"]),
        addresses=str(flat["addresses"]),
        blocks=str(flat["blocks"]),
        block_numbers=str(flat["block_numbers"]),
        vtu=str(flat["vtu"]),
        db_path=str(flat.get("sica_core_db", DEFAULT_DB_PATH)),
        bbox=bbox,
    )
