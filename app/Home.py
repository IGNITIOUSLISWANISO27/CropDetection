"""FieldPriority dashboard: entry point and navigation (run: streamlit run app/Home.py)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import streamlit as st

st.set_page_config(page_title="FieldPriority · Maize drought-risk monitoring", page_icon=":material/agriculture:",
                   layout="wide", initial_sidebar_state="collapsed")
from _lib import CSS, load_data

st.markdown(CSS, unsafe_allow_html=True)
st.session_state["fp_data"] = load_data()

V = Path(__file__).resolve().parent / "views"
pages = [
    st.Page(V / "overview.py", title="Overview", icon=":material/dashboard:", url_path="overview", default=True),
    st.Page(V / "field_map.py", title="Field Map", icon=":material/map:", url_path="field-map"),
    st.Page(V / "assessments.py", title="Assessments", icon=":material/assignment:", url_path="assessments"),
    st.Page(V / "risk_analysis.py", title="Risk Analysis", icon=":material/monitoring:", url_path="risk-analysis"),
    st.Page(V / "data_quality.py", title="Data Quality", icon=":material/fact_check:", url_path="data-quality"),
    st.Page(V / "reports.py", title="Reports", icon=":material/description:", url_path="reports"),
]
st.navigation(pages, position="top").run()
