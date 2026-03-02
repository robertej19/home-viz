# Product Viz

Flask app that downloads a Google Sheet and builds interactive visualizations.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate   # or: .venv\Scripts\activate on Windows
pip install -r requirements.txt
```

## Spreadsheet URL

1. Open **config.py** and set `SPREADSHEET_URL` to your Google Sheets URL, or
2. Set the env var: `export SPREADSHEET_URL="https://docs.google.com/spreadsheets/d/..."`

The sheet must be shared so **Anyone with the link can view** (for CSV export without API keys).

## Download data

```bash
python download_data.py
```

This fetches the sheet as CSV and saves it to `data/sheet_data.csv`. You can also use `download_sheet()` from Python.

## Run the Flask app

```bash
python app.py
```

Open http://127.0.0.1:5000 for the summary dashboard. API endpoints:
- `GET /api/summary` — JSON summary stats
- `GET /api/data` — raw product data (for visualizations)
- `GET /api/product_image/<slug>` — product image (fetched and cached on first request)

## Product images

**To populate images**, run once (after `data/sheet_data.csv` exists):

```bash
pip install playwright && playwright install chromium
python download_product_images.py
```

This uses Playwright (headless Chromium) to search Bing Images for each product name, downloads the first usable result, crops to a square, resizes to 256×256, and saves under `data/product_images/`. Already-cached files are skipped.

- **Manual override:** Put a file in `data/product_images/` with the slug as the name (e.g. `anua-3-cream.jpg`). Slugs are in `data/product_images/manifest.json`.
- The app serves images from that cache; if a file is missing it tries to fetch on first request (can be slow or 404 if fetch fails). Pre-running the script avoids that.
