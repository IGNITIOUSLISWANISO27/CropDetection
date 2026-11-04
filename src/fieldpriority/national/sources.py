"""Data readers for the district layers.

CHIRPS v3.0 monthly rainfall: only the Zambia window of each global file is read (over HTTP if it is not on
disk), and saved as a small Zambia-only GeoTIFF in data/national/chirps (about 100 KB per month), so a month is
never downloaded twice. Whole global files already in a pilot's _download_cache are reused.

NASA POWER monthly point data (temperature, solar radiation) at each district's central point. Complete years
come from the monthly endpoint; months of the current year from the daily endpoint (averaged). Values are kept
in data/national/power_monthly.csv and only missing months are requested.
"""
import datetime as dt
import json
import time
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

from ..fetch_data import CHIRPS3_URL, UA

ZAMBIA_BOUNDS = (21.9, -18.2, 33.8, -8.1)          # lon/lat window read from the global CHIRPS files
POWER_URL = "https://power.larc.nasa.gov/api/temporal"
POWER_PARAMS = "T2M,T2M_MAX,ALLSKY_SFC_SW_DWN"


# ------------------------------------------------------------------ CHIRPS
def chirps_zambia(y, m, data_dir, global_caches=(), log=print):
    """Monthly CHIRPS v3.0 rainfall (mm) for Zambia as (array, transform, crs). Raises if not published yet."""
    import rasterio
    from rasterio.windows import from_bounds
    out = Path(data_dir) / "chirps" / f"chirps-v3.0.{y}.{m:02d}_zmb.tif"
    if out.exists():
        with rasterio.open(out) as s:
            a = s.read(1).astype("float32")
            return a, s.transform, s.crs
    name = f"chirps-v3.0.{y}.{m:02d}.tif"
    src_path = next((str(Path(c) / name) for c in global_caches if (Path(c) / name).exists()), None)
    how = "from cache"
    try:
        if src_path:
            a, tr, crs = _read_window(src_path)
        else:
            try:                                    # 1) read only the Zambia window over the internet
                a, tr, crs = _read_window(f"/vsicurl/{CHIRPS3_URL}/{name}", tries=2)
                how = "read over the internet"
            except RuntimeError:                    # 2) download the global file, cut Zambia out, delete it
                from ..fetch_data import _download_file
                tmp = Path(data_dir) / "chirps" / ("_tmp_" + name)
                try:
                    _download_file(f"{CHIRPS3_URL}/{name}", tmp)
                    a, tr, crs = _read_window(str(tmp))
                    how = "downloaded, Zambia cut out"
                finally:
                    tmp.unlink(missing_ok=True)
    except Exception as e:                          # not published yet, or no connection
        raise RuntimeError(f"CHIRPS {y}-{m:02d} not readable ({e})")
    out.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(out, "w", driver="GTiff", height=a.shape[0], width=a.shape[1], count=1, dtype="float32",
                       crs=crs, transform=tr, nodata=np.nan, compress="deflate") as d:
        d.write(a, 1)
    log(f"    CHIRPS {y}-{m:02d}: saved Zambia window ({how})")
    return a, tr, crs


def _read_window(url, tries=1):
    import rasterio
    from rasterio.windows import from_bounds
    env = dict(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_HTTP_MAX_RETRY="3", GDAL_HTTP_RETRY_DELAY="2",
               GDAL_HTTP_TIMEOUT="90", CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif", GDAL_HTTP_USERAGENT=UA["User-Agent"])
    last = None
    for i in range(tries):
        try:
            with rasterio.Env(**env), rasterio.open(url) as s:
                win = from_bounds(*ZAMBIA_BOUNDS, transform=s.transform).round_offsets().round_lengths()
                a = s.read(1, window=win).astype("float32")
                if s.nodata is not None:
                    a[a == s.nodata] = np.nan
                a[a < 0] = np.nan
                return a, s.window_transform(win), s.crs
        except Exception as e:
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(str(last))


def district_index(districts, shape, transform):
    """Raster of district numbers (0 = outside) on the CHIRPS grid."""
    from rasterio.features import rasterize
    return rasterize(((g, i + 1) for i, g in enumerate(districts.geometry)), out_shape=shape, transform=transform,
                     fill=0, dtype="int32", all_touched=False)


def zonal_means(arr, idx, n):
    ok = np.isfinite(arr) & (idx > 0)
    s = np.bincount(idx[ok], weights=arr[ok], minlength=n + 1)
    c = np.bincount(idx[ok], minlength=n + 1)
    with np.errstate(invalid="ignore", divide="ignore"):
        return (s / c)[1:], c[1:]


# ------------------------------------------------------------------ NASA POWER
def _get_json(url, tries=4):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            last = e
            time.sleep(3 * (i + 1))
    raise RuntimeError(f"{url[:90]}... failed ({last})")


def power_monthly_years(lat, lon, y0, y1):
    d = _get_json(f"{POWER_URL}/monthly/point?parameters={POWER_PARAMS}&community=AG&longitude={lon}"
                  f"&latitude={lat}&start={y0}&end={y1}&format=JSON")
    p = d["properties"]["parameter"]
    rows = []
    for k in p["T2M"]:
        if k[4:] == "13":                         # annual value
            continue
        rows.append({"ym": int(k), "t2m": p["T2M"][k], "t2m_max": p["T2M_MAX"][k],
                     "allsky_mj": p["ALLSKY_SFC_SW_DWN"][k]})
    return rows


def power_daily_months(lat, lon, months):
    """Monthly means from the daily endpoint, for months of the current year (monthly data not out yet)."""
    if not months:
        return []
    (y0, m0), (y1, m1) = min(months), max(months)
    end = min(dt.date(y1 + (m1 == 12), m1 % 12 + 1, 1) - dt.timedelta(days=1), dt.date.today())
    d = _get_json(f"{POWER_URL}/daily/point?parameters={POWER_PARAMS}&community=AG&longitude={lon}&latitude={lat}"
                  f"&start={y0}{m0:02d}01&end={end:%Y%m%d}&format=JSON")
    p = d["properties"]["parameter"]
    df = pd.DataFrame({k: pd.Series(v) for k, v in p.items()}).replace(-999, np.nan)
    df["ym"] = [int(k[:6]) for k in df.index]
    out = []
    for ym, g in df.groupby("ym"):
        if (ym // 100, ym % 100) not in months:
            continue
        days = pd.Period(f"{ym // 100}-{ym % 100:02d}", "M").days_in_month
        ok = g["T2M"].notna().sum() >= days - 3          # nearly every day present
        out.append({"ym": ym, "t2m": g["T2M"].mean() if ok else np.nan,
                    "t2m_max": g["T2M_MAX"].mean() if ok else np.nan,
                    "allsky_mj": g["ALLSKY_SFC_SW_DWN"].mean() if g["ALLSKY_SFC_SW_DWN"].notna().sum() >= days - 3 else np.nan})
    return out


def power_table(districts, needed, table_path, log=print, today=None):
    """Make sure power_monthly.csv has every (district, month) in `needed`; fetch only what is missing."""
    today = today or dt.date.today()
    p = Path(table_path)
    t = pd.read_csv(p) if p.exists() else pd.DataFrame(columns=["district_id", "ym", "t2m", "t2m_max", "allsky_mj"])
    have = set(zip(t["district_id"], t["ym"].astype(int)))
    new = []
    fails = 0
    for r in districts.itertuples():
        miss = sorted({(y, m) for y, m in needed if (r.district_id, y * 100 + m) not in have})
        if not miss:
            continue
        past = [x for x in miss if x[0] < today.year]
        cur = [x for x in miss if x[0] >= today.year]
        try:
            rows = power_monthly_years(r.lat, r.lon, min(past)[0], max(past)[0]) if past else []
            rows = [x for x in rows if (x["ym"] // 100, x["ym"] % 100) in set(past)]
            rows += power_daily_months(r.lat, r.lon, cur)
        except RuntimeError as e:
            fails += 1
            log(f"    NASA POWER {r.district}: {e}")
            if fails >= 5:
                log("    NASA POWER not reachable; temperature and solar keep their previous values")
                break
            continue
        new += [{"district_id": r.district_id, **x} for x in rows]
    if new:
        t = pd.concat([t, pd.DataFrame(new)], ignore_index=True).drop_duplicates(["district_id", "ym"], keep="last")
        p.parent.mkdir(parents=True, exist_ok=True)
        t.sort_values(["district_id", "ym"]).to_csv(p, index=False)
        log(f"    NASA POWER: {len(new)} district-months added")
    t = t.replace(-999, np.nan)
    return t
