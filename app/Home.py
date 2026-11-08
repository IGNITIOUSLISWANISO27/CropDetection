"""FieldPriority dashboard: entry point and navigation (run: streamlit run app/Home.py)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import streamlit as st

st.set_page_config(page_title="FieldPriority · Zambia Agricultural Intelligence", page_icon=":material/agriculture:",
                   layout="wide", initial_sidebar_state="collapsed")
from _lib import CSS, CSS_V2, CSS_V3, CSS_ZMD, CSS_V4, CSS_V5, CSS_WX, CSS_V6, load_data

A_DIR = Path(__file__).resolve().parent / "assets"
st.logo(str(A_DIR / "logo_wordmark.svg"), size="large")
st.markdown(CSS + CSS_V2 + CSS_V3 + CSS_ZMD + CSS_V4 + CSS_V5 + CSS_WX + CSS_V6, unsafe_allow_html=True)

# ---- accounts: field evidence pages exist only for a signed-in account, limited to its own pilot areas
from _lib import _cfg, current_user, user_pilots
user = current_user()
MINE = user_pilots()                       # [] when signed out
V = Path(__file__).resolve().parent / "views"
FIELD_PAGES = {"field-map", "assessments", "data-quality", "reports"}

# ---- pilot area for the field pages, kept in the URL as ?area= (only the account's own areas)
qa = str(st.query_params.get("area") or "").lower()
if MINE:
    if st.session_state.get("pilot") not in MINE:
        st.session_state["pilot"] = qa if qa in MINE else (st.session_state.get("_area_seen")
                                                          if st.session_state.get("_area_seen") in MINE else MINE[0])
    elif qa in MINE and qa != st.session_state.get("_area_seen"):
        st.session_state["pilot"] = qa      # a link to another of the account's pilots (the URL changed)
login_page = st.Page(V / "login.py", title="Your account" if user else "Sign in",
                     icon=":material/account_circle:" if user else ":material/lock:", url_path="login")
pages = {
    "": [st.Page(V / "overview.py", title="Overview", icon=":material/dashboard:", default=True),
         st.Page(V / "location.py", title="Explore Locations", icon=":material/location_on:", url_path="location"),
         st.Page(V / "map.py", title="Zambia Map", icon=":material/public:", url_path="map"),
         st.Page(V / "about.py", title="About / Methodology", icon=":material/info:", url_path="about"),
         # weather supports the location reports (linked from them); not a separate app in the menu
         st.Page(V / "weather.py", title="Weather & Warnings", icon=":material/thunderstorm:", url_path="weather",
                 visibility="hidden")],
    "Field Evidence": ([
        st.Page(V / "field_map.py", title="Field Map", icon=":material/map:", url_path="field-map"),
        st.Page(V / "assessments.py", title="Field Assessments", icon=":material/assignment:", url_path="assessments"),
        st.Page(V / "data_quality.py", title="Data Quality", icon=":material/fact_check:", url_path="data-quality"),
        st.Page(V / "reports.py", title="Reports", icon=":material/description:", url_path="reports")]
        if MINE else []) + [login_page],
}
nav = st.navigation(pages, position="top")
if len(MINE) > 1 and nav.url_path in FIELD_PAGES:
    _, sw = st.columns([3, 1.4])
    with sw:
        st.segmented_control("Pilot area", MINE, key="pilot", required=True, width="stretch",
                             format_func=lambda p: _cfg(p)["pilot_short"], label_visibility="collapsed",
                             help="Each pilot area has its own fields, assessments, alerts and field visits.")
if MINE:
    st.query_params["area"] = st.session_state["pilot"]
    st.session_state["_area_seen"] = st.session_state["pilot"]
elif "area" in st.query_params:
    del st.query_params["area"]
st.session_state["fp_data"] = load_data()
nav.run()
