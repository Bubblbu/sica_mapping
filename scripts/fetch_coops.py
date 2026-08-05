"""Fetch CHF BC's "Find a Co-op" data and extract Vancouver-city co-ops to CSV.

Source: https://www.chf.bc.ca/find-a-co-op/ embeds its entire province-wide
co-op dataset (287 records as of 2026-08-04) as inline JSON in the page:

    <script type="application/json" class="coop-explorer__data">[...]</script>

No API call is needed — one page fetch gets everything. This script pulls
that page, extracts the JSON, filters to `location.city == "Vancouver"`
(city-wide, not just West End — CHF's own "city" field, not our block/bbox
geometry), and writes a flat CSV to data/coops_vancouver.csv.

This is a manual/occasional pull (like the other CSVs in data/), not a
build-time dependency — re-run this script by hand when you want a refresh,
then re-run the normal pipeline on the resulting CSV.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import pandas as pd
import requests

SOURCE_URL = "https://www.chf.bc.ca/find-a-co-op/"
DEFAULT_OUT = "data/coops_vancouver.csv"

# CHF's page blocks bare-looking scripted requests; a normal browser UA gets
# a plain 200.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}

_DATA_SCRIPT_RE = re.compile(
    r'<script type="application/json" class="coop-explorer__data">(.*?)</script>',
    re.S,
)


def fetch_html(url: str = SOURCE_URL) -> str:
    resp = requests.get(url, headers=_HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.text


def extract_coops(html: str) -> list[dict]:
    match = _DATA_SCRIPT_RE.search(html)
    if not match:
        raise RuntimeError(
            "Could not find coop-explorer__data script tag — CHF's page "
            "markup may have changed; re-check the source before assuming "
            "an empty result."
        )
    return json.loads(match.group(1))


def normalize_coops(records: list[dict], city: str = "Vancouver") -> pd.DataFrame:
    """Flatten CHF's nested JSON into one row per co-op, filtered to `city`.

    Filters on CHF's own `location.city` field — i.e. all of Vancouver
    proper, not clipped to any block/bbox geometry of ours.
    """
    rows = []
    for rec in records:
        loc = rec.get("location") or {}
        if (loc.get("city") or "").strip() != city:
            continue
        coords = rec.get("coordinates") or [None, None]
        lon, lat = (coords + [None, None])[:2]
        bedrooms = rec.get("bedrooms") or []
        rows.append(
            {
                "id": rec.get("id"),
                "title": rec.get("title"),
                "city": loc.get("city"),
                "region": loc.get("region"),
                "neighbourhood": loc.get("neighbourhood"),
                "school_district": loc.get("school_district"),
                "address": loc.get("address_line"),
                "lat": lat,
                "lon": lon,
                "status": rec.get("status"),
                "ownership_model": rec.get("ownership_model"),
                "bedrooms_min": min(bedrooms) if bedrooms else None,
                "bedrooms_max": max(bedrooms) if bedrooms else None,
                "home_types": ";".join(rec.get("home_types") or []),
                "features": ";".join(rec.get("features") or []),
                "summary": rec.get("summary"),
                "featured_image": rec.get("featured_image"),
                "website": rec.get("website"),
                "read_more_url": rec.get("read_more_url"),
            }
        )
    df = pd.DataFrame(rows)
    if df.empty:
        raise RuntimeError(
            f"No records matched city={city!r} — check CHF's `location.city` "
            "values haven't changed format (e.g. 'Vancouver' vs 'City of Vancouver')."
        )
    return df.sort_values("title").reset_index(drop=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=DEFAULT_OUT, help="Output CSV path")
    parser.add_argument(
        "--city", default="Vancouver", help="location.city value to filter to"
    )
    parser.add_argument(
        "--html-file",
        help="Read HTML from this local file instead of fetching (for offline reruns)",
    )
    args = parser.parse_args()

    html = Path(args.html_file).read_text() if args.html_file else fetch_html()
    records = extract_coops(html)
    print(f"Fetched {len(records)} co-ops province-wide.", file=sys.stderr)

    df = normalize_coops(records, city=args.city)
    print(f"{len(df)} co-ops in city={args.city!r}.", file=sys.stderr)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)
    print(f"Wrote {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
