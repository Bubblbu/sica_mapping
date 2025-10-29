from __future__ import annotations

from html import escape
from importlib import resources
from string import Template

import folium
import numpy as np
import pandas as pd
from .colors import greens_color, plasma_color


def _load_template(name: str) -> str:
    return resources.files(__package__).joinpath(f"templates/{name}").read_text()


SIDEBAR_HTML_TEMPLATE = Template(_load_template("sidebar.html"))
WIRING_JS_TEMPLATE = Template(_load_template("wiring.js"))
LEGEND_BLOCKS_TEMPLATE = Template(_load_template("legend_blocks.html"))
LEGEND_BUILDINGS_TEMPLATE = Template(_load_template("legend_buildings.html"))
LEGEND_FILTERS_TEMPLATE = Template(_load_template("legend_filters.html"))

def compute_vmax(pts_df) -> float:
    counts = pts_df["member_count"].replace([np.inf, -np.inf], np.nan)
    pos = counts[(counts > 0) & (~counts.isna())]
    if len(pos) == 0:
        return 1.0
    max_val = float(np.nanmax(pos))
    if len(pos) >= 10:
        percentile = 98 if len(pos) >= 50 else 95
        capped = float(np.nanpercentile(pos, percentile))
        vmax = min(max_val, max(capped, max_val * 0.8))
    else:
        vmax = max_val
    return max(vmax, 1.0)

def add_blocks_layer(m: folium.Map, feature_collection: dict) -> folium.GeoJson:
    features = feature_collection.get("features") or []
    max_member_buildings = 0
    for feat in features:
        props = feat.get("properties") or {}
        try:
            member_count = int(props.get("member_buildings") or 0)
        except (TypeError, ValueError):
            member_count = 0
        if member_count > max_member_buildings:
            max_member_buildings = member_count

    def block_style(feat):
        props = feat.get("properties") or {}
        member_buildings = props.get("member_buildings") or 0
        try:
            member_buildings = float(member_buildings)
        except (TypeError, ValueError):
            member_buildings = 0.0
        if max_member_buildings > 0:
            scaled = min(max(member_buildings / max_member_buildings, 0.0), 1.0)
        else:
            scaled = 0.0
        return {"fillColor": greens_color(scaled), "color": "#b8b8b8", "weight": 1, "fillOpacity": 0.35}
    popup = None
    if feature_collection.get("features"):
        popup = folium.GeoJsonPopup(
            fields=["block_id","buildings","total_units","median_year_built","member_buildings","total_members"],
            aliases=["Block","Buildings","# Units","Median year","Buildings w/ VTU","Total VTU members"],
            localize=True
        )
    g = folium.GeoJson(
        data=feature_collection, name="Blocks: VTU buildings (count gradient)",
        style_function=block_style,
        popup=popup
    )
    g.add_to(m)
    return g

def marker_radius(units) -> float:
    if pd.isna(units) or units <= 0:
        return 3.2
    u = float(units)
    capped = min(max(u, 1.0), 600.0)
    ratio = float(np.log1p(capped) / np.log1p(600.0))
    return 2.5 + 7.0 * ratio

def vtu_opacity(scaled: float) -> float:
    return 0.30 + 0.40*scaled

def add_buildings_layers(m: folium.Map, pts_df, vmax: float):
    # 1. Update layer name to reflect coloring by count
    layer_vtu = folium.FeatureGroup(name="VTU member buildings (Plasma by count)", show=True, overlay=True)
    layer_non = folium.FeatureGroup(name="Other buildings (gray)", show=True, overlay=True)
    marker_metadata: list[dict[str, object]] = []

    for _, r in pts_df.iterrows():
        count = r["member_count"]
        has_vtu_member = bool(r["has_vtu_member"])
        scaled = 0.0 if pd.isna(count) or count <= 0 else min(float(count) / vmax, 1.0)
        color = plasma_color(count, vmax) if has_vtu_member else "#9e9e9e"
        neutral_color = "#9e9e9e"
        opacity = vtu_opacity(scaled) if has_vtu_member else 0.35
        radius_val = marker_radius(r["units"])
        member_share = r.get("member_share_building", 0.0)
        units_val = None if pd.isna(r["units"]) else int(r["units"])

        popup_html = (
            f"<b>{escape(str(r['address']))}</b><br>"
            f"Units: {'' if pd.isna(r['units']) else int(r['units'])}<br>"
            f"VTU members: {int(r['member_count'])}<br>"
            f"Member share: {member_share*100:.0f}%<br>"
            f"Owner: {escape(str(r['owner_group']))}<br>"
            f"Year built: {'' if pd.isna(r['year_built']) else int(r['year_built'])}"
        )
        
        block_id_val = r.get("block_id")
        block_id = int(block_id_val) if pd.notna(block_id_val) else None
        members_payload = r.get("members_payload", [])
        
        mk = folium.CircleMarker(
            location=[r["lat"], r["lon"]],
            radius=radius_val,
            fill=True,
            fill_opacity=opacity,
            color=None,
            weight=0,
            fill_color=color,
        ).add_child(folium.Popup(popup_html, max_width=320))
        
        (layer_vtu if has_vtu_member else layer_non).add_child(mk)

        marker_metadata.append({
            "marker_var": mk.get_name(),
            "b_id": int(r["b_id"]),
            "owner_key": r["owner_key"],
            "block_id": block_id,
            "members_payload": members_payload,
            "base_radius": radius_val,
            "base_opacity": opacity,
            "base_color": color,
            "neutral_color": neutral_color if has_vtu_member else color,
            "is_vtu": has_vtu_member,
            "member_count": int(count) if pd.notna(count) else 0,
            "units": units_val,
        })

    layer_vtu.add_to(m)
    layer_non.add_to(m)
    layer_vtu_name = layer_vtu.get_name()
    layer_non_name = layer_non.get_name()
    
    return layer_vtu, layer_non, layer_vtu_name, layer_non_name, marker_metadata



def sidebar_html(buildings_rows: str, blocks_rows: str, landlords_rows: str, sidebar_width: int) -> str:
    return SIDEBAR_HTML_TEMPLATE.safe_substitute(
        sidebar_width=sidebar_width,
        buildings_rows=buildings_rows,
        blocks_rows=blocks_rows,
        landlords_rows=landlords_rows,
    )

def wiring_js(
    blocks_layer_var: str,
    layer_vtu_var: str,
    layer_non_var: str,
    filter_config_url: str,
    marker_metadata_url: str,
    building_records_url: str,
) -> str:
    return WIRING_JS_TEMPLATE.safe_substitute(
        blocks_layer_var=blocks_layer_var,
        layer_vtu_var=layer_vtu_var,
        layer_non_var=layer_non_var,
        filter_config_url=filter_config_url,
        marker_metadata_url=marker_metadata_url,
        building_records_url=building_records_url,
    )


def legends_html(vmax: float, sidebar_width: int, filter_config: dict[str, object]) -> tuple[str, str, str]:
    neighbourhoods = filter_config.get("neighbourhoods") or []
    hood_entries: list[str] = []
    for nei in neighbourhoods:
        name = str(nei.get("name", ""))
        count_val = int(nei.get("count", 0))
        units_val = int(nei.get("units", 0))
        hood_entries.append(
            f'<label class="filter-tag"><input type="checkbox" class="filter-neighbourhood-option" '
            f'value="{escape(name.lower())}" checked> {escape(name)} '
            f'<span class="filter-tag-count">({format(count_val, ",")} bldgs · {format(units_val, ",")} units)</span></label>'
        )
    if hood_entries:
        hood_html = "".join(hood_entries)
    else:
        hood_html = '<em class="filter-none">No neighbourhood data</em>'

    block_max_raw = filter_config.get("blocks_member_building_max")
    try:
        block_max = int(block_max_raw)
    except (TypeError, ValueError):
        block_max = 0
    block_max = max(block_max, 0)
    if block_max == 0:
        block_ticks = ["0"] * 6
    else:
        fractions = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
        block_ticks = []
        for frac in fractions:
            value = int(round(block_max * frac))
            if frac == 1.0:
                value = block_max
            block_ticks.append(format(value, ","))
    block_ticks_html = "".join(f"<span>{escape(tick)}</span>" for tick in block_ticks)
    legend_blocks = LEGEND_BLOCKS_TEMPLATE.substitute(
        block_ticks_html=block_ticks_html,
        block_max_label=format(block_max, ","),
    )

    try:
        sidebar_width_px = int(sidebar_width)
    except (TypeError, ValueError):
        sidebar_width_px = 0
    legend_left_offset = max(sidebar_width_px, 0) + 20

    try:
        vmax_value = int(round(float(vmax)))
    except (TypeError, ValueError):
        vmax_value = 0
    if vmax_value < 0:
        vmax_value = 0
    legend_buildings = LEGEND_BUILDINGS_TEMPLATE.substitute(
        legend_left_offset=legend_left_offset,
        vmax_label=format(vmax_value, ","),
    )

    legend_filters = LEGEND_FILTERS_TEMPLATE.substitute(
        hood_html=hood_html,
    )

    return legend_blocks, legend_buildings, legend_filters
