import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import datetime as dt
import html
import pandas as pd
import streamlit as st
from _lib import (setup, chip, real_visits, period_text, status_by_field, sort_by_risk, CFG)

data = setup("Fields to visit first")
A = sort_by_risk(data.assessments)
status = status_by_field(data)
st.title("Fields to visit first")
alert_date = data.meta.get("alert_date") or "unknown date"
as_date = data.meta.get("assessment_date") or "unknown"
st.markdown(f'<div class="fp-sub">Possible drought-related stress in maize, {CFG["pilot_area"]}. Satellite and climate data: '
            f'{period_text(data)}. Conditions assessed for {as_date}. Alerts issued {alert_date}.</div>',
            unsafe_allow_html=True)
st.write("")

# ---- honest status first
real = real_visits(data)
if real.empty:
    st.warning("No real field verifications yet. These results come from satellite and climate data only. "
               "They are not confirmed drought, and their accuracy has not been tested on the ground.")
try:
    end = pd.Period(str(data.meta["period"]).partition("..")[2], "M").end_time.date()
    gap = (dt.date.fromisoformat(str(alert_date)) - end).days
    dcfg = CFG.get("dashboard", {})
    if dcfg.get("stale_data_warning", True) and gap > dcfg.get("stale_after_days", 150):
        st.warning(f"These results use data that ended {gap} days before the alert date. Confirm this is intended "
                   "before sending verifiers to the field.")
except Exception:
    pass


def field_row(r):
    e = html.escape
    ex = r.get("explanation") or {}
    c1, c2, c3, c4 = st.columns([1.2, 2.1, 3.4, 1.6])
    c1.markdown(f"**{e(r['field_id'])}**", unsafe_allow_html=True)
    ha = fields.loc[r['field_id'], 'area_ha']
    c1.caption(f"{ha:.1f} ha" if ha >= 1 else f"{ha:.2f} ha")
    c2.markdown(f"{e(str(r['outcome']))}<br>{chip(r['risk_level'])}", unsafe_allow_html=True)
    c2.caption(f"Data confidence: {r['data_confidence']}")
    for w in ex.get("what_changed", [])[:3]:
        c3.markdown(f"- {e(w)}")
    if r.get("missing_data"):
        c3.markdown("- Missing: " + e("; ".join(r["missing_data"])))
    if ex.get("checks"):
        c3.caption("Check: " + "; ".join(ex["checks"][:2]))
    c4.write(status.get(r["field_id"], "Not yet verified"))
    st.divider()


fields = data.fields.set_index("Field_ID")
levels = CFG["alerts"]["alert_levels"] + CFG["alerts"].get("check_levels", [])
visit = A[A["risk_level"].isin(levels)]
if visit.empty and (A["risk_level"] == "Insufficient data").all():
    st.info("No field could be assessed: essential data is missing. Each field below lists what is missing.")
elif visit.empty:
    st.success("No field meets the rule for possible drought stress or unexplained crop stress in this run.")
else:
    st.subheader(f"{len(visit)} field{'s' if len(visit) != 1 else ''} to verify")
if len(visit):
    head = st.columns([1.2, 2.1, 3.4, 1.6])
    for c, t in zip(head, ["Field", "Result and risk level", "What changed and what to check", "Field verification"]):
        c.caption(t)
for r in visit.to_dict("records"):
    field_row(r)

groups = [("Watch", "Water deficit without vegetation decline (watch)"),
          ("Insufficient data", "Insufficient data (not the same as low risk)"),
          ("Low", "No drought-stress signal or expected maturity drying"),
          ("Not assessed", "Not assessed (crop is not maize)")]
for lvl, title in groups:
    g = A[A["risk_level"] == lvl]
    if len(g):
        with st.expander(f"{title}: {len(g)} field{'s' if len(g) != 1 else ''}", expanded=visit.empty):
            for r in g.to_dict("records"):
                field_row(r)
st.caption("Visiting a few fields that were not flagged is the only way to find out whether the system misses real stress.")

# ---- numbers
c = st.columns(4)
nreal_ok = int(real["analysis_eligible"].astype(bool).sum()) if len(real) else 0
vr = (data.metrics or {}).get("verification_rate") or {}
n_alerts = int(A["risk_level"].isin(CFG["alerts"]["alert_levels"]).sum())
c[0].metric("Drought alerts issued", n_alerts)
c[1].metric("Real visits accepted", nreal_ok)
c[2].metric("Alerts verified", f"{vr.get('k', 0)} of {vr.get('n', n_alerts)}")
c[3].metric("Model version", str(data.meta.get("model_version") or "n/a").split("-")[0])

# ---- how to read
with st.expander("How to read these results"):
    st.markdown("""
- **Scope.** The system looks only for possible drought-related stress in maize. It does not diagnose pests, disease or nutrient problems.
- **Possible drought stress** needs two things together: rainfall below its long-term baseline *and* a decline in the field's vegetation (NDVI). One alone is not enough.
- **Crop stress—cause uncertain** means vegetation declined while rainfall was not below its baseline. Something else may be the cause.
- **Water deficit—no vegetation decline yet** means rainfall was low but the crop has not shown a decline. Watch the next update.
- **Insufficient data** means something essential is missing. It is never shown as low risk.
- **Growth stage matters.** Drying at maturity is normal and is not counted as drought. When the stage is unknown, the risk is capped at Moderate.
- **Three separate labels.** *Risk level* is what the data suggests, *data confidence* is how well the data supports it, and *verification* is what was found in the field.
- **Next steps are verification or professional assessment**, never automatic treatment.
- **Thresholds are provisional.** They are set in `config/settings.yaml` under `rules` and need agricultural review.
""")
notes = (data.report or {}).get("notes") or []
if notes:
    with st.expander(f"Data notes from the latest run ({len(notes)})"):
        for n in notes:
            st.write(n)
with st.expander("Data sources"):
    st.table(pd.DataFrame({"Layer": list(CFG["sources"].keys()), "Source": list(CFG["sources"].values())}))
