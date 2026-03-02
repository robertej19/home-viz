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
