"""
Product image cache: fetch images by product name, standardize, and serve from disk.
If a file already exists for a slug, we use it (allows human to substitute).
"""
import io
import json
import re
from pathlib import Path

import requests
from PIL import Image

# Cache under data/product_images/; manifest maps slug -> product name for fetch
BASE_DIR = Path(__file__).resolve().parent
IMAGE_CACHE_DIR = BASE_DIR / "data" / "product_images"
MANIFEST_FILE = IMAGE_CACHE_DIR / "manifest.json"
IMAGE_SIZE = 256  # standard output size (square)
REQUEST_TIMEOUT = 15
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; rv:109.0) Gecko/20100101 Firefox/115.0",
}


def slugify(name: str) -> str:
    """Turn product name into a safe filename (lowercase, alphanumeric + dashes)."""
    if not name or not str(name).strip():
        return ""
    s = str(name).strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")
    return s or "unknown"


def _ensure_cache_dir() -> None:
    IMAGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def ensure_manifest(product_names: list[str]) -> None:
    """Write manifest.json mapping slug -> product name so we can resolve slug to name on fetch."""
    _ensure_cache_dir()
    names = [str(n).strip() for n in product_names if n and str(n).strip()]
    manifest = {}
    for n in names:
        s = slugify(n)
        if s:
            manifest[s] = n
    with open(MANIFEST_FILE, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)


def load_manifest() -> dict[str, str]:
    """Read manifest slug -> product name."""
    if not MANIFEST_FILE.exists():
        return {}
    try:
        with open(MANIFEST_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def get_cached_image_path(slug: str) -> Path | None:
    """Return path to cached image if it exists (.jpg or .png). Human can drop a file here to override."""
    if not slug:
        return None
    _ensure_cache_dir()
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        p = IMAGE_CACHE_DIR / f"{slug}{ext}"
        if p.exists():
            return p
    return None


def _search_image_urls_playwright(
    query: str,
    max_urls: int = 8,
    page=None,
) -> list[str]:
    """
    Return image URLs from Bing Image Search using Playwright (real browser).
    If page is provided, use it and do not close; else create a new browser/page and close after.
    """
    import urllib.parse

    own_browser = False
    playwright = None
    browser = None
    try:
        if page is None:
            from playwright.sync_api import sync_playwright

            playwright = sync_playwright().start()
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            own_browser = True

        encoded = urllib.parse.quote_plus(query)
        url = f"https://www.bing.com/images/search?q={encoded}&first=1"
        page.goto(url, wait_until="domcontentloaded", timeout=20000)
        page.wait_for_timeout(2000)  # let images load

        urls = []
        # Bing stores image URL in a.iusc element's "m" attribute (JSON with murl)
        loc = page.locator("a.iusc")
        n = min(loc.count(), max_urls * 2)  # check extra in case some fail
        for i in range(n):
            try:
                el = loc.nth(i)
                m_attr = el.get_attribute("m")
                if not m_attr:
                    continue
                data = json.loads(m_attr)
                murl = data.get("murl")
                if murl and murl.startswith("http") and murl not in urls:
                    urls.append(murl)
                    if len(urls) >= max_urls:
                        break
            except (json.JSONDecodeError, TypeError, KeyError):
                continue

        return urls
    except Exception:
        return []
    finally:
        if own_browser and browser:
            try:
                browser.close()
            except Exception:
                pass
            if playwright:
                try:
                    playwright.stop()
                except Exception:
                    pass


def _search_image_urls(query: str, max_urls: int = 8, page=None) -> list[str]:
    """Return image URLs using Playwright (Bing). Pass page to reuse browser across calls."""
    return _search_image_urls_playwright(query, max_urls=max_urls, page=page)


def _download_image(url: str) -> bytes | None:
    """Download image bytes from URL. Returns None if response looks like HTML/error."""
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT, headers=REQUEST_HEADERS)
        resp.raise_for_status()
        raw = resp.content
        if not raw or len(raw) < 200:
            return None
        # Skip HTML error pages
        start = raw[:50].lower()
        if b"<html" in start or b"<!doctype" in start or b"<script" in start:
            return None
        return raw
    except Exception:
        return None


def _process_image(image_bytes: bytes) -> Image.Image | None:
    """Open image, center-crop to square, resize to IMAGE_SIZE. Returns PIL Image or None."""
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception:
        return None
    w, h = img.size
    if w <= 0 or h <= 0:
        return None
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    img = img.crop((left, top, left + side, top + side))
    img = img.resize((IMAGE_SIZE, IMAGE_SIZE), Image.Resampling.LANCZOS)
    return img


def fetch_and_process(
    product_name: str,
    verbose: bool = False,
    page=None,
) -> Path | None:
    """
    Search for an image for product_name, try each result until one works, then save.
    Returns path to saved image or None on failure.
    If verbose=True, prints why each attempt failed (for debugging).
    If page= is provided (Playwright page), reuse it for search (faster when batch-running).
    """
    slug = slugify(product_name)
    if not slug:
        if verbose:
            print("      (no slug)")
        return None

    urls = _search_image_urls(product_name, page=page)
    # Fallback 1: try shorter query (first few words)
    if not urls and " " in product_name:
        short = " ".join(product_name.split()[:3]).strip()
        if short and short != product_name:
            urls = _search_image_urls(short, page=page)
            if verbose and urls:
                print(f"      (used shorter query: {short!r})")
    # Fallback 2: try with "skincare" for product-style images
    if not urls:
        urls = _search_image_urls(f"{product_name} skincare", page=page)
        if verbose and urls:
            print(f"      (used query: ... skincare)")
    if not urls:
        if verbose:
            print("      (no search results)")
        return None

    if verbose:
        print(f"      (trying {len(urls)} URLs...)")

    for i, url in enumerate(urls):
        raw = _download_image(url)
        if not raw:
            if verbose:
                print(f"      URL {i+1}: download failed")
            continue
        img = _process_image(raw)
        if not img:
            if verbose:
                print(f"      URL {i+1}: not a valid image ({len(raw)} bytes)")
            continue
        _ensure_cache_dir()
        out_path = IMAGE_CACHE_DIR / f"{slug}.jpg"
        try:
            img.save(out_path, "JPEG", quality=88)
            if verbose:
                print(f"      URL {i+1}: saved")
            return out_path
        except Exception as e:
            if verbose:
                print(f"      URL {i+1}: save failed ({e})")
            continue
    if verbose:
        print("      (all URLs failed)")
    return None


def get_or_create_image_path(slug: str, product_name: str | None = None) -> Path | None:
    """
    Return path to image for this slug. Use cache if present; else resolve name from manifest,
    fetch and process, then return path. product_name can be passed if manifest not yet written.
    """
    path = get_cached_image_path(slug)
    if path is not None:
        return path
    name = product_name or load_manifest().get(slug)
    if not name:
        return None
    return fetch_and_process(name)
