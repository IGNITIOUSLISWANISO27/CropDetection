"""Drought-stress rules engine (the team's 12 rules).

This decides what the system says about each field. The legacy weighted score (scoring.py) is kept
only as a relative ranking for comparison; it no longer sets the alert.

 1  Scope: possible drought-related stress in MAIZE only. Other crops are "Not assessed".
 2  Needs a field ID, a location (polygon), an assessment date and usable environmental data.
 3  Rainfall is compared with its multi-year baseline (CHIRPS). Vegetation is compared with a
    multi-year NDVI baseline when one exists, otherwise with this season's earlier peak.
 4  "Possible drought stress" only when water-deficit evidence AND vegetation decline occur together.
 5  Vegetation decline without water-deficit evidence -> "Crop stress—cause uncertain".
 6  Growth stage: decline at maturity/harvest is treated as expected drying, not drought.
    Unknown stage caps the risk at Moderate and asks for the stage to be checked.
 7  Missing essential data -> "Insufficient data", never "Low".
 8  Every result explains what changed, which indicators contributed and what needs checking.
 9  Risk level, data confidence and verification status are separate fields.
12  Next actions recommend verification or professional assessment, never treatment.
(Rules 10 and 11 are applied in pipeline.py / validation: alert ledger and TEST exclusion.)

All thresholds live in config/settings.yaml -> rules (provisional, need agricultural review).
"""
import datetime as dt
import math

import pandas as pd

# ---- fixed vocabulary (agree with Person 2/3 before changing; the dashboard and Kobo mapping use these)
OUTCOMES = {
    "possible_drought": "Possible drought stress",
    "cause_uncertain": "Crop stress—cause uncertain",
    "insufficient": "Insufficient data",
    "watch": "Water deficit—no vegetation decline yet",
    "maturity": "Drying consistent with crop maturity",
    "no_signal": "No drought-stress signal",
    "out_of_scope": "Not assessed (crop is not maize)",
}
RISK_LEVELS = ["High", "Moderate", "Not attributed", "Watch", "Low", "Insufficient data", "Not assessed"]
STAGE_LABELS = {"emergence": "Emergence", "early_vegetative": "Early vegetative", "vegetative": "Vegetative growth",
                "tasselling_silking": "Tasselling/silking", "grain_filling": "Grain filling",
                "maturity_harvest": "Maturity/harvest", "unknown": "Unknown"}
MONTHS = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

NEXT_ACTION = {
    "possible_drought": ("Verify in the field with the Kobo form using this alert ID. If the visit supports "
                         "drought stress, refer to an extension officer for professional assessment. "
                         "Do not start treatment or change irrigation on this alert alone."),
    "cause_uncertain": ("Field check to identify the cause (pests, disease, nutrients, waterlogging, late planting "
                        "or management) and seek an extension officer's assessment. No treatment based on this alert."),
    "insufficient": ("Obtain the missing data listed and re-run the assessment. A field check is optional "
                     "if there is a local concern; this result is not 'low risk'."),
    "watch": "Monitor the next satellite update. An optional field check can record the crop's condition now.",
    "maturity": ("Optional field check that the drying matches normal maturity and is not premature drying."),
    "no_signal": "No visit needed for drought stress. Can be used as an optional comparison (control) visit.",
    "out_of_scope": "Outside the system's scope. Use other agricultural advice for this field.",
}


def _num(x):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(x) else x


def _date(x):
    if x is None or (isinstance(x, float) and math.isnan(x)) or str(x).strip() in ("", "nan", "NaT", "None"):
        return None
    if isinstance(x, dt.date):
        return x
    try:
        return dt.date.fromisoformat(str(x)[:10])
    except ValueError:
        return None


def month_end(year, month):
    nxt = dt.date(year + (month == 12), month % 12 + 1, 1)
    return nxt - dt.timedelta(days=1)


def stage_from_planting(planting, on_date, stage_days):
    """Growth stage from days after planting. Returns (stage, days_after_planting)."""
    if planting is None or on_date is None or planting > on_date:
        return "unknown", None
    dap = (on_date - planting).days
    stage = "unknown"
    for name, start in sorted(stage_days.items(), key=lambda kv: kv[1]):
        if dap >= start:
            stage = name
    return stage, dap


def _rain_pct(r, m):
    tot, anom = _num(r.get(f"rain_total_mm_m{m:02d}")), _num(r.get(f"rain_anom_mm_m{m:02d}"))
    if tot is None or anom is None:
        return None, None, None
    base = tot - anom
    return (100.0 * anom / base if base > 0 else None), anom, base


def assess_field(r, info, cfg, assessment_date, has_location=True):
    """r: one row of the season table (dict). info: dict from field_info.csv (may be empty).
    Returns a dict with outcome, risk level, data confidence, explanation and next action."""
    rc = cfg["rules"]
    months = sorted(cfg["months"])
    year, latest = int(cfg["year"]), months[-1]
    data_end = month_end(year, latest)
    fid = r.get("Field_ID")
    missing, issues, changed, indicators, checks = [], [], [], [], []

    # ---------- rule 1: scope
    crop = str(info.get("crop") or "").strip().lower()
    if crop and crop != rc.get("crop", "maize"):
        return _result(fid, "out_of_scope", "Not assessed", "n/a", [f"Crop recorded as '{crop}'."], [], [],
                       [], [], None, None, assessment_date, data_end)

    # ---------- rule 2/7: essential data
    if not fid:
        missing.append("field ID")
    if not has_location:
        missing.append("field location (valid polygon)")
    if assessment_date is None:
        missing.append("assessment date")
    if not crop:
        missing.append("crop type (field_info.csv)")
    if assessment_date is not None:
        age = (assessment_date - data_end).days
        if age < 0:
            missing.append(f"environmental data up to the assessment date (data end {data_end}, "
                           f"assessment {assessment_date})")
        elif age > rc.get("max_data_age_days", 45):
            missing.append(f"recent environmental data (latest data end {data_end} is {age} days before the "
                           f"assessment date {assessment_date})")

    # rainfall vs multi-year baseline (rule 3)
    wd = rc["water_deficit"]
    lookback = int(wd.get("lookback_months", 1))
    deficit_months = []
    rain_latest_pct, rain_latest_anom, rain_latest_base = _rain_pct(r, latest)
    sm_latest_base = _num(r.get(f"sm_baseline_m{latest:02d}"))
    sm_latest_val = _num(r.get(f"sm_m{latest:02d}"))
    sm_has_baseline = sm_latest_base is not None and sm_latest_val is not None
    if rain_latest_pct is None and not sm_has_baseline:
        missing.append(f"rainfall with its baseline, or soil moisture with a multi-year baseline, "
                       f"for {MONTHS[latest]} {year}")
    elif rain_latest_pct is None:
        issues.append("No rainfall data: water deficit is judged from soil moisture alone")
    for m in [mm for mm in months if latest - lookback <= mm <= latest]:
        pct, anom, base = _rain_pct(r, m)
        if pct is None:
            continue
        finding = "deficit" if pct <= wd["rain_anomaly_pct_max"] else "normal or above"
        if finding == "deficit":
            deficit_months.append(m)
        indicators.append({"indicator": f"Rainfall {MONTHS[m]} {year}", "scale": "regional cell",
                           "value": f"{base + anom:.0f} mm", "baseline": f"{base:.0f} mm, CHIRPS multi-year mean",
                           "change": f"{anom:+.0f} mm ({pct:+.0f}%)", "finding": finding,
                           "contributed": finding == "deficit"})
    # root-zone soil moisture against the same month of earlier years (rule 3)
    smt = wd.get("soil_moisture_anomaly_pct_max")
    by = r.get("sm_baseline_years") or "earlier years"
    for m in [mm for mm in months if latest - lookback <= mm <= latest]:
        v, b = _num(r.get(f"sm_m{m:02d}")), _num(r.get(f"sm_baseline_m{m:02d}"))
        if v is None or b is None or not b or smt is None:
            continue
        pct = 100.0 * (v - b) / b
        dry = pct <= smt
        if dry:
            deficit_months.append(m)
        indicators.append({"indicator": f"Soil moisture ({r.get('sm_layer') or 'root zone'}) {MONTHS[m]} {year}",
                           "scale": "regional (area mean)", "value": f"{v:.3f}",
                           "baseline": f"{b:.3f}, mean of {MONTHS[m]} {by}", "change": f"{v - b:+.3f} ({pct:+.0f}%)",
                           "finding": "deficit" if dry else "normal or wetter", "contributed": dry})
    water_deficit = bool(deficit_months)

    sm_drop = _num(r.get("sm_change_latest"))
    sm_support = sm_drop is not None and sm_drop <= wd["soil_moisture_drop_support"]
    if sm_drop is not None:
        indicators.append({"indicator": f"Soil moisture {MONTHS[latest]} vs {MONTHS[months[-2]]}" if len(months) > 1 else "Soil moisture",
                           "scale": "regional cell", "value": f"{_num(r.get('sm_latest')) or 0:.3f}",
                           "baseline": "previous month",
                           "change": f"{sm_drop:+.3f}", "finding": "drying" if sm_support else "no marked change",
                           "contributed": bool(water_deficit and sm_support)})

    # vegetation vs baseline (rule 3)
    vg = rc["vegetation"]
    vf_latest = _num(r.get(f"ndvi_valid_frac_m{latest:02d}"))
    ndvi_latest = _num(r.get(f"ndvi_m{latest:02d}"))
    if ndvi_latest is None:
        missing.append(f"NDVI for {MONTHS[latest]} {year}")
    elif vf_latest is not None and vf_latest < vg["min_valid_fraction"]:
        missing.append(f"usable NDVI for {MONTHS[latest]} {year} (only {vf_latest*100:.0f}% cloud-free pixels)")
        ndvi_latest = None
    ref_val, ref_label = None, None
    ml_base = _num(r.get(f"ndvi_baseline_m{latest:02d}"))
    if vg.get("baseline") == "multi_year" and ml_base is not None:
        ref_val, ref_label = ml_base, f"multi-year {MONTHS[latest]} NDVI baseline"
    else:
        if vg.get("require_multi_year_baseline"):
            missing.append(f"multi-year NDVI baseline for {MONTHS[latest]}")
        earlier = []
        for m in months[:-1]:
            v, f = _num(r.get(f"ndvi_m{m:02d}")), _num(r.get(f"ndvi_valid_frac_m{m:02d}"))
            if v is not None and (f is None or f >= vg["min_valid_fraction"]):
                earlier.append((v, m))
        if earlier:
            ref_val, pm = max(earlier)
            ref_label = f"this season's earlier peak, {MONTHS[pm]} {year}"
            issues.append("Vegetation is compared with this season's earlier peak, not a multi-year NDVI baseline")
        elif "multi-year NDVI baseline" not in " ".join(missing):
            missing.append("an earlier usable NDVI month or a multi-year NDVI baseline to compare with")

    decline = severe = False
    if ndvi_latest is not None and ref_val is not None:
        d_abs = ndvi_latest - ref_val
        d_rel = d_abs / ref_val if ref_val > 0 else 0.0
        decline = d_abs <= vg["decline_abs"] and d_rel <= vg["decline_rel"]
        severe = decline and d_abs <= vg["severe_abs"]
        indicators.insert(0, {"indicator": f"Vegetation (NDVI) {MONTHS[latest]} {year}", "scale": "field (10 m)",
                              "value": f"{ndvi_latest:.2f}", "baseline": f"{ref_val:.2f}, {ref_label}",
                              "change": f"{d_abs:+.2f} ({d_rel*100:+.0f}%)",
                              "finding": ("marked decline" if severe else "decline") if decline else "no decline",
                              "contributed": decline})

    # ---------- rule 6: growth stage
    stage_obs = str(info.get("stage") or "").strip().lower()
    planting = _date(info.get("planting_date"))
    if stage_obs in STAGE_LABELS and stage_obs != "unknown":
        stage, dap, stage_src = stage_obs, None, "recorded"
    else:
        stage, dap = stage_from_planting(planting, data_end, rc["stage_days"])
        stage_src = "from planting date" if stage != "unknown" else "unknown"
    if stage == "unknown":
        issues.append("Growth stage unknown (no planting date or observed stage)")

    # ---------- data-quality issues (rule 9: data confidence)
    px = _num(r.get("n_pixels_10m"))
    if px is not None and px < rc.get("small_field_pixels", 100):
        issues.append(f"Small field (about {int(px)} pixels at 10 m), so edge pixels can shift NDVI")

    # ---------- decide
    if missing:
        key, risk = "insufficient", "Insufficient data"
        checks = [f"Missing: {m}" for m in missing]
    elif decline and stage == "maturity_harvest":
        key, risk = "maturity", "Low"
        checks.append("Confirm the drying is normal maturity and not premature drying")
    elif decline and water_deficit:
        key = "possible_drought"
        if stage == "unknown":
            risk = "Moderate"
            checks.append("Record the growth stage: drying near maturity is normal and is not drought")
        elif severe or stage in rc.get("sensitive_stages", []):
            risk = "High"
        else:
            risk = "Moderate"
        if stage in rc.get("sensitive_stages", []):
            checks.append(f"{STAGE_LABELS[stage]} is especially sensitive to water deficit; prioritise the visit")
        checks += ["Look for leaf rolling, leaf drying and dry soil across more than the field edge",
                   "Rule out pests, disease, nutrient problems, weeds, late planting and waterlogging",
                   "Record recent rain or irrigation since the satellite data date"]
    elif decline:
        key, risk = "cause_uncertain", "Not attributed"
        checks += ["Rainfall was not below its baseline, so check other causes first: pests, disease, nutrients, "
                   "waterlogging, weeds, late planting, harvest or management",
                   "Record the growth stage"]
    elif water_deficit:
        key, risk = "watch", "Watch"
        checks.append("Check the next NDVI update for a decline")
    else:
        key, risk = "no_signal", "Low"

    # what changed (rule 8)
    for i in indicators:
        if (i["contributed"] or i["finding"] in ("deficit", "decline", "marked decline", "drying")
                or i["indicator"].startswith("Vegetation") or "(rootzone)" in i["indicator"]
                or "(surface)" in i["indicator"]):
            changed.append(f"{i['indicator']}: {i['change']} against {i['baseline']}. Finding: {i['finding']}")
    if not changed and key not in ("insufficient",):
        changed.append("No indicator moved beyond its threshold against its baseline")

    n = len(issues)
    lim = rc.get("confidence_issue_limits", {"medium": 1, "low": 2})
    conf = "Low" if (key == "insufficient" or n >= lim["low"]) else "Medium" if n >= lim["medium"] else "High"
    return _result(fid, key, risk, conf, changed, indicators, checks, issues, missing,
                   stage, stage_src, assessment_date, data_end, dap=dap, water_deficit=water_deficit,
                   decline=decline, sm_support=sm_support)


def _result(fid, key, risk, conf, changed, indicators, checks, issues, missing, stage, stage_src,
            assessment_date, data_end, dap=None, water_deficit=None, decline=None, sm_support=None):
    contrib = [i["indicator"] for i in indicators if i.get("contributed")]
    return {
        "field_id": fid,
        "outcome_code": key,
        "outcome": OUTCOMES[key],
        "risk_level": risk,
        "data_confidence": conf,
        "data_confidence_issues": issues,
        "missing_data": missing,
        "growth_stage": stage or "unknown",
        "growth_stage_label": STAGE_LABELS.get(stage or "unknown", "Unknown"),
        "growth_stage_source": stage_src or "unknown",
        "days_after_planting": dap,
        "water_deficit": water_deficit,
        "vegetation_decline": decline,
        "soil_moisture_support": sm_support,
        "assessment_date": assessment_date.isoformat() if assessment_date else None,
        "data_end_date": data_end.isoformat() if data_end else None,
        "explanation": {"headline": OUTCOMES[key], "what_changed": changed,
                        "contributing_indicators": contrib, "indicators": indicators, "checks": checks},
        "next_action": NEXT_ACTION[key],
    }


def load_field_info(path):
    try:
        d = pd.read_csv(path, dtype=str).fillna("")
    except FileNotFoundError:
        return {}
    return {r["Field_ID"].strip(): r for r in d.to_dict("records")}


def assess_all(season, cfg, assessment_date, field_info=None, locations=None):
    """season: DataFrame (one row per field). locations: {Field_ID: bool has valid polygon}."""
    field_info = field_info or {}
    out = []
    for r in season.to_dict("records"):
        fid = r.get("Field_ID")
        out.append(assess_field(r, field_info.get(fid, {}), cfg, assessment_date,
                                True if locations is None else bool(locations.get(fid))))
    return out
