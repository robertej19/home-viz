"""
Flask app that loads product data from CSV and serves summary statistics.
"""
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from flask import Flask, jsonify, render_template_string, send_file

app = Flask(__name__)

DATA_PATH = Path(__file__).parent / "data" / "sheet_data.csv"

import image_cache


def load_data() -> pd.DataFrame:
    """Load and clean the product CSV."""
    if not DATA_PATH.exists():
        return pd.DataFrame()

    df = pd.read_csv(DATA_PATH)
    # Drop completely empty rows
    df = df.dropna(how="all")
    # Drop unnamed columns
    df = df.loc[:, ~df.columns.str.startswith("Unnamed")]
    # Strip whitespace from column names
    df.columns = df.columns.str.strip()
    return df


def parse_price(price_str) -> float:
    """Parse price string like '$21.68' to float."""
    if pd.isna(price_str):
        return 0.0
    s = str(price_str).replace("$", "").replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return 0.0


def normalize_type(type_str: str) -> str:
    """Normalize type: any 'X cream' (eye cream, sensitive cream, etc.) -> 'Cream'."""
    if pd.isna(type_str):
        return ""
    s = str(type_str).strip()
    if "cream" in s.lower():
        return "Cream"
    return s


def get_summary(df: pd.DataFrame) -> dict:
    """Compute basic summary statistics from the product data."""
    if df.empty:
        return {"error": "No data loaded"}

    # Parse prices for total spend
    df = df.copy()
    df["price_num"] = df.get("Price", pd.Series()).apply(parse_price)

    # Count by type (drop empty); normalize "X cream" -> "Cream"
    type_col = "Type" if "Type" in df.columns else df.columns[0]
    types = (
        df[type_col]
        .dropna()
        .astype(str)
        .str.strip()
        .replace("", pd.NA)
        .dropna()
        .apply(normalize_type)
    )
    types = types[types != ""]
    type_counts = types.value_counts().to_dict()

    type_list = [{"name": k, "count": v} for k, v in type_counts.items()]
    type_total = sum(type_counts.values()) or 1  # avoid div by zero in template

    return {
        "total_products": len(df),
        "total_spend": round(df["price_num"].sum(), 2),
        "count_by_type": type_counts,
        "type_list": type_list,
        "type_total": type_total,
        "active_in_rotation": int(
            df.get("Active Rotation", pd.Series()).astype(str).str.lower().eq("true").sum()
        ),
    }


# Electric / tech palette (neon, high contrast on dark)
PIE_COLORS = [
    "#00fff5", "#ff00aa", "#7b2fff", "#00ff88", "#ff3366",
    "#00ccff", "#ffcc00", "#bf00ff", "#39ff14",
]


def build_pie_chart_html(type_list: list[dict]) -> str:
    """Build an interactive Plotly pie chart (hover only, no legend)."""
    if not type_list:
        return ""

    labels = [t["name"] for t in type_list]
    values = [t["count"] for t in type_list]

    fig = go.Figure(
        data=[
            go.Pie(
                labels=labels,
                values=values,
                hole=0.4,
                marker_colors=PIE_COLORS,
                textinfo="none",
                hovertemplate="<b>%{label}</b><br>%{value} product(s)<br>%{percent}<extra></extra>",
            )
        ],
        layout=go.Layout(
            margin=dict(t=20, b=20, l=20, r=20),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            showlegend=False,
            font=dict(family="system-ui, sans-serif", color="#e8e8e8", size=13),
            hoverlabel=dict(
                bgcolor="rgba(30, 30, 50, 0.95)",
                bordercolor="rgba(255,255,255,0.2)",
                font=dict(color="#e8e8e8", size=13),
            ),
            uniformtext=dict(minsize=10, mode="hide"),
        ),
    )
    fig.update_traces(
        textposition="inside",
        insidetextorientation="radial",
    )
    return fig.to_html(full_html=False, include_plotlyjs="cdn", config=dict(displayModeBar=False))


def _unique_products_with_slugs(df: pd.DataFrame) -> list[dict]:
    """Unique product names and slugs for image display."""
    if df.empty or "Product" not in df.columns:
        return []
    names = df["Product"].dropna().astype(str).str.strip().replace("", pd.NA).dropna().unique().tolist()
    image_cache.ensure_manifest(names)
    return [{"name": n, "slug": image_cache.slugify(n)} for n in names if image_cache.slugify(n)]


@app.route("/")
def index():
    """Serve the main page with summary data."""
    df = load_data()
    summary = get_summary(df)
    pie_html = build_pie_chart_html(summary.get("type_list", [])) if not df.empty else ""
    unique_products = _unique_products_with_slugs(df)
    return render_template_string(
        INDEX_HTML,
        summary=summary,
        has_data=not df.empty,
        pie_html=pie_html,
        unique_products=unique_products,
    )


@app.route("/api/summary")
def api_summary():
    """JSON endpoint for summary statistics."""
    df = load_data()
    return jsonify(get_summary(df))


@app.route("/api/product_image/<slug>")
def product_image(slug: str):
    """Serve cached product image, or fetch+process and cache then serve. 404 if not found."""
    path = image_cache.get_or_create_image_path(slug)
    if path is None:
        return "", 404
    ext = path.suffix.lower()
    mimetype = "image/webp" if ext == ".webp" else "image/jpeg" if ext in (".jpg", ".jpeg") else "image/png"
    return send_file(path, mimetype=mimetype, max_age=86400 * 7)


@app.route("/api/data")
def api_data():
    """JSON endpoint for raw data (for future visualizations)."""
    df = load_data()
    # Convert to records, handling NaN
    records = df.fillna("").to_dict(orient="records")
    return jsonify(records)


INDEX_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
    <meta name="theme-color" content="#1a1b2e">
    <title>Skin Care Tracking</title>
    <style>
        *, *::before, *::after { box-sizing: border-box; }
        html {
            -webkit-text-size-adjust: 100%;
            min-height: 100%;
        }
        body {
            font-family: "SF Pro Text", -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
            margin: 0;
            min-height: 100vh;
            min-height: 100dvh;
            padding: max(1.25rem, env(safe-area-inset-top)) max(1rem, env(safe-area-inset-right)) max(1.25rem, env(safe-area-inset-bottom)) max(1rem, env(safe-area-inset-left));
            background: linear-gradient(165deg, #1a1b2e 0%, #16213e 40%, #0f3460 100%);
            color: #e8e8e8;
            font-size: clamp(1rem, 2.5vw, 1.0625rem);
        }
        .page {
            max-width: 28rem;
            margin: 0 auto;
        }
        h1 {
            font-size: clamp(1.5rem, 5vw, 1.75rem);
            font-weight: 700;
            margin: 0 0 1.25rem;
            letter-spacing: -0.02em;
            text-align: center;
        }
        .pie-wrap {
            background: rgba(255, 255, 255, 0.06);
            backdrop-filter: blur(12px);
            -webkit-backdrop-filter: blur(12px);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 1.25rem;
            padding: 0.5rem;
            margin-bottom: 1.5rem;
            overflow: hidden;
        }
        .pie-wrap .js-plotly-plot {
            width: 100% !important;
            max-width: 320px;
            margin: 0 auto;
        }
        .summary {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 0.75rem;
            margin-bottom: 1.5rem;
        }
        .card {
            background: rgba(255, 255, 255, 0.08);
            backdrop-filter: blur(12px);
            -webkit-backdrop-filter: blur(12px);
            border: 1px solid rgba(255, 255, 255, 0.12);
            border-radius: 1rem;
            padding: 1rem 0.75rem;
            text-align: center;
            -webkit-tap-highlight-color: transparent;
        }
        .card h3 {
            margin: 0 0 0.35rem;
            font-size: 0.7rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.06em;
            color: rgba(255, 255, 255, 0.6);
        }
        .card .value {
            font-size: clamp(1.25rem, 4vw, 1.5rem);
            font-weight: 700;
            color: #fff;
        }
        .products-wrap {
            background: rgba(255, 255, 255, 0.06);
            backdrop-filter: blur(12px);
            -webkit-backdrop-filter: blur(12px);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 1.25rem;
            padding: 1rem;
            margin-bottom: 1rem;
        }
        .products-wrap h2 {
            font-size: 0.9rem;
            font-weight: 600;
            margin: 0 0 0.75rem;
            color: rgba(255, 255, 255, 0.85);
        }
        .product-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(72px, 1fr));
            gap: 0.75rem;
        }
        .product-card {
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 0.35rem;
        }
        .product-card img {
            width: 64px;
            height: 64px;
            object-fit: cover;
            border-radius: 12px;
            background: rgba(0, 0, 0, 0.3);
        }
        .product-card .name {
            font-size: 0.7rem;
            color: rgba(255, 255, 255, 0.8);
            text-align: center;
            line-height: 1.2;
            display: -webkit-box;
            -webkit-line-clamp: 2;
            -webkit-box-orient: vertical;
            overflow: hidden;
        }
        .empty {
            background: rgba(255, 255, 255, 0.06);
            backdrop-filter: blur(12px);
            -webkit-backdrop-filter: blur(12px);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 1rem;
            padding: 1.25rem;
            color: rgba(255, 255, 255, 0.55);
        }
        .empty code { font-size: 0.9em; opacity: 0.9; }
    </style>
</head>
<body>
    <div class="page">
        <h1>Skin Care Tracking</h1>
        {% if has_data %}
        <div class="pie-wrap">
            {{ pie_html | safe }}
        </div>
        <div class="summary">
            <div class="card">
                <h3>Products</h3>
                <div class="value">{{ summary.total_products }}</div>
            </div>
            <div class="card">
                <h3>Spend</h3>
                <div class="value">${{ "%.2f"|format(summary.total_spend) }}</div>
            </div>
            <div class="card">
                <h3>Active</h3>
                <div class="value">{{ summary.active_in_rotation }}</div>
            </div>
        </div>
        {% if unique_products %}
        <section class="products-wrap">
            <h2>Products</h2>
            <div class="product-grid">
                {% for p in unique_products %}
                <div class="product-card" title="{{ p.name }}">
                    <img src="/api/product_image/{{ p.slug }}" alt="{{ p.name }}" loading="lazy" onerror="this.onerror=null; this.style.background='rgba(255,255,255,0.08)'; this.style.minWidth='64px'; this.style.minHeight='64px';">
                    <span class="name">{{ p.name }}</span>
                </div>
                {% endfor %}
            </div>
        </section>
        {% endif %}
        {% else %}
        <p class="empty">No data loaded. Run <code>python download_data.py</code> and ensure <code>data/sheet_data.csv</code> exists.</p>
        {% endif %}
    </div>
</body>
</html>
"""


if __name__ == "__main__":
    # host="0.0.0.0" so other devices on your network (e.g. phone) can connect
    app.run(debug=True, host="0.0.0.0", port=5000)
