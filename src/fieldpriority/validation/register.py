"""Export processed Kobo records in the exact column layout of FieldPriority_Validation_Register_v1.xlsx."""
import pandas as pd
from . import labels as L

COLUMNS = ["Alert ID", "Field ID", "Record Type", "District", "Camp / Ward / Cooperative", "Alert Date",
           "Field Visit Date", "System Risk Level", "Maize Growth Stage", "Ground Verdict", "Main Stress Signs",
           "Alternative Cause", "Photo Available", "Data Quality Status", "Recommended Action", "Verifier ID", "Notes"]


def _signs(r):
    s = []
    for k, name in [("leaf_rolling", "leaf rolling"), ("leaf_drying", "leaf drying")]:
        if r.get(k) not in (None, "none") and pd.notna(r.get(k)):
            s.append(f"{name} ({r[k]})")
    if r.get("moisture_stress") == "yes":
        s.append("visible moisture stress")
    if r.get("stunted_growth") == "yes":
        s.append("stunted/uneven growth")
    if r.get("soil_condition") in L.DRY_SOIL:
        s.append(f"{str(r['soil_condition']).replace('_', ' ')} soil")
    return "; ".join(s)


def _photo(r):
    if r.get("permission") == "no":
        return "Not applicable"
    return "Yes" if (pd.notna(r.get("crop_photo")) or pd.notna(r.get("soil_photo"))) else "No"


def to_register(rec):
    rows = []
    for r in rec.to_dict("records"):
        notes = "; ".join(f"{f['code']}: {f['text']}" for f in r["flags"] if f["severity"] in ("error", "warning"))
        rows.append({
            "Alert ID": r.get("alert_id"), "Field ID": r.get("field_id_pipeline") or r.get("field_id"),
            "Record Type": "TEST" if r.get("is_test") else L.RECORD_TYPE.get(r.get("record_type")),
            "District": r.get("district"), "Camp / Ward / Cooperative": r.get("camp"),
            "Alert Date": r.get("alert_date") if pd.notna(r.get("alert_date")) else r.get("alert_date_issued"),
            "Field Visit Date": r.get("visit_date"),
            # rule 10: the issued (original) prediction, not what the verifier typed
            "System Risk Level": (r.get("prediction_risk_level") if isinstance(r.get("prediction_risk_level"), str)
                                  else L.RISK.get(r.get("system_risk"))),
            "Maize Growth Stage": L.STAGE.get(r.get("maize_stage")),
            "Ground Verdict": L.VERDICT.get(r.get("field_verdict")),
            "Main Stress Signs": _signs(r), "Alternative Cause": L.ALT_CAUSE.get(r.get("main_cause")),
            "Photo Available": _photo(r), "Data Quality Status": r["validation_status_final"],
            "Recommended Action": L.NEXT_STEP.get(r.get("next_step")), "Verifier ID": r.get("verifier_id"),
            "Notes": notes})
    return pd.DataFrame(rows, columns=COLUMNS)
