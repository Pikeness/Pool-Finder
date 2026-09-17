"""
Shared pipeline logic used by both the CLI (main.py) and the GUI
(gui_app.py), so both stay in sync and neither duplicates the work.

Note: this pipeline does NOT auto-fetch street addresses. An earlier
version did, via OpenStreetMap's free Nominatim reverse-geocoding
service, but that service has become unreliable for automated/non-
browser use (frequent 403 errors unrelated to anything this script
does wrong). Instead, each candidate gets a ready-to-click Google
Maps link -- open it for any pool you visually confirm, and read the
address off the map yourself. That's a small bit of manual work, but
only for the (much smaller) set of pools you've already confirmed
are real, not for every raw candidate.
"""
import csv
import os

import cv2

from pool_finder.geocode import geocode_town, maps_link
from pool_finder.naip_fetch import fetch_naip_tiles
from pool_finder.detect import detect_pools_in_tile


def run_pipeline(town: str, out_dir: str = "pool_leads", max_tiles: int = 20,
                  progress=None) -> list:
    """
    Runs the free pipeline: geocode town -> download NAIP imagery ->
    detect pools -> save thumbnails + CSV.

    progress: optional callable(str) invoked with human-readable status
        updates as the pipeline runs, so a GUI can show live progress.

    Returns a list of dicts, one per candidate:
        {id, lat, lon, confidence, maps_url, thumbnail_path}
    """
    def log(msg):
        if progress:
            progress(msg)
        else:
            print(msg)

    os.makedirs(out_dir, exist_ok=True)
    tiles_dir = os.path.join(out_dir, "naip_tiles")
    thumbs_dir = os.path.join(out_dir, "thumbnails")
    os.makedirs(thumbs_dir, exist_ok=True)

    log(f"Looking up '{town}' ...")
    place = geocode_town(town)
    log(f"Found: {place['display_name']}")

    log("Downloading free NAIP aerial imagery (this can take a few minutes)...")
    tif_paths = fetch_naip_tiles(place, tiles_dir, max_tiles=max_tiles)
    log(f"Downloaded {len(tif_paths)} imagery tile(s).")

    raw_candidates = []
    for i, tif_path in enumerate(tif_paths):
        log(f"Scanning tile {i + 1}/{len(tif_paths)} for pools...")
        for cand in detect_pools_in_tile(tif_path):
            raw_candidates.append(cand)

    log(f"Found {len(raw_candidates)} candidate pool(s). Saving thumbnails...")

    results = []
    csv_path = os.path.join(out_dir, "candidates.csv")
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "lat", "lon", "confidence", "thumbnail_file", "google_maps_link"])

        for i, cand in enumerate(raw_candidates):
            thumb_name = f"candidate_{i:04d}.jpg"
            thumb_path = os.path.join(thumbs_dir, thumb_name)
            cv2.imwrite(thumb_path, cand["crop"])

            url = maps_link(cand["lat"], cand["lon"])
            writer.writerow([i, cand["lat"], cand["lon"], cand["confidence"], thumb_name, url])

            results.append({
                "id": i,
                "lat": cand["lat"],
                "lon": cand["lon"],
                "confidence": cand["confidence"],
                "maps_url": url,
                "thumbnail_path": thumb_path,
            })

    log(f"Done. {len(results)} candidate(s) found. Results in: {out_dir}/")
    return results
