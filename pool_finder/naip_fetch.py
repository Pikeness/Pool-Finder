"""
Downloads free NAIP aerial imagery covering a bounding box, via
Microsoft's Planetary Computer - a free, public STAC catalog.
No account or API key needed to read NAIP data.

NAIP = National Agriculture Imagery Program (USDA). It's public
domain, ~0.6-1m/pixel resolution, and covers the continental US.
Imagery is refreshed roughly every 2-3 years per state, so brand new
pools may not show up yet.
"""
import os

import planetary_computer
import pystac_client
import requests

STAC_API_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"


def fetch_naip_tiles(bbox: dict, out_dir: str, max_tiles: int = 20) -> list:
    """
    bbox: dict with south/north/west/east keys (from geocode_town)
    out_dir: local folder to save downloaded GeoTIFFs into
    max_tiles: safety cap on number of scenes downloaded (a mid-size
        town is usually covered by a handful of NAIP tiles; raise this
        for a larger area, but each tile can be 100-300MB)

    Returns a list of local file paths that were downloaded.
    """
    os.makedirs(out_dir, exist_ok=True)

    catalog = pystac_client.Client.open(
        STAC_API_URL, modifier=planetary_computer.sign_inplace
    )

    search = catalog.search(
        collections=["naip"],
        bbox=[bbox["west"], bbox["south"], bbox["east"], bbox["north"]],
        limit=max_tiles,
    )

    items = list(search.items())
    if not items:
        raise RuntimeError(
            "No NAIP imagery found for this area. NAIP only covers the "
            "continental United States."
        )

    paths = []
    for item in items[:max_tiles]:
        asset = item.assets.get("image")
        if asset is None:
            continue
        url = asset.href
        local_path = os.path.join(out_dir, f"{item.id}.tif")
        if not os.path.exists(local_path):
            print(f"  Downloading imagery tile: {item.id}")
            r = requests.get(url, stream=True, timeout=180)
            r.raise_for_status()
            with open(local_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 20):
                    f.write(chunk)
        paths.append(local_path)

    return paths
