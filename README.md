# Pool Lead Finder (100% free version)

A small pipeline that finds candidate backyard swimming pools in a US
town from free public aerial imagery, so you can build a mailing list
for flyers. Every piece of this uses free data/services — no paid
APIs required.

## How it works

1. **Geocode the town** → Open-Meteo's free geocoding API turns
   "Wayne, NJ" into an approximate bounding box.
2. **Download aerial imagery** → Microsoft's Planetary Computer hosts
   NAIP (National Agriculture Imagery Program) imagery for free — US
   government, public domain, ~0.6–1m/pixel resolution.
3. **Detect pools** → a simple, free color/shape heuristic (no paid AI
   model, no training data needed) scans the imagery for blue,
   pool-shaped blobs.
4. **Output** → a CSV of candidates, each with a thumbnail crop and a
   ready-to-click Google Maps link, so you can visually confirm each
   one is a real pool and read off its street address.

### Why isn't the address auto-filled in?

An earlier version of this tool used OpenStreetMap's free Nominatim
service to automatically turn coordinates into a street address.
In practice, Nominatim's public server has become increasingly
aggressive about blocking automated (non-browser) requests — even
ones that follow its usage policy exactly — which showed up as
random `403 Forbidden` errors. Rather than rely on something that
intermittently breaks, this version gives you a one-click Google
Maps link per candidate instead: open it, and read/copy the address
yourself. You only need to do this for pools you've already visually
confirmed are real, which is a much smaller list than every raw
detection.

## Setup

```bash
pip install -r requirements.txt
```

Note: `rasterio` needs GDAL under the hood. The pip wheels bundle it
on Mac/Windows/most Linux; if install fails on your machine, install
GDAL first (`brew install gdal` on Mac, `apt install gdal-bin
libgdal-dev` on Ubuntu/Debian).

## Usage

```bash
python main.py "Wayne, NJ"
```

Options:
```bash
python main.py "Boca Raton, FL" --out boca_leads --max-tiles 40
```

Output lands in a folder (default `pool_leads/`):
- `candidates.csv` — id, lat, lon, confidence score, thumbnail filename, Google Maps link
- `thumbnails/` — small cropped images of each detected blob

## Important — read this before mailing anyone

- **This is a heuristic, not a trained AI model.** It will flag false
  positives: blue tarps, hot tubs, ponds, trampoline covers, blue roof
  panels. It will also miss some real pools: covered pools, algae-
  green water, heavily shaded yards. **Always open the thumbnail for
  each candidate and visually confirm it's actually a pool before
  adding the address to your list.** This is the "legwork" step —
  it's much faster than scanning the whole town by eye, but it's not
  meant to be fully automatic.
- **Coverage**: NAIP only covers the continental US, and each state's
  imagery is refreshed roughly every 2–3 years, so very recently
  installed pools may not show up yet.
- **Rate limits**: reverse geocoding sleeps ~1.1 seconds between
  requests to respect Nominatim's free usage policy. A town with a
  few hundred candidates will take several minutes — let it run in
  the background.
- **Local rules**: check your town/county's rules on unsolicited
  flyers or direct mail before your first mailing run.

## GUI version (point-and-click)

Instead of the command line, you can use `gui_app.py`:

```bash
python gui_app.py
```

- Type a town name, click **Find Pools**, and watch the log at the
  bottom while it works (a few minutes — imagery download + detection).
- Once it finishes, the **left list** fills with every candidate
  (confidence score + coordinates). Click any row to preview its
  thumbnail on the right.
- Click **"Open in Google Maps"** to check the real location and read
  off its street address.
- If it's a real pool, type the address into the box, then check
  **"Confirmed pool"**.
- Click **"Export confirmed list to CSV"** to save everything you've
  confirmed (with the addresses you typed in) to
  `confirmed_mailing_list.csv` — this is the clean file you'd
  actually use for flyers.

## Building an executable (no terminal needed)

There are two ways to get a real double-clickable executable — pick
whichever matches your OS.

### Option A: Build it yourself on your own machine

Run this **on the machine/OS you want the executable for** — PyInstaller
builds for whatever OS it runs on, it does not cross-compile:

```bash
pip install -r requirements.txt
pyinstaller --onefile --windowed --name PoolLeadFinder \
  --hidden-import PIL._tkinter_finder \
  --collect-all rasterio \
  --collect-all fiona \
  --collect-data rasterio \
  gui_app.py
```

The finished executable appears in `dist/`.

### Option B: Get a Windows .exe with zero local setup (recommended if you're on Windows)

This repo includes a GitHub Actions workflow
(`.github/workflows/build.yml`) that builds the `.exe` for you on an
actual Windows machine in the cloud — you never install Python,
PyInstaller, or open a terminal. GitHub's free tier covers this.

1. **Create a free GitHub account** at github.com if you don't have one.
2. **Create a new repository** (click the "+" top-right → "New
   repository"). Any name, Public or Private both work.
3. **Upload this whole project folder** to it: on the repo's page,
   click "Add file" → "Upload files", then drag every file/folder
   from this project in (including the hidden `.github` folder — if
   your drag-and-drop tool hides dotfiles, use "choose your files"
   instead and select them all). Commit the upload.
4. Click the **"Actions"** tab at the top of the repo. You should see
   "Build Windows executable" — click it, then click **"Run
   workflow"** (it also runs automatically the moment you upload).
5. Wait 2–5 minutes for it to finish (green checkmark).
6. Click into the finished run, scroll to **"Artifacts"** at the
   bottom, and download **PoolLeadFinder-windows** — that's a zip
   containing your real `PoolLeadFinder.exe`, built on Windows, ready
   to double-click.

You only need to repeat steps 4–6 (not the whole upload) any time you
want to rebuild after changing the code.

Notes:
- The `--collect-all rasterio` / `fiona` flags matter — without them
  the exe builds fine but crashes on launch, because rasterio loads
  some of its GDAL bindings dynamically in a way PyInstaller can't
  auto-detect.
- On first run, Windows SmartScreen will warn about an "unrecognized
  app" since the exe isn't code-signed (that costs money and isn't
  worth it for personal use). Click "More info" → "Run anyway."
- Each output CSV/thumbnail folder is created next to wherever the
  executable is run from.

## If you want better accuracy later (optional, still free)

The heuristic in `pool_finder/detect.py` is deliberately simple so it
works out of the box with zero setup. If false positives become
annoying, options that are still free:

- Tune the HSV color thresholds and size/aspect-ratio filters at the
  top of `detect_pools_in_tile()` for your specific area's imagery.
- Swap in an open-source pretrained pool-detection model (there are a
  few published on GitHub) in place of the color heuristic — same
  input/output shape, just a better classifier.
- Cross-reference candidates against your county assessor's public
  GIS parcel data, which sometimes already flags "pool" as a taxable
  property improvement — this can double-confirm a hit for free.
