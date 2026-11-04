import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd
import streamlit as st
from _lib import setup, build_map, show_map, status_by_field, sort_by_risk, COLOR_BY, VIEWS, RISK_COLORS, RISK_ORDER, score_color

data = setup("Risk map")
A = data.assessments
st.title("Risk map")

c1, c2, c3 = st.columns([1.6, 1.1, 1.3])
color_by = c1.selectbox("Colour fields by", list(COLOR_BY), help="Risk level comes from the drought-stress rules. The legacy score is a relative ranking for comparison.")
zoom_to = c2.selectbox("Zoom to", ["All fields"] + sorted(A["field_id"]), help="Small fields are hard to see at full extent.")
basemap = c3.radio("Background", ["Satellite", "Street map"], horizontal=True)
c4, c5 = st.columns([1.6, 2.4])
view = c4.selectbox("View", list(VIEWS), help="How much area to show around the fields. You can also zoom with the "
                    "+ and - buttons or the mouse wheel.")
height = c5.slider("Map height (pixels)", 400, 1100, 600, 50)

status = status_by_field(data)
show_map(build_map(data.fields, A, color_by, basemap, status, zoom_to, view), height=height)

if COLOR_BY[color_by] is None:
    present = [p for p in RISK_ORDER if (A["risk_level"] == p).any()]
    st.markdown(" &nbsp; ".join(f'<span class="fp-chip" style="background:{RISK_COLORS[p]}">{p}</span>'
                                for p in present), unsafe_allow_html=True)
else:
    st.markdown(" &nbsp; ".join(f'<span class="fp-chip" style="background:{score_color(s)}">{s:.2f}</span>' for s in (0, 0.25, 0.5, 0.75, 1)) +
                " &nbsp; legacy relative score, lowest to highest (not the alert)", unsafe_allow_html=True)
st.caption("Fields are small and far apart, so each is shown as a polygon plus a numbered circle. Hover a field for details.")

# shared cells
groups = A.dropna(subset=["rain_cell"]).groupby("rain_cell")["field_id"].apply(list)
shared = [g for g in groups if len(g) > 1]
if shared:
    st.info("Fields in the same climate cell share the same rainfall, soil moisture and temperature values: "
            + "; ".join(", ".join(g) for g in shared) + ". Their results differ only through field-level vegetation (NDVI).")

t = sort_by_risk(A).merge(data.fields[["Field_ID", "area_ha"]], left_on="field_id", right_on="Field_ID")
t["status"] = t["field_id"].map(status).fillna("Not yet verified")
t = t[["field_id", "outcome", "risk_level", "data_confidence", "status", "area_ha", "integrated_score"]]
t.columns = ["Field", "Result", "Risk level", "Data confidence", "Verification", "Area (ha)", "Legacy score"]
st.dataframe(t, hide_index=True, width="stretch", column_config={
    "Legacy score": st.column_config.ProgressColumn(min_value=0, max_value=1, format="%.2f",
                     help="v1 relative ranking among the pilot fields. Comparison only; it does not set the alert."),
    "Area (ha)": st.column_config.NumberColumn(format="%.2f"),
    "Verification": st.column_config.TextColumn(width="medium")})
