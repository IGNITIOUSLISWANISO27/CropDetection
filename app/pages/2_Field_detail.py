import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd
import streamlit as st
from _lib import (setup, chip, issue_labels, trend_chart, contribution_chart, verification_status, period_year,
                  drivers_text, sort_by_risk, REASON_TITLES, LABELS, COMPONENTS)

data = setup("Field detail")
A, M, S = data.assessments, data.monthly, data.season
order = sort_by_risk(A)["field_id"].tolist()
st.title("Field detail")
field = st.selectbox("Field", order, help="Ordered from highest to lowest risk level.")
r = A[A["field_id"] == field].iloc[0].to_dict()
f = data.fields.set_index("Field_ID").loc[field]
s = S[S["Field_ID"] == field].iloc[0].to_dict() if len(S) else {}
status = verification_status(data, r["alert_id"])
ex = r.get("explanation") or {}

st.markdown(f"### {field} &nbsp;{chip(r['risk_level'])}", unsafe_allow_html=True)
st.markdown(f"**{r['outcome']}**")
st.caption(f"Alert {r['alert_id']}. {f['area_ha']:.2f} ha. Conditions assessed for {r.get('assessment_date')}; "
           f"data up to {r.get('data_end_date')}.")
c = st.columns(4)
for col, (lab, val, tip) in zip(c, [
        ("Risk level", r["risk_level"], "What the satellite and climate data suggest, under the drought-stress rules."),
        ("Data confidence", r["data_confidence"], "How well the data supports the result. Not tested accuracy."),
        ("Field verification", status, "What a verifier found in the field. Kept separate from the prediction."),
        ("Growth stage", r.get("growth_stage_label") or "Unknown", f"Source: {r.get('growth_stage_source')}")]):
    col.caption(lab, help=tip)
    col.markdown(f"**{val}**")
ip = r.get("issued_prediction") or {}
if ip and (ip.get("outcome"), ip.get("risk_level")) != (r["outcome"], r["risk_level"]):
    st.info(f"The prediction issued for this alert was '{ip.get('outcome')}' ({ip.get('risk_level')}), on "
            f"{str(ip.get('issued_at'))[:10]}. It is kept unchanged for evaluation.")

tab1, tab2, tab3, tab4 = st.tabs(["Why this result", "Indicators over time", "Methods and context", "Field verification"])

with tab1:
    st.markdown("**What changed**")
    for w in ex.get("what_changed", []):
        st.markdown(f"- {w}")
    if r.get("missing_data"):
        st.markdown("**Missing data**")
        for m in r["missing_data"]:
            st.markdown(f"- {m}")
    ind = ex.get("indicators") or []
    if ind:
        st.markdown("**Indicators compared with their baselines**")
        t = pd.DataFrame(ind)[["indicator", "scale", "value", "baseline", "change", "finding", "contributed"]]
        t.columns = ["Indicator", "Scale", "Value", "Baseline", "Change", "Finding", "Contributed"]
        st.dataframe(t, hide_index=True, width="stretch")
    if ex.get("checks"):
        st.markdown("**What needs checking**")
        for x in ex["checks"]:
            st.markdown(f"- {x}")
    st.markdown("**Recommended next step**")
    st.write(r.get("next_action"))
    ctx = ex.get("context") or []
    if ctx:
        st.markdown("**Whole-year values (context only)**")
        for x in ctx:
            st.markdown(f"- {x}")
    if r.get("data_confidence_issues"):
        st.markdown("**Why data confidence is not higher**")
        for x in r["data_confidence_issues"]:
            st.markdown(f"- {x}")

with tab2:
    yr = period_year(data)
    shared = str(r.get("rain_shared_with") or "")
    cc = st.columns(2)
    for col, args in zip([cc[0], cc[1], cc[0], cc[1]], [
            ("ndvi", "Vegetation greenness (NDVI), monthly", "NDVI", False),
            ("rainfall_anomaly", "Rainfall anomaly versus 2015 to 2024 (regional cell)", "mm per month", True),
            ("soil_moisture", "Soil moisture (regional cell)", "Volumetric", False),
            ("temperature", "Temperature (regional cell)", "Degrees C", False)]):
        ch = trend_chart(M, args[0], field, args[1], args[2], yr, bars=args[3])
        if ch is not None:
            col.altair_chart(ch, width="stretch")
    st.caption("The selected field is highlighted. Grey lines are the other pilot fields."
               + (f" Rainfall, soil moisture and temperature are shared with {shared}." if shared else ""))
    ndvi = M[(M["variable"] == "ndvi") & (M["Field_ID"] == field) & (M["month"] > 0)].sort_values("month")
    if len(ndvi):
        t = ndvi[["month", "mean", "valid_fraction"]].copy()
        t["month"] = t["month"].map(lambda m: f"{yr}-{int(m):02d}")
        t.columns = ["Month", "NDVI", "Cloud-free pixels"]
        st.dataframe(t, hide_index=True, width="content", column_config={
            "NDVI": st.column_config.NumberColumn(format="%.3f"),
            "Cloud-free pixels": st.column_config.ProgressColumn(min_value=0, max_value=1, format="percent")})
        if (t["Cloud-free pixels"] < 0.5).any():
            st.warning("At least one month has under half of the field's pixels usable, so its NDVI is less reliable.")

with tab3:
    st.markdown("**Legacy relative score (comparison only)**")
    st.caption("The v1 weighted score ranks the pilot fields against each other. It does not set the alert: "
               "the drought-stress rules do. One field always scores 1 and one 0 on each indicator, even if all are healthy.")
    if pd.isna(r.get("integrated_score")):
        st.write("Not computed: the legacy score ranks fields against each other and needs at least two fields with monthly data.")
    else:
        st.write(f"Legacy score {r['integrated_score']:.2f} ({r['priority']}). " + drivers_text(r))
    st.altair_chart(contribution_chart(r), width="stretch")
    with st.expander("Legacy reasons"):
        for x in r["reasons"]:
            st.markdown(f"**{REASON_TITLES.get(x['code'], x['code'])}.** {x['text']}")
    st.markdown("**How the legacy score is built**")
    rows = [{"Indicator": LABELS[c], "Score (0 to 1)": r.get(f"score_{c}"), "Weight": 0.25, "Adds": r.get(f"contrib_{c}")} for c in COMPONENTS]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", column_config={
        "Score (0 to 1)": st.column_config.NumberColumn(format="%.2f"), "Adds": st.column_config.NumberColumn(format="%.3f")})
    st.markdown("**Other methods, for comparison**")
    st.dataframe(pd.DataFrame([
        {"Method": "Primary (relative to pilot fields)", "Score": r["integrated_score"], "Class": r["priority"]},
        {"Method": f"Experimental fixed reference ({r.get('exp_components')}; provisional ranges)", "Score": r.get("exp_score"), "Class": r.get("exp_priority")},
        {"Method": "Earlier v1 workflow", "Score": r.get("v1_score"), "Class": r.get("v1_priority")}]),
        hide_index=True, width="stretch", column_config={"Score": st.column_config.NumberColumn(format="%.2f")})
    st.caption("If the methods disagree, treat the field as uncertain. The experimental method uses placeholder reference ranges until a multi-year baseline exists.")
    if s:
        st.markdown("**Context**")
        vv = s.get("s1_vv_db")
        if vv is None or pd.isna(vv):
            st.write("Sentinel-1 radar context was not supplied for this run (it is not part of the rules).")
        else:
            st.write(f"Sentinel-1 VV backscatter {vv:.1f} dB ({s.get('s1_vv_context')}). "
                 "Radar responds to roughness, canopy and moisture together, so it is context and not part of the score.")
        st.write(f"Climate cells: rainfall {r.get('rain_cell')}, soil moisture {r.get('sm_cell')}, temperature {r.get('temp_cell')}.")
    parts = {k: r.get(f"conf_{k}") for k in ("agreement", "data_quality", "size_support", "margin")}
    if any(v is not None and not pd.isna(v) for v in parts.values()):
        st.markdown("**What sits behind the confidence label**")
        st.dataframe(pd.DataFrame({"Part": ["Indicators agree", "Data quality", "Size of field in pixels", "Distance from class threshold"],
                                   "Value (0 to 1)": list(parts.values())}), hide_index=True, width="content",
                     column_config={"Value (0 to 1)": st.column_config.ProgressColumn(min_value=0, max_value=1, format="%.2f")})

with tab4:
    v = data.verifications
    mine = pd.DataFrame()
    if v is not None and len(v) and "field_id_pipeline" in v:
        mine = v[v["field_id_pipeline"] == field]
    show_test = st.checkbox("Include TEST records", value=False, key="t4")
    if len(mine) and not show_test:
        mine = mine[mine["record_type"] == "real_visit"]
    if mine.empty:
        st.info(f"No field visit recorded for {field} yet. Use Field ID {field} and Alert ID {r['alert_id']} in the Kobo form.")
    else:
        t = mine[["visit_date", "record_type", "field_verdict", "validation_status_final", "flag_codes"]].copy()
        t["flag_codes"] = t["flag_codes"].map(issue_labels)
        t.columns = ["Visit date", "Record type", "Verdict", "Status", "Issues found"]
        st.dataframe(t, hide_index=True, width="stretch")
