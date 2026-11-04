"""Import a pilot area's Google Earth Engine exports (Person 1) into the pipeline's data folder.

Reads, from one folder:
  <name>.shp/.shx/.dbf/.prj/.cpg          field polygons (Field_ID, Crop, Area_ha, ...)
  *_Field_*_Statistics_<YYYY>.csv,
  *_Field_Rainfall_<YYYY>*.csv            per-field values for one year (reduceRegion exports)
  *_Monthly_Soil_Moisture_<YYYY>.csv      area-level monthly soil moisture (e.g. SMAP L4), one file per year
  *_Sentinel1_VV_Statistics_<YYYY>.csv    per-field monthly (and annual) Sentinel-1 VV backscatter, dB
  *.tif                                   checked only: single-value rasters clipped to a polygon smaller
                                          than one pixel come out empty and are reported, not used

Writes to the data folder (default: the `paths.data_dir` in settings.yaml):
  the shapefile, field_annual.csv, soil_moisture_monthly.csv, s1_vv_monthly.csv, field_info.csv (crop per field;
  planting dates kept if already filled in) and import_report.json.

Run:  python -m fieldpriority.import_gee --src "C:\\path\\to\\gee_exports"
"""
import argparse
import datetime as dt
import json
import re
import shutil
from pathlib import Path

import numpy as np
import pandas as pd

# GEE column -> pipeline column, for per-field annual statistics
ANNUAL = {"mean": "ndvi_mean", "min": "ndvi_min", "max": "ndvi_max",
          "Rainfall_{y}_mm": "rainfall_mm",
          "Minimum_Temperature_C": "temp_min_c", "Mean_Temperature_C": "temp_mean_c",
          "Maximum_Temperature_C": "temp_max_c",
          "Rootzone_Soil_Moisture_{y}": "sm_rootzone", "Surface_Soil_Moisture_{y}": "sm_surface"}
META = ["Field_ID", "Crop", "Area_ha", "Observatio", "Condition"]


def _year(name):
    m = re.search(r"(19|20)\d{2}", name)
    return int(m.group(0)) if m else None


def read_annual(src):
    """Merge every per-field statistics CSV into one table: one row per field and year."""
    parts = []
    for f in sorted(Path(src).glob("*.csv")):
        if "Monthly" in f.name:
            continue
        d = pd.read_csv(f)
        if "Field_ID" not in d.columns:
            continue
        y = _year(f.name)
        cols = {}
        for gee, ours in ANNUAL.items():
            g = gee.format(y=y)
            if g in d.columns:
                # NDVI min/mean/max only from the NDVI file (other files could reuse those names)
                if gee in ("mean", "min", "max") and "NDVI" not in f.name:
                    continue
                cols[g] = ours
        if not cols:
            continue
        keep = d[[c for c in META if c in d.columns] + list(cols)].rename(columns=cols)
        keep["year"] = y
        parts.append((f.name, keep))
    if not parts:
        return pd.DataFrame(), []
    out = None
    for _, p in parts:
        out = p if out is None else out.merge(p, on=[c for c in ["Field_ID", "year"] + META if c in p.columns
                                                     and c in out.columns], how="outer")
    out = out.rename(columns={"Crop": "crop", "Area_ha": "area_ha_gee", "Observatio": "observation",
                              "Condition": "condition"})
    return out, [n for n, _ in parts]


def read_monthly_soil_moisture(src):
    """One row per year and month: root-zone and surface soil moisture (area mean)."""
    rows, files = [], []
    for f in sorted(Path(src).glob("*Monthly_Soil_Moisture_*.csv")):
        d = pd.read_csv(f)
        y = _year(f.name)
        root = next((c for c in d.columns if c.lower().startswith("rootzone")), None)
        surf = next((c for c in d.columns if c.lower().startswith("surface")), None)
        if "Month" not in d.columns or root is None:
            continue
        for r in d.itertuples(index=False):
            r = r._asdict()
            rows.append({"year": y, "month": int(float(r["Month"])), "rootzone": float(r[root]),
                         "surface": float(r[surf]) if surf else np.nan,
                         "observations": r.get("Observation_Count")})
        files.append(f.name)
    return pd.DataFrame(rows).sort_values(["year", "month"]).reset_index(drop=True) if rows else pd.DataFrame(), files


def read_s1(src):
    """Per-field Sentinel-1 VV statistics (dB): one row per field, year and month (month 0 = annual)."""
    parts, files = [], []
    for f in sorted(Path(src).glob("*Sentinel1*VV*Statistics*.csv")):
        d = pd.read_csv(f)
        if not {"Field_ID", "mean"} <= set(d.columns):
            continue
        y = d["year"] if "year" in d.columns else _year(f.name)
        out = pd.DataFrame({"Field_ID": d["Field_ID"], "year": y,
                            "month": pd.to_numeric(d.get("month", 0), errors="coerce").fillna(0).astype(int),
                            "period": d.get("period", "Monthly")})
        for c, n in [("mean", "vv_mean_db"), ("median", "vv_median_db"), ("min", "vv_min_db"), ("max", "vv_max_db"),
                     ("stdDev", "vv_std_db"), ("count", "pixels"), ("image_count", "images")]:
            if c in d.columns:
                out[n] = d[c]
        parts.append(out)
        files.append(f.name)
    if not parts:
        return pd.DataFrame(), []
    return pd.concat(parts).sort_values(["Field_ID", "year", "month"]).reset_index(drop=True), files


def check_rasters(src):
    import rasterio
    out = []
    for f in sorted(Path(src).glob("*.tif")):
        try:
            with rasterio.open(f) as s:
                a = s.read(1, masked=True).astype("float64").filled(np.nan)
                n = int(np.isfinite(a).sum())
                out.append({"file": f.name, "pixels": int(a.size), "with_value": n,
                            "resolution": [round(x, 5) for x in s.res], "crs": str(s.crs),
                            "band": (s.descriptions or [None])[0],
                            "status": "usable" if n else "EMPTY: no value (clipped to a polygon smaller than one "
                                                         "pixel). Use the CSV statistics or re-export without clip()"})
        except Exception as e:
            out.append({"file": f.name, "status": f"unreadable: {e}"})
    return out


def run_import(src, dest, info_path=None):
    src, dest = Path(src), Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    shps = sorted(src.glob("*.shp"))
    if len(shps) != 1:
        raise SystemExit(f"Expected exactly one .shp in {src}, found {[s.name for s in shps]}")
    shp = shps[0]
    for f in src.glob(shp.stem + ".*"):
        if f.suffix.lower() in (".shp", ".shx", ".dbf", ".prj", ".cpg", ".qmd"):
            shutil.copy2(f, dest / f.name)
    import geopandas as gpd
    g = gpd.read_file(dest / shp.name)
    if "Field_ID" not in g.columns:
        raise SystemExit(f"{shp.name} has no Field_ID column; columns: {list(g.columns)}")
    area = g.to_crs(g.estimate_utm_crs()).area / 1e4

    annual, afiles = read_annual(src)
    sm, smfiles = read_monthly_soil_moisture(src)
    s1, s1files = read_s1(src)
    rasters = check_rasters(src)
    if len(annual):
        annual.to_csv(dest / "field_annual.csv", index=False)
    if len(sm):
        sm.to_csv(dest / "soil_moisture_monthly.csv", index=False)
    if len(s1):
        s1.to_csv(dest / "s1_vv_monthly.csv", index=False)

    # field_info: crop from the shapefile, planting dates kept if someone already filled them in
    info_path = Path(info_path) if info_path else dest / "field_info.csv"
    old = pd.read_csv(info_path, dtype=str).fillna("") if info_path.exists() else pd.DataFrame()
    old = old.set_index("Field_ID") if len(old) else old
    rows = []
    for fid, crop in zip(g["Field_ID"], g["Crop"] if "Crop" in g.columns else [""] * len(g)):
        prev = old.loc[fid].to_dict() if len(old) and fid in old.index else {}
        rows.append({"Field_ID": fid, "crop": (str(crop or "").strip().lower() or prev.get("crop", "")),
                     "planting_date": prev.get("planting_date", ""), "stage": prev.get("stage", ""),
                     "source": prev.get("source") or f"{shp.name} (Crop column); planting date not yet collected"})
    pd.DataFrame(rows).to_csv(info_path, index=False)

    small = [f for f, a in zip(g["Field_ID"], area) if a < 0.1]
    report = {"imported_at": dt.datetime.now().isoformat(timespec="seconds"), "source_folder": str(src),
              "fields": len(g), "field_ids": list(g["Field_ID"]),
              "field_area_ha": {f: round(float(a), 4) for f, a in zip(g["Field_ID"], area)},
              "annual_files": afiles, "annual_years": sorted(annual["year"].unique().tolist()) if len(annual) else [],
              "soil_moisture_files": smfiles,
              "soil_moisture_years": sorted(sm["year"].unique().tolist()) if len(sm) else [],
              "s1_files": s1files, "s1_years": sorted(s1["year"].unique().tolist()) if len(s1) else [],
              "rasters": rasters,
              "warnings": ([f"Very small field(s) {small}: under 0.1 ha is only a few 10 m pixels, so NDVI is "
                            "dominated by edge pixels. Check the polygon in QGIS."] if small else [])
                          + [f"{r['file']}: {r['status']}" for r in rasters if r.get("with_value") == 0]
                          + ([] if len(sm) else ["No monthly soil moisture files found"])}
    (dest / "import_report.json").write_text(json.dumps(report, indent=1, default=str))
    return report


def main():
    from .config import load_config
    ap = argparse.ArgumentParser(description="Import Google Earth Engine exports for a pilot area")
    ap.add_argument("--src", required=True, help="folder with the GEE exports and the field shapefile")
    ap.add_argument("--dest", default=None, help="default: paths.data_dir in settings.yaml")
    a = ap.parse_args()
    cfg = load_config()
    root = Path(cfg["_root"])
    dest = Path(a.dest) if a.dest else root / cfg["paths"]["data_dir"]
    info = root / cfg["rules"]["field_info"]
    r = run_import(a.src, dest, info)
    print(f"Imported {r['fields']} field(s) {r['field_ids']} into {dest}")
    print(f"Annual statistics: {r['annual_years']}; monthly soil moisture years: {r['soil_moisture_years']}; "
          f"Sentinel-1 VV years: {r['s1_years']}")
    for w in r["warnings"]:
        print("WARNING:", w)


if __name__ == "__main__":
    main()
