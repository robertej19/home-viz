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


def _products_by_type(df: pd.DataFrame) -> list[dict]:
    """Products grouped by (normalized) type; each group has type name and list of {slug, name}."""
    if df.empty or "Product" not in df.columns or "Type" not in df.columns:
        return []
    type_col = "Type"
    df = df.dropna(subset=["Product", type_col])
    df = df.drop_duplicates(subset=["Product"])
    df = df.copy()
    df["Type_norm"] = df[type_col].astype(str).str.strip().apply(normalize_type)
    df = df[df["Type_norm"] != ""]
    df["slug"] = df["Product"].astype(str).str.strip().apply(image_cache.slugify)
    df = df[df["slug"] != ""]
    names = df["Product"].astype(str).str.strip().unique().tolist()
    image_cache.ensure_manifest(names)

    def _str(val):
        if pd.isna(val) or val == "":
            return ""
        return str(val).strip()

    def to_products(g):
        return [
            {
                "slug": r["slug"],
                "name": r["Product"],
                "open_date": _str(r.get("Open Date", "")),
                "price": _str(r.get("Price", "")),
                "comments": _str(r.get("Comments", "")),
            }
            for _, r in g.iterrows()
        ]

    def col_row_span(n: int) -> tuple[int, int]:
        """Grid span (col_span, row_span) so section size reflects product count. Puzzle-like."""
        if n <= 0:
            return (1, 1)
        col_span = min(n, 3)
        row_span = max(1, (n + col_span - 1) // col_span)
        return (col_span, row_span)

    groups = df.groupby("Type_norm", sort=True).apply(to_products).to_dict()
    out = []
    for t in groups:
        products = groups[t]
        c, r = col_row_span(len(products))
        out.append({"type": t, "products": products, "col_span": c, "row_span": r})
    return out


@app.route("/")
def index():
    """Serve the main page with summary data."""
    df = load_data()
    summary = get_summary(df)
    products_by_type = _products_by_type(df)
    return render_template_string(
        INDEX_HTML,
        summary=summary,
        has_data=not df.empty,
        products_by_type=products_by_type,
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
    resp = send_file(path, mimetype=mimetype)
    # Avoid long-lived cache so updated/replaced images show on phones
    resp.headers["Cache-Control"] = "no-cache, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    return resp


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
    <title>Skin Care Console</title>
    <style>
        *, *::before, *::after { box-sizing: border-box; }
        html {
            -webkit-text-size-adjust: 100%;
            height: 100%;
            max-height: 100dvh;
            overflow: hidden;
        }
        body {
            font-family: "SF Pro Text", -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
            margin: 0;
            height: 100%;
            max-height: 100dvh;
            overflow: hidden;
            padding: max(0.75rem, env(safe-area-inset-top)) max(0.75rem, env(safe-area-inset-right)) max(0.75rem, env(safe-area-inset-bottom)) max(0.75rem, env(safe-area-inset-left));
            background: linear-gradient(165deg, #1a1b2e 0%, #16213e 40%, #0f3460 100%);
            color: #e8e8e8;
            font-size: clamp(0.9rem, 2.5vw, 1rem);
        }
        .page {
            display: flex;
            flex-direction: column;
            max-width: 28rem;
            margin: 0 auto;
            height: 100%;
            max-height: 100%;
            min-height: 0;
        }
        h1 {
            flex-shrink: 0;
            font-size: clamp(1.25rem, 4vw, 1.5rem);
            font-weight: 700;
            margin: 0 0 0.5rem;
            letter-spacing: -0.02em;
            text-align: center;
        }
        .dashboard-scroll {
            flex: 1;
            min-height: 0;
            overflow-y: auto;
            -webkit-overflow-scrolling: touch;
        }
        .products-grid {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            grid-auto-rows: 88px;
            grid-auto-flow: dense;
            gap: 0.35rem;
            padding-bottom: 0.5rem;
        }
        .products-grid .type-block {
            display: flex;
            flex-direction: column;
            align-items: center;
            border-radius: 0.5rem;
            padding: 0.3rem 0.4rem;
            border-left: 3px solid;
            min-height: 0;
            overflow: hidden;
        }
        .products-grid .type-label {
            font-size: 0.58rem;
            font-weight: 700;
            color: #fff;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 0.2rem;
            flex-shrink: 0;
        }
        .products-grid .type-products {
            display: flex;
            flex-wrap: wrap;
            gap: 0.25rem;
            justify-content: center;
            align-content: flex-start;
            flex: 1;
            min-height: 0;
        }
        .products-grid .product-cell {
            display: inline-flex;
            flex-shrink: 0;
            cursor: pointer;
        }
        .products-grid .product-cell img {
            width: 64px;
            height: 64px;
            object-fit: cover;
            border-radius: 6px;
            background: rgba(0, 0, 0, 0.25);
            flex-shrink: 0;
        }
        .summary {
            flex-shrink: 0;
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 0.5rem;
            padding-top: 0.5rem;
        }
        .card {
            background: rgba(255, 255, 255, 0.08);
            backdrop-filter: blur(12px);
            -webkit-backdrop-filter: blur(12px);
            border: 1px solid rgba(255, 255, 255, 0.12);
            border-radius: 0.75rem;
            padding: 0.6rem 0.5rem;
            text-align: center;
            -webkit-tap-highlight-color: transparent;
        }
        .card h3 {
            margin: 0 0 0.2rem;
            font-size: 0.6rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.06em;
            color: rgba(255, 255, 255, 0.6);
        }
        .card .value {
            font-size: clamp(1.1rem, 3.5vw, 1.35rem);
            font-weight: 700;
            color: #fff;
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
        .product-modal-overlay {
            display: none;
            position: fixed;
            inset: 0;
            background: transparent;
            z-index: 100;
            align-items: center;
            justify-content: center;
            padding: 1rem;
            pointer-events: none;
        }
        .product-modal-overlay.is-open { display: flex; pointer-events: auto; }
        .product-modal-overlay.is-open .product-modal { pointer-events: auto; }
        .product-modal {
            background: rgba(26, 27, 46, 0.98);
            border: 1px solid rgba(255, 255, 255, 0.2);
            border-radius: 1rem;
            padding: 1.25rem;
            max-width: 22rem;
            width: 100%;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
        }
        .product-modal-img {
            width: 140px;
            height: 140px;
            object-fit: cover;
            border-radius: 10px;
            background: rgba(0, 0, 0, 0.3);
            display: block;
            margin: 0 auto 1rem;
        }
        .product-modal h3 {
            margin: 0 0 0.5rem;
            font-size: 1rem;
            color: #fff;
        }
        .product-modal .product-type {
            font-size: 0.75rem;
            color: rgba(255, 255, 255, 0.6);
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 0.75rem;
        }
        .product-modal-details {
            font-size: 0.85rem;
            color: rgba(255, 255, 255, 0.9);
        }
        .product-modal-details dt {
            font-weight: 600;
            color: rgba(255, 255, 255, 0.6);
            font-size: 0.7rem;
            text-transform: uppercase;
            letter-spacing: 0.04em;
            margin-top: 0.5rem;
        }
        .product-modal-details dt:first-of-type { margin-top: 0; }
        .product-modal-details dd {
            margin: 0.2rem 0 0;
        }
        .product-modal-close {
            margin-top: 1rem;
            padding: 0.4rem 0.75rem;
            font-size: 0.8rem;
            background: rgba(255, 255, 255, 0.1);
            border: 1px solid rgba(255, 255, 255, 0.2);
            border-radius: 0.5rem;
            color: #e8e8e8;
            cursor: pointer;
        }
    </style>
</head>
<body>
    <div class="page">
        <h1>SkinCare Rotation</h1>
        {% if has_data %}
        <div class="dashboard-scroll">
        {% if products_by_type %}
        {% set type_colors = ['#00fff5', '#ff00aa', '#7b2fff', '#00ff88', '#ff3366', '#00ccff', '#ffcc00', '#bf00ff', '#39ff14'] %}
        <section class="products-grid">
            {% for row in products_by_type %}
            <div class="type-block" style="background: {{ type_colors[loop.index0 % type_colors|length] }}18; border-left-color: {{ type_colors[loop.index0 % type_colors|length] }}; grid-column: span {{ row.col_span }}; grid-row: span {{ row.row_span }};">
                <div class="type-label">{{ row.type }}</div>
                <div class="type-products">
                    {% for p in row.products %}
                    <div class="product-cell" data-name="{{ p.name }}" data-type="{{ row.type }}" data-slug="{{ p.slug }}" data-open-date="{{ p.open_date }}" data-price="{{ p.price }}" data-comments="{{ p.comments }}" role="button" tabindex="0">
                        <img src="/api/product_image/{{ p.slug }}" alt="" loading="lazy" onerror="this.onerror=null; this.style.background='rgba(255,255,255,0.08)'; this.style.minWidth='64px'; this.style.minHeight='64px';">
                    </div>
                    {% endfor %}
                </div>
            </div>
            {% endfor %}
        </section>
        {% endif %}
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
        {% else %}
        <p class="empty">No data loaded. Run <code>python download_data.py</code> and ensure <code>data/sheet_data.csv</code> exists.</p>
        {% endif %}
    </div>
    <div class="product-modal-overlay" id="productModal" aria-hidden="true">
        <div class="product-modal" onclick="event.stopPropagation()">
            <img class="product-modal-img" id="productModalImg" src="" alt="">
            <h3 id="productModalName"></h3>
            <div class="product-type" id="productModalType"></div>
            <dl class="product-modal-details">
                <dt>Open Date</dt>
                <dd id="productModalOpenDate">—</dd>
                <dt>Price</dt>
                <dd id="productModalPrice">—</dd>
                <dt>Comments</dt>
                <dd id="productModalComments">—</dd>
            </dl>
            <button type="button" class="product-modal-close" id="productModalClose">Close</button>
        </div>
    </div>
    <script>
        (function() {
            var overlay = document.getElementById('productModal');
            var nameEl = document.getElementById('productModalName');
            var typeEl = document.getElementById('productModalType');
            var imgEl = document.getElementById('productModalImg');
            var openDateEl = document.getElementById('productModalOpenDate');
            var priceEl = document.getElementById('productModalPrice');
            var commentsEl = document.getElementById('productModalComments');
            function setText(el, val) { el.textContent = (val && val !== '') ? val : '—'; }
            document.querySelectorAll('.product-cell').forEach(function(cell) {
                cell.addEventListener('click', function() {
                    var slug = this.getAttribute('data-slug') || '';
                    nameEl.textContent = this.getAttribute('data-name') || '';
                    typeEl.textContent = this.getAttribute('data-type') || '';
                    imgEl.src = slug ? '/api/product_image/' + slug : '';
                    setText(openDateEl, this.getAttribute('data-open-date'));
                    setText(priceEl, this.getAttribute('data-price'));
                    setText(commentsEl, this.getAttribute('data-comments'));
                    overlay.classList.add('is-open');
                    overlay.setAttribute('aria-hidden', 'false');
                });
            });
            function closeModal() {
                overlay.classList.remove('is-open');
                overlay.setAttribute('aria-hidden', 'true');
            }
            document.getElementById('productModalClose').addEventListener('click', closeModal);
            overlay.addEventListener('click', closeModal);
        })();
    </script>
</body>
</html>
"""


if __name__ == "__main__":
    # host="0.0.0.0" so other devices on your network (e.g. phone) can connect
    app.run(debug=True, host="0.0.0.0", port=5000)
