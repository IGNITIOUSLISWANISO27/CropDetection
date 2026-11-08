"""Offline (pitch) mode: run the full dashboard on this PC with no internet.

  prepare_offline.bat   (once, while online)  saves ZMD forecasts/warnings and every field photo on this PC
  run_offline.bat       (at the pitch)        starts the dashboard at http://localhost:8501 from local files only

In offline mode the maps use a bundled copy of Leaflet (app/vendor), the fonts are bundled, field photos come
from data/photo_cache (never uploaded to GitHub) and ZMD data from the saved copies.
"""
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VENDOR = ROOT / "app" / "vendor"
PHOTO_CACHE = Path(os.environ.get("FIELDPRIORITY_PHOTO_CACHE") or ROOT / "data" / "photo_cache")


def is_offline():
    return os.environ.get("FIELDPRIORITY_OFFLINE") == "1"


# ------------------------------------------------------------------ field photos
def _photo_path(url):
    return PHOTO_CACHE / (hashlib.sha1(str(url).encode()).hexdigest() + ".jpg")


def cached_photo(url):
    p = _photo_path(url) if url else None
    try:
        return p.read_bytes() if p and p.exists() else None
    except OSError:
        return None


def save_photo(url, data):
    try:
        PHOTO_CACHE.mkdir(parents=True, exist_ok=True)
        _photo_path(url).write_bytes(data)
    except OSError:
        pass


# ------------------------------------------------------------------ maps: inline Leaflet, drop CDN files
def offline_map_html(html_doc):
    """Make a rendered folium page self-contained: bundled Leaflet inline, other CDN scripts/styles removed
    (the maps use only Leaflet), plain background where online base-map tiles would be."""
    import re
    try:
        js = (VENDOR / "leaflet.js").read_text(encoding="utf-8")
        css = (VENDOR / "leaflet.css").read_text(encoding="utf-8")
    except OSError:
        return html_doc
    h = re.sub(r'<script[^>]+src="https?://[^"]+"[^>]*>\s*</script>', "", html_doc)
    h = re.sub(r'<link[^>]+href="https?://[^"]+"[^>]*/?>', "", h)
    inject = (f"<style>{css}\n.leaflet-container{{background:#E9EEE7}} .leaflet-control-attribution{{display:none}}</style>"
              f"<script>{js}</script>")
    return h.replace("<head>", "<head>" + inject, 1) if "<head>" in h else inject + h


# ------------------------------------------------------------------ fonts
FONTS = [("Inter", 400, "inter-latin-400-normal"), ("Inter", 500, "inter-latin-500-normal"),
         ("Inter", 600, "inter-latin-600-normal"), ("Plus Jakarta Sans", 600, "plus-jakarta-sans-latin-600-normal"),
         ("Plus Jakarta Sans", 700, "plus-jakarta-sans-latin-700-normal"),
         ("Plus Jakarta Sans", 800, "plus-jakarta-sans-latin-800-normal")]


def font_faces_css():
    import base64
    out = []
    for fam, w, f in FONTS:
        p = VENDOR / "fonts" / f"{f}.woff2"
        if p.exists():
            b = base64.b64encode(p.read_bytes()).decode("ascii")
            out.append(f"@font-face{{font-family:'{fam}';font-style:normal;font-weight:{w};font-display:swap;"
                       f"src:url(data:font/woff2;base64,{b}) format('woff2')}}")
    return "\n".join(out)


# ------------------------------------------------------------------ prepare (run while online)
def _attachments(v):
    a = v
    if isinstance(a, str):
        try:
            a = json.loads(a)
        except ValueError:
            return []
    return [x for x in a if isinstance(x, dict) and not x.get("is_deleted")] if isinstance(a, list) else []


def prepare():
    import pandas as pd
    import urllib.request
    from .config import available_pilots
    from .ingest.kobo import load_dotenv
    print("1/2  ZMD forecasts and warnings ...")
    try:
        from . import zmd
        zmd.main()
    except SystemExit:
        pass
    except Exception as e:
        print(f"     could not refresh ZMD ({type(e).__name__}); the last saved copies will be used")
    print("2/2  Field photos from KoboToolbox ...")
    load_dotenv()
    tok = os.environ.get("KOBO_TOKEN")
    if not tok:
        print("     KOBO_TOKEN missing in .env: photos cannot be downloaded")
        return
    got = have = failed = 0
    for p in available_pilots():
        f = ROOT / "outputs" / p / "verification_records.csv"
        if not f.exists():
            continue
        df = pd.read_csv(f)
        for raw in df.get("_attachments", pd.Series(dtype=object)).dropna():
            for a in _attachments(raw):
                for url in {a.get("download_medium_url"), a.get("download_url")} - {None, ""}:
                    if cached_photo(url):
                        have += 1
                        continue
                    try:
                        req = urllib.request.Request(url, headers={"Authorization": f"Token {tok}",
                                                                   "User-Agent": "FieldPriority"})
                        with urllib.request.urlopen(req, timeout=30) as r:
                            save_photo(url, r.read())
                        got += 1
                    except Exception:
                        failed += 1
    print(f"     {got} downloaded, {have} already saved, {failed} failed  ->  {PHOTO_CACHE}")
    print("\nReady. At the pitch, double-click run_offline.bat (no internet needed).")


if __name__ == "__main__":
    prepare()
