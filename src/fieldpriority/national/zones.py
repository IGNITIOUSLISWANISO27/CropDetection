"""Agricultural zones: Zambia's agro-ecological regions, approximated from rainfall.

Zambia's three agro-ecological regions are defined mainly by annual rainfall (FAO, Zambia country profile):
  Region I    less than 800 mm    semi-arid valleys (Luangwa, Zambezi, Lunsemfwa) and the south / south-west
  Region II   800 to 1,000 mm     the central plateau (IIa) and the Kalahari sands of the west (IIb)
  Region III  more than 1,000 mm  the high-rainfall north (Northern, Luapula, Copperbelt, North-Western)

Until the official map is loaded, the regions here are APPROXIMATE: each 5 km CHIRPS cell is classed by its mean
rainfall from October to May (practically the whole year's rain in Zambia) over the baseline seasons. The official
map also uses soils and altitude, so its borders differ; the IIa / IIb split needs soil data and is not made.
To use the official map instead, save it as config/agro_regions_official.geojson with a 'region' property
(I, IIa, IIb, III); it then replaces the approximation everywhere.
"""
from pathlib import Path

import numpy as np

REGIONS = {
    "I": {"name": "Region I", "rain": "less than 800 mm", "short": "Semi-arid valleys and south",
          "color": "#D08C3A",
          "about": "Low, unreliable rainfall, high temperatures and a short growing season. Drought-tolerant and "
                   "early-maturing varieties matter most; water harvesting and irrigation reduce risk."},
    "II": {"name": "Region II", "rain": "800 to 1,000 mm", "short": "Central and western plateau",
           "color": "#E9D27A",
           "about": "Zambia's main maize belt. Dry spells during the season are the main risk; soils range from "
                    "fertile plateau soils (IIa) to sandy Kalahari soils in the west (IIb)."},
    "III": {"name": "Region III", "rain": "more than 1,000 mm", "short": "High-rainfall north",
            "color": "#6FA85A",
            "about": "Reliable, high rainfall but leached, acidic soils. Liming and fertiliser limit yields more "
                     "often than water does."},
}
REGIONS["IIa"] = {**REGIONS["II"], "name": "Region IIa", "short": "Central plateau"}
REGIONS["IIb"] = {**REGIONS["II"], "name": "Region IIb", "short": "Western Kalahari sands", "color": "#F1E3A8"}
ORDER = ["I", "II", "III"]
ZONE_MONTHS = [10, 11, 12, 1, 2, 3, 4, 5]             # October to May: the whole rainy season


def classify(annual_mm):
    a = np.asarray(annual_mm, dtype=float)
    out = np.zeros(a.shape, dtype="uint8")
    out[np.isfinite(a) & (a < 800)] = 1
    out[np.isfinite(a) & (a >= 800) & (a <= 1000)] = 2
    out[np.isfinite(a) & (a > 1000)] = 3
    return out


def annual_grid(seasons, read_month, log=print):
    """Mean Oct-May rainfall (mm) per cell over the given season start-years. read_month(y, m) returns
    (array, transform, crs) or raises. Seasons with a missing month are left out."""
    total, n, tr, crs = None, 0, None, None
    used = []
    for sy in seasons:
        acc = None
        try:
            for m in ZONE_MONTHS:
                a, tr, crs = read_month(sy if m >= 7 else sy + 1, m)
                acc = a.copy() if acc is None else acc + a
        except RuntimeError as e:
            log(f"    zones: season {sy}/{str(sy + 1)[-2:]} left out ({e})")
            continue
        total = acc if total is None else total + acc
        n += 1
        used.append(sy)
    if not n:
        return None, None, None, []
    return total / n, tr, crs, used


def district_zones(districts, region_grid, rain_grid, idx):
    """Per district: share of each region (by cells), majority region and mean annual rainfall."""
    out = {}
    for i, did in enumerate(districts["district_id"], start=1):
        sel = (idx == i) & (region_grid > 0)
        cnt = sel.sum()
        if not cnt:
            continue
        shares = {k: float((region_grid[sel] == j).sum() / cnt * 100) for j, k in enumerate(ORDER, start=1)}
        major = max(shares, key=shares.get)
        out[did] = {"shares": shares, "major": major, "rain": float(np.nanmean(rain_grid[sel])), "cells": int(cnt)}
    return out


def zone_polygons(region_grid, transform, districts, simplify_deg=0.02):
    """Region polygons (GeoDataFrame: region, geometry), cut to Zambia's outline and smoothed for display."""
    import geopandas as gpd
    from rasterio.features import shapes
    from shapely.geometry import shape
    rows = [{"code": int(v), "geometry": shape(g)} for g, v in shapes(region_grid, mask=region_grid > 0,
                                                                      transform=transform)]
    g = gpd.GeoDataFrame(rows, geometry="geometry", crs=4326).dissolve("code").reset_index()
    outline = districts.union_all() if hasattr(districts, "union_all") else districts.unary_union
    g["geometry"] = g.geometry.buffer(0).intersection(outline).simplify(simplify_deg, preserve_topology=True)
    g["region"] = g["code"].map({1: "I", 2: "II", 3: "III"})
    g = g[~g.geometry.is_empty]
    return g[["region", "geometry"]]


def official_regions(root):
    p = Path(root) / "config" / "agro_regions_official.geojson"
    if not p.exists():
        return None
    import geopandas as gpd
    g = gpd.read_file(p).to_crs(4326)
    if "region" not in g.columns:
        raise SystemExit(f"{p.name} needs a 'region' column (I, IIa, IIb, III)")
    return g
