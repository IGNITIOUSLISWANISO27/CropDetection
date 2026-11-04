import pandas as pd
import streamlit as st
from _lib import (get_data, page_title, build_map, show_map, badge, legend_html, field_location, status_by_field,
                  period_text, html_block, sort_by_risk, VIEWS, RISK, RISK_ORDER, E, empty, src_tag)

data = get_data()
A = data.assessments
page_title("Field Map", "Where the assessed maize fields are and what their drought-risk class is. Boundaries are "
           "drawn from the digitised field polygons; colours follow the risk classes used everywhere in FieldPriority.",
           eyebrow="Geographical overview", icon_name="pin")

status = status_by_field(data)
locs = {f: field_location(data, f) for f in A["field_id"]}
present = [k for k in RISK_ORDER if (A["risk_level"] == k).any()]

with st.container(border=True):
    f1, f2, f3, f4, f5 = st.columns([1.8, 1.1, 1.1, 1.1, 1])
    risk_sel = f1.multiselect("Risk class", present, default=present, placeholder="All risk classes",
                              format_func=lambda k: RISK[k]["short"])
    periods = sorted(A["period"].dropna().unique().tolist()) or ["n/a"]
    per = f2.selectbox("Assessment period", ["All"] + periods,
                       format_func=lambda p: p if p in ("All", "n/a") else period_text(data) if p == data.meta.get("period") else p)
    places = sorted({l["district"] for l in locs.values()})
    place = f3.selectbox("Location", ["All"] + places)
    view = f4.selectbox("View", list(VIEWS), help="How much area to show. You can also zoom with + / - or the mouse wheel.")
    base = f5.radio("Map", ["Satellite", "Street map"], horizontal=False, label_visibility="visible")

sel = A[A["risk_level"].isin(risk_sel or present)]
if per != "All":
    sel = sel[sel["period"] == per]
if place != "All":
    sel = sel[sel["field_id"].map(lambda f: locs[f]["district"]) == place]

left, right = st.columns([2.2, 1], gap="large")
with right:
    st.markdown("**Fields shown**")
    if sel.empty:
        empty("No field matches these filters.")
        focus = None
    else:
        ids = sort_by_risk(sel)["field_id"].tolist()
        focus = st.selectbox("Select a field", ids, index=0,
                             help="Zooms the map to the field and shows its details below.")
        r = sel.set_index("field_id").loc[focus]
        loc = locs[focus]
        area = data.fields.set_index("Field_ID").loc[focus, "area_ha"]
        html_block(f"""
<div class="fp-card"><div style="display:flex;justify-content:space-between;align-items:center;gap:8px">
<h4 style="margin:0">{E(focus)}</h4>{badge(r["risk_level"])}</div>
<div class="fp-sub" style="margin:.3rem 0 .8rem">{E(str(r["outcome"]))}</div>
<div class="fp-kv">
<div>Location</div><div>{E(loc["district"])} · {loc["lat"]:.5f}, {loc["lon"]:.5f}</div>
<div>Crop</div><div>Maize</div>
<div>Assessment period</div><div>{E(period_text(data))}</div>
<div>Assessed for</div><div>{E(str(r.get("assessment_date")))}</div>
<div>Field area</div><div>{area:.2f} ha {src_tag("est")}</div>
<div>Data confidence</div><div>{E(str(r["data_confidence"]))}</div>
<div>Verification</div><div>{E(status.get(focus, "Not yet verified"))}</div>
</div></div>""")
        st.page_link("views/assessments.py", label=f"Open full profile of {focus}", icon=":material/open_in_new:",
                     query_params={"field": focus})
    st.markdown("**Legend**")
    html_block(legend_html([k for k in RISK_ORDER if k != "Not assessed"]))
    html_block('<div class="fp-sub" style="margin-top:.6rem">Colour and label always appear together. '
               '<b>Insufficient data</b> (grey) means the risk could not be judged; it never means low risk.</div>')

with left:
    if sel.empty:
        empty("Nothing to show on the map with these filters.")
    else:
        show_map(build_map(data, A=sel, basemap=base, view=view, focus=focus if view != "Fit fields" or len(sel) == 1 else None),
                 height=640)
        st.caption("Click a field on the map for a summary and a link to its profile. Switch between satellite and "
                   "street map with the layer button (top right). Satellite imagery: Esri, Maxar, Earthstar Geographics.")
