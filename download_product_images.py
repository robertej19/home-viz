#!/usr/bin/env python3
"""
Pre-download product images into the cache. Run this once (or when you add products)
so the app can serve images without fetching on first request.

  python download_product_images.py
  python download_product_images.py --verbose   # show why each failure happened

Images are saved under data/product_images/. If a file already exists for a slug,
it is skipped (so you can replace any file manually).
"""
import argparse
import sys
import time
from pathlib import Path

# Run from project root
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd

import image_cache

DATA_PATH = Path(__file__).parent / "data" / "sheet_data.csv"


def load_products_from_csv():
    if not DATA_PATH.exists():
        print(f"No data at {DATA_PATH}. Run download_data.py first.")
        return []
    df = pd.read_csv(DATA_PATH)
    df = df.dropna(how="all")
    if "Product" not in df.columns:
        col = df.columns[0] if len(df.columns) else None
        if col:
            df = df.rename(columns={col: "Product"})
        else:
            return []
    names = df["Product"].dropna().astype(str).str.strip().replace("", pd.NA).dropna().unique().tolist()
    return names


def main():
    parser = argparse.ArgumentParser(description="Pre-download product images into cache.")
    parser.add_argument("--verbose", "-v", action="store_true", help="Print why each fetch fails")
    args = parser.parse_args()

    names = load_products_from_csv()
    if not names:
        print("No product names found. Ensure data/sheet_data.csv has a 'Product' column.")
        sys.exit(1)

    image_cache.ensure_manifest(names)
    print(f"Manifest updated: {len(names)} unique products.")
    print("Downloading images (skip if file already exists)...\n")

    ok = 0
    skip = 0
    fail = 0

    # Reuse one browser for all searches (faster; Playwright)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright not installed. Run: pip install playwright && playwright install chromium")
        sys.exit(1)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            for name in names:
                slug = image_cache.slugify(name)
                if not slug:
                    continue
                if image_cache.get_cached_image_path(slug):
                    print(f"  [skip] {name}")
                    skip += 1
                    continue
                if args.verbose:
                    print(f"  [try]  {name}")
                path = image_cache.fetch_and_process(name, verbose=args.verbose, page=page)
                if path:
                    print(f"  [ok]   {name} -> {path.name}")
                    ok += 1
                else:
                    print(f"  [fail] {name}")
                    fail += 1
                time.sleep(1.5)  # short pause between searches
        finally:
            browser.close()

    print(f"\nDone: {ok} downloaded, {skip} already cached, {fail} failed.")
    if fail:
        print("Tip: Run with --verbose to see why each failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()
