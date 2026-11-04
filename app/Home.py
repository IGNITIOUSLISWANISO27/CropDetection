"""FieldPriority dashboard: entry point and navigation (run: streamlit run app/Home.py)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import streamlit as st

st.set_page_config(page_title="FieldPriority · Maize drought-risk monitoring", page_icon=":material/agriculture:",
                   layout="wide", initial_sidebar_state="collapsed")
from _lib import CSS, CSS_V2, load_data

A_DIR = Path(__file__).resolve().parent / "assets"
st.logo(str(A_DIR / "logo_wordmark.svg"), size="large")
st.markdown(CSS + CSS_V2, unsafe_allow_html=True)

# ---- pilot area (Solwezi, Chongwe, ...): one switch for the whole dashboard, kept in the URL as ?area=
from _lib import PILOTS, _cfg
if "pilot" not in st.session_state:
    qa = str(st.query_params.get("area") or "").lower()
    st.session_state["pilot"] = qa if qa in PILOTS else PILOTS[0]
if len(PILOTS) > 1:
    _, sw = st.columns([3, 1.4])
    with sw:
        st.segmented_control("Pilot area", PILOTS, key="pilot", required=True, width="stretch",
                             format_func=lambda p: _cfg(p)["pilot_short"], label_visibility="collapsed",
                             help="Each pilot area has its own fields, assessments, alerts and field visits.")
st.query_params["area"] = st.session_state["pilot"]
st.session_state["fp_data"] = load_data()

V = Path(__file__).resolve().parent / "views"
pages = [
    st.Page(V / "overview.py", title="Overview", icon=":material/dashboard:", default=True),
    st.Page(V / "field_map.py", title="Field Map", icon=":material/map:", url_path="field-map"),
    st.Page(V / "assessments.py", title="Assessments", icon=":material/assignment:", url_path="assessments"),
    st.Page(V / "risk_analysis.py", title="Risk Analysis", icon=":material/monitoring:", url_path="risk-analysis"),
    st.Page(V / "data_quality.py", title="Data Quality", icon=":material/fact_check:", url_path="data-quality"),
    st.Page(V / "reports.py", title="Reports", icon=":material/description:", url_path="reports"),
]
st.navigation(pages, position="top").run()
