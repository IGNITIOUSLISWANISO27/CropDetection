import pandas as pd
import streamlit as st
from _lib import (get_data, page_title, section, kpi, html_block, badge, visits, field_location, status_by_field,
                  issue_label, empty, icon, attachments, ISSUE_KIND, CFG, E, C)

data = get_data()
A = data.assessments
V = visits(data)
Vall = visits(data, include_test=True)
m = data.metrics or {}
status = status_by_field(data)
page_title("Data Quality and Verification", "How complete and reliable the field information is.",
           eyebrow="Transparency", icon_name="check")

complete = A[A["missing_data"].map(len) == 0] if len(A) else A
incomplete = A[A["missing_data"].map(len) > 0] if len(A) else A
unverified = [f for f, s in status.items() if not s.startswith("Verified")]
c = st.columns(5)
c[0].markdown(kpi("layers", "Records", f"{len(A) + len(V)}", f"{len(A)} field assessments + {len(V)} field visits "
                  f"({len(Vall) - len(V)} test records excluded)."), unsafe_allow_html=True)
c[1].markdown(kpi("check", "Complete", f"{len(complete)}", "Assessments with every input the rules need."), unsafe_allow_html=True)
c[2].markdown(kpi("dash", "Incomplete", f"{len(incomplete)}", "Missing an input; shown as Insufficient data."), unsafe_allow_html=True)
c[3].markdown(kpi("clock", "Need verification", f"{len(unverified)}", "No approved field visit yet."), unsafe_allow_html=True)
low_conf = int((A["data_confidence"] == "Low").sum()) if len(A) else 0
c[4].markdown(kpi("gauge", "Low confidence", f"{low_conf}", "Assessments whose data support is weak."), unsafe_allow_html=True)

# ---------------------------------------------------------------- per field
section("Field-by-field checks", "field", "Each problem is explained. <b>Missing</b> = information not provided; "
        "<b>Invalid</b> = provided but not usable; <b>Not verified</b> = not yet checked in the field.")
rows = []
for r in A.to_dict("records"):
    fid = r["field_id"]
    loc = field_location(data, fid)
    area = float(data.fields.set_index("Field_ID").loc[fid, "area_ha"])
    probs = []
    if loc["geom_type"] not in ("Polygon", "MultiPolygon"):
        probs.append(("Missing", "Only a location point, no field-boundary polygon: crop greenness cannot be measured for the field."))
    elif not loc["valid"]:
        probs.append(("Invalid", "The boundary polygon is not a valid shape (for example it crosses itself). Redraw it in QGIS."))
    if area < 0.1:
        probs.append(("Invalid", f"Very small field ({area:.2f} ha, a few 10 m satellite pixels): edge pixels such as roads "
                                 "or trees can dominate the greenness value. Check the outline in QGIS."))
    probs.append(("Not verified", "The boundary is digitised from imagery and has not been checked on the ground."))
    if (r.get("growth_stage") or "unknown") == "unknown":
        probs.append(("Missing", "No planting date or observed growth stage in the system, so the crop period is unknown "
                                 "and maturity drying cannot be ruled out (rule 6)."))
    for x in r.get("missing_data") or []:
        probs.append(("Missing", x))
    for x in r.get("data_confidence_issues") or []:
        if "Small field" not in x and "Growth stage unknown" not in x:
            probs.append(("Limitation", x))
    if not status.get(fid, "").startswith("Verified"):
        probs.append(("Not verified", "No approved field visit linked to this field's alert."))
    rows.append((fid, r, probs, area, loc))

kind_col = {"Missing": "#B9342B", "Invalid": "#DB7A1F", "Not verified": "#6A4C93", "Limitation": "#5E6B63"}
for fid, r, probs, area, loc in rows:
    items = "".join(f'<li style="margin:4px 0"><span class="fp-src" style="background:{kind_col[k]}1A;color:{kind_col[k]}">'
                    f'{k}</span> {E(t)}</li>' for k, t in probs)
    geo = ("Field-boundary polygon" if loc["geom_type"] in ("Polygon", "MultiPolygon") else "Location point only")
    html_block(f'<div class="fp-card" style="margin-bottom:10px"><div style="display:flex;gap:10px;align-items:center;'
               f'flex-wrap:wrap"><h4 style="margin:0">{E(fid)}</h4>{badge(r["risk_level"])}'
               f'<span class="fp-sub">Data confidence: <b>{E(r["data_confidence"])}</b> · {geo} · {area:.2f} ha</span></div>'
               f'<ul style="margin:.6rem 0 0 1rem;padding:0">{items}</ul></div>')

# ---------------------------------------------------------------- Kobo records
section("Field-visit records (KoboToolbox)", "clipboard",
        "Automatic checks on every submission. A record counts for evaluation only when it is a real visit, passes "
        "the checks, is linked to an issued alert and has been approved by the validation lead.")
if Vall.empty:
    empty("No submissions yet.")
else:
    t = Vall.copy()
    def kinds(codes):
        cs = [c for c in str(codes).split(";") if c and c != "nan"]
        out = []
        for k, lab in [("missing", "Missing"), ("invalid", "Invalid")]:
            hit = [issue_label(c) for c in cs if c in ISSUE_KIND[k]]
            if hit:
                out.append(f"{lab}: " + ", ".join(hit))
        other = [issue_label(c) for c in cs if c not in ISSUE_KIND["missing"] | ISSUE_KIND["invalid"]]
        if other:
            out.append("Note: " + ", ".join(other))
        return " | ".join(out) or "No problems found"
    t["Problems"] = t["flag_codes"].map(kinds)
    t["GPS point"] = t["_geolocation"].map(lambda g: "Yes" if isinstance(g, (list, tuple)) and len(g) == 2 and g[0] is not None else "No") \
        if "_geolocation" in t else "No"
    t["Photos"] = t["_attachments"].map(lambda a: len(attachments(a))) if "_attachments" in t else 0
    t["Type"] = t["record_type"].map({"real_visit": "Real visit", "test": "Test (excluded)"}).fillna(t["record_type"])
    t["Usable for evaluation"] = t["analysis_eligible"].fillna(False).astype(bool).map({True: "Yes", False: "No"})
    cols = {"field_id": "Field ID (typed)", "visit_date": "Visit date", "Type": "Type", "GPS point": "GPS point",
            "Photos": "Photos", "validation_status_final": "Status", "Usable for evaluation": "Usable for evaluation",
            "Problems": "Problems found"}
    st.dataframe(t[[c for c in cols if c in t]].rename(columns=cols), hide_index=True, width="stretch")
    st.caption("Test records never count (rule 11). Original Kobo answers are never edited by the system.")

# ---------------------------------------------------------------- verification performance
section("Verification performance", "gauge", "How often alerts matched what verifiers found. Only High and Moderate "
        "alerts can be scored as correct or false.")


def pct(x):
    if not x or x.get("value") is None:
        return "n/a"
    lo, hi = (x.get("ci95") or [None, None])
    rng = f"; 95% range {lo*100:.0f} to {hi*100:.0f}%" if lo is not None else ""
    return f"{x['value']*100:.0f}% ({x['k']} of {x['n']}{rng})"


k = st.columns(4)
k[0].metric("Submissions", m.get("records_total", len(Vall)))
k[1].metric("Real visits", m.get("records_real", len(V)))
k[2].metric("Accepted for analysis", m.get("records_eligible", 0))
k[3].metric("Test records (excluded)", m.get("records_test", 0))
if m.get("correct_alerts") is None and m.get("status") in (None, "no_eligible_verifications"):
    html_block('<div class="fp-note">No accuracy figure yet: there are no approved visits to High or Moderate alerts. '
               'Results appear once verifiers visit flagged fields, the validation lead approves the records in '
               'KoboToolbox, and the validation step is run and synced.</div>')
else:
    k2 = st.columns(4)
    k2[0].metric("Correct alerts", m.get("correct_alerts"))
    k2[1].metric("False alerts", m.get("false_alerts"))
    k2[2].metric("Uncertain", m.get("uncertain_alerts"))
    k2[3].metric("Missed by the system", m.get("missed_detections"))
    st.markdown(f"**Share of verified alerts that were correct:** {pct(m.get('precision_correct_alert_rate'))}  \n"
                f"**Alerts verified:** {pct(m.get('verification_rate'))}")
    if m.get("status") == "descriptive_only" and m.get("message"):
        st.caption(m["message"])
