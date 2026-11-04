import datetime as dt
import streamlit as st
from _lib import (get_data, page_title, section, html_block, risk_distribution_html, risk_counts, field_location,
                  period_text, empty, kpi, RISK, RISK_ORDER, CFG, E)
from _reports import build_pdf, build_excel, build_geojson

data = get_data()
A = data.assessments
page_title("Reports", "Professional summaries of FieldPriority assessments for presentations, research documentation "
           "and decision-making. Choose what to include, check the preview, then download.",
           eyebrow="Analytical outputs", icon_name="doc")

with st.container(border=True):
    c = st.columns(4)
    locs = {f: field_location(data, f)["district"] for f in A["field_id"]}
    area = c[0].selectbox("Geographical area", ["All"] + sorted(set(locs.values())))
    per = c[1].selectbox("Assessment period", ["All"] + sorted(A["period"].dropna().unique().tolist()))
    stages = sorted(A["growth_stage_label"].fillna("Unknown").unique().tolist())
    stage = c[2].selectbox("Crop-development stage", ["All"] + stages)
    risk = c[3].multiselect("Risk class", [k for k in RISK_ORDER if (A["risk_level"] == k).any()],
                            format_func=lambda k: RISK[k]["short"], placeholder="All")

sel = A.copy()
if area != "All":
    sel = sel[sel["field_id"].map(locs) == area]
if per != "All":
    sel = sel[sel["period"] == per]
if stage != "All":
    sel = sel[sel["growth_stage_label"].fillna("Unknown") == stage]
if risk:
    sel = sel[sel["risk_level"].isin(risk)]
filters = {"Area": area if area != "All" else "", "Period": per if per != "All" else "",
           "Stage": stage if stage != "All" else "", "Risk class": ", ".join(RISK[k]["short"] for k in risk)}

section("Preview", "doc")
if sel.empty:
    empty("No field matches these filters, so there is nothing to report.")
    st.stop()
p = st.columns(3)
p[0].markdown(kpi("pin", "Fields in report", f"{len(sel)}", f"{E(CFG['pilot_area'])}"), unsafe_allow_html=True)
p[1].markdown('<div class="fp-card fp-kpi"><div class="top">Risk classes</div>' + risk_distribution_html(risk_counts(sel))
              + '</div>', unsafe_allow_html=True)
p[2].markdown(kpi("clock", "Assessment period", "", E(period_text(data)) + f" · generated {dt.date.today():%d %b %Y}"),
              unsafe_allow_html=True)

section("Download", "layers")
stamp = f"{dt.date.today():%Y%m%d}"
d = st.columns(3)
with d[0]:
    st.markdown("**PDF report**  \nSummary, key findings, risk chart, field map, field table, sources.")
    try:
        st.download_button("Download PDF", build_pdf(data, sel, filters), f"FieldPriority_report_{stamp}.pdf",
                           "application/pdf", icon=":material/picture_as_pdf:", width="stretch")
    except Exception as e:
        st.error(f"PDF could not be built: {e}")
with d[1]:
    st.markdown("**Excel workbook**  \nAssessments, indicators, field visits, history and sources, one sheet each.")
    st.download_button("Download Excel", build_excel(data, sel), f"FieldPriority_data_{stamp}.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       icon=":material/table_view:", width="stretch")
with d[2]:
    st.markdown("**Field boundaries (GeoJSON)**  \nPolygons with risk class and status, for QGIS or Earth Engine.")
    st.download_button("Download GeoJSON", build_geojson(data, sel), f"FieldPriority_fields_{stamp}.geojson",
                       "application/geo+json", icon=":material/map:", width="stretch")
st.caption("Reports are built from the same data the dashboard shows. Boundaries are marked as digitised estimates "
           "until checked on the ground; risk classes are screening results, not confirmed drought.")
