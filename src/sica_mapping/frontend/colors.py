"""Colour scale helpers for the Folium layers."""

from __future__ import annotations

from typing import List, Tuple


PLASMA_STOPS: List[Tuple[float, str]] = [
    (0.00, "#0d0887"),
    (0.15, "#5c01a6"),
    (0.30, "#9c179e"),
    (0.45, "#cc4778"),
    (0.60, "#ed7953"),
    (0.75, "#fb9f3a"),
    (0.90, "#fdca26"),
    (1.00, "#f0f921"),
]


def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))


def _interp(c1: str, c2: str, t: float) -> str:
    r1, g1, b1 = _hex_to_rgb(c1)
    r2, g2, b2 = _hex_to_rgb(c2)
    r = int(r1 + (r2 - r1) * t)
    g = int(g1 + (g2 - g1) * t)
    b = int(b1 + (b2 - b1) * t)
    return f"#{r:02x}{g:02x}{b:02x}"


def plasma_color(x: float, vmax: float) -> str:
    s = 0.0 if (x is None) or (x <= 0) else min(float(x) / vmax, 1.0)
    for (x0, c0), (x1, c1) in zip(PLASMA_STOPS[:-1], PLASMA_STOPS[1:]):
        if s <= x1:
            t = (s - x0) / (x1 - x0) if x1 > x0 else 0.0
            return _interp(c0, c1, t)
    return PLASMA_STOPS[-1][1]


def greens_color(s: float) -> str:
    s = 0.0 if s is None else max(0.0, min(float(s), 1.0))
    if s <= 0.10:
        return "#f7fcf5"
    if s <= 0.25:
        return "#e5f5e0"
    if s <= 0.50:
        return "#c7e9c0"
    if s <= 0.75:
        return "#74c476"
    if s < 1.00:
        return "#31a354"
    return "#006d2c"
