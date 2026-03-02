"""
Configuration for the product-viz app.
Paste your Google Sheets URL below.
"""
import os

# Google Sheets URL — paste your spreadsheet URL here
# Example: https://docs.google.com/spreadsheets/d/1ABC...xyz/edit#gid=0
SPREADSHEET_URL = os.environ.get("SPREADSHEET_URL", "https://docs.google.com/spreadsheets/d/1D_76rG3KMcwbLMXANHNpbCU3lfemq5dj7PVHEshCeoU/edit?usp=sharing")

# Optional: sheet GID if you want a specific sheet (default 0 = first sheet)
# Can be overridden in the URL fragment, e.g. .../edit#gid=123456
DEFAULT_SHEET_GID = "0"
