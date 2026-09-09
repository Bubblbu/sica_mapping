from __future__ import annotations

from html import escape
from importlib import resources
from string import Template

import folium
import numpy as np
import pandas as pd
from shapely.geometry import shape

from .colors import greens_color


def _load_template(name: str) -> str:
    return resources.files(__package__).joinpath(f"templates/{name}").read_text()


SIDEBAR_HTML_TEMPLATE = Template(_load_template("sidebar.html"))
WIRING_JS_TEMPLATE = Template(_load_template("wiring.js"))
LEGEND_BLOCKS_TEMPLATE = Template(_load_template("legend_blocks.html"))
LEGEND_FILTERS_TEMPLATE = Template(_load_template("legend_filters.html"))


def add_blocks_layer(m: folium.Map, feature_collection: dict) -> folium.GeoJson:
    features = feature_collection.get("features") or []
    max_total_units = 0
    for feat in features:
        props = feat.get("properties") or {}
        try:
            units_count = int(props.get("total_units") or 0)
        except (TypeError, ValueError):
            units_count = 0
        if units_count > max_total_units:
            max_total_units = units_count

    def block_style(feat):
        props = feat.get("properties") or {}
        try:
            buildings = int(props.get("buildings") or 0)
        except (TypeError, ValueError):
            buildings = 0
        if buildings <= 0:
            # Empty blocks carry no meaningful data — leave them transparent
            # rather than painting them into the color scale.
            return {
                "fillColor": "transparent",
                "color": "#b8b8b8",
                "weight": 1,
                "fillOpacity": 0,
            }
        total_units = props.get("total_units") or 0
        try:
            total_units = float(total_units)
        except (TypeError, ValueError):
            total_units = 0.0
        if max_total_units > 0:
            scaled = min(max(total_units / max_total_units, 0.0), 1.0)
        else:
            scaled = 0.0
        return {
            "fillColor": greens_color(scaled),
            "color": "#b8b8b8",
            "weight": 1,
            "fillOpacity": 0.7,
        }

    popup = None
    if feature_collection.get("features"):
        popup = folium.GeoJsonPopup(
            fields=[
                "block_label",
                "buildings",
                "total_units",
                "median_year_built",
                "member_buildings",
                "total_members",
            ],
            aliases=[
                "Block",
                "Buildings",
                "# Units",
                "Median year",
                "Buildings w/ VTU",
                "Total VTU members",
            ],
            localize=True,
        )
    g = folium.GeoJson(
        data=feature_collection,
        name="Blocks: Total units (green gradient)",
        style_function=block_style,
        popup=popup,
    )
    g.add_to(m)
    return g


def _neighbourhood_style(feat):
    return {
        "color": "#ff8c00",
        "weight": 2,
        "opacity": 0.9,
        "fill": False,
    }


def add_neighbourhoods_layer(m: folium.Map, feature_collection: dict) -> folium.FeatureGroup:
    """Vancouver's 22 local-area boundaries — a static reference overlay (name
    + outline only, no data join). Boundary lines and name labels both in
    orange, grouped into one togglable layer.
    """
    layer = folium.FeatureGroup(
        name="Neighbourhoods (orange boundaries)", show=True, overlay=True
    )
    for feat in feature_collection.get("features") or []:
        props = feat.get("properties") or {}
        name = str(props.get("name", ""))
        folium.GeoJson(data=feat, style_function=_neighbourhood_style).add_to(layer)
        geom = shape(feat["geometry"])
        centroid = geom.centroid
        folium.Marker(
            location=[centroid.y, centroid.x],
            icon=folium.DivIcon(
                html=(
                    '<div style="color:#ff8c00;font-weight:700;font-size:12px;'
                    "text-shadow:-1px -1px 0 #fff,1px -1px 0 #fff,-1px 1px 0 #fff,"
                    '1px 1px 0 #fff;white-space:nowrap;pointer-events:none;">'
                    f"{escape(name)}</div>"
                ),
                icon_size=(0, 0),
            ),
        ).add_to(layer)
    layer.add_to(m)
    return layer


def marker_radius(units) -> float:
    if pd.isna(units) or units <= 0:
        return 3.2
    u = float(units)
    capped = min(max(u, 1.0), 600.0)
    ratio = float(np.log1p(capped) / np.log1p(600.0))
    return 2.5 + 7.0 * ratio


# Housing-type ring colors (a building's stroke when it matches exactly one
# type; the first type wins the stroke on a rare dual match, see below).
COOP_RING_COLOR = "#d97706"
SRO_RING_COLOR = "#3182bd"
RING_STROKE_WEIGHT = 2.2
DEFAULT_STROKE_COLOR = "#ffffff"
DEFAULT_STROKE_WEIGHT = 0.6

_REZONING_STATUS_COLORS = {
    "approved": "#2ca25f",
    "rezoning": "#e6550d",
    "upcoming": "#756bb1",
}
REZONING_BADGE_RADIUS = 3.0
# Small fixed (lat, lon) offset so the badge sits just NE of the building
# marker. Not zoom-invariant in pixel space, but acceptable at this tool's
# typical zoom 13-16 operating range, and lets the badge reuse the existing
# CircleMarker-only show/hide machinery instead of a DivIcon.
REZONING_BADGE_OFFSET = (0.00004, 0.00006)

UNMATCHED_MARKER_RADIUS = 3.5
UNMATCHED_MARKER_WEIGHT = 1.4
UNMATCHED_MARKER_OPACITY = 0.55

_SOURCE_LAYER_NAMES = {
    "sro": "SRO/SRA hotels (unmatched)",
    "coop": "Co-op housing (unmatched)",
    "rezoning": "Rezoning applications (unmatched)",
}
_SOURCE_RING_COLOR = {
    "sro": SRO_RING_COLOR,
    "coop": COOP_RING_COLOR,
}


def add_buildings_layers(m: folium.Map, pts_df):
    layer_vtu = folium.FeatureGroup(
        name="VTU member buildings", show=True, overlay=True
    )
    layer_non = folium.FeatureGroup(
        name="Other buildings (gray)", show=True, overlay=True
    )
    marker_metadata: list[dict[str, object]] = []

    for _, r in pts_df.iterrows():
        has_vtu_member = bool(r["has_vtu_member"])
        # Binary indicator only — has a VTU member or not, no gradient by count.
        color = "#cc4778" if has_vtu_member else "#9e9e9e"
        neutral_color = "#9e9e9e"
        opacity = 0.75 if has_vtu_member else 0.35
        radius_val = marker_radius(r["units"])
        member_share = r.get("member_share_building", 0.0)
        units_val = None if pd.isna(r["units"]) else int(r["units"])

        popup_html = (
            f"<b>{escape(str(r['address']))}</b><br>"
            f"Units: {'' if pd.isna(r['units']) else int(r['units'])}<br>"
            f"VTU members: {int(r['member_count'])}<br>"
            f"Member share: {member_share * 100:.0f}%<br>"
            f"Owner: {escape(str(r['owner_group']))}<br>"
            f"Year built: {'' if pd.isna(r['year_built']) else int(r['year_built'])}"
        )

        # Housing type (SRO/co-op) — ring color, not mutually exclusive: a
        # building matching both gets the first type as its own stroke and an
        # extra outer ring in the second type's color (one known case today:
        # 853 e pender st).
        is_coop = bool(r.get("is_coop", False))
        is_sro = bool(r.get("is_sro", False))
        is_rezoning = bool(r.get("is_rezoning", False))

        housing_types: list[tuple[str, str]] = []
        if is_coop:
            housing_types.append(("coop", COOP_RING_COLOR))
        if is_sro:
            housing_types.append(("sro", SRO_RING_COLOR))

        if housing_types:
            stroke_color = housing_types[0][1]
            stroke_weight = RING_STROKE_WEIGHT
        else:
            stroke_color = DEFAULT_STROKE_COLOR
            stroke_weight = DEFAULT_STROKE_WEIGHT

        if is_coop:
            coop_status = str(r.get("coop_status") or "").strip()
            coop_ownership_model = str(r.get("coop_ownership_model") or "").strip()
            popup_html += "<br><b>Co-op</b>"
            if coop_status:
                popup_html += f": {escape(coop_status)}"
            if coop_ownership_model:
                popup_html += f" ({escape(coop_ownership_model)})"
        if is_sro:
            sro_owner = str(r.get("sro_owner") or "").strip()
            sro_operator = str(r.get("sro_operator") or "").strip()
            sro_occupancy = str(r.get("sro_occupancy_status") or "").strip()
            popup_html += (
                f"<br><b>SRO/SRA:</b> Owner {escape(sro_owner)} · "
                f"Operator {escape(sro_operator)}"
            )
            if sro_occupancy:
                popup_html += f" · {escape(sro_occupancy)}"
        if is_rezoning:
            rezoning_status = str(r.get("rezoning_status") or "").strip()
            rezoning_category = str(r.get("rezoning_category") or "").strip()
            rezoning_link = str(r.get("rezoning_link") or "").strip()
            popup_html += f"<br><b>Rezoning:</b> {escape(rezoning_status)}"
            if rezoning_category:
                popup_html += f" — {escape(rezoning_category)}"
            if rezoning_link:
                popup_html += (
                    f' (<a href="{escape(rezoning_link)}" target="_blank" '
                    f'rel="noopener">source</a>)'
                )

        block_id_val = r.get("block_id")
        block_id = int(block_id_val) if pd.notna(block_id_val) else None

        target_layer = layer_vtu if has_vtu_member else layer_non

        # Extra concentric ring(s) for every housing type beyond the first —
        # added before the building marker so they paint underneath it as a
        # halo (same insertion-order-is-paint-order rule wiring.js documents
        # for blocks vs buildings).
        extra_rings: list[dict[str, str]] = []
        for i, (htype, hcolor) in enumerate(housing_types[1:], start=1):
            ring = folium.CircleMarker(
                location=[r["lat"], r["lon"]],
                radius=radius_val + 3.0 * i,
                fill=False,
                color=hcolor,
                weight=2.0,
                opacity=0.9,
            )
            target_layer.add_child(ring)
            extra_rings.append({"housing_type": htype, "marker_var": ring.get_name()})

        mk = folium.CircleMarker(
            location=[r["lat"], r["lon"]],
            radius=radius_val,
            fill=True,
            fill_opacity=opacity,
            color=stroke_color,
            weight=stroke_weight,
            fill_color=color,
        ).add_child(folium.Popup(popup_html, max_width=320))
        target_layer.add_child(mk)

        # Rezoning badge — a small filled marker offset from the building,
        # added after it so it paints on top.
        rezoning_badge_var = None
        if is_rezoning:
            badge_color = _REZONING_STATUS_COLORS.get(
                str(r.get("rezoning_status") or "").lower(), "#999999"
            )
            badge = folium.CircleMarker(
                location=[
                    r["lat"] + REZONING_BADGE_OFFSET[0],
                    r["lon"] + REZONING_BADGE_OFFSET[1],
                ],
                radius=REZONING_BADGE_RADIUS,
                fill=True,
                fill_opacity=0.9,
                color="#ffffff",
                weight=1,
                fill_color=badge_color,
            )
            target_layer.add_child(badge)
            rezoning_badge_var = badge.get_name()

        marker_metadata.append(
            {
                "marker_var": mk.get_name(),
                "b_id": int(r["b_id"]),
                "owner_key": r["owner_key"],
                "block_id": block_id,
                "base_radius": radius_val,
                "base_opacity": opacity,
                "base_color": color,
                "neutral_color": neutral_color if has_vtu_member else color,
                "is_vtu": has_vtu_member,
                "member_count": int(r["member_count"]) if pd.notna(r["member_count"]) else 0,
                "units": units_val,
                "local_area": r.get("local_area"),
                "year_built": None if pd.isna(r["year_built"]) else int(r["year_built"]),
                "housing_type": r.get("housing_type") or "",
                "primary_housing_type": housing_types[0][0] if housing_types else "",
                "stroke_color": stroke_color,
                "stroke_weight": stroke_weight,
                "extra_rings": extra_rings,
                "is_rezoning": is_rezoning,
                "rezoning_status_group": (
                    (r.get("rezoning_status_group") or None) if is_rezoning else None
                ),
                "rezoning_badge_var": rezoning_badge_var,
            }
        )

    layer_non.add_to(m)
    layer_vtu.add_to(m)
    layer_vtu_name = layer_vtu.get_name()
    layer_non_name = layer_non.get_name()

    return layer_vtu, layer_non, layer_vtu_name, layer_non_name, marker_metadata


def _unmatched_marker_color(rec: dict) -> str:
    source = rec.get("source")
    if source == "rezoning":
        status = str(rec.get("rezoning_status") or "").lower()
        return _REZONING_STATUS_COLORS.get(status, "#999999")
    return _SOURCE_RING_COLOR.get(source, "#999999")


def _unmatched_popup_html(rec: dict) -> str:
    """Mirrors the field selection the old standalone SRO/rezoning overlay
    popups used to show, for records that never matched an existing building.
    """
    fields = rec.get("popup_fields") or {}
    source = rec.get("source")
    address = escape(str(rec.get("address") or ""))

    if source == "coop":
        title = escape(str(fields.get("title") or "")) or address
        html = f"<b>{title}</b><br>Address: {address}<br>"
        status = fields.get("status")
        if status:
            html += f"Status: {escape(str(status))}<br>"
        ownership_model = fields.get("ownership_model")
        if ownership_model:
            html += f"Ownership model: {escape(str(ownership_model))}<br>"
        read_more = fields.get("read_more_url")
        if read_more:
            html += (
                f'<a href="{escape(str(read_more))}" target="_blank" '
                f'rel="noopener">More info</a>'
            )
        return html

    if source == "sro":
        name = escape(str(fields.get("building_name") or "")) or address
        html = f"<b>{name}</b><br>Address: {address}<br>"
        secondary = fields.get("secondary_address")
        if secondary:
            html += f"Secondary: {escape(str(secondary))}<br>"
        html += (
            f"Owner: {escape(str(fields.get('owner') or ''))}<br>"
            f"Operator: {escape(str(fields.get('operator') or ''))}<br>"
            f"Operator Group: {escape(str(fields.get('operator_group') or ''))}<br>"
            f"Ownership Group: {escape(str(fields.get('ownership_group') or ''))}<br>"
        )
        rooms = fields.get("registered_rooms")
        if rooms:
            html += f"Registered rooms: {escape(str(rooms))}<br>"
        occupancy = fields.get("occupancy_status")
        if occupancy:
            html += f"Occupancy: {escape(str(occupancy))}"
        return html

    # rezoning
    name = escape(str(fields.get("name") or "")) or address
    html = f"<b>{name}</b><br>Status: {escape(str(fields.get('status') or ''))}<br>"
    category = fields.get("category")
    if category:
        html += f"Category: {escape(str(category))}<br>"
    status_detail = fields.get("status_detail")
    if status_detail:
        html += f"Detail: {escape(str(status_detail))}<br>"
    link = fields.get("link")
    if link:
        html += f'<a href="{escape(str(link))}" target="_blank" rel="noopener">Source</a>'
    return html


def add_unmatched_overlay_layers(
    m: folium.Map, unmatched_records: list[dict]
) -> tuple[dict[str, folium.FeatureGroup], dict[str, str], list[dict[str, object]]]:
    """Standalone markers for SRO/co-op/rezoning records that didn't match any
    existing building — hollow and muted so they read as clearly distinct from
    real building markers, one FeatureGroup per source so Housing Data's two
    checkboxes and the Rezoning section can each toggle independently.
    """
    layers: dict[str, folium.FeatureGroup] = {
        source: folium.FeatureGroup(name=name, show=True, overlay=True)
        for source, name in _SOURCE_LAYER_NAMES.items()
    }
    marker_metadata: list[dict[str, object]] = []

    for rec in unmatched_records:
        lat, lon = rec.get("lat"), rec.get("lon")
        if lat is None or lon is None or pd.isna(lat) or pd.isna(lon):
            continue
        source = rec.get("source")
        layer = layers.get(source)
        if layer is None:
            continue

        color = _unmatched_marker_color(rec)
        popup_html = _unmatched_popup_html(rec)

        mk = folium.CircleMarker(
            location=[float(lat), float(lon)],
            radius=UNMATCHED_MARKER_RADIUS,
            fill=False,
            color=color,
            weight=UNMATCHED_MARKER_WEIGHT,
            opacity=UNMATCHED_MARKER_OPACITY,
        ).add_child(folium.Popup(popup_html, max_width=320))
        layer.add_child(mk)

        # Reuses the buildings marker_metadata schema so it can append
        # straight into the same list/JSON file, and applyMarkerMetadata()
        # needs almost no new logic to pick these up (its existing owner_key/
        # block_id guards already no-op correctly on None).
        marker_metadata.append(
            {
                "marker_var": mk.get_name(),
                "b_id": rec["synthetic_id"],
                "owner_key": None,
                "block_id": None,
                "base_radius": UNMATCHED_MARKER_RADIUS,
                "base_opacity": 0.0,
                "base_color": color,
                "neutral_color": color,
                "is_vtu": False,
                "member_count": 0,
                "units": None,
                "local_area": rec.get("local_area"),
                "year_built": None,
                "housing_type": rec.get("housing_type") or "",
                # "" (not "coop"/"sro") — an unmatched marker's own visibility
                # is gated by its Buildings-table row (see rows_synthetic /
                # applyFilters's data-synthetic path), not by the ring-stroke
                # override mechanism matched buildings use.
                "primary_housing_type": "",
                "stroke_color": color,
                "stroke_weight": UNMATCHED_MARKER_WEIGHT,
                "extra_rings": [],
                "is_rezoning": source == "rezoning",
                "rezoning_status_group": rec.get("rezoning_status_group") or None,
                "rezoning_badge_var": None,
                "is_synthetic": True,
                "source": source,
            }
        )

    layer_var_names: dict[str, str] = {}
    for source, layer in layers.items():
        layer.add_to(m)
        layer_var_names[source] = layer.get_name()

    return layers, layer_var_names, marker_metadata


def sidebar_html(
    buildings_rows: str,
    blocks_rows: str,
    landlords_rows: str,
    neighbourhoods_rows: str,
    sidebar_width: int,
) -> str:
    return SIDEBAR_HTML_TEMPLATE.safe_substitute(
        sidebar_width=sidebar_width,
        buildings_rows=buildings_rows,
        blocks_rows=blocks_rows,
        landlords_rows=landlords_rows,
        neighbourhoods_rows=neighbourhoods_rows,
    )


def wiring_js(
    blocks_layer_var: str,
    layer_vtu_var: str,
    layer_non_var: str,
    layer_neighbourhoods_var: str,
    filter_config_url: str,
    marker_metadata_url: str,
    building_records_url: str,
) -> str:
    # Unmatched SRO/co-op/rezoning FeatureGroups (see
    # add_unmatched_overlay_layers) are always added to the map by Python and
    # need no JS-side layer var — their per-marker visibility is driven
    # entirely through marker_metadata (the same Housing Data/Rezoning
    # checkboxes hide/show individual markers, not whole layers).
    return WIRING_JS_TEMPLATE.safe_substitute(
        blocks_layer_var=blocks_layer_var,
        layer_vtu_var=layer_vtu_var,
        layer_non_var=layer_non_var,
        layer_neighbourhoods_var=layer_neighbourhoods_var,
        filter_config_url=filter_config_url,
        marker_metadata_url=marker_metadata_url,
        building_records_url=building_records_url,
    )


def legends_html(
    sidebar_width: int, filter_config: dict[str, object]
) -> tuple[str, str]:
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

    block_max_raw = filter_config.get("blocks_total_units_max")
    if block_max_raw is None:
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
    try:
        sidebar_width_px = int(sidebar_width)
    except (TypeError, ValueError):
        sidebar_width_px = 0
    legend_left_offset = max(sidebar_width_px, 0) + 20

    block_ticks_html = "".join(f"<span>{escape(tick)}</span>" for tick in block_ticks)
    legend_map = LEGEND_BLOCKS_TEMPLATE.substitute(
        block_ticks_html=block_ticks_html,
        block_max_label=format(block_max, ","),
        legend_left_offset=legend_left_offset,
    )

    legend_filters = LEGEND_FILTERS_TEMPLATE.substitute(
        hood_html=hood_html,
    )

    return legend_map, legend_filters
