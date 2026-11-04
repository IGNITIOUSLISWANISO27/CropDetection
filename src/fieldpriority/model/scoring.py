"""Weighted integrated score, priority classes, driver breakdown."""
import numpy as np
import pandas as pd
from .normalise import cohort_minmax, fixed_reference

COMPONENTS = ["greenness", "rainfall", "soil_moisture", "temperature"]
REGIONAL = ["rainfall", "soil_moisture", "temperature"]   # coarse-cell indicators
# column used for each component, and whether a higher raw value means more priority
PRIMARY_INPUT = {
    "greenness": ("greenness_seasonal", False),
    "rainfall": ("rain_anom_mm_mean", False),
    "soil_moisture": ("sm_mean", False),
    "temperature": ("temp_c_mean", True),
}


def _combine(scores, weights):
    """Weighted mean over components that have a score; returns (score, used list)."""
    used = [c for c in COMPONENTS if c in scores and scores[c].notna().any()]
    if not used:                                  # no component has data (e.g. no monthly rasters yet)
        idx = next(iter(scores.values())).index
        return pd.Series(np.nan, index=idx), [], np.array([])
    w = np.array([weights[c] for c in used], dtype=float)
    mat = np.column_stack([scores[c].to_numpy(dtype=float) for c in used])
    # per-row renormalise if a value is missing
    mask = ~np.isnan(mat)
    wm = mask * w
    tot = wm.sum(axis=1)
    val = np.where(tot > 0, np.nansum(np.nan_to_num(mat) * wm, axis=1) / np.where(tot > 0, tot, np.nan), np.nan)
    wsum = w.sum()
    return pd.Series(val, index=scores[used[0]].index), used, w / wsum


def score_primary(df, cfg):
    """Primary method: cohort min-max, equal weights (v1 compatible)."""
    wts = cfg["scoring"]["weights"]
    scores = {c: cohort_minmax(df[col], hs) for c, (col, hs) in PRIMARY_INPUT.items()}
    integ, used, w = _combine(scores, wts)
    out = df[["Field_ID"]].copy()
    for c in COMPONENTS:
        out[f"{c}_score"] = scores[c]
    out["integrated_score"] = integ
    # contribution of each component to the integrated score
    for c, wi in zip(used, w):
        out[f"{c}_contrib"] = scores[c] * wi
    for c in COMPONENTS:
        if f"{c}_contrib" not in out:
            out[f"{c}_contrib"] = np.nan
    reg = out[[f"{c}_contrib" for c in REGIONAL]].sum(axis=1)
    out["regional_share"] = (reg / out["integrated_score"]).where(out["integrated_score"] > 0, 0.0)
    return out


def score_reference(df, cfg):
    """Experimental fixed-reference method. Components without a reference are excluded."""
    rr = cfg["scoring"]["reference_range"]
    scores = {}
    g = rr.get("greenness")
    if g:
        col = "ndvi_latest" if g.get("window", "latest") == "latest" else "greenness_seasonal"
        scores["greenness"] = fixed_reference(df[col], g["neutral"], g["severe"])
    r = rr.get("rainfall_anomaly_mm")
    if r:
        lw = rr.get("latest_weight", 0.5)
        s_latest = fixed_reference(df["rain_anom_mm_latest"], r["neutral"], r["severe"])
        s_mean = fixed_reference(df["rain_anom_mm_mean"], r["neutral"], r["severe"])
        scores["rainfall"] = lw * s_latest + (1 - lw) * s_mean
    for c, key, col in [("soil_moisture", "soil_moisture", "sm_latest"),
                        ("temperature", "temperature", "temp_c_latest")]:
        spec = rr.get(key)
        if spec:
            scores[c] = fixed_reference(df[col], spec["neutral"], spec["severe"])
    if not scores:
        raise ValueError("reference_range has no usable component")
    integ, used, _ = _combine(scores, cfg["scoring"]["weights"])
    out = df[["Field_ID"]].copy()
    out["ref_method_score"] = integ
    out["ref_method_components"] = ",".join(used)
    for c in used:
        out[f"ref_method_{c}"] = scores[c]
    return out


def classify(score, cfg):
    t = cfg["scoring"]["classes"]
    if pd.isna(score):
        return "Unclassified"
    if score >= t["high"]:
        return "High priority"
    if score >= t["moderate"]:
        return "Moderate priority"
    return "Low priority"
