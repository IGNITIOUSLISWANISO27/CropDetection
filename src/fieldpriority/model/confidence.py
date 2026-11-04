"""Confidence for each assessment. Describes data support, NOT verified accuracy."""
import numpy as np
import pandas as pd
from .scoring import COMPONENTS


def compute_confidence(season, scored, cfg):
    cc, ex = cfg["confidence"], cfg["extraction"]
    t = cfg["scoring"]["classes"]
    df = season.merge(scored, on="Field_ID")
    rows = []
    for r in df.itertuples(index=False):
        d = r._asdict()
        comp = [d[f"{c}_score"] for c in COMPONENTS if pd.notna(d.get(f"{c}_score"))]
        s = d["integrated_score"]
        if not comp or pd.isna(s):
            rows.append({"Field_ID": d["Field_ID"], "confidence": np.nan, "confidence_label": "n/a"})
            continue
        # 1. agreement: share of components on the same side of 0.5 as the final score
        side = s >= 0.5
        agreement = float(np.mean([(x >= 0.5) == side for x in comp]))
        # 2. data quality: worst NDVI valid fraction x completeness of expected inputs
        vf = d.get("ndvi_valid_frac_min")
        vf = 0.0 if pd.isna(vf) else float(vf)
        needed = ["greenness_seasonal", "rain_anom_mm_mean", "sm_mean", "temp_c_mean", "s1_vv_db"]
        completeness = float(np.mean([pd.notna(d.get(k)) for k in needed]))
        quality = vf * completeness
        # 3. size support: enough 10 m pixels inside the polygon
        px = d.get("n_pixels_10m")
        size = 0.0 if pd.isna(px) else min(1.0, float(px) / ex["full_support_pixels"])
        # 4. margin: distance from the nearest class threshold
        margin = min(1.0, min(abs(s - t["high"]), abs(s - t["moderate"])) / 0.25)
        w = cc["weights"]
        conf = (w["agreement"] * agreement + w["data_quality"] * quality
                + w["size_support"] * size + w["margin"] * margin)
        reg = d.get("regional_share")
        if pd.notna(reg) and reg >= cc["regional_driven_share"]:
            conf -= cc["regional_penalty"]          # field-level evidence is thin
        conf = max(0.0, min(conf, cc["max_before_validation"]))
        lab = cc["labels"]
        label = "High" if conf >= lab["high"] else "Medium" if conf >= lab["medium"] else "Low"
        rows.append({"Field_ID": d["Field_ID"], "confidence": round(conf, 3), "confidence_label": label,
                     "conf_agreement": round(agreement, 3), "conf_data_quality": round(quality, 3),
                     "conf_size_support": round(size, 3), "conf_margin": round(margin, 3)})
    return pd.DataFrame(rows)
