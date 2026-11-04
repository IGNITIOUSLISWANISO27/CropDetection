import pandas as pd
import streamlit as st
from _lib import (get_data, page_title, section, kpi, html_block, badge, src_tag, visits, verification_status,
                  status_by_field, field_location, period_text, period_year, sort_by_risk, build_map, show_map,
                  trend_chart, issue_labels, empty, icon, attachments, RISK, RISK_ORDER, E, C)

data = get_data()
A = data.assessments
V = visits(data)
status = status_by_field(data)
qp_field = st.query_params.get("field")


# ================================================================ field profile
def profile(fid):
    r = A[A["field_id"] == fid].iloc[0].to_dict()
    loc = field_location(data, fid)
    area = data.fields.set_index("Field_ID").loc[fid, "area_ha"]
    ex = r.get("explanation") or {}
    stat = verification_status(data, r["alert_id"])
    if st.button("Back to all assessments", icon=":material/arrow_back:"):
        st.query_params.clear()
        st.rerun()
    html_block(f'<div class="fp-eyebrow">Field profile</div><div class="fp-title"><h1>{E(fid)}</h1>'
               f'{badge(r["risk_level"], large=True)}</div>'
               f'<p class="fp-lead">{E(str(r["outcome"]))}. {E(RISK.get(r["risk_level"], {}).get("means", ""))}</p>')
    c = st.columns(4)
    for col, (lab, val, tip) in zip(c, [
            ("Risk level", RISK.get(r["risk_level"], {}).get("short", r["risk_level"]),
             "Calculated from satellite and climate data with the drought-stress rules."),
            ("Data confidence", r["data_confidence"], "How well the data supports the result. It is not tested accuracy."),
            ("Field verification", stat, "What a verifier found in the field. Kept separate from the prediction."),
            ("Growth stage", r.get("growth_stage_label") or "Unknown", f"Source: {r.get('growth_stage_source')}")]):
        col.metric(lab, val, help=tip)

    # ---- geography
    section("Geographical overview", "pin")
    g1, g2 = st.columns([1.6, 1], gap="large")
    with g1:
        show_map(build_map(data, A=A[A["field_id"] == fid], basemap="Satellite", focus=fid), height=360)
    with g2:
        gtype = "Field-boundary polygon" if loc["geom_type"] in ("Polygon", "MultiPolygon") else "Location point only"
        html_block(f"""<div class="fp-card"><div class="fp-kv">
<div>Field ID</div><div>{E(fid)}</div>
<div>Location</div><div>{E(loc["district"])}</div>
<div>Centre (lat, lon)</div><div>{loc["lat"]:.6f}, {loc["lon"]:.6f} {src_tag("calc")}</div>
<div>Geometry</div><div>{gtype}{"" if loc["valid"] else " (invalid shape)"} {src_tag("est")}</div>
<div>Area</div><div>{area:.2f} ha {src_tag("est")}</div>
<div>Assessment period</div><div>{E(period_text(data))}</div>
<div>Data up to</div><div>{E(str(r.get("data_end_date")))}</div>
<div>Alert ID</div><div>{E(str(r["alert_id"]))}</div>
</div><div class="fp-sub" style="margin-top:.7rem">The boundary was digitised from imagery and is an estimate
until checked on the ground. The centre point is calculated from it.</div></div>""")

    # ---- crop + assessment summary
    section("Crop and assessment summary", "leaf")
    s1, s2 = st.columns([1, 1], gap="large")
    mine = V[V["field_id_pipeline"] == fid] if len(V) and "field_id_pipeline" in V else pd.DataFrame()
    planting = None
    if len(mine) and "planting_date" in mine and mine["planting_date"].notna().any():
        planting = str(mine["planting_date"].dropna().iloc[-1])
    with s1:
        html_block(f"""<div class="fp-card"><h4>Crop information</h4><div class="fp-kv">
<div>Crop</div><div>Maize</div>
<div>Growth stage (system)</div><div>{E(str(r.get("growth_stage_label") or "Unknown"))} {src_tag("calc")}</div>
<div>Planting date</div><div>{E(planting) + " " + src_tag("obs") if planting else "Not recorded in the system yet"}</div>
<div>Stage seen by verifier</div><div>{E(str(mine["maize_stage"].dropna().iloc[-1]).replace("_", " ")) + " " + src_tag("obs") if len(mine) and "maize_stage" in mine and mine["maize_stage"].notna().any() else "No visit yet"}</div>
</div></div>""")
    with s2:
        nxt = r.get("next_action") or ""
        html_block(f"""<div class="fp-card"><h4>Result {src_tag("calc")}</h4>
<div style="margin:.3rem 0 .6rem">{badge(r["risk_level"])}</div>
<div class="fp-sub" style="color:{C['ink']}">{E(str(r["outcome"]))}</div>
<div style="margin-top:.7rem"><b>Recommended follow-up:</b> {E(str(nxt))}</div></div>""")
    ind = ex.get("indicators") or []
    if ind:
        st.markdown("**Indicators compared with their baselines** "
                    + src_tag("calc"), unsafe_allow_html=True)
        t = pd.DataFrame(ind)[["indicator", "scale", "value", "baseline", "change", "finding", "contributed"]]
        t.columns = ["Indicator", "Scale", "Value", "Baseline", "Change", "Finding", "Used for the result"]
        st.dataframe(t, hide_index=True, width="stretch")
    if r.get("missing_data"):
        st.warning("**Missing information:** " + "; ".join(r["missing_data"]))
    if r.get("data_confidence_issues"):
        with st.expander("Why data confidence is not higher"):
            for x in r["data_confidence_issues"]:
                st.markdown(f"- {x}")
    if ex.get("context"):
        with st.expander("Whole-year and radar values (context only, not used by the rules)"):
            for x in ex["context"]:
                st.markdown(f"- {x}")

    # ---- indicators over time
    section("Indicators over time", "rise")
    yr = period_year(data)
    cc = st.columns(2)
    for col, args in zip([cc[0], cc[1], cc[0], cc[1]], [
            ("ndvi", "Crop greenness (NDVI, Sentinel-2, 10 m)", "NDVI", False),
            ("rainfall_anomaly", "Rainfall versus its 10-year normal (regional cell)", "mm per month", True),
            ("soil_moisture", "Soil moisture (regional cell)", "Volumetric", False),
            ("temperature", "Temperature (regional cell)", "°C", False)]):
        ch = trend_chart(data.monthly, args[0], fid, args[1], args[2], yr, bars=args[3])
        if ch is not None:
            col.altair_chart(ch, width="stretch")

    # ---- field visits and photos
    section("Field visits and photographs", "camera",
            "What verifiers recorded in KoboToolbox. Observations are shown as submitted; the system's prediction is "
            "never changed by them (rule 10).")
    if mine.empty:
        empty(f"No field visit recorded for {E(fid)} yet. Verifiers should use Field ID <b>{E(fid)}</b> and Alert ID "
              f"<b>{E(str(r['alert_id']))}</b> in the Kobo form.")
    for v in mine.sort_values("visit_date").to_dict("records") if len(mine) else []:
        verdict = {"confirmed": "Confirmed drought stress", "rejected": "No drought stress",
                   "uncertain": "Uncertain"}.get(str(v.get("field_verdict")), str(v.get("field_verdict")))
        obs = [("Overall condition", v.get("overall_condition")), ("Area affected", v.get("affected_area")),
               ("Leaf rolling", v.get("leaf_rolling")), ("Leaf drying", v.get("leaf_drying")),
               ("Stunted growth", v.get("stunted_growth")), ("Soil condition", v.get("soil_condition")),
               ("Pests", v.get("pest_damage")), ("Disease", v.get("disease_symptoms")),
               ("Weeds", v.get("weed_pressure")), ("Main cause", v.get("main_cause"))]
        nice = {"p0_25": "0 to 25%", "p25_50": "25 to 50%", "p50_75": "50 to 75%", "p75_100": "75 to 100%"}
        kv = "".join(f"<div>{E(k)}</div><div>{E(nice.get(str(x), str(x).replace('_', ' ')))}</div>"
                     for k, x in obs if x not in (None, "") and str(x) != "nan")
        html_block(f"""<div class="fp-card" style="margin-bottom:12px">
<div style="display:flex;justify-content:space-between;flex-wrap:wrap;gap:6px"><h4>Visit on {E(str(v.get("visit_date")))} {src_tag("obs")}</h4>
<span class="fp-sub">Verifier {E(str(v.get("verifier_id") or "n/a"))} · status {E(str(v.get("validation_status_final")))}</span></div>
<div style="margin:.4rem 0 .7rem"><b>Verifier's verdict:</b> {E(verdict)} {src_tag("ver") if v.get("analysis_eligible") else ""}</div>
<div class="fp-kv">{kv}</div>
{f'<p style="margin-top:.8rem"><b>Reason:</b> {E(str(v.get("verdict_reason")))}</p>' if v.get("verdict_reason") else ""}
{f'<p class="fp-sub">Crop notes: {E(str(v.get("crop_comments")))}</p>' if v.get("crop_comments") else ""}
{f'<p class="fp-sub">Soil and water notes: {E(str(v.get("soil_water_comments")))}</p>' if v.get("soil_water_comments") else ""}
</div>""")
        att = attachments(v)
        if att:
            pc = st.columns(min(3, len(att)))
            for col, a in zip(pc * 3, att):
                with col:
                    html_block(f'<div class="fp-photo">{icon("camera", 20, C["forest"])} '
                               f'<b>{"Crop photo" if a.get("media_file_basename") == v.get("crop_photo") else "Soil photo" if a.get("media_file_basename") == v.get("soil_photo") else "Photo"}</b>'
                               f'<div class="fp-sub" style="word-break:break-all">{E(str(a.get("media_file_basename")))}</div>'
                               f'<a href="{E(str(a.get("download_medium_url") or a.get("download_url")))}" target="_blank">'
                               f'Open in KoboToolbox</a> <span class="fp-sub">(KoboToolbox sign-in needed)</span></div>')
        if v.get("flag_codes"):
            st.caption("Data checks: " + issue_labels(v.get("flag_codes")))

    # ---- history
    section("Assessment history", "clock", "Every prediction issued for this field, unchanged since it was issued.")
    L = data.ledger if data.ledger is not None else pd.DataFrame()
    h = L[L["field_id"] == fid].sort_values("issued_at") if len(L) and "field_id" in L else pd.DataFrame()
    if h.empty:
        empty("No history yet.")
    else:
        t = h[["alert_date", "alert_id", "risk_level", "outcome", "data_confidence", "data_end_date", "model_version"]].copy()
        t.columns = ["Issued", "Alert ID", "Risk level", "Result", "Data confidence", "Data up to", "Model"]
        st.dataframe(t, hide_index=True, width="stretch")
        if h["data_end_date"].nunique() < 2:
            st.caption("All entries use the same data period, so there is no change over time to show yet.")


if qp_field and qp_field in set(A["field_id"]):
    profile(qp_field)
    st.stop()

# ================================================================ list of assessments
page_title("Assessments", "Every field the system has assessed, with its drought-risk class and verification "
           "status, and every field visit received through KoboToolbox. Open a record to see the full field profile.",
           eyebrow="Field assessment records", icon_name="clipboard")

stat = A["field_id"].map(status)
verified = int(stat.str.startswith("Verified").sum())
pending = int((stat == "Not yet verified").sum() + (stat == "Visit submitted, under review").sum())
needs = int((A["risk_level"] == "Insufficient data").sum() + (A["missing_data"].map(len) > 0).sum()
            - ((A["risk_level"] == "Insufficient data") & (A["missing_data"].map(len) > 0)).sum())
c = st.columns(4)
c[0].markdown(kpi("clipboard", "Fields assessed", f"{len(A)}", f"Satellite assessments in the latest run ({E(period_text(data))})."), unsafe_allow_html=True)
c[1].markdown(kpi("check", "Verified", f"{verified}", "With an approved field visit linked to the alert."), unsafe_allow_html=True)
c[2].markdown(kpi("clock", "Pending verification", f"{pending}", "No approved visit yet."), unsafe_allow_html=True)
c[3].markdown(kpi("dash", "Need more information", f"{needs}", "Missing inputs; shown as Insufficient data, never Low."), unsafe_allow_html=True)

tab1, tab2 = st.tabs(["System assessments", f"Field visits (KoboToolbox) · {len(V)}"])
with tab1:
    f1, f2, f3 = st.columns([1.4, 1.4, 1.2])
    q = f1.text_input("Search field ID", placeholder="e.g. F001", key="q_assess")
    risk_f = f2.multiselect("Risk class", [k for k in RISK_ORDER if (A["risk_level"] == k).any()],
                            format_func=lambda k: RISK[k]["short"], placeholder="All")
    stat_f = f3.selectbox("Verification", ["All", "Verified", "Pending", "Under review"])
    t = sort_by_risk(A).copy()
    t["Verification"] = t["field_id"].map(status)
    t["Location"] = t["field_id"].map(lambda f: field_location(data, f)["district"])
    if q:
        t = t[t["field_id"].str.contains(q.strip(), case=False, na=False)]
    if risk_f:
        t = t[t["risk_level"].isin(risk_f)]
    if stat_f != "All":
        t = t[t["Verification"].str.startswith({"Verified": "Verified", "Pending": "Not yet", "Under review": "Visit"}[stat_f])]
    show = t[["field_id", "risk_level", "outcome", "data_confidence", "Verification", "Location", "assessment_date", "alert_id"]]
    show.columns = ["Field ID", "Risk class", "Result", "Data confidence", "Verification", "Location", "Assessed for", "Alert ID"]
    if show.empty:
        empty("No assessment matches these filters.")
    else:
        ev = st.dataframe(show, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row",
                          key="tbl_assess")
        st.caption("Select a row to open the field profile.")
        rows = ev.selection.rows if ev and hasattr(ev, "selection") else []
        if rows:
            st.query_params["field"] = show.iloc[rows[0]]["Field ID"]
            st.rerun()

with tab2:
    if V.empty:
        empty("No field visits received yet. Test records are excluded by design.")
    else:
        q2 = st.text_input("Search field or alert ID", key="q_visit")
        t = V.copy()
        t["Field"] = t.get("field_id_pipeline", t.get("field_id"))
        if q2:
            m = t["Field"].astype(str).str.contains(q2, case=False) | t["alert_id"].astype(str).str.contains(q2, case=False)
            t = t[m]
        t["Verdict"] = t["field_verdict"].map({"confirmed": "Confirmed", "rejected": "Rejected", "uncertain": "Uncertain"}).fillna(t["field_verdict"])
        t["Checks"] = t["flag_codes"].map(issue_labels)
        cols = {"Field": "Field ID", "visit_date": "Visit date", "district": "Location", "verifier_id": "Verifier",
                "Verdict": "Verdict", "validation_status_final": "Status", "alert_id": "Alert ID (as typed)",
                "matched_alert_id": "Linked alert", "Checks": "Data checks"}
        show = t[[c for c in cols if c in t]].rename(columns=cols)
        ev = st.dataframe(show, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row", key="tbl_visit")
        st.caption("Original Kobo answers are kept unchanged; 'Linked alert' is the system's link to the issued prediction.")
        rows = ev.selection.rows if ev and hasattr(ev, "selection") else []
        if rows and show.iloc[rows[0]]["Field ID"] in set(A["field_id"]):
            st.query_params["field"] = show.iloc[rows[0]]["Field ID"]
            st.rerun()
