"""Colour scale helpers for the Folium layers."""

from __future__ import annotations


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
