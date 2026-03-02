"""
Download spreadsheet data from Google Sheets as CSV and return a pandas DataFrame.

The spreadsheet must be shared so that "Anyone with the link can view" (for the
simple export URL). For private sheets, you would need the Google Sheets API and
credentials instead.
"""
import io
import re
import sys
from pathlib import Path

import pandas as pd
import requests

# Allow importing config from project root when running as script
sys.path.insert(0, str(Path(__file__).resolve().parent))
import config


def spreadsheet_url_to_export_url(spreadsheet_url: str, gid: str | None = None) -> str:
    """
    Convert a Google Sheets edit/view URL to the CSV export URL.

    Args:
        spreadsheet_url: Full URL, e.g.
            https://docs.google.com/spreadsheets/d/1ABC...xyz/edit#gid=0
        gid: Optional sheet GID. If None, taken from URL fragment (#gid=...) or config.

    Returns:
        URL that returns CSV when fetched.
    """
    # Extract spreadsheet ID (the long string between /d/ and /edit or similar)
    match = re.search(r"/d/([a-zA-Z0-9_-]+)", spreadsheet_url)
    if not match:
        raise ValueError(
            "Invalid Google Sheets URL. Expected format: "
            "https://docs.google.com/spreadsheets/d/SPREADSHEET_ID/..."
        )
    sheet_id = match.group(1)

    # Optional: extract gid from URL fragment (#gid=123)
    if gid is None:
        gid_match = re.search(r"[#&]gid=(\d+)", spreadsheet_url)
        gid = gid_match.group(1) if gid_match else config.DEFAULT_SHEET_GID

    return (
        f"https://docs.google.com/spreadsheets/d/{sheet_id}/export"
        f"?format=csv&gid={gid}"
    )


def download_sheet(
    spreadsheet_url: str | None = None,
    gid: str | None = None,
) -> pd.DataFrame:
    """
    Download a Google Sheet as CSV and return a pandas DataFrame.

    Args:
        spreadsheet_url: Google Sheets URL. If None, uses config.SPREADSHEET_URL.
        gid: Optional sheet GID. If None, uses URL fragment or config default.

    Returns:
        DataFrame of the sheet contents.
    """
    url = spreadsheet_url or config.SPREADSHEET_URL
    if not url:
        raise ValueError(
            "No spreadsheet URL. Set SPREADSHEET_URL in config.py or pass spreadsheet_url=..."
        )

    export_url = spreadsheet_url_to_export_url(url, gid=gid)
    resp = requests.get(export_url, timeout=30)
    resp.raise_for_status()

    return pd.read_csv(io.StringIO(resp.text))


def main():
    """Download sheet and optionally save to CSV."""
    try:
        df = download_sheet()
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)
    except requests.RequestException as e:
        print(f"Download failed: {e}")
        sys.exit(1)

    out_path = Path(__file__).parent / "data" / "sheet_data.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)
    print(f"Downloaded {len(df)} rows, {len(df.columns)} columns -> {out_path}")
    return df


if __name__ == "__main__":
    main()
