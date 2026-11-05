"""Build the Zambia-wide district layers.

Run (monthly_update.bat does this):
    python -m fieldpriority.national.build                 latest season to date (or last full season)
    python -m fieldpriority.national.build --period 2025-01..2025-04
    python -m fieldpriority.national.build --offline        no internet: use only data already on disk

Writes to outputs/national/:
    district_indicators.csv   one indicator record per district and indicator (see fieldpriority.evidence)
    district_monthly.csv      monthly values: rainfall, temperature, solar, NDVI, soil moisture (district_id,
                              variable, year, month, value)
    district_seasons.csv      the same months in each of the earlier seasons (seasonal comparison)
    national_report.json      period, baseline, sources, notes
"""
import argparse
import datetime as dt
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from . import (MON, baseline_years, latest_window, load_national_config, month_end, season_name, season_of, shift,
               window_label)
from .interpret import below_class, rain_class, temp_class, water_stress
from .sources import chirps_zambia, district_index, power_table, zonal_means
from . import zones as Z
from ..evidence import pending, record


def load_districts(cfg):
    g = gpd.read_file(Path(cfg["_root"]) / cfg["boundaries"]).to_crs(4326)
    return g.sort_values("district").reset_index(drop=True)


def _caches(root):
    return sorted(str(p) for p in (Path(root) / "data").glob("*/_download_cache"))


def rainfall_monthly(districts, months, data_dir, caches, log=print):
    """DataFrame district_id, year, month, rainfall_mm, cells. Months that cannot be read are skipped."""
    rows, idx, n = [], None, len(districts)
    for y, m in months:
        try:
            a, tr, _ = chirps_zambia(y, m, data_dir, caches, log)
        except RuntimeError as e:
            log(f"    {e}")
            continue
        if idx is None or idx.shape != a.shape:
            idx = district_index(districts, a.shape, tr)
        mean, cnt = zonal_means(a, idx, n)
        rows += [{"district_id": d, "year": y, "month": m, "rainfall_mm": float(v), "cells": int(c)}
                 for d, v, c in zip(districts["district_id"], mean, cnt)]
    return pd.DataFrame(rows)


def _gee_table(cfg):
    p = Path(cfg["_root"]) / cfg["data_dir"] / "gee_district_layers.csv"
    if not p.exists():
        return None
    t = pd.read_csv(p)
    need = {"district_id", "variable", "year", "month", "value"}
    if not need <= set(t.columns):
        raise SystemExit(f"{p.name} needs the columns {sorted(need)}")
    return t


def _window_vs_base(t, var, did, window, base_seasons):
    """Mean over the window, and mean over the same months of the baseline seasons, for one district."""
    d = t[(t["district_id"] == did) & (t["variable"] == var)].set_index(["year", "month"])["value"]
    cur = [d.get((y, m)) for y, m in window]
    cur = [v for v in cur if v is not None and np.isfinite(v)]
    base = []
    for k in range(1, len(base_seasons) + 1):
        vals = [d.get((y, m)) for y, m in shift(window, k)]
        vals = [v for v in vals if v is not None and np.isfinite(v)]
        if len(vals) == len(window):
            base.append(np.mean(vals))
    if not cur or len(cur) < len(window) or len(base) < 3:
        return None, None, len(base)
    return float(np.mean(cur)), float(np.mean(base)), len(base)


def agro_zones(cfg, districts, bseasons, data_dir, caches, offline, available, log=print):
    """(zone_info per district, region polygons, source dict, seasons used). Official map first, else the
    rainfall approximation (CHIRPS October-May mean over the baseline seasons)."""
    off = Z.official_regions(cfg["_root"])
    if off is not None:
        g = off.dissolve("region").reset_index()[["region", "geometry"]]
        eq = "EPSG:32735"
        info = {}
        du = districts.to_crs(eq)
        gu = g.to_crs(eq)
        for d in du.itertuples():
            inter = gu.geometry.intersection(d.geometry).area
            if inter.sum() <= 0:
                continue
            shares = {r: float(a / inter.sum() * 100) for r, a in zip(gu["region"], inter) if a > 0}
            info[d.district_id] = {"shares": shares, "major": max(shares, key=shares.get), "rain": None}
        src = {"name": "Official agro-ecological region map (config/agro_regions_official.geojson)",
               "period": "", "resolution": "Map polygons", "confidence": "High", "note": "",
               "method": "Share of each district's area in each official region", "official": True}
        return info, g, src, []

    def read(y, m):
        if offline and not available(y, m):
            raise RuntimeError(f"{y}-{m:02d} not on disk")
        return chirps_zambia(y, m, data_dir, caches, log)

    grid, tr, crs, used = Z.annual_grid(bseasons, read, log)
    if grid is None or len(used) < 5:
        return None, None, {}, used
    regions = Z.classify(grid)
    idx = district_index(districts, grid.shape, tr)
    regions[idx == 0] = 0
    info = Z.district_zones(districts, regions, grid, idx)
    polys = Z.zone_polygons(regions, tr, districts)
    period = f"{season_name(used[0])} to {season_name(used[-1])} ({len(used)} seasons)"
    src = {"name": "Agro-ecological region rainfall criterion (FAO Zambia country profile) applied to CHIRPS v3.0 "
                   "October-May rainfall", "period": period, "resolution": "0.05 degree (about 5 km) cells",
           "confidence": "Medium", "official": False,
           "method": "Mean October-May rainfall per cell: Region I below 800 mm, II 800-1,000 mm, III above 1,000 mm",
           "note": "Approximate: rainfall only, ten seasons; the official map also uses soils and altitude, and "
                   "splits Region II into IIa and IIb."}
    return info, polys, src, used


def build(cfg=None, today=None, offline=False, log=print):
    cfg = cfg or load_national_config()
    root = Path(cfg["_root"])
    today = today or dt.date.today()
    data_dir, out_dir = root / cfg["data_dir"], root / cfg["output_dir"]
    out_dir.mkdir(parents=True, exist_ok=True)
    districts = load_districts(cfg)
    caches = _caches(root)
    c, S = cfg["classes"], cfg["sources"]
    notes = []

    def available(y, m):
        if offline:
            return (data_dir / "chirps" / f"chirps-v3.0.{y}.{m:02d}_zmb.tif").exists() or any(
                (Path(x) / f"chirps-v3.0.{y}.{m:02d}.tif").exists() for x in caches)
        try:
            chirps_zambia(y, m, data_dir, caches, log)
            return True
        except RuntimeError:
            return False

    window = latest_window(today, cfg, available)
    nb = int(cfg["season"].get("baseline_years", 10))
    bseasons = baseline_years(window, nb)
    sy = season_of(*window[0])
    label = window_label(window)
    season_lbl = season_name(sy)
    start, end = dt.date(*window[0], 1), month_end(*window[-1])
    log(f"District layers for {label} ({season_lbl} season), baseline seasons "
        f"{season_name(bseasons[0])} to {season_name(bseasons[-1])}")

    # ---- rainfall (CHIRPS)
    all_months = [ym for k in range(0, nb + 1) for ym in shift(window, k)]
    log("Rainfall (CHIRPS v3.0)")
    rain = rainfall_monthly(districts, [ym for ym in all_months if not offline or available(*ym)], data_dir,
                            caches, log)

    # ---- agricultural zones (agro-ecological regions): official map if supplied, else rainfall approximation
    log("Agricultural zones")
    if cfg.get("skip_zones"):         # past-season replays (drought test) do not need the zones
        zone_info, zone_polys, zone_src, zone_seasons = None, None, None, []
    else:
        zone_info, zone_polys, zone_src, zone_seasons = agro_zones(cfg, districts, bseasons, data_dir, caches,
                                                                   offline, available, log)
    if zone_info is None:
        notes.append("Agricultural zones not computed: October and May rainfall for at least 5 baseline seasons is "
                     "needed (run the update with internet).")

    # ---- temperature + solar (NASA POWER)
    solar_year = today.year - 1
    need = set(all_months) | {(solar_year, m) for m in range(1, 13)}
    log("Temperature and solar radiation (NASA POWER)")
    ptab = data_dir / "power_monthly.csv"
    if offline:
        power = pd.read_csv(ptab) if ptab.exists() else pd.DataFrame(columns=["district_id", "ym", "t2m", "t2m_max",
                                                                               "allsky_mj"])
    else:
        power = power_table(districts, need, ptab, log, today)
    power = power.copy()
    power["year"], power["month"] = power["ym"].astype(int) // 100, power["ym"].astype(int) % 100

    gee = _gee_table(cfg)
    if gee is None:
        notes.append("No Earth Engine district export (data/national/gee_district_layers.csv): vegetation, soil "
                     "moisture and maize/cropland layers are shown as not yet available.")

    # ---- long monthly table (charts) and season comparison table
    mt = []
    if len(rain):
        mt.append(rain.rename(columns={"rainfall_mm": "value"}).assign(variable="rainfall_mm")
                  [["district_id", "variable", "year", "month", "value"]])
    for v in ("t2m", "t2m_max", "allsky_mj"):
        if len(power):
            mt.append(power[["district_id", "year", "month", v]].rename(columns={v: "value"}).assign(variable=v)
                      [["district_id", "variable", "year", "month", "value"]])
    if gee is not None:
        mt.append(gee[["district_id", "variable", "year", "month", "value"]])
    monthly = pd.concat(mt, ignore_index=True) if mt else pd.DataFrame(
        columns=["district_id", "variable", "year", "month", "value"])
    wanted = set(all_months) | {(solar_year, m) for m in range(1, 13)}
    monthly = monthly[[(y, m) in wanted for y, m in zip(monthly["year"], monthly["month"])]]

    seasons = []
    for k in range(0, nb + 1):
        w = shift(window, k)
        for did in districts["district_id"]:
            row = {"district_id": did, "season": season_name(sy - k), "season_start": sy - k, "current": k == 0}
            for var, agg in (("rainfall_mm", "sum"), ("t2m", "mean")):
                d = monthly[(monthly["district_id"] == did) & (monthly["variable"] == var)].set_index(["year", "month"])["value"]
                vals = [d.get(ym) for ym in w]
                ok = [v for v in vals if v is not None and np.isfinite(v)]
                row[var] = (float(np.sum(ok)) if agg == "sum" else float(np.mean(ok))) if len(ok) == len(w) else None
            seasons.append(row)
    seasons = pd.DataFrame(seasons)

    # ---- indicator records per district
    recs = []
    cov = "District average"
    per = (start, end)
    blabel = f"same months of the {nb} seasons {season_name(bseasons[0])} to {season_name(bseasons[-1])}"
    for d in districts.itertuples():
        L = ("district", d.district_id, d.district)
        P = d.province
        # rainfall
        s = seasons[seasons["district_id"] == d.district_id]
        cur = s[s["current"]]["rainfall_mm"].iloc[0] if len(s) else None
        cur = float(cur) if cur is not None and pd.notna(cur) else None
        base = s[~s["current"]]["rainfall_mm"].dropna()
        cells = rain[(rain["district_id"] == d.district_id)]["cells"].min() if len(rain) else 0
        if cur is not None and len(base) >= 5:
            bm = float(base.mean())
            pct = round((cur - bm) / bm * 100) if bm > 0 else None
            conf = "High" if len(base) >= 8 and cells >= 4 else "Medium"
            qn = "" if cells >= 4 else f"Small district: only {cells} rainfall cells."
            rc = rain_class(pct, c)
            recs.append(record(*L, "rainfall_total", cur, "mm", f"{cur:.0f} mm (normal {bm:.0f} mm)", None, per, label,
                               S["rainfall"]["name"], S["rainfall"]["url"], S["rainfall"]["resolution"], cov,
                               S["rainfall"]["data_type"], "Sum of monthly totals, mean over the district's cells",
                               blabel, conf, qn, province=P))
            recs.append(record(*L, "rainfall_anomaly_pct", pct, "%", f"{pct:+.0f}% · {rc}", rc, per, label,
                               S["rainfall"]["name"], S["rainfall"]["url"], S["rainfall"]["resolution"], cov,
                               S["rainfall"]["data_type"], "(season-to-date total − baseline mean) ÷ baseline mean",
                               blabel, conf, qn, province=P))
        else:
            pct = None
            recs.append(pending(*L, "rainfall_anomaly_pct", "CHIRPS rainfall not available for this period",
                                S["rainfall"]["name"], P))
        # temperature
        pw = power[power["district_id"] == d.district_id].set_index(["year", "month"])
        tdev = None
        if len(pw):
            def wmean(col, w):
                v = [pw[col].get(ym) for ym in w]
                v = [x for x in v if x is not None and np.isfinite(x)]
                return float(np.mean(v)) if len(v) == len(w) else None
            tc_ = wmean("t2m", window)
            tb = [wmean("t2m", shift(window, k)) for k in range(1, nb + 1)]
            tb = [x for x in tb if x is not None]
            xc = wmean("t2m_max", window)
            xb = [wmean("t2m_max", shift(window, k)) for k in range(1, nb + 1)]
            xb = [x for x in xb if x is not None]
            if tc_ is not None and len(tb) >= 5:
                tdev = round(tc_ - float(np.mean(tb)), 1)
                tcl = temp_class(tdev, c)
                recs.append(record(*L, "temperature_mean", tc_, "°C", f"{tc_:.1f} °C", None, per, label,
                                   S["temperature"]["name"], S["temperature"]["url"], S["temperature"]["resolution"],
                                   "District central point", S["temperature"]["data_type"],
                                   "Mean of monthly mean 2 m air temperature", blabel, "Medium", province=P))
                recs.append(record(*L, "temperature_deviation", tdev, "°C", f"{tdev:+.1f} °C · {tcl}", tcl, per, label,
                                   S["temperature"]["name"], S["temperature"]["url"], S["temperature"]["resolution"],
                                   "District central point", S["temperature"]["data_type"],
                                   "Season-to-date mean minus baseline mean", blabel, "Medium",
                                   "Coarse grid (about 50 km): local differences are not visible.", province=P))
            else:
                recs.append(pending(*L, "temperature_deviation", "NASA POWER temperature not available",
                                    S["temperature"]["name"], P))
            if xc is not None and len(xb) >= 5:
                xdev = xc - float(np.mean(xb))
                hot = xc >= c["heat_days_tmax_c"]
                recs.append(record(*L, "tmax_mean", xc, "°C", f"{xc:.1f} °C ({xdev:+.1f} °C vs normal)",
                                   "Hot" if hot else "", per, label, S["temperature"]["name"], S["temperature"]["url"],
                                   S["temperature"]["resolution"], "District central point",
                                   S["temperature"]["data_type"],
                                   "Highest temperature of each month, averaged over the season's months",
                                   blabel, "Medium", province=P))
            sol = [pw["allsky_mj"].get((solar_year, m)) for m in range(1, 13)]
            sol = [x for x in sol if x is not None and np.isfinite(x)]
            if len(sol) == 12:
                kwh = float(np.mean(sol)) / 3.6
                recs.append(record(*L, "solar_resource", kwh, "kWh/m²/day", f"{kwh:.1f} kWh/m²/day", None,
                                   (dt.date(solar_year, 1, 1), dt.date(solar_year, 12, 31)), str(solar_year),
                                   S["solar"]["name"], S["solar"]["url"], S["solar"]["resolution"],
                                   "District central point", S["solar"]["data_type"],
                                   "Annual mean of daily all-sky global horizontal irradiance (MJ ÷ 3.6)", "",
                                   "Medium", "Resource only: says nothing about the suitability of a solar system.",
                                   province=P))
        else:
            recs.append(pending(*L, "temperature_deviation", "NASA POWER temperature not downloaded yet",
                                S["temperature"]["name"], P))
        # vegetation / soil moisture / cropland (Earth Engine export by Person 1)
        sm = None
        for var, ind, src, k in (("ndvi", "vegetation_anomaly_pct", "vegetation", "vegetation_pct"),
                                 ("sm_rootzone", "soil_moisture_anomaly_pct", "soil_moisture", "soil_moisture_pct")):
            cur_v = base_v = None
            nbv = 0
            if gee is not None:
                cur_v, base_v, nbv = _window_vs_base(gee, var, d.district_id, window, bseasons)
            if cur_v is not None and base_v:
                p_ = round((cur_v - base_v) / base_v * 100)
                cl = below_class(p_, c[k])
                recs.append(record(*L, ind, p_, "%", f"{p_:+.0f}% · {cl}", cl, per, label, S[src]["name"], "",
                                   "250 m pixels" if var == "ndvi" else "about 9 km cells",
                                   "Cropland pixels of the district" if var == "ndvi" else cov, S[src]["data_type"],
                                   "Season-to-date mean vs the mean of the same months in earlier seasons",
                                   f"{nbv} earlier seasons", "Medium", province=P))
                if var == "sm_rootzone":
                    sm = p_
            else:
                recs.append(pending(*L, ind, "Needs the Earth Engine district export (gee/district_layers.js)",
                                    S[src]["name"], P))
        ws, basis, wconf = water_stress(pct, tdev, sm, c)
        if ws:
            recs.append(record(*L, "water_stress", None, "", ws, ws, per, label,
                               "FieldPriority rules on " + basis, "", "As the inputs", cov, "derived",
                               "Rules in config/national.yaml (classes)", "", wconf,
                               "" if sm is not None else "Indication only: soil moisture is not yet included.",
                               province=P))
        else:
            recs.append(pending(*L, "water_stress", "Rainfall not available", "", P))
        done = False
        if gee is not None:
            for var, ind in (("maize_pct", "maize_share_pct"), ("cropland_pct", "cropland_share_pct")):
                t = gee[(gee["district_id"] == d.district_id) & (gee["variable"] == var)]
                if len(t):
                    v = float(t["value"].iloc[-1])
                    yy = int(t["year"].iloc[-1])
                    grow = "Maize-growing" if v >= c["maize_share_pct"] else "Little maize"
                    recs.append(record(*L, ind, v, "%", f"{v:.1f}% of land" + (f" · {grow}" if var == "maize_pct" else ""),
                                       grow if var == "maize_pct" else "", (dt.date(yy, 1, 1), dt.date(yy, 12, 31)),
                                       str(yy), S["cropland"]["name"], "", "10 m pixels", cov, "satellite_estimate",
                                       "Share of the district's land classified as " + var.split("_")[0], "",
                                       "Medium", "Map year may differ from the season shown.", province=P))
                    done = done or var == "maize_pct"
        if not done:
            recs.append(pending(*L, "maize_share_pct", "Needs the Earth Engine district export (WorldCereal maize map)",
                                S["cropland"]["name"], P))

    # agricultural zone of each district
    for d in districts.itertuples():
        L = ("district", d.district_id, d.district)
        z = (zone_info or {}).get(d.district_id)
        if not z:
            recs.append(pending(*L, "agro_zone", "Needs October and May rainfall for the baseline seasons, or the "
                                "official agro-ecological region map", "", d.province))
            continue
        R = Z.REGIONS[z["major"]]
        others = ", ".join(f"{Z.REGIONS[k]['name']} {v:.0f}%" for k, v in sorted(z["shares"].items(),
                           key=lambda kv: -kv[1]) if k != z["major"] and v >= 5)
        recs.append(record(*L, "agro_zone", z["shares"][z["major"]], "% of district",
                           f"{R['name']} ({R['short']})" + (f" · also {others}" if others else ""), z["major"],
                           (dt.date(zone_seasons[0], 10, 1), dt.date(zone_seasons[-1] + 1, 5, 31))
                           if zone_seasons else (None, None), zone_src["period"], zone_src["name"], "",
                           zone_src["resolution"], "District: share of its area in each region", "derived",
                           zone_src["method"], "", zone_src["confidence"], zone_src["note"], province=d.province))
        if z.get("rain") is not None:
            recs.append(record(*L, "annual_rainfall_normal", z["rain"], "mm", f"{z['rain']:.0f} mm a year", None,
                               (dt.date(zone_seasons[0], 10, 1), dt.date(zone_seasons[-1] + 1, 5, 31)),
                               zone_src["period"], S["rainfall"]["name"], S["rainfall"]["url"],
                               S["rainfall"]["resolution"], "District average", S["rainfall"]["data_type"],
                               "Mean October-May rainfall over the baseline seasons", "", "High",
                               "Ten seasons only, not a 30-year climate normal.", province=d.province))
    if zone_polys is not None:
        zp = zone_polys.copy()
        zp["name"] = zp["region"].map(lambda r: Z.REGIONS[r]["name"])
        zp["short"] = zp["region"].map(lambda r: Z.REGIONS[r]["short"])
        zp["rain"] = zp["region"].map(lambda r: Z.REGIONS[r]["rain"])
        zp["source"] = zone_src["name"]
        zp.to_file(out_dir / "agro_zones.geojson", driver="GeoJSON", COORDINATE_PRECISION=3)

    ind = pd.DataFrame(recs)
    ind.to_csv(out_dir / "district_indicators.csv", index=False)
    monthly.to_csv(out_dir / "district_monthly.csv", index=False)
    seasons.to_csv(out_dir / "district_seasons.csv", index=False)
    rain_ok = ind[(ind["indicator"] == "rainfall_anomaly_pct") & (ind["status"] == "ok")]
    report = {"built_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
              "period_label": label, "season": season_lbl, "window": [f"{y}-{m:02d}" for y, m in window],
              "period_start": str(start), "period_end": str(end),
              "baseline_seasons": [season_name(s) for s in bseasons], "solar_year": solar_year,
              "n_districts": int(len(districts)), "rain_districts": int(len(rain_ok)),
              "boundaries_source": cfg["boundaries_source"], "sources": cfg["sources"], "notes": notes,
              "zones": ({k: v for k, v in zone_src.items()} if zone_info else None)}
    (out_dir / "national_report.json").write_text(json.dumps(report, indent=2, default=str))
    log(f"Wrote {len(ind)} indicator records for {len(districts)} districts to {out_dir}")
    for n in notes:
        log("NOTE: " + n)
    return ind, monthly, seasons, report


def main():
    ap = argparse.ArgumentParser(description="Zambia district layers (rainfall, temperature, solar, ...)")
    ap.add_argument("--period", default=None, help="YYYY-MM..YYYY-MM (default: latest season to date)")
    ap.add_argument("--offline", action="store_true", help="use only data already on disk")
    a = ap.parse_args()
    cfg = load_national_config()
    if a.period:
        cfg["period"] = a.period
    build(cfg, offline=a.offline)


if __name__ == "__main__":
    main()
