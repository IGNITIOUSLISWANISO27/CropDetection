import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd
import streamlit as st
from _lib import setup, alert_status, chip

data = setup("Verify queue")
Q = alert_status(data)
V = data.verifications if data.verifications is not None else pd.DataFrame()
st.title("Verification queue")
st.write("Give verifiers these Field IDs and Alert IDs. They must be entered in the Kobo form exactly as shown, "
         "so that each visit is linked to its alert. The issued prediction is stored separately and never changed by a visit.")

# ---- queue
if Q.empty:
    st.info("No fields are queued.")
else:
    t = Q[["alert_id", "field_id", "visit_type", "outcome", "risk_level", "data_confidence", "status", "checks"]].copy()
    t.columns = ["Alert ID", "Field ID", "Visit type", "Result", "Risk level", "Data confidence", "Verification",
                 "What to check"]
    st.dataframe(t, hide_index=True, width="stretch", column_config={
        "Verification": st.column_config.TextColumn(width="medium"),
        "What to check": st.column_config.TextColumn(width="large")})
st.caption("Control visits are optional but valuable: they are the only way to find stress the system missed. "
           "Fields with insufficient data are not queued; fix their data first. "
           "Verifiers should record what they see before looking at the system result.")
st.download_button("Download queue for verifiers (CSV)", Q.drop(columns=["status"]).to_csv(index=False),
                   file_name="verification_queue.csv", mime="text/csv")

# ---- submissions
st.subheader("Submissions to check")
show_test = st.checkbox("Include TEST records", value=False)
if V.empty or "record_type" not in V:
    st.info("No Kobo submissions have been loaded yet. Export the form data and run the validation step.")
else:
    is_t = V["is_test"].fillna(False).astype(bool) if "is_test" in V else (V["record_type"] == "test")
    S = V if show_test else V[(V["record_type"] == "real_visit") & ~is_t]
    if S.empty:
        st.info("No real field visits have been submitted yet. TEST records are hidden.")
    for r in S.to_dict("records"):
        flags = r.get("flags") or []
        errs = [x for x in flags if x["severity"] == "error"]
        warns = [x for x in flags if x["severity"] == "warning"]
        label = (f"{r.get('alert_id') or 'No alert ID'} | {r.get('field_id') or 'no field'} | "
                 f"{r.get('validation_status_final')} | {len(errs)} to fix, {len(warns)} to check")
        with st.expander(label, expanded=bool(errs) and len(S) <= 3):
            st.caption(f"Record type: {r.get('record_type')}. Status set by: {r.get('status_source')}. Visit date: {r.get('visit_date')}.")
            for x in errs:
                st.markdown(f"**Fix:** {x['text']}")
            for x in warns:
                st.markdown(f"**Check:** {x['text']}")
            for x in [x for x in flags if x["severity"] == "info"]:
                st.markdown(f"Note: {x['text']}")
            if not flags:
                st.write("No issues found by the automatic checks.")
    st.caption("The automatic checks only suggest a status. The validation lead sets Accepted, Needs review or "
               "Rejected for analysis in Kobo, and only accepted real visits count towards performance.")
    try:
        from fieldpriority.validation.register import to_register
        reg = to_register(V if show_test else V[V["record_type"] == "real_visit"]) if "flags" in V else None
        if reg is not None and len(reg):
            st.download_button("Download validation register (CSV)", reg.to_csv(index=False),
                               file_name="validation_register.csv", mime="text/csv")
    except Exception:
        pass

with st.expander("Field verification checklist (from the SOP)"):
    st.markdown("""
**Before the visit.** Take the Alert ID and Field ID from the queue. Confirm the farmer's permission before observing or photographing anything. Do not collect names, phone numbers or other personal details.

**In the field.** Record the growth stage (choose Unknown if unsure). Note leaf rolling, leaf drying, stunting, soil dryness and recent rainfall. Rule out other causes: pests, disease, nutrient problems, weeds, late planting and waterlogging. Take a crop photo and a soil photo where permission and access allow.

**Verdict.** Choose Confirmed, Rejected or Uncertain, and write a reason of at least a full sentence. Use Uncertain when the evidence does not settle it. It is a valid answer and is reported separately. Do not confuse normal drying at maturity with drought.

**Next step.** Recommend verification follow-up or professional assessment by an extension officer. Do not prescribe treatment from the alert.

**After the visit.** The validation lead checks each record and sets its status. Fix anything flagged above and resubmit.
""")
