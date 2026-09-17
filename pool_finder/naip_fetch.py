"""
Downloads free NAIP aerial imagery covering a bounding box, via
Microsoft's Planetary Computer - a free, public STAC catalog.
No account or API key needed to read NAIP data.

NAIP = National Agriculture Imagery Program (USDA). It's public
domain, ~0.6-1m/pixel resolution, and covers the continental US.
Imagery is refreshed roughly every 2-3 years per state, so brand new
pools may not show up yet.

Note: individual NAIP tiles are large (roughly 100-300MB each), so
downloading several of them is the slowest part of the whole pipeline
by far -- this can take anywhere from under a minute to 15+ minutes
depending on your internet connection and how many tiles the search
area covers. This module reports live per-tile progress (including
size and percent complete) via the optional `progress` callback so a
GUI never looks frozen during this step.
"""
import os

import planetary_computer
import pystac_client
import requests

STAC_API_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"


def fetch_naip_tiles(bbox: dict, out_dir: str, max_tiles: int = 20, progress=None) -> list:
    """
    bbox: dict with south/north/west/east keys (from geocode_town)
    out_dir: local folder to save downloaded GeoTIFFs into
    max_tiles: safety cap on number of scenes downloaded (a mid-size
        town is usually covered by a handful of NAIP tiles; raise this
        for a larger area, but each tile can be 100-300MB)
    progress: optional callable(str) for live status updates (tile
        counts, download size, percent complete). Falls back to
        print() if not given.

    Returns a list of local file paths that were downloaded.
    """
    def log(msg):
        if progress:
            progress(msg)
        else:
            print(msg)

    os.makedirs(out_dir, exist_ok=True)

    # Note: we deliberately do NOT sign every item's URL up front here
    # (e.g. via a `modifier=planetary_computer.sign_inplace` on
    # Client.open). Each signed URL is a temporary, time-limited
    # access token. If a whole batch of tiles is signed at once but
    # takes a long time to download (large files + a slow connection),
    # a later tile's token can go stale by the time we get to it,
    # causing a 403 "signature" error partway through a run. Instead,
    # each tile below is signed individually, right before it's
    # downloaded, so the token is always fresh.
    catalog = pystac_client.Client.open(STAC_API_URL)

    search = catalog.search(
        collections=["naip"],
        bbox=[bbox["west"], bbox["south"], bbox["east"], bbox["north"]],
        limit=max_tiles,
    )

    items = list(search.items())[:max_tiles]
    if not items:
        raise RuntimeError(
            "No NAIP imagery found for this area. NAIP only covers the "
            "continental United States."
        )

    log(f"Found {len(items)} imagery tile(s) covering this area. "
        f"Each tile is roughly 100-300MB, so this download can take "
        f"a while depending on your internet speed -- this is normal.")

    paths = []
    for idx, item in enumerate(items, start=1):
        asset = item.assets.get("image")
        if asset is None:
            continue
        local_path = os.path.join(out_dir, f"{item.id}.tif")

        if os.path.exists(local_path):
            log(f"Tile {idx}/{len(items)} already downloaded, skipping: {item.id}")
            paths.append(local_path)
            continue

        log(f"Downloading tile {idx}/{len(items)}: {item.id} ...")

        # Sign fresh, right before use (see note above).
        signed_url = planetary_computer.sign(asset.href)
        r = requests.get(signed_url, stream=True, timeout=180)
        try:
            r.raise_for_status()
        except requests.HTTPError:
            if r.status_code == 403:
                # Extremely unlikely now that we sign right before
                # downloading, but just in case of a race, sign once
                # more and retry before giving up.
                log(f"  Tile {idx}/{len(items)} got a 403, retrying with "
                    f"a freshly-signed link...")
                signed_url = planetary_computer.sign(asset.href)
                r = requests.get(signed_url, stream=True, timeout=180)
                r.raise_for_status()
            else:
                raise

        total_bytes = int(r.headers.get("content-length", 0))
        downloaded = 0
        last_reported_pct = -1

        with open(local_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):  # 1MB chunks
                f.write(chunk)
                downloaded += len(chunk)
                if total_bytes:
                    pct = int(downloaded * 100 / total_bytes)
                    # only log every ~10% so this doesn't flood the log
                    if pct >= last_reported_pct + 10:
                        mb_done = downloaded / (1 << 20)
                        mb_total = total_bytes / (1 << 20)
                        log(f"  Tile {idx}/{len(items)}: {pct}% "
                            f"({mb_done:.0f}MB / {mb_total:.0f}MB)")
                        last_reported_pct = pct

        log(f"Tile {idx}/{len(items)} done: {item.id}")
        paths.append(local_path)

    return paths
