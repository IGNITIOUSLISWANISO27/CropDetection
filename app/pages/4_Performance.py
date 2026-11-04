import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import altair as alt
import pandas as pd
import streamlit as st
from _lib import setup, real_visits, issue_label, FIELD_COLOR, REGIONAL_COLOR

data = setup("Performance")
m = data.metrics or {}
V = data.verifications if data.verifications is not None else pd.DataFrame()
st.title("Performance against field verification")
st.write("How often the alerts matched what verifiers found in the field.")

c = st.columns(4)
c[0].metric("Submissions", m.get("records_total", len(V)))
c[1].metric("Real visits", m.get("records_real", len(real_visits(data))))
c[2].metric("Accepted for analysis", m.get("records_eligible", 0))
c[3].metric("Test records (excluded)", m.get("records_test", 0), help="Rule 11: TEST records never count.")

def pct(x):
    if not x or x.get("value") is None:
        return "n/a"
    lo, hi = (x.get("ci95") or [None, None])
    return f"{x['value']*100:.0f}% ({x['k']} of {x['n']}; 95% range {lo*100:.0f} to {hi*100:.0f}%)"

status = m.get("status")
if status in (None, "no_eligible_verifications"):
    st.info(m.get("message") or "No performance results yet.")
    st.markdown("""
Results appear once:
1. verifiers submit real visits in Kobo,
2. the validation lead sets each good record to Accepted in Kobo, and
3. the validation step is run and the results are synced.
""")
    st.caption("Alerts verified so far: " + pct(m.get("verification_rate")))
else:
    if status == "descriptive_only":
        st.warning(m.get("message"))
    k = st.columns(4)
    k[0].metric("Correct alerts", m.get("correct_alerts"), help="Alerts where the verifier confirmed stress.")
    k[1].metric("False alerts", m.get("false_alerts"), help="Alerts where the verifier rejected stress.")
    k[2].metric("Uncertain", m.get("uncertain_alerts"), help="Reported separately, never forced into yes or no.")
    k[3].metric("Missed by the system", m.get("missed_detections"), help="Stress confirmed on a field the system did not flag.")
    st.markdown(f"**Alerts verified:** {pct(m.get('verification_rate'))}  \n"
                f"**Share of verified alerts that were correct:** {pct(m.get('precision_correct_alert_rate'))}  \n"
                f"**Share of verified alerts that were false:** {pct(m.get('false_alert_rate'))}  \n"
                f"**Stress found that the system caught (recall):** {pct(m.get('recall'))}")
    lag = m.get("verification_lag_days")
    if lag:
        st.write(f"Time from alert to visit: median {lag['median']:.0f} days (range {lag['min']:.0f} to {lag['max']:.0f}). "
                 "This is not warning lead time, which would need the date stress began.")
    cf = m.get("confusion")
    if cf:
        st.markdown("**Alert against field finding**")
        st.dataframe(pd.DataFrame({"Stress confirmed": [cf["alert_confirmed"], cf["no_alert_confirmed"]],
                                   "Stress rejected": [cf["alert_rejected"], cf["no_alert_rejected"]]},
                                  index=["System alerted", "System did not alert"]), width="content")
    if m.get("by_alert_level"):
        st.markdown("**By alert level**")
        st.dataframe(pd.DataFrame(m["by_alert_level"]).T.rename(columns=str.capitalize), width="content")

# ---- quality of submissions (useful even before real visits)
st.subheader("Quality of submissions")
if V.empty or "flags" not in V:
    st.caption("No submissions loaded.")
else:
    show_test = st.checkbox("Include TEST records", value=True, key="pt")
    S = V if show_test else V[V["record_type"] == "real_visit"]
    rows = [{"Issue": issue_label(x["code"]), "Type": "Must fix" if x["severity"] == "error" else "Check"}
            for fl in S["flags"] for x in (fl or []) if x["severity"] in ("error", "warning")]
    if rows:
        d = pd.DataFrame(rows).value_counts().reset_index(name="Records")
        st.altair_chart(alt.Chart(d).mark_bar().encode(
            x=alt.X("Records:Q", axis=alt.Axis(tickMinStep=1)), y=alt.Y("Issue:N", sort="-x", title=None, axis=alt.Axis(labelLimit=240)),
            color=alt.Color("Type:N", scale=alt.Scale(domain=["Must fix", "Check"], range=["#B3261E", REGIONAL_COLOR]),
                            legend=alt.Legend(orient="bottom", title=None))).properties(height=34 * d["Issue"].nunique() + 110),
            width="stretch")
        st.caption("Frequent issues point to questions in the Kobo form that need clearer wording or a constraint.")
    else:
        st.success("No issues found in these submissions.")
    sc = S["validation_status_final"].value_counts()
    if len(sc):
        st.write("Status: " + ", ".join(f"{k} {v}" for k, v in sc.items()))

# ---- backtest against known past seasons (possible before any field visits)
st.subheader("Backtest against known past seasons")
import json, os
from _lib import ROOT, CFG
bt_path = Path(os.environ.get("FIELDPRIORITY_OUTPUTS") or ROOT / CFG["paths"]["output_dir"]) / "backtest" / "backtest_summary.json"
if not bt_path.exists():
    st.caption("No backtest yet. Run: python -m fieldpriority.backtest")
else:
    bt = json.loads(bt_path.read_text())
    st.write("The system is replayed month by month on past seasons whose outcome is known, using the same rules. "
             "A drought season should be flagged; a good season should stay quiet.")
    rows = [{"Season": f"{x['season']} {x.get('label') or ''}".strip(), "Known outcome": x["expected"], "Result": x["result"],
             "Fields flagged for drought": f"{x.get('fields_flagged_drought', '-')} of {x.get('fields', '-')}",
             "Evidence": x.get("evidence") or x.get("todo", "")} for x in bt["seasons"]]
    if not rows:
        st.caption("No past seasons with a known outcome are listed for this pilot yet (config/backtest_reference.csv).")
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                 column_config={"Evidence": st.column_config.TextColumn(width="large")})
    res_path = bt_path.with_name("backtest_results.csv")
    if res_path.exists():
        with st.expander("Month-by-month results"):
            r = pd.read_csv(res_path)
            st.dataframe(r[["month", "field_id", "outcome", "risk_level", "data_confidence"]].rename(columns={
                "month": "Month", "field_id": "Field", "outcome": "Result", "risk_level": "Risk level",
                "data_confidence": "Data confidence"}), hide_index=True, width="stretch")
    st.caption(f"Rules fingerprint {bt['rules_fingerprint']} (thresholds frozen before testing). {bt['caveat']}")

with st.expander("What counts as correct"):
    st.markdown("""
- **Alert**: a field whose *issued* prediction was Possible drought stress (risk High or Moderate). The prediction stored at issue is used, never a later re-run.
- **Correct alert**: the verifier's verdict was Confirmed. **False alert**: Rejected. **Uncertain** is shown separately.
- **Cause checks** (Crop stress—cause uncertain) are visited but are not drought alerts, so they are counted separately.
- **Missed**: a Watch or Low field where drought stress was Confirmed. This needs control visits to unflagged fields. Insufficient-data fields are never treated as controls.
- **Alerts verified**: alerts with at least one accepted real visit, out of all alerts issued.
- Only real visits that the validation lead accepted count. TEST records never do.
- With only a handful of fields, every rate has a wide range. The 95% range is shown so small samples are not over-read.
""")
