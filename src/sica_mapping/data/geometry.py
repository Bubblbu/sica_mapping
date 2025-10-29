"""Geometry helpers for working with Shapely objects."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from shapely.geometry import MultiPolygon, Polygon, base as shapely_base, shape

from ..core import logger


def parse_geom(raw: Any) -> Optional[shapely_base.BaseGeometry]:
    if raw is None:
        return None
    try:
        return shape(json.loads(raw))
    except Exception as exc:  # pragma: no cover - log then swallow
        logger.debug("parse_geom error: %s", exc)
        return None


def poly_to_geojson(geom: shapely_base.BaseGeometry) -> Optional[Dict[str, Any]]:
    if isinstance(geom, Polygon):
        return {"type": "Polygon", "coordinates": [list(map(list, geom.exterior.coords))]}
    if isinstance(geom, MultiPolygon):
        return {
            "type": "MultiPolygon",
            "coordinates": [[list(map(list, poly.exterior.coords))] for poly in geom.geoms],
        }
    return None
