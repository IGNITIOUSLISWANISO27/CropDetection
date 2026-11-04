"""Province view: the district layers combined into one location report per province.

Values are AREA-WEIGHTED means of the districts (a large district counts more than a small one). Rainfall and
temperature are recomputed from the weighted monthly series, so the province anomaly compares the province's own
season total with its own normal. A layer is shown only when districts covering at least MIN_COVER of the
province's area have it.
"""
import datetime as dt

import numpy as np
import pandas as pd

from . import month_end, shift
from .interpret import below_class, rain_class, temp_class, water_stress
from ..evidence import pending, record

MIN_COVER = 0.8


def province_id(name):
    return "province:" + str(name)


def weighted_monthly(monthly, districts, members):
    """Area-weighted monthly series for a set of districts (district_id, variable, year, month, value)."""
    w = districts.set_index("district_id")["area_km2"].astype(float)
    m = monthly[monthly["district_id"].isin(members)].copy()
    if m.empty:
        return pd.DataFrame(columns=["variable", "year", "month", "value"])
    m["w"] = m["district_id"].map(w)
    m = m[np.isfinite(m["value"].astype(float))]
    total = float(w.loc[list(members)].sum())
    out = []
    for (v, y, mo), g in m.groupby(["variable", "year", "month"]):
        cover = g["w"].sum() / total
        if cover >= MIN_COVER:
            out.append({"variable": v, "year": int(y), "month": int(mo),
                        "value": float((g["value"] * g["w"]).sum() / g["w"].sum())})
    return pd.DataFrame(out, columns=["variable", "year", "month", "value"])


def _season_value(series, w, how):
    vals = [series.get(ym) for ym in w]
    vals = [v for v in vals if v is not None and np.isfinite(v)]
    if len(vals) != len(w):
        return None
    return float(np.sum(vals) if how == "sum" else np.mean(vals))


def province_view(nd, cfg, province):
    """Returns (records {indicator: record}, monthly DataFrame with district_id = province id, seasons DataFrame,
    member district ids). nd: NationalData; cfg: national config (classes, sources)."""
    D = nd.districts
    members = D[D["province"] == province]["district_id"].tolist()
    return group_view(nd, cfg, members, ("province", province_id(province), f"{province} Province"), province,
                      "Province")


def zone_id(code):
    return "zone:" + str(code)


def zone_members(nd, code):
    """Districts whose largest share lies in agricultural zone `code` (I, II, III, IIa, IIb)."""
    if not nd.available:
        return []
    t = nd.indicators[(nd.indicators["indicator"] == "agro_zone") & (nd.indicators["status"] == "ok")]
    return t[t["class"] == code]["location_id"].tolist()


def zone_view(nd, cfg, code):
    from .zones import REGIONS
    members = zone_members(nd, code)
    return group_view(nd, cfg, members, ("zone", zone_id(code), f"Agricultural zone: {REGIONS[code]['name']}"), "",
                      "Zone")


def group_view(nd, cfg, members, L, province="", kind="Area"):
    """Area-weighted view of a set of districts (a province or an agricultural zone)."""
    D = nd.districts
    pid = L[1]
    if not nd.available or not members:
        return {}, pd.DataFrame(), pd.DataFrame(), members
    c, S = cfg["classes"], cfg["sources"]
    rep = nd.report
    window = [tuple(map(int, x.split("-"))) for x in rep.get("window", [])]
    nb = len(rep.get("baseline_seasons", []))
    per = (dt.date(*window[0], 1), month_end(*window[-1]))
    label = rep.get("period_label", "")
    blabel = f"same months of the {nb} previous seasons"
    cov = f"{kind} average: area-weighted mean of its {len(members)} districts"
    M = weighted_monthly(nd.monthly, D, members)
    M["district_id"] = pid
    recs = {}
    I = nd.indicators[nd.indicators["location_id"].isin(members)]

    def worst_conf(ind):
        t = I[(I["indicator"] == ind) & (I["status"] == "ok")]["confidence"]
        for k in ("Low", "Medium", "High"):
            if (t == k).any():
                return k
        return "Medium"

    def series(var):
        t = M[M["variable"] == var]
        return dict(zip(zip(t["year"], t["month"]), t["value"]))

    rain, t2m, tmax, sol = series("rainfall_mm"), series("t2m"), series("t2m_max"), series("allsky_mj")
    seasons = []
    sy0 = window[0][0] if window[0][1] >= 7 else window[0][0] - 1
    for k in range(0, nb + 1):
        w = shift(window, k)
        seasons.append({"district_id": pid, "season": f"{sy0 - k}/{str(sy0 - k + 1)[-2:]}", "season_start": sy0 - k,
                        "current": k == 0, "rainfall_mm": _season_value(rain, w, "sum"),
                        "t2m": _season_value(t2m, w, "mean"), "t2m_max": _season_value(tmax, w, "mean")})
    seasons = pd.DataFrame(seasons)
    cur, base = seasons[seasons["current"]].iloc[0], seasons[~seasons["current"]]

    pct = tdev = None
    b = base["rainfall_mm"].dropna()
    if cur["rainfall_mm"] is not None and pd.notna(cur["rainfall_mm"]) and len(b) >= 5:
        bm = float(b.mean())
        pct = round((cur["rainfall_mm"] - bm) / bm * 100)
        rc = rain_class(pct, c)
        conf = worst_conf("rainfall_anomaly_pct")
        recs["rainfall_total"] = record(*L, "rainfall_total", cur["rainfall_mm"], "mm",
                                        f"{cur['rainfall_mm']:.0f} mm (normal {bm:.0f} mm)", None, per, label,
                                        S["rainfall"]["name"], S["rainfall"]["url"], S["rainfall"]["resolution"], cov,
                                        S["rainfall"]["data_type"], "Sum of monthly totals", blabel, conf,
                                        province=province)
        recs["rainfall_anomaly_pct"] = record(*L, "rainfall_anomaly_pct", pct, "%", f"{pct:+.0f}% · {rc}", rc, per,
                                              label, S["rainfall"]["name"], S["rainfall"]["url"],
                                              S["rainfall"]["resolution"], cov, S["rainfall"]["data_type"],
                                              "(season-to-date total − normal) ÷ normal", blabel, conf,
                                              province=province)
    else:
        recs["rainfall_anomaly_pct"] = pending(*L, "rainfall_anomaly_pct", "Rainfall not available", S["rainfall"]["name"],
                                               province)
    b = base["t2m"].dropna()
    if cur["t2m"] is not None and pd.notna(cur["t2m"]) and len(b) >= 5:
        tdev = round(cur["t2m"] - float(b.mean()), 1)
        tc = temp_class(tdev, c)
        recs["temperature_mean"] = record(*L, "temperature_mean", cur["t2m"], "°C", f"{cur['t2m']:.1f} °C", None, per,
                                          label, S["temperature"]["name"], S["temperature"]["url"],
                                          S["temperature"]["resolution"], cov, S["temperature"]["data_type"],
                                          "Mean of monthly mean 2 m air temperature", blabel, "Medium",
                                          province=province)
        recs["temperature_deviation"] = record(*L, "temperature_deviation", tdev, "°C", f"{tdev:+.1f} °C · {tc}", tc,
                                               per, label, S["temperature"]["name"], S["temperature"]["url"],
                                               S["temperature"]["resolution"], cov, S["temperature"]["data_type"],
                                               "Season-to-date mean minus normal", blabel, "Medium",
                                               province=province)
    bx = base["t2m_max"].dropna()
    if cur["t2m_max"] is not None and pd.notna(cur["t2m_max"]) and len(bx) >= 5:
        xd = cur["t2m_max"] - float(bx.mean())
        recs["tmax_mean"] = record(*L, "tmax_mean", cur["t2m_max"], "°C",
                                   f"{cur['t2m_max']:.1f} °C ({xd:+.1f} °C vs normal)", "", per, label,
                                   S["temperature"]["name"], S["temperature"]["url"], S["temperature"]["resolution"], cov,
                                   S["temperature"]["data_type"],
                                   "Highest temperature of each month, averaged over the season's months", blabel,
                                   "Medium", province=province)
    sy = int(rep.get("solar_year") or 0)
    sv = [sol.get((sy, m)) for m in range(1, 13)]
    if sy and all(v is not None and np.isfinite(v) for v in sv):
        kwh = float(np.mean(sv)) / 3.6
        recs["solar_resource"] = record(*L, "solar_resource", kwh, "kWh/m²/day", f"{kwh:.1f} kWh/m²/day", None,
                                        (dt.date(sy, 1, 1), dt.date(sy, 12, 31)), str(sy), S["solar"]["name"],
                                        S["solar"]["url"], S["solar"]["resolution"], cov, S["solar"]["data_type"],
                                        "Annual mean of daily all-sky irradiance", "", "Medium",
                                        "Resource only: says nothing about the suitability of a solar system.",
                                        province=province)
    # layers that exist only as district percentages (Earth Engine export): area-weighted mean of the districts
    w = D.set_index("district_id")["area_km2"].astype(float)
    total = float(w.loc[members].sum())
    sm = None
    for ind, k, src in (("vegetation_anomaly_pct", "vegetation_pct", "vegetation"),
                        ("soil_moisture_anomaly_pct", "soil_moisture_pct", "soil_moisture"),
                        ("maize_share_pct", None, "cropland")):
        t = I[(I["indicator"] == ind) & (I["status"] == "ok")]
        if len(t) and w.loc[t["location_id"]].sum() / total >= MIN_COVER:
            v = float((t["value"].astype(float) * w.loc[t["location_id"]].values).sum() / w.loc[t["location_id"]].sum())
            r0 = t.iloc[0]
            if k:
                cl = below_class(v, c[k])
                disp = f"{v:+.0f}% · {cl}"
            else:
                cl = "Maize-growing" if v >= c["maize_share_pct"] else "Little maize"
                disp = f"{v:.1f}% of land · {cl}"
            recs[ind] = record(*L, ind, round(v, 1), "%", disp, cl, (r0["period_start"], r0["period_end"]),
                               r0["period_label"], r0["source"], r0["source_url"], r0["resolution"], cov,
                               r0["data_type"], r0["method"], r0["baseline"], worst_conf(ind), province=province)
            if ind == "soil_moisture_anomaly_pct":
                sm = v
        else:
            recs[ind] = pending(*L, ind, "Needs the Earth Engine district export (gee/district_layers.js)",
                                S[src]["name"], province)
    ws, basis, wconf = water_stress(pct, tdev, sm, c)
    if ws:
        recs["water_stress"] = record(*L, "water_stress", None, "", ws, ws, per, label, "FieldPriority rules on " + basis,
                                      "", "As the inputs", cov, "derived", "Rules in config/national.yaml (classes)", "",
                                      wconf, "" if sm is not None else "Indication only: soil moisture is not yet included.",
                                      province=province)
    return recs, M, seasons, members
