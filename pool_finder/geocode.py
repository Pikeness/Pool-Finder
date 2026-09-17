"""
Turns a town name into an approximate bounding box for aerial-imagery
searching, using Open-Meteo's free Geocoding API.

Why not OpenStreetMap's Nominatim (used in an earlier version of this
project)? Nominatim's public demo server has become increasingly
aggressive about blocking automated/non-browser clients -- even ones
that follow its usage policy exactly (custom User-Agent, 1 req/sec).
This is a widely-reported, ongoing problem as of 2026, not something
specific to this script. Open-Meteo's geocoding API is free, needs no
key, and is explicitly built for this kind of automated lookup.

Trade-off: Open-Meteo returns a center point, not an official town
boundary, so we build an approximate square bounding box around it.
That's fine for our purposes -- it just needs to be big enough to
cover the town for the NAIP imagery search.
"""
import math
import requests

OPEN_METEO_URL = "https://geocoding-api.open-meteo.com/v1/search"

# How far out from the town's center point to search, in kilometers.
# Kept fairly small by default since each NAIP tile is 100-300MB --
# a bigger radius means a bigger (and slower) first download. You can
# widen this later once you've confirmed everything works.
DEFAULT_RADIUS_KM = 3.0


def geocode_town(town_query: str, radius_km: float = DEFAULT_RADIUS_KM) -> dict:
    """
    Look up a town/city and return an approximate bounding box centered
    on it. town_query: e.g. "Wayne, NJ" or "Boca Raton, Florida".
    """
    resp = requests.get(
        OPEN_METEO_URL,
        params={"name": town_query, "count": 1, "language": "en", "format": "json"},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    results = data.get("results")
    if not results:
        raise ValueError(
            f"Could not find a location for '{town_query}'. "
            "Try a different spelling, or 'Town, State' format, e.g. 'Wayne, NJ'."
        )

    r = results[0]
    lat, lon = r["latitude"], r["longitude"]
    display_name = ", ".join(
        part for part in [r.get("name"), r.get("admin1"), r.get("country")] if part
    )

    lat_delta = radius_km / 111.0  # ~111 km per degree of latitude
    lon_delta = radius_km / (111.0 * max(0.1, math.cos(math.radians(lat))))

    return {
        "display_name": display_name,
        "lat": lat,
        "lon": lon,
        "south": lat - lat_delta,
        "north": lat + lat_delta,
        "west": lon - lon_delta,
        "east": lon + lon_delta,
    }


def maps_link(lat: float, lon: float) -> str:
    """
    A plain Google Maps URL for a coordinate pair -- free, no API key,
    works in any browser. This replaces automatic reverse-geocoding
    (turning coordinates into a street address), which we deliberately
    removed: the free services for that are unreliable at any scale
    (see README). Open this link for any candidate you visually
    confirm, and read/copy the address yourself.
    """
    return f"https://www.google.com/maps/search/?api=1&query={lat},{lon}"
