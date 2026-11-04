"""SOP section 7 data-quality checks and ID matching for Kobo verification records.
Statuses match the Validation Register: Accepted / Needs review / Rejected for analysis."""
import datetime as dt
import re
from pathlib import Path
import numpy as np
import pandas as pd
from . import labels as L

TEXT_FIELDS = ["crop_comments", "soil_water_comments", "other_causes", "verdict_reason", "additional_comments"]
OBS_FIELDS = ["overall_condition", "soil_condition", "crop_photo", "soil_photo", "field_verdict"]
ALT_FIELDS = ["pest_damage", "disease_symptoms", "nutrient_deficiency", "weed_pressure", "late_planting", "main_cause"]
REJECT_CODES = {"NO_PERMISSION", "NOT_MAIZE", "ID_MISSING"}
PHONE = re.compile(r"(\+?\d[\d\s\-]{7,}\d)")
EMAIL = re.compile(r"\S+@\S+\.\S+")
KOBO_STATUS = {"approved": "Accepted", "on_hold": "Needs review", "not_approved": "Rejected for analysis"}


def norm_id(x):
    return None if pd.isna(x) else re.sub(r"[\s_\-]+", "", str(x)).upper()


def load_field_map(path):
    m = pd.read_csv(path, dtype=str)
    return {norm_id(k): v.strip() for k, v in zip(m["kobo_field_id"], m["field_id"])}


def exact_id(x):
    """Alias keys match the Kobo text exactly (ignoring case and outer spaces), so 'Test 001' never matches 'TEST-001'."""
    return None if pd.isna(x) else str(x).strip().upper()


def load_alert_map(path):
    """Kobo alert IDs a person has approved as another name for an issued alert (config/alert_id_map.csv).
    Returns {normalised Kobo alert ID: row dict}. Missing file -> {}."""
    if not path or not Path(path).exists():
        return {}
    m = pd.read_csv(path, dtype=str).fillna("")
    return {exact_id(r["kobo_alert_id"]): r for r in m.to_dict("records") if r.get("kobo_alert_id")}


def _d(x):
    t = pd.to_datetime(x, errors="coerce")
    return None if pd.isna(t) else t.date()


def _kobo_status(v):
    if pd.isna(v):
        return None
    s = str(v).lower().replace(" ", "_")
    for k in ("not_approved", "on_hold", "approved"):   # check 'not_approved' before 'approved'
        if k in s:
            return KOBO_STATUS[k]
    return None


def _f(code, sev, text):
    return {"code": code, "severity": sev, "text": text}


def is_test(g, approved_ids=()):
    """Rule 11: a record is TEST if Kobo marks it so, or any ID says TEST. Test records never reach metrics.
    Exception: an ID listed in config/alert_id_map.csv or config/field_id_map.csv was approved by a person as the
    real ID of a real visit, so the word TEST inside it does not make the record a test. record_type=test always wins."""
    if str(g.get("record_type") or "").strip().lower() == "test":
        return True
    for k in ("alert_id", "field_id", "verifier_id"):
        v = g.get(k)
        if isinstance(v, str) and exact_id(v) not in approved_ids and norm_id(v) not in approved_ids and re.search(r"(^|[^A-Z])TEST([^A-Z]|$)", v.upper()):
            return True
    return False


def check_record(g, cfg, field_map, issued, today, alert_map=None):
    """g: dict of one submission. Returns (flags, context dict)."""
    v, flags, ctx = cfg["validation"], [], {}
    alert_map = alert_map or {}
    gv = lambda k: None if pd.isna(g.get(k)) else g.get(k)

    if is_test(g, set(alert_map) | set(field_map)):
        flags.append(_f("TEST_RECORD", "info", "TEST record: excluded from evaluation (rule 11; never present test data as field observations)"))

    # --- identifiers and matching
    aid, fid = gv("alert_id"), gv("field_id")
    alias = alert_map.get(exact_id(aid)) if aid else None
    if alias:
        flags.append(_f("ALERT_ID_ALIAS", "info", f"Kobo alert ID '{aid}' linked to {alias['alert_id']} by "
                        f"config/alert_id_map.csv (approved {alias.get('approved_on') or 'n/a'} "
                        f"by {alias.get('approved_by') or 'n/a'}); the Kobo record itself is unchanged"))
        ctx["kobo_alert_id"] = aid
        aid = alias["alert_id"]
    if not aid or not fid:
        flags.append(_f("ID_MISSING", "error", "Alert ID or Field ID missing"))
    mapped = field_map.get(norm_id(fid)) if fid else None
    ctx["field_id_pipeline"] = mapped
    if fid and not mapped:
        flags.append(_f("FIELD_UNMAPPED", "error", f"Field ID '{fid}' is not in the field ID map"))
    ctx["matched_alert_id"] = None
    if aid and issued is not None and len(issued):
        hit = issued[issued["alert_key"] == norm_id(aid)]
        if len(hit):
            a = hit.iloc[0]
            # rule 10: link by alert ID + field ID and carry the ORIGINAL prediction alongside the observation
            ctx.update(matched_alert_id=a["alert_id"], alert_level=a["alert_level"], alert_date_issued=a["alert_date"],
                       field_id_pipeline=mapped or a["field_id"],
                       prediction_outcome=a.get("outcome"), prediction_risk_level=a.get("risk_level"),
                       prediction_data_confidence=a.get("data_confidence"),
                       prediction_model_version=a.get("model_version"))
            if mapped and mapped != a["field_id"]:
                flags.append(_f("ALERT_FIELD_MISMATCH", "error", f"Alert {a['alert_id']} belongs to {a['field_id']}, not {mapped}"))
            ok = L.RISK_TO_LEVELS.get(gv("system_risk"))
            if ok and a["alert_level"] not in ok:
                flags.append(_f("RISK_MISMATCH", "warning", f"Form says '{gv('system_risk')}', issued prediction is "
                                                           f"'{a['alert_level']}' (the issued prediction is kept)"))
        else:
            sug = None
            if mapped:
                c = issued[issued["field_id"] == mapped]
                sug = c.iloc[-1]["alert_id"] if len(c) else None
            flags.append(_f("ALERT_NOT_FOUND", "error",
                            f"Alert ID '{aid}' not in issued alerts" + (f" (did you mean {sug}?)" if sug else "")))

    # --- permission
    perm = gv("permission")
    if perm is None:
        flags.append(_f("PERMISSION_MISSING", "error", "Permission question not answered"))
    if perm == "no":
        flags.append(_f("NO_PERMISSION", "info", "Permission refused: kept only to document non-participation"))
        if any(gv(k) for k in OBS_FIELDS):
            flags.append(_f("NO_PERMISSION_OBS", "error", "Observations or photos recorded although permission was refused"))
        return flags, ctx

    # --- required content (SOP 7)
    if gv("maize_main") == "no":
        flags.append(_f("NOT_MAIZE", "error", "Maize is not the main crop observed"))
    if not gv("maize_stage"):
        flags.append(_f("STAGE_MISSING", "error", "Growth stage not recorded (use Unknown if unsure)"))
    if not gv("overall_condition") or not gv("soil_condition"):
        flags.append(_f("EVIDENCE_MISSING", "error", "Crop or soil observations missing"))
    if any(not gv(k) for k in ALT_FIELDS):
        flags.append(_f("ALT_CAUSES_MISSING", "error", "Alternative causes not all considered"))
    verdict, reason = gv("field_verdict"), gv("verdict_reason")
    if not verdict:
        flags.append(_f("VERDICT_MISSING", "error", "No verdict selected"))
    if not reason or len(str(reason).strip()) < v["min_reason_chars"]:
        flags.append(_f("REASON_SHORT", "error", f"Verdict reason missing or under {v['min_reason_chars']} characters"))
    if not gv("crop_photo") or not gv("soil_photo"):
        flags.append(_f("PHOTO_MISSING", "warning", "Crop and/or soil photo missing"))

    # --- consistency
    stage, cause = gv("maize_stage"), gv("main_cause")
    if gv("flowering_concern") == "yes" and stage in L.EARLY_STAGES:
        flags.append(_f("FLOWERING_STAGE", "error", "Flowering/grain-development concern at an early growth stage"))
    if (gv("irrigation_type") == "rainfed" and gv("irrigation_operating") == "yes") or \
       (gv("water_source") == "no" and gv("irrigation_operating") == "yes"):
        flags.append(_f("IRRIG_CONFLICT", "error", "Irrigation operating but field is rain-fed or no usable water source"))
    soil = gv("soil_condition")
    if (soil == "waterlogged" and gv("waterlogging") == "no") or (soil in L.DRY_SOIL and gv("waterlogging") == "yes"):
        flags.append(_f("SOIL_WATERLOG", "error", "Soil condition conflicts with waterlogging answer"))
    if verdict == "confirmed" and cause not in ("drought_stress", "mixed"):
        flags.append(_f("VERDICT_CAUSE", "error", "Confirmed, but main cause is not drought-related or mixed"))
    if verdict == "rejected" and cause == "drought_stress":
        flags.append(_f("VERDICT_CAUSE", "error", "Rejected, but main cause is drought-related moisture stress"))
    if verdict == "confirmed":
        signs = (gv("leaf_rolling") not in (None, "none")) or (gv("leaf_drying") not in (None, "none")) \
                or gv("moisture_stress") == "yes" or soil in L.DRY_SOIL
        if not signs:
            flags.append(_f("CONFIRMED_NO_SIGNS", "error", "Confirmed, but no stress signs recorded"))

    # --- privacy
    for k in TEXT_FIELDS:
        t = gv(k)
        if t and (PHONE.search(str(t)) or EMAIL.search(str(t))):
            flags.append(_f("PRIVACY", "error", f"Possible phone number or email in '{k}'"))

    # --- dates
    visit, adate = _d(gv("visit_date")), _d(gv("alert_date")) or _d(ctx.get("alert_date_issued"))
    ctx["visit_date"], ctx["alert_date_used"] = visit, adate
    if visit is None:
        flags.append(_f("DATE_MISSING", "error", "Visit date missing"))
    else:
        if visit > today:
            flags.append(_f("DATE_FUTURE", "error", "Visit date is in the future"))
        if adate is None:
            flags.append(_f("ALERT_DATE_MISSING", "warning", "No alert date; verification lag cannot be computed"))
        else:
            lag = (visit - adate).days
            ctx["lag_days"] = lag
            if lag < 0:
                flags.append(_f("DATE_ORDER", "error", "Visit is before the alert date"))
            elif lag > v["max_alert_to_visit_days"]:
                flags.append(_f("LATE_VISIT", "warning", f"Visit {lag} days after alert (limit {v['max_alert_to_visit_days']})"))
        pd_ = _d(gv("planting_date"))
        if pd_ and pd_ > visit:
            flags.append(_f("PLANTING_AFTER_VISIT", "error", "Planting date after visit date"))
    return flags, ctx


def suggest_status(flags):
    codes = {f["code"] for f in flags}
    if codes & REJECT_CODES:
        return "Rejected for analysis"
    if any(f["severity"] == "error" for f in flags):
        return "Needs review"
    return "Accepted"


def process_records(df, cfg, field_map, issued, today=None, alert_map=None):
    today = today or dt.date.today()
    alert_map = alert_map or {}
    approved = set(alert_map) | set(field_map)
    if issued is not None and len(issued):
        issued = issued.assign(alert_key=issued["alert_id"].map(norm_id))
    rows = []
    for g in df.to_dict("records"):
        flags, ctx = check_record(g, cfg, field_map, issued, today, alert_map)
        sugg = suggest_status(flags)
        human = _kobo_status(g.get("_validation_status"))
        final = human or sugg
        test = is_test(g, approved)
        real = g.get("record_type") == "real_visit" and not test
        rows.append({**g, **ctx, "is_test": test, "flags": flags, "flag_codes": ";".join(f["code"] for f in flags),
                     "suggested_status": sugg, "validation_status_final": final,
                     "status_source": "Kobo validation (human)" if human else "automatic suggestion",
                     "analysis_eligible": bool(real and final == "Accepted" and ctx.get("matched_alert_id")
                                                and (human or not cfg["validation"]["require_human_status"])
                                                and g.get("permission") == "yes" and g.get("field_verdict") in L.VERDICT)})
    return pd.DataFrame(rows)
