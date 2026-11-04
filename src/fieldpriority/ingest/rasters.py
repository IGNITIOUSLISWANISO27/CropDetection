"""Discover GEE raster exports by filename and build a catalogue."""
import re
from pathlib import Path
import pandas as pd

MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
          "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}

# Order matters: rainfall_anomaly must be tried before rainfall.
PATTERNS = [
    ("ndvi", r"^(?P<m>[A-Za-z]+)_NDVI_(?P<y>\d{4})(?:(?:_|\s*\()(?P<v>\d+)\)?)?\.tif$"),
    ("rainfall_anomaly", r"^Rainfall_Anomaly_(?P<m>[A-Za-z]{3})(?P<y>\d{4})(?:(?:_|\s*\()(?P<v>\d+)\)?)?\.tif$"),
    ("rainfall", r"^Rainfall_(?P<m>[A-Za-z]{3})(?P<y>\d{4})(?:(?:_|\s*\()(?P<v>\d+)\)?)?\.tif$"),
    ("soil_moisture", r"^SoilMoisture_(?P<m>[A-Za-z]{3})(?P<y>\d{4})(?:(?:_|\s*\()(?P<v>\d+)\)?)?\.tif$"),
    ("temperature", r"^Temperature_(?P<m>[A-Za-z]{3})(?P<y>\d{4})(?:(?:_|\s*\()(?P<v>\d+)\)?)?\.tif$"),
    ("s1_vv", r"^Sentinel1_VV_(?P<y>\d{4})(?:(?:_|\s*\()(?P<v>\d+)\)?)?\.tif$"),
]
EXPECTED_MONTHLY = ["ndvi", "rainfall", "rainfall_anomaly", "soil_moisture", "temperature"]


def discover_rasters(data_dir, year, months):
    """Return (catalogue DataFrame, notes list). Re-exports (_1, _2) supersede originals."""
    notes, rows = [], []
    for f in sorted(Path(data_dir).glob("*.tif")):
        matched = False
        for var, pat in PATTERNS:
            m = re.match(pat, f.name, re.I)
            if not m:
                continue
            d = m.groupdict()
            matched = True
            if int(d["y"]) != year:
                break
            month = MONTHS[d["m"][:3].lower()] if d.get("m") else 0
            version = int(d["v"]) if d.get("v") else 0
            rows.append({"variable": var, "month": month, "version": version,
                         "path": str(f), "file": f.name})
            break
        if not matched:
            notes.append(f"IGNORED unrecognised file name: {f.name}")
    cat = pd.DataFrame(rows, columns=["variable", "month", "version", "path", "file"])
    if cat.empty:
        raise FileNotFoundError(f"no matching .tif files for {year} in {data_dir}")

    for (var, mo), grp in cat.groupby(["variable", "month"]):
        if len(grp) > 1:
            keep = grp.sort_values("version").iloc[-1]["file"]
            notes.append(f"{var} month={mo or '-'}: several files {sorted(grp.file)}; using {keep}")
    cat = (cat.sort_values("version").groupby(["variable", "month"], as_index=False).last()
              .sort_values(["variable", "month"]).reset_index(drop=True))

    for var in EXPECTED_MONTHLY:
        have = set(cat.loc[cat.variable == var, "month"].astype(int))
        missing = sorted(set(months) - have)
        if missing:
            notes.append(f"MISSING {var} for months {missing}")
    if not (cat.variable == "s1_vv").any():
        notes.append("MISSING Sentinel-1 VV composite")
    keep = (cat.variable == "s1_vv") | cat.month.isin(months)
    return cat[keep].reset_index(drop=True), notes
