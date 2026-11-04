"""Build the monthly and per-field (season) indicator tables from rasters + v1 reference."""
import numpy as np
import pandas as pd
from .zonal import zonal_stats

PREFIX = {"ndvi": "ndvi", "rainfall": "rain_total_mm", "rainfall_anomaly": "rain_anom_mm",
          "soil_moisture": "sm", "temperature": "temp_c"}
CELL_COL = {"rainfall_anomaly": "rain_cell", "soil_moisture": "sm_cell", "temperature": "temp_cell"}


def build_monthly(fields, catalog, cfg):
    """Long table: one row per field x variable x month (month 0 = season composite)."""
    ex, idc = cfg["extraction"], cfg["fields"]["id_column"]
    ranges = {"ndvi": ex["ndvi_valid_range"], "s1_vv": ex["s1_valid_range_db"]}
    parts = []
    cols = [idc, "variable", "month", "file", "mean", "median", "valid_fraction", "n_pixels", "n_valid",
            "cell_id", "coarse"]
    if catalog.empty:
        return pd.DataFrame(columns=cols)
    for r in catalog.itertuples():
        z = zonal_stats(r.path, fields, idc, ranges.get(r.variable),
                        ex["all_touched"], ex["coarse_res_deg"])
        z.insert(1, "variable", r.variable)
        z.insert(2, "month", int(r.month))
        z.insert(3, "file", r.file)
        parts.append(z)
    return pd.concat(parts, ignore_index=True)


def _shared(cells):
    """For each field, the other fields that share its climate cell."""
    out = {}
    for fid, c in cells.items():
        out[fid] = ",".join(sorted(o for o, oc in cells.items() if o != fid and oc == c and c))
    return out


def build_season(monthly, fields, ref, cfg):
    """Wide table: one row per field with monthly values, seasonal/latest/change features."""
    idc = cfg["fields"]["id_column"]
    months = sorted(cfg["months"])
    latest, prev = months[-1], months[-2]
    wide = fields[[idc, "area_ha"]].set_index(idc)

    for var, pre in PREFIX.items():
        sub = monthly[(monthly.variable == var) & (monthly.month > 0)]
        if sub.empty:
            continue
        piv = sub.pivot(index=idc, columns="month", values="mean").reindex(columns=months)
        for m in months:
            wide[f"{pre}_m{m:02d}"] = piv[m]
        wide[f"{pre}_mean"] = piv.mean(axis=1)
        wide[f"{pre}_latest"] = piv[latest]
        wide[f"{pre}_change_latest"] = piv[latest] - piv[prev]
        if var == "ndvi":
            vf = sub.pivot(index=idc, columns="month", values="valid_fraction").reindex(columns=months)
            for m in months:
                wide[f"ndvi_valid_frac_m{m:02d}"] = vf[m]
            wide["ndvi_valid_frac_min"] = vf.min(axis=1)
            npx = sub[sub.month == latest].set_index(idc)["n_pixels"]
            wide["n_pixels_10m"] = npx
        if var in CELL_COL:
            cells = sub[sub.month == latest].set_index(idc)["cell_id"].to_dict()
            wide[CELL_COL[var]] = pd.Series(cells)
            wide[CELL_COL[var] + "_shared_with"] = pd.Series(_shared(cells))

    # rainfall baseline implied by total - anomaly, and anomaly as % of baseline
    if {"rain_total_mm_latest", "rain_anom_mm_latest"} <= set(wide.columns):
        base = wide["rain_total_mm_latest"] - wide["rain_anom_mm_latest"]
        wide["rain_baseline_mm_latest"] = base
        wide["rain_anom_pct_latest"] = 100 * wide["rain_anom_mm_latest"] / base.replace(0, np.nan)

    # Sentinel-1 VV (single season composite)
    s1 = monthly[monthly.variable == "s1_vv"].set_index(idc)
    if not s1.empty:
        wide["s1_vv_db"] = s1["mean"]
        wide["s1_vv_median_db"] = s1["median"]
        wide["s1_vv_valid_frac"] = s1["valid_fraction"]
        rng = wide["s1_vv_db"].max() - wide["s1_vv_db"].min()
        wide["s1_vv_relative"] = (wide["s1_vv_db"] - wide["s1_vv_db"].min()) / rng if rng > 0 else 0.0
        wide["s1_vv_context"] = np.where(wide["s1_vv_relative"] >= 0.5, "High relative VV", "Low relative VV")
    else:  # Sentinel-1 is context only; keep the columns so downstream code still works
        for c in ["s1_vv_db", "s1_vv_median_db", "s1_vv_valid_frac", "s1_vv_relative"]:
            wide[c] = np.nan
        wide["s1_vv_context"] = "not available"

    # greenness used for scoring: relative vegetation greenness, NOT an NDVI anomaly
    src = cfg["greenness"]["seasonal_source"]
    if src == "shapefile_NDVI_Mean" and "ref_ndvi_composite" in ref.columns:
        comp = ref.set_index(idc)["ref_ndvi_composite"]
        wide["greenness_seasonal"] = comp
        wide["greenness_source"] = "Jan-Mar median composite (shapefile NDVI_Mean)"
    else:
        wide["greenness_seasonal"] = wide["ndvi_mean"] if "ndvi_mean" in wide else np.nan
        wide["greenness_source"] = "mean of monthly NDVI rasters"

    wide["latest_month"] = f"{cfg['year']}-{latest:02d}"
    return wide.reset_index()
