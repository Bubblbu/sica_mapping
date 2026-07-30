"""Geometry parsing helpers.

Forked from `src/sica_mapping/data/geometry.py` (see normalize.py's
provenance note). Only `parse_geom` is needed here — GeoJSON re-serialization
uses `geom.__geo_interface__` directly at the export/checkpoint layer instead
of porting `poly_to_geojson`, matching what `sica_mapping`'s own cache-writer
already does.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from shapely.geometry import base as shapely_base, shape


def parse_geom(raw: Any) -> Optional[shapely_base.BaseGeometry]:
    if raw is None:
        return None
    try:
        return shape(json.loads(raw))
    except Exception:
        return None
