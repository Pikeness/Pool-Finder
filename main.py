#!/usr/bin/env python3
"""
Pool Lead Finder (command-line version) - a free, no-budget pipeline
for finding backyard pools in a US town from public aerial imagery.

For a point-and-click version instead of the command line, run
gui_app.py (see README.md).

USAGE:
    python main.py "Wayne, NJ"
    python main.py "Boca Raton, FL" --out boca_leads --max-tiles 40

READ BEFORE USING - see README.md for full details on limitations
and coverage. In short: this uses a free heuristic detector (not a
trained AI model), so always visually check the thumbnails before
mailing anyone. Addresses are NOT auto-filled in -- each row in the
CSV includes a Google Maps link, which you can open to read off the
address for any pool you visually confirm.
"""
import argparse

from pool_finder.pipeline import run_pipeline


def main():
    parser = argparse.ArgumentParser(
        description="Find backyard pools in a US town from free aerial imagery."
    )
    parser.add_argument("town", help="Town to search, e.g. 'Wayne, NJ'")
    parser.add_argument("--out", default="pool_leads", help="Output folder")
    parser.add_argument("--max-tiles", type=int, default=20,
                         help="Max NAIP imagery scenes to download (safety cap)")
    args = parser.parse_args()

    results = run_pipeline(args.town, out_dir=args.out, max_tiles=args.max_tiles)

    print(f"\nDone! {len(results)} candidate(s) in: {args.out}/")
    print(f"  - {args.out}/candidates.csv  (coordinates, confidence, Google Maps link)")
    print(f"  - {args.out}/thumbnails/  (LOOK AT THESE before mailing anyone)")
    print("\nOpen each candidate's Maps link to read off the street address")
    print("for any pool you visually confirm is real.")


if __name__ == "__main__":
    main()
