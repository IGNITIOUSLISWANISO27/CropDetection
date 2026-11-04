"""Download REAL past-season data for the pilot fields from free public sources (no accounts, no keys)
and write it in the file format the pipeline reads, so past seasons can be backtested.

Sources (all real observations / reanalysis; nothing is simulated):
  NDVI           Sentinel-2 L2A, Element 84 Earth Search STAC (AWS open data), 10 m, clouds masked with SCL,
                 monthly median per pixel, read only over the field polygons
  Rainfall       CHIRPS v2.0 monthly (Africa), 0.05 deg; anomaly = month total minus the mean of the same
                 month over the BASELINE years (default: the 10 years before the season)
  Temperature    ERA5-Land via the Open-Meteo historical archive, 0.1 deg cells, monthly mean of daily means
  Soil moisture  ERA5-Land via Open-Meteo, 0-7 cm volumetric water, 0.1 deg cells, monthly mean

Run (on a computer with internet):
  python -m fieldpriority.fetch_data --year 2024 --months 1 2 3            -> data/backtest_2024/
  python -m fieldpriority.fetch_data --check                               -> tests the connections only
Then: python -m fieldpriority.backtest

Output names match the pipeline: January_NDVI_2024.tif, Rainfall_Jan2024.tif, Rainfall_Anomaly_Jan2024.tif,
SoilMoisture_Jan2024.tif, Temperature_Jan2024.tif, plus sources_<year>.json listing every scene and file used.
"""
import argparse
import datetime as dt
import gzip
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np

STAC_URL = os.environ.get("FP_STAC_URL", "https://earth-search.aws.element84.com/v1")
# CHIRPS v3.0 (current; v2.0 files were retired by the Climate Hazards Center in 2026). Global monthly GeoTIFFs,
# read over HTTP for the small window around the fields only, so the ~57 MB global files are never downloaded.
CHIRPS3_URL = os.environ.get("FP_CHIRPS3_URL", "https://data.chc.ucsb.edu/products/CHIRPS/v3.0/monthly/global/tifs")
CHIRPS_URL = os.environ.get("FP_CHIRPS_URL",
                            "https://data.chc.ucsb.edu/products/CHIRPS-2.0/africa_monthly/tifs")
METEO_URL = os.environ.get("FP_METEO_URL", "https://archive-api.open-meteo.com/v1/archive")
MON = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
FULL = ["", "January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
        "November", "December"]
SCL_OK = {4, 5, 6, 7}           # vegetation, bare soil, water, unclassified (clouds, shadow, snow removed)
UA = {"User-Agent": "FieldPriority/0.2 (crop early-warning pilot, Copperbelt University)"}


# ------------------------------------------------------------------ http helpers
def _http(url, data=None, tries=4):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=data, headers={**UA, **({"Content-Type": "application/json"}
                                                                           if data else {})})
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code in (404, 400):
                raise RuntimeError(f"{e.code} for {url.split('?')[0]}") from None
            err = e
        except urllib.error.URLError as e:
            err = e
        time.sleep(2 * (i + 1))
    raise RuntimeError(f"could not download {url.split('?')[0]} ({err})")


def _json(url, body=None):
    return json.loads(_http(url, json.dumps(body).encode() if body is not None else None))


def month_range(y, m):
    start = dt.date(y, m, 1)
    end = dt.date(y + (m == 12), m % 12 + 1, 1) - dt.timedelta(days=1)
    return start, end


# ------------------------------------------------------------------ Sentinel-2 NDVI
def _asset(item, *keys):
    for k in keys:
        if k in item["assets"]:
            return item["assets"][k]
    raise KeyError(f"none of {keys} in scene {item.get('id')}")


def _scale_offset(item, asset):
    """Reflectance = DN * scale + offset. Newer scenes (processing baseline >= 04.00) carry an offset of
    -0.1 (DN -1000); ignoring it would bias NDVI, so it is read from the metadata."""
    rb = (asset.get("raster:bands") or [{}])[0]
    if "scale" in rb or "offset" in rb:
        return float(rb.get("scale", 1e-4)), float(rb.get("offset", 0.0))
    pb = str(item["properties"].get("s2:processing_baseline", "00.00"))
    return 1e-4, (-0.1 if pb >= "04.00" else 0.0)


def stac_search(bbox, start, end, max_cloud):
    body = {"collections": ["sentinel-2-l2a"], "bbox": bbox, "limit": 200,
            "datetime": f"{start}T00:00:00Z/{end}T23:59:59Z", "query": {"eo:cloud_cover": {"lt": max_cloud}}}
    items, url = [], f"{STAC_URL}/search"
    while url:
        page = _json(url, body)
        items += page.get("features", [])
        nxt = [l for l in page.get("links", []) if l.get("rel") == "next"]
        url, body = (nxt[0]["href"], nxt[0].get("body", body)) if nxt else (None, None)
    return items


def ndvi_month(fields_utm, grid, y, m, max_cloud, log):
    """Monthly median NDVI on the target 10 m grid, filled only inside each field's window."""
    import rasterio
    from rasterio.vrt import WarpedVRT
    from rasterio.enums import Resampling
    from rasterio.transform import from_origin
    x0, y1, W, H, crs = grid["x0"], grid["y1"], grid["W"], grid["H"], grid["crs"]
    out = np.full((H, W), np.nan, dtype="float32")
    start, end = month_range(y, m)
    used = []
    env = dict(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_HTTP_MAX_RETRY="4", GDAL_HTTP_RETRY_DELAY="2",
               CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif,.TIF,.tiff")
    with rasterio.Env(**env):
        for fid, (geom_ll, geom_utm) in fields_utm.items():
            bx0, by0, bx1, by1 = geom_utm.bounds
            cx0 = int(np.floor((bx0 - x0) / 10)) - 2
            cx1 = int(np.ceil((bx1 - x0) / 10)) + 2
            ry0 = int(np.floor((y1 - by1) / 10)) - 2
            ry1 = int(np.ceil((y1 - by0) / 10)) + 2
            fx0, fx1, fy1, fy0 = x0 + cx0 * 10, x0 + cx1 * 10, y1 - ry0 * 10, y1 - ry1 * 10
            h, w = ry1 - ry0, cx1 - cx0
            items = stac_search(list(geom_ll.bounds), start, end, max_cloud)
            stack = []
            for it in items:
                try:
                    red_a, nir_a, scl_a = _asset(it, "red", "B04"), _asset(it, "nir", "B08"), _asset(it, "scl", "SCL")
                    bands = []
                    for a in (red_a, nir_a, scl_a):
                        # warp straight onto the field's window of the 10 m target grid (SCL 20 m -> nearest)
                        with rasterio.open(a["href"]) as src, \
                                WarpedVRT(src, crs=crs, transform=from_origin(fx0, fy1, 10, 10), width=w, height=h,
                                          resampling=Resampling.nearest, nodata=0) as vrt:
                            bands.append(vrt.read(1).astype("float32"))
                    red, nir, scl = bands
                    s_r, o_r = _scale_offset(it, red_a)
                    s_n, o_n = _scale_offset(it, nir_a)
                    red, nir = red * s_r + o_r, nir * s_n + o_n
                    ok = np.isin(scl, list(SCL_OK)) & (red > 0) & (nir > 0)
                    with np.errstate(invalid="ignore", divide="ignore"):
                        nd = np.where(ok, (nir - red) / (nir + red), np.nan)
                    if np.isfinite(nd).any():
                        stack.append(nd)
                        used.append({"field": fid, "scene": it["id"], "date": it["properties"].get("datetime"),
                                     "cloud_cover": it["properties"].get("eo:cloud_cover")})
                except Exception as e:                       # one bad scene must not stop the month
                    log(f"    skipped scene {it.get('id')}: {e}")
            if stack:
                import warnings
                with warnings.catch_warnings():          # pixels cloudy in every scene stay empty (expected)
                    warnings.simplefilter("ignore", RuntimeWarning)
                    med = np.nanmedian(np.stack(stack), axis=0)
                tgt = out[ry0:ry1, cx0:cx1]
                np.copyto(tgt, med.astype("float32"), where=np.isfinite(med))
            log(f"    {fid}: {len(stack)} usable scenes")
    return out, used


# ------------------------------------------------------------------ CHIRPS
CHIRPS_MODE = {"mode": "download"}      # download: keep whole files in the cache; stream: read the window only


def _download_file(url, dest):
    """Stream a large file to disk (via a .part file, so an interrupted download is never used)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=300) as r, open(part, "wb") as f:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
    part.replace(dest)


def chirps3_month(y, m, bounds, cache=None):
    """CHIRPS v3.0 monthly total (mm) for the window around bounds. In 'download' mode the whole global file
    (~57 MB) is saved in the cache once and read locally; in 'stream' mode (or if saving fails, e.g. a full
    disk) only the window is read over HTTP."""
    import rasterio
    from rasterio.windows import from_bounds
    env = dict(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_HTTP_MAX_RETRY="4", GDAL_HTTP_RETRY_DELAY="2",
               CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif")
    url = f"{CHIRPS3_URL}/chirps-v3.0.{y}.{m:02d}.tif"
    if cache is not None and CHIRPS_MODE["mode"] == "download":
        local = Path(cache) / f"chirps-v3.0.{y}.{m:02d}.tif"
        try:
            if not local.exists():
                print(f"    downloading {local.name} (about 57 MB)")
                _download_file(url, local)
            url = str(local)
        except OSError as e:                          # disk full or connection cut: fall back to streaming
            print(f"    could not save {local.name} ({e}); reading only the field's window instead")
    last = None
    for i in range(3):
        try:
            with rasterio.Env(**env), rasterio.open(url) as src:
                win = from_bounds(*bounds, transform=src.transform).round_offsets().round_lengths()
                arr = src.read(1, window=win).astype("float32")
                if src.nodata is not None:
                    arr[arr == src.nodata] = np.nan
                arr[arr < 0] = np.nan
                return arr, src.window_transform(win), src.crs
        except Exception as e:                          # network hiccup: retry, then report clearly
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"could not read {url} ({last})")


def chirps_month(y, m, bounds, cache, version="3"):
    """Monthly CHIRPS total (mm) clipped to bounds, as (array, transform, crs)."""
    if version == "3":
        return chirps3_month(y, m, bounds, cache)
    import rasterio
    from rasterio.io import MemoryFile
    from rasterio.windows import from_bounds
    name = f"chirps-v2.0.{y}.{m:02d}.tif.gz"
    f = Path(cache) / name
    if not f.exists():
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(_http(f"{CHIRPS_URL}/{name}"))
    with MemoryFile(gzip.decompress(f.read_bytes())) as mem, mem.open() as src:
        win = from_bounds(*bounds, transform=src.transform).round_offsets().round_lengths()
        arr = src.read(1, window=win).astype("float32")
        arr[(arr < 0) | (arr == src.nodata)] = np.nan
        return arr, src.window_transform(win), src.crs


# ------------------------------------------------------------------ ERA5-Land via Open-Meteo
def era5_cells(bounds, res=0.1):
    """0.1 deg cells covering the bounds, as (row, col, lat, lon) of the cell centres."""
    minx, miny, maxx, maxy = bounds
    gx0, gy1 = np.floor(minx / res) * res, np.ceil(maxy / res) * res
    W, H = int(np.ceil((maxx - gx0) / res)), int(np.ceil((gy1 - miny) / res))
    cells = [(r, c, round(gy1 - (r + 0.5) * res, 4), round(gx0 + (c + 0.5) * res, 4)) for r in range(H) for c in range(W)]
    return cells, (gx0, gy1, W, H, res)


def era5_point(lat, lon, start, end):
    q = (f"{METEO_URL}?latitude={lat}&longitude={lon}&start_date={start}&end_date={end}"
         "&daily=temperature_2m_mean&hourly=soil_moisture_0_to_7cm&timezone=Africa%2FLusaka&models=era5_land")
    d = _json(q)
    days = d["daily"]["time"]
    t = np.array([np.nan if v is None else v for v in d["daily"]["temperature_2m_mean"]], dtype=float)
    hours = d["hourly"]["time"]
    sm = np.array([np.nan if v is None else v for v in d["hourly"]["soil_moisture_0_to_7cm"]], dtype=float)
    return days, t, hours, sm


# ------------------------------------------------------------------ writing
def write_tif(path, arr, transform, crs):
    import rasterio
    with rasterio.open(path, "w", driver="GTiff", height=arr.shape[0], width=arr.shape[1], count=1,
                       dtype="float32", crs=crs, transform=transform, nodata=np.nan, compress="deflate",
                       tiled=arr.shape[0] >= 256 and arr.shape[1] >= 256) as dst:
        dst.write(arr.astype("float32"), 1)


def fetch(year, months, out_dir, shp, baseline, max_cloud=60, skip=(), log=print):
    import geopandas as gpd
    import rasterio
    from rasterio.transform import from_origin
    from shapely.geometry import box
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    cache = out / "_download_cache"
    g = gpd.read_file(shp).to_crs(4326)
    g = g[~g.geometry.is_empty]
    utm = g.estimate_utm_crs()
    gu = g.to_crs(utm)
    fields = {f: (a, b) for f, a, b in zip(g["Field_ID"], g.geometry, gu.geometry)}
    minx, miny, maxx, maxy = g.total_bounds
    buf = 0.15
    ll_bounds = (minx - buf, miny - buf, maxx + buf, maxy + buf)
    ux0, uy0, ux1, uy1 = gu.total_bounds
    x0, y1 = np.floor((ux0 - 100) / 10) * 10, np.ceil((uy1 + 100) / 10) * 10
    grid = {"x0": x0, "y1": y1, "W": int(np.ceil((ux1 + 100 - x0) / 10)), "H": int(np.ceil((y1 - uy0 + 100) / 10)),
            "crs": utm}
    prov = {"season_year": year, "months": months, "created": dt.datetime.now().isoformat(timespec="seconds"),
            "fields": list(fields), "baseline_years": baseline,
            "sources": {"ndvi": f"Sentinel-2 L2A via {STAC_URL} (collection sentinel-2-l2a), SCL cloud mask, "
                                f"scenes with cloud cover < {max_cloud}%, monthly per-pixel median",
                        "rainfall": "CHIRPS monthly (version chosen at run time, see rainfall_version)",
                        "temperature_soil_moisture": f"ERA5-Land via Open-Meteo archive {METEO_URL}"},
            "ndvi_scenes": {}, "notes": []}

    # --- NDVI
    if "ndvi" not in skip:
        for m in months:
            log(f"NDVI {MON[m]} {year}: searching Sentinel-2 scenes")
            arr, used = ndvi_month(fields, grid, year, m, max_cloud, log)
            write_tif(out / f"{FULL[m]}_NDVI_{year}.tif", arr, from_origin(grid["x0"], grid["y1"], 10, 10), utm)
            prov["ndvi_scenes"][f"{year}-{m:02d}"] = used
            if not used:
                prov["notes"].append(f"No usable Sentinel-2 scene for {MON[m]} {year}")

    # --- CHIRPS rainfall and anomaly
    if "rain" not in skip:
        # one CHIRPS version for the season AND its baseline (never mixed): v3.0, else the old v2.0 Africa files
        try:
            chirps3_month(year, months[0], ll_bounds, cache)
            ver = "3"
        except RuntimeError as e:
            log(f"CHIRPS v3.0 not readable ({e}); trying the old v2.0 files")
            ver = "2"
        prov["rainfall_version"] = ("CHIRPS v3.0 global monthly, " + CHIRPS3_URL) if ver == "3" else \
            ("CHIRPS v2.0 Africa monthly, " + CHIRPS_URL)
        for m in months:
            log(f"Rainfall {MON[m]} {year} + baseline {baseline[0]}-{baseline[-1]}")
            tot, tr, crs = chirps_month(year, m, ll_bounds, cache, ver)
            base = np.nanmean(np.stack([chirps_month(b, m, ll_bounds, cache, ver)[0] for b in baseline]), axis=0)
            write_tif(out / f"Rainfall_{MON[m]}{year}.tif", tot, tr, crs)
            write_tif(out / f"Rainfall_Anomaly_{MON[m]}{year}.tif", tot - base, tr, crs)

    # --- ERA5-Land temperature and soil moisture (only the 0.1 deg cells that touch a field)
    if "era5" not in skip:
        cells, (gx0, gy1, W, H, res) = era5_cells(g.total_bounds)
        need = [c for c in cells if any(box(c[3] - res / 2, c[2] - res / 2, c[3] + res / 2, c[2] + res / 2)
                                        .intersects(geom) for geom, _ in fields.values())]
        start, end = month_range(year, months[0])[0], month_range(year, months[-1])[1]
        t_arr = {m: np.full((H, W), np.nan, "float32") for m in months}
        s_arr = {m: np.full((H, W), np.nan, "float32") for m in months}
        log(f"Temperature and soil moisture: {len(need)} ERA5-Land cells")
        for r, c, lat, lon in need:
            days, t, hours, sm = era5_point(lat, lon, start, end)
            for m in months:
                key = f"{year}-{m:02d}"
                t_arr[m][r, c] = np.nanmean([v for d, v in zip(days, t) if d.startswith(key)])
                s_arr[m][r, c] = np.nanmean([v for h, v in zip(hours, sm) if h.startswith(key)])
        tr = from_origin(gx0, gy1, res, res)
        for m in months:
            write_tif(out / f"Temperature_{MON[m]}{year}.tif", t_arr[m], tr, "EPSG:4326")
            write_tif(out / f"SoilMoisture_{MON[m]}{year}.tif", s_arr[m], tr, "EPSG:4326")

    # keep the record of earlier downloads for this season (e.g. Jan-Mar, then April added later)
    pf = out / f"sources_{year}.json"
    if pf.exists():
        try:
            old = json.loads(pf.read_text())
            prov["months"] = sorted(set(old.get("months", [])) | set(months))
            prov["ndvi_scenes"] = {**old.get("ndvi_scenes", {}), **prov["ndvi_scenes"]}
            prov["notes"] = old.get("notes", []) + prov["notes"]
            prov["downloads"] = old.get("downloads", [{"created": old.get("created"), "months": old.get("months")}])
        except (ValueError, KeyError):
            pass
    prov.setdefault("downloads", []).append({"created": prov["created"], "months": months})
    pf.write_text(json.dumps(prov, indent=1, default=str))
    log(f"Done. Files in {out}. Provenance: sources_{year}.json")
    return prov


def check():
    ok = True
    for name, fn in [("Sentinel-2 (Earth Search)", lambda: _json(f"{STAC_URL}/collections/sentinel-2-l2a")["id"]),
                     ("CHIRPS v3.0", lambda: chirps3_month(2024, 1, (26.3, -12.3, 26.6, -12.0))[0].size > 0),
                     ("Open-Meteo ERA5-Land", lambda: _json(f"{METEO_URL}?latitude=-15.3&longitude=28.7&start_date="
                                                            "2024-01-01&end_date=2024-01-02&daily=temperature_2m_mean")
                      ["daily"]["time"][0])]:
        try:
            fn()
            print(f"OK      {name}")
        except Exception as e:
            ok = False
            print(f"FAILED  {name}: {e}")
    return ok


def main():
    from .config import load_config
    ap = argparse.ArgumentParser(description="Download real past-season data for the pilot fields")
    ap.add_argument("--year", type=int, default=2024)
    ap.add_argument("--months", type=int, nargs="+", default=[1, 2, 3])
    ap.add_argument("--out-dir", default=None, help="default: data/backtest_<year>")
    ap.add_argument("--baseline", type=int, nargs=2, default=None, metavar=("FIRST", "LAST"),
                    help="rainfall baseline years (default: the 10 years before --year)")
    ap.add_argument("--max-cloud", type=float, default=60)
    ap.add_argument("--skip", nargs="*", default=[], choices=["ndvi", "rain", "era5"])
    ap.add_argument("--chirps-mode", default="download", choices=["download", "stream"],
                    help="download (default): keep the whole CHIRPS files (~57 MB each) in _download_cache; "
                         "stream: read only the area around the fields")
    ap.add_argument("--check", action="store_true", help="only test the connections")
    a = ap.parse_args()
    if a.check:
        raise SystemExit(0 if check() else 1)
    CHIRPS_MODE["mode"] = a.chirps_mode
    cfg = load_config()
    root = Path(cfg["_root"])
    b0, b1 = a.baseline or (a.year - 10, a.year - 1)
    fetch(a.year, a.months, a.out_dir or root / "data" / f"backtest_{a.year}",
          root / cfg["paths"]["data_dir"] / cfg["paths"]["fields_shapefile"], list(range(b0, b1 + 1)),
          a.max_cloud, set(a.skip))


if __name__ == "__main__":
    main()
