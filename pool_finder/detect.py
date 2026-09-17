"""
Free, no-training-required pool detector.

STRATEGY: swimming pools show up in aerial imagery as saturated
blue/cyan blobs of a fairly regular (roughly rectangular or oval)
shape within a certain size range. This is a color/shape HEURISTIC,
not a trained ML model.

That means it WILL produce false positives (blue tarps, ponds, blue
roofing, trampoline covers, hot tubs) and occasional false negatives
(covered, algae-green, or shaded pools). Treat its output as a
shortlist to visually confirm using the saved thumbnails - not a
final mailing list.

If you later want higher accuracy, this is the piece to swap out for
a trained CNN (there are open-source pool-detection models on GitHub
you could plug in here instead).
"""
import cv2
import numpy as np
import rasterio
from rasterio.windows import Window


def _pixel_to_lonlat(transform, col, row):
    lon, lat = rasterio.transform.xy(transform, row, col)
    return lon, lat


def detect_pools_in_tile(tif_path: str, tile_size: int = 1024,
                          min_area_px: int = 30, max_area_px: int = 1500,
                          max_candidates_per_chunk: int = 15):
    """
    Scans a NAIP GeoTIFF for pool-like blobs.

    Yields dicts: {lon, lat, confidence, pixel_area, crop, source_tile}
    for each candidate found. `crop` is a small BGR numpy image you can
    save as a thumbnail for manual review.

    max_candidates_per_chunk guards against a specific failure mode:
    a natural water body (a lake, reservoir, or river) is a large,
    contiguous blue area, but JPEG-style compression noise can fragment
    it into hundreds or thousands of small "pool-sized" speckles in a
    single 1024x1024 chunk. That's not one ambiguous shape you'd want
    to keep and manually check -- it's a strong signal the whole chunk
    is dominated by open water, not a residential yard, so the entire
    chunk's candidates are discarded rather than flooding the results
    with an unusable number of false positives.
    """
    with rasterio.open(tif_path) as src:
        transform = src.transform
        width, height = src.width, src.height

        for row0 in range(0, height, tile_size):
            for col0 in range(0, width, tile_size):
                win = Window(col0, row0,
                             min(tile_size, width - col0),
                             min(tile_size, height - row0))
                img = src.read([1, 2, 3], window=win)  # R, G, B bands
                if img.size == 0:
                    continue

                # rasterio gives (bands, rows, cols) -> HxWx3 BGR for OpenCV
                img = np.transpose(img, (1, 2, 0))
                bgr = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)

                hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
                # Blue/cyan pool-water range. Tune these if you get too
                # many false positives/negatives for your area's imagery.
                lower = np.array([85, 60, 60])
                upper = np.array([130, 255, 255])
                mask = cv2.inRange(hsv, lower, upper)

                mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
                # A larger closing kernel merges nearby speckles from a
                # single noisy water surface into one contiguous blob
                # (which then correctly gets rejected by max_area_px)
                # instead of leaving them as hundreds of separate
                # "pool-sized" fragments.
                mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))

                contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                                cv2.CHAIN_APPROX_SIMPLE)

                chunk_candidates = []
                for c in contours:
                    area = cv2.contourArea(c)
                    if area < min_area_px or area > max_area_px:
                        continue

                    x, y, w, h = cv2.boundingRect(c)
                    aspect = w / float(h) if h else 0
                    if aspect < 0.3 or aspect > 3.5:
                        continue  # too sliver-shaped to plausibly be a pool

                    rect_area = w * h
                    fill_ratio = area / rect_area if rect_area else 0
                    if fill_ratio < 0.4:
                        continue  # too irregular a shape

                    cx_local, cy_local = x + w / 2, y + h / 2
                    col = col0 + cx_local
                    row = row0 + cy_local
                    lon, lat = _pixel_to_lonlat(transform, col, row)

                    pad = 15
                    y0, y1 = max(0, y - pad), min(bgr.shape[0], y + h + pad)
                    x0, x1 = max(0, x - pad), min(bgr.shape[1], x + w + pad)
                    crop = bgr[y0:y1, x0:x1].copy()

                    confidence = round(min(1.0, fill_ratio) * min(1.0, area / 200), 2)

                    chunk_candidates.append({
                        "lon": lon,
                        "lat": lat,
                        "pixel_area": area,
                        "confidence": confidence,
                        "crop": crop,
                        "source_tile": tif_path,
                    })

                # A real residential chunk has at most a handful of
                # pools; a chunk full of dozens of "candidates" is a
                # strong sign it's actually a lake/reservoir/river
                # fragmenting into noise, not a neighborhood -- discard
                # the whole chunk rather than keep the speckles.
                if len(chunk_candidates) > max_candidates_per_chunk:
                    continue

                for cand in chunk_candidates:
                    yield cand
