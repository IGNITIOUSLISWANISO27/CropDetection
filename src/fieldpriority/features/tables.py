"""Inputs that arrive as tables (Earth Engine CSV exports, imported by import_gee.py) rather than rasters.

* soil_moisture_monthly.csv: area-level monthly soil moisture for several years. The season's months become
  the soil moisture series of every field (a regional value, like a coarse raster cell), and the same months
  of earlier years become its multi-year baseline (rule 3).
* s1_vv_monthly.csv: per-field monthly Sentinel-1 VV backscatter (dB). Context only, like the radar raster
  it replaces: the season value is the mean of the season's months.
* field_annual.csv: per-field values for a whole year (NDVI, rainfall, temperature, soil moisture). Shown as
  context only: a yearly value cannot show a change within the season.
"""
from pathlib import Path

import numpy as np
import pandas as pd

MON = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# every season column the rules, reasons and dashboard read; created empty when no data supplies it
MONTHLY_PREFIXES = ["ndvi", "rain_total_mm", "rain_anom_mm", "sm", "temp_c"]


def ensure_columns(season, cfg):
    months = sorted(cfg["months"])
    cols = {}
    for p in MONTHLY_PREFIXES:
        for m in months:
            cols[f"{p}_m{m:02d}"] = np.nan
        cols.update({f"{p}_mean": np.nan, f"{p}_latest": np.nan, f"{p}_change_latest": np.nan})
    for m in months:
        cols[f"ndvi_valid_frac_m{m:02d}"] = np.nan
    cols.update({"ndvi_valid_frac_min": np.nan, "n_pixels_10m": np.nan, "rain_baseline_mm_latest": np.nan,
                 "rain_anom_pct_latest": np.nan, "s1_vv_db": np.nan, "s1_vv_median_db": np.nan,
                 "s1_vv_valid_frac": np.nan, "s1_vv_relative": np.nan, "s1_vv_context": "not available",
                 "greenness_seasonal": np.nan, "greenness_source": "not available"})
    for c in ("rain_cell", "sm_cell", "temp_cell"):
        cols[c] = None
        cols[c + "_shared_with"] = ""
    for c, v in cols.items():
        if c not in season.columns:
            season[c] = v
    return season


def _recompute(season, prefix, months):
    vals = season[[f"{prefix}_m{m:02d}" for m in months]]
    season[f"{prefix}_mean"] = vals.mean(axis=1)
    season[f"{prefix}_latest"] = season[f"{prefix}_m{months[-1]:02d}"]
    if len(months) > 1:
        season[f"{prefix}_change_latest"] = season[f"{prefix}_m{months[-1]:02d}"] - season[f"{prefix}_m{months[-2]:02d}"]


def add_table_inputs(season, monthly, cfg, data_dir):
    """Returns (season, monthly, notes)."""
    t = cfg.get("tables") or {}
    notes = []
    months, year = sorted(cfg["months"]), int(cfg["year"])
    idc = cfg["fields"]["id_column"]
    smf = Path(data_dir) / t.get("soil_moisture_monthly", "soil_moisture_monthly.csv")
    if smf.exists():
        sm = pd.read_csv(smf)
        layer = t.get("soil_moisture_layer", "rootzone")
        cur = sm[sm["year"] == year].set_index("month")[layer]
        years = t.get("soil_moisture_baseline_years")
        base_rows = sm[sm["year"].between(*years)] if years else sm[sm["year"] < year]
        base = base_rows.groupby("month")[layer].mean()
        byears = sorted(base_rows["year"].unique().tolist())
        have = [m for m in months if m in cur.index]
        if have:
            rows = []
            for m in months:
                v = float(cur[m]) if m in cur.index else np.nan
                season[f"sm_m{m:02d}"] = v
                season[f"sm_baseline_m{m:02d}"] = float(base[m]) if m in base.index else np.nan
                rows += [{idc: f, "variable": "soil_moisture", "month": m, "file": smf.name, "mean": v,
                          "median": v, "valid_fraction": np.nan, "n_pixels": 0, "n_valid": 0,
                          "cell_id": "area series", "coarse": True} for f in season[idc]]
            _recompute(season, "sm", months)
            season["sm_cell"] = "area series"
            season["sm_cell_shared_with"] = season[idc].map(lambda f: ",".join(x for x in season[idc] if x != f))
            season["sm_baseline_years"] = f"{byears[0]}-{byears[-1]}" if byears else ""
            season["sm_layer"] = layer
            monthly = pd.concat([monthly[monthly["variable"] != "soil_moisture"], pd.DataFrame(rows)],
                                ignore_index=True)
            notes.append(f"Soil moisture ({layer}) from {smf.name} for {year}, baseline {season['sm_baseline_years'].iloc[0]}"
                         + (" (replaces any soil moisture rasters)" if (monthly["file"] != smf.name).any() else ""))
        else:
            notes.append(f"{smf.name} has no rows for {year}")
    s1f = Path(data_dir) / t.get("s1_vv_monthly", "s1_vv_monthly.csv")
    if s1f.exists():
        s1 = pd.read_csv(s1f)
        s1 = s1[(s1["year"] == year) & (s1["month"].isin(months))]
        if len(s1):
            g = s1.groupby("Field_ID")
            mean, med = g["vv_mean_db"].mean(), g["vv_median_db"].mean() if "vv_median_db" in s1 else g["vv_mean_db"].mean()
            season["s1_vv_db"] = season[idc].map(mean)
            season["s1_vv_median_db"] = season[idc].map(med)
            season["s1_vv_valid_frac"] = season[idc].map(lambda f: 1.0 if f in mean.index else np.nan)
            for m in months:
                season[f"s1_vv_m{m:02d}"] = season[idc].map(s1[s1["month"] == m].set_index("Field_ID")["vv_mean_db"])
            if "images" in s1:
                season["s1_vv_images"] = season[idc].map(g["images"].sum())
            v = season["s1_vv_db"]
            if v.notna().sum() >= 2:
                rng = v.max() - v.min()
                season["s1_vv_relative"] = (v - v.min()) / rng if rng > 0 else 0.0
                season["s1_vv_context"] = np.where(season["s1_vv_relative"] >= 0.5, "High relative VV", "Low relative VV")
            else:
                season["s1_vv_relative"] = np.nan
                season["s1_vv_context"] = "single field, no comparison"
            span = f"{MON[months[0]]}-{MON[months[-1]]} {year}"
            notes.append(f"Sentinel-1 VV from {s1f.name}: {span} mean per field (context only)")
        else:
            notes.append(f"{s1f.name} has no rows for {year} months {months}")
    af = Path(data_dir) / t.get("field_annual", "field_annual.csv")
    if af.exists():
        a = pd.read_csv(af)
        a = a[a["year"] == a["year"].max()]
        keep = [c for c in ["ndvi_mean", "ndvi_min", "ndvi_max", "rainfall_mm", "temp_min_c", "temp_mean_c",
                            "temp_max_c", "sm_rootzone", "sm_surface", "year"] if c in a.columns]
        a = a[["Field_ID"] + keep].rename(columns={c: f"annual_{c}" for c in keep})
        season = season.merge(a, left_on=idc, right_on="Field_ID", how="left", suffixes=("", "_a"))
        season = season.drop(columns=[c for c in season.columns if c.endswith("_a")])
        notes.append(f"Annual field values from {af.name} shown as context")
    return season, monthly, notes


def s1_context(r, months):
    """One plain-language line for the monthly radar values (context, never used by the rules)."""
    vals = [(m, r.get(f"s1_vv_m{m:02d}")) for m in months]
    vals = [(m, v) for m, v in vals if v is not None and not (isinstance(v, float) and np.isnan(v))]
    if not vals:
        return []
    return [f"Radar (Sentinel-1 VV, 10 m): " + ", ".join(f"{MON[m]} {v:.1f} dB" for m, v in vals)
            + f"; season mean {r['s1_vv_db']:.1f} dB. Radar responds to canopy, roughness and moisture together, "
              "so it is context only."]


def annual_context(r):
    """Plain-language lines for the per-field annual values (context, never used by the rules)."""
    y = r.get("annual_year")
    if y is None or (isinstance(y, float) and np.isnan(y)):
        return []
    f = lambda v, d=2: "n/a" if v is None or (isinstance(v, float) and np.isnan(v)) else f"{v:.{d}f}"
    out = []
    if pd.notna(r.get("annual_ndvi_mean")):
        out.append(f"Greenness over all of {int(y)}: NDVI mean {f(r['annual_ndvi_mean'])} "
                   f"(lowest pixel {f(r.get('annual_ndvi_min'))}, highest {f(r.get('annual_ndvi_max'))})")
    if pd.notna(r.get("annual_rainfall_mm")):
        out.append(f"Rainfall total for {int(y)}: {r['annual_rainfall_mm']:,.0f} mm")
    if pd.notna(r.get("annual_temp_mean_c")):
        out.append(f"Temperature over {int(y)}: mean {f(r['annual_temp_mean_c'], 1)} C, "
                   f"range {f(r.get('annual_temp_min_c'), 1)} to {f(r.get('annual_temp_max_c'), 1)} C")
    if pd.notna(r.get("annual_sm_rootzone")):
        out.append(f"Soil moisture average for {int(y)}: root zone {f(r['annual_sm_rootzone'], 3)}, "
                   f"surface {f(r.get('annual_sm_surface'), 3)}")
    if out:
        out.append("Yearly values cannot show a change within the season, so the rules do not use them.")
    return out
