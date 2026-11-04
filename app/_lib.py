"""Shared helpers for the FieldPriority dashboard. The app reads data only through the repository
(Firebase or local files); it never recomputes scores."""
import html
import os
import sys
import datetime as dt
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import altair as alt
import folium
import numpy as np
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from fieldpriority.config import load_config
from fieldpriority.storage.repository import get_repository

CFG = load_config()
# Risk levels from the drought-stress rules (model/rules.py). Kept separate from data confidence and
# verification status everywhere on the dashboard (rule 9).
RISK_COLORS = {"High": "#B3261E", "Moderate": "#C77700", "Not attributed": "#6A4C93", "Watch": "#8A6D00",
               "Low": "#2E7D4F", "Insufficient data": "#5F6B76", "Not assessed": "#8C959F"}
RISK_ORDER = ["High", "Moderate", "Not attributed", "Watch", "Low", "Insufficient data", "Not assessed"]
LEGACY_COLORS = {"High priority": "#B3261E", "Moderate priority": "#C77700",
                 "Low priority": "#2E7D4F", "Unclassified": "#6B7280"}
PRIORITY_COLORS = RISK_COLORS
FIELD_COLOR, REGIONAL_COLOR = "#2F6B4F", "#4C78A8"
COMPONENTS = ["greenness", "rainfall", "soil_moisture", "temperature"]
LABELS = {"greenness": "Vegetation greenness", "rainfall": "Rainfall", "soil_moisture": "Soil moisture",
          "temperature": "Temperature"}
EVIDENCE = {"greenness": "Field-level", "rainfall": "Regional (shared cell)",
            "soil_moisture": "Regional (shared cell)", "temperature": "Regional (shared cell)"}
REASON_TITLES = {"PRIORITY": "Summary", "GREENNESS_LOW": "Vegetation greenness", "GREENNESS_OK": "Vegetation greenness",
                 "GREENNESS_MID": "Vegetation greenness", "RAIN": "Rainfall", "RAIN_LATE_DRY": "Rainfall",
                 "SOIL_MOISTURE": "Soil moisture", "TEMPERATURE": "Temperature", "S1_CONTEXT": "Radar context",
                 "S1_MISSING": "Radar context", "REGIONAL_DRIVEN": "Limits of the evidence",
                 "DQ_NDVI": "Data quality", "DQ_SMALL_FIELD": "Data quality"}

ISSUE_LABELS = {
    "ID_MISSING": "Alert ID or Field ID missing", "FIELD_UNMAPPED": "Field ID not recognised",
    "ALERT_NOT_FOUND": "Alert ID not found", "ALERT_FIELD_MISMATCH": "Alert ID belongs to a different field",
    "RISK_MISMATCH": "System risk differs from the stored alert", "PERMISSION_MISSING": "Permission not answered",
    "NO_PERMISSION_OBS": "Observations recorded without permission", "NOT_MAIZE": "Maize not the main crop",
    "STAGE_MISSING": "Growth stage missing", "EVIDENCE_MISSING": "Crop or soil observations missing",
    "ALT_CAUSES_MISSING": "Alternative causes not all checked", "VERDICT_MISSING": "No verdict",
    "REASON_SHORT": "Verdict reason too short", "PHOTO_MISSING": "Photo missing",
    "FLOWERING_STAGE": "Flowering concern at an early stage", "IRRIG_CONFLICT": "Irrigation answers conflict",
    "SOIL_WATERLOG": "Soil and waterlogging answers conflict", "VERDICT_CAUSE": "Verdict and main cause conflict",
    "CONFIRMED_NO_SIGNS": "Confirmed without any stress signs", "PRIVACY": "Possible personal contact details",
    "DATE_MISSING": "Visit date missing", "DATE_FUTURE": "Visit date in the future", "ALERT_DATE_MISSING": "No alert date",
    "DATE_ORDER": "Visit before alert date", "LATE_VISIT": "Visit long after the alert",
    "PLANTING_AFTER_VISIT": "Planting date after visit", "TEST_RECORD": "Test record", "NO_PERMISSION": "Permission refused"}


def issue_label(code):
    return ISSUE_LABELS.get(code, code)


def issue_labels(codes):
    return "; ".join(issue_label(c) for c in str(codes).split(";") if c and c != "nan")


CSS = """
<style>
.fp-chip{display:inline-block;padding:1px 9px;border-radius:4px;color:#fff;font-size:.82rem;font-weight:600;white-space:nowrap}
.fp-sub{color:#52606d;font-size:.9rem}
.block-container{padding-top:2.2rem}
</style>
"""


def chip(level):
    c = RISK_COLORS.get(level) or LEGACY_COLORS.get(level, "#6B7280")
    return f'<span class="fp-chip" style="background:{c}">{html.escape(str(level).replace(" priority", ""))}</span>'


def score_color(s):
    """green -> amber -> red"""
    stops = [(0.0, (46, 125, 79)), (0.5, (224, 165, 38)), (1.0, (179, 38, 30))]
    s = 0.0 if s is None or pd.isna(s) else min(1.0, max(0.0, float(s)))
    for (a, ca), (b, cb) in zip(stops, stops[1:]):
        if s <= b:
            t = (s - a) / (b - a)
            return "#%02x%02x%02x" % tuple(int(ca[i] + (cb[i] - ca[i]) * t) for i in range(3))
    return "#B3261E"


# ---------------------------------------------------------------- data
@st.cache_data(ttl=120, show_spinner="Loading data")
def _load(source, outputs_dir, cred):
    return get_repository(source, outputs_dir, cred).load()


def setup(page_title, icon="🌽"):
    """Page config, theme CSS, sidebar data-source selector. Returns DashboardData."""
    st.set_page_config(page_title=f"{page_title} | FieldPriority", page_icon=icon, layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)
    default = os.environ.get("FIELDPRIORITY_SOURCE", "auto")
    opts = ["auto", "firebase", "local"]
    with st.sidebar:
        st.markdown("**FieldPriority**")
        st.caption(f"Maize drought-risk screening, {CFG['pilot_area']}")
        source = st.radio("Data source", opts, index=opts.index(default), key="source",
                          format_func={"auto": "Automatic", "firebase": "Firebase", "local": "Local files"}.get,
                          help="Automatic uses Firebase when a key is configured, otherwise the local outputs folder.")
        if st.button("Reload data", width="stretch"):
            st.cache_data.clear()
    outputs = os.environ.get("FIELDPRIORITY_OUTPUTS") or str(ROOT / CFG["paths"]["output_dir"])
    try:
        data = _load(source, outputs, None)
    except Exception as e:
        st.error(f"Could not load data. {e}")
        st.stop()
    with st.sidebar:
        st.caption(f"Showing: {data.source_note}")
        if data.meta.get("assessed_at"):
            st.caption(f"Assessed {str(data.meta['assessed_at'])[:16].replace('T', ' ')} UTC")
    return data


def period_year(data):
    p = str(data.meta.get("period") or CFG["period_label"])
    return int(p[:4])


def period_text(data):
    p = str(data.meta.get("period") or CFG["period_label"])
    a, _, b = p.partition("..")
    return f"{pd.Period(a, 'M').strftime('%b %Y')} to {pd.Period(b or a, 'M').strftime('%b %Y')}"


# ---------------------------------------------------------------- verification status
def real_visits(data):
    v = data.verifications
    if v is None or v.empty or "record_type" not in v:
        return pd.DataFrame()
    return v[v["record_type"] == "real_visit"]


def verification_status(data, aid):
    """Field-verification status of one alert, from Kobo records only (never from the prediction)."""
    v = data.verifications if data.verifications is not None else pd.DataFrame()
    verdicts = {"confirmed": "Confirmed", "rejected": "Rejected", "uncertain": "Uncertain"}
    if v.empty or "matched_alert_id" not in v:
        return "Not yet verified"
    real = v["record_type"] == "real_visit"
    if "is_test" in v:
        real &= ~v["is_test"].fillna(False).astype(bool)
    r = v[(v["matched_alert_id"] == aid) & real]
    if r.empty:
        return "Not yet verified"
    ok = r[r["analysis_eligible"].astype(bool)]
    if len(ok):
        return "Verified: " + verdicts.get(str(ok.iloc[-1]["field_verdict"]), "n/a")
    return "Visit submitted, under review"


def status_by_field(data):
    return {r["field_id"]: verification_status(data, r["alert_id"]) for r in data.assessments.to_dict("records")}


def alert_status(data):
    """Queue table with a plain-language verification status per alert."""
    q = data.queue.copy()
    q["status"] = q["alert_id"].map(lambda a: verification_status(data, a)) if len(q) else []
    return q


def sort_by_risk(A):
    return A.assign(_o=A["risk_level"].map({k: i for i, k in enumerate(RISK_ORDER)}).fillna(99)) \
            .sort_values(["_o", "integrated_score"], ascending=[True, False]).drop(columns="_o")


def drivers_text(row):
    """Name every indicator that contributes materially, and say whether any is field-level."""
    vals = {c: (row.get(f"contrib_{c}") or 0) for c in COMPONENTS}
    top = [c for c in sorted(COMPONENTS, key=lambda c: (-vals[c], COMPONENTS.index(c))) if vals[c] >= 0.10]
    if not top:
        return "No single indicator contributes strongly."
    if len(top) == len(COMPONENTS):
        return "All four indicators contribute, including field-level vegetation greenness."
    names = ", ".join(LABELS[c].lower() for c in top[:-1]) + (" and " if len(top) > 1 else "") + LABELS[top[-1]].lower()
    names = names[0].upper() + names[1:]
    tail = "all regional values" if all(EVIDENCE[c] != "Field-level" for c in top) else "includes field-level greenness"
    return f"{names} ({tail})."


def score_bar(score):
    """Horizontal bar coloured by severity (the default progress bar looks 'good' when green)."""
    s = 0.0 if pd.isna(score) else min(1.0, max(0.0, float(score)))
    return (f'<div style="background:#E3E7EA;border-radius:4px;height:8px;margin:6px 0 2px 0">'
            f'<div style="width:{s*100:.0f}%;background:{score_color(s)};height:8px;border-radius:4px"></div></div>'
            f'<div class="fp-sub">{s:.2f}</div>')


# ---------------------------------------------------------------- map
ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
COLOR_BY = {"Risk level": None, "Legacy relative score": "integrated_score"}
# how much area to show around the fields: name -> fixed zoom level (None = fit the fields)
VIEWS = {"Fit fields": None, "Field close-up": 18, "Neighbourhood (~2 km)": 15, "Town (~10 km)": 13,
         "District (~40 km)": 11, "Province (~200 km)": 8}


def build_map(gdf, A, color_by, basemap, status=None, zoom_to=None, view="Fit fields"):
    target = gdf[gdf["Field_ID"] == zoom_to] if zoom_to and zoom_to != "All fields" else gdf
    minx, miny, maxx, maxy = target.total_bounds
    z = VIEWS.get(view)
    m = folium.Map(location=[(miny + maxy) / 2, (minx + maxx) / 2], zoom_start=z or 10, tiles=None,
                   control_scale=True, zoom_control=True, max_zoom=20)
    if basemap == "Satellite":
        # Esri has no imagery beyond zoom 17 in much of rural Zambia ("Map data not yet available"), so closer
        # zooms enlarge the zoom-17 tiles instead of requesting missing ones
        folium.TileLayer(ESRI, attr="Imagery: Esri, Maxar, Earthstar Geographics", name="Satellite",
                         max_native_zoom=17, max_zoom=20).add_to(m)
    else:
        folium.TileLayer("OpenStreetMap", name="Street map", max_native_zoom=19, max_zoom=20).add_to(m)
    A = A.set_index("field_id")
    col = COLOR_BY[color_by]
    for r in gdf.itertuples():
        a = A.loc[r.Field_ID]
        color = RISK_COLORS.get(a["risk_level"], "#6B7280") if col is None else score_color(a[col])
        st_txt = status.get(r.Field_ID, "Not yet verified") if status else "Not yet verified"
        e = html.escape
        tip = (f"<b>{e(str(r.Field_ID))}</b>: {e(str(a['outcome']))}<br>Risk level: {e(str(a['risk_level']))}"
               f"<br>Data confidence: {e(str(a['data_confidence']))}<br>Verification: {e(str(st_txt))}"
               f"<br>{r.area_ha:.2f} ha")
        folium.GeoJson(r.geometry.__geo_interface__, tooltip=folium.Tooltip(tip),
                       style_function=lambda _, c=color: {"color": "#ffffff", "weight": 2, "fillColor": c, "fillOpacity": 0.65}).add_to(m)
        cen = r.geometry.centroid
        folium.CircleMarker([cen.y, cen.x], radius=11, color="#ffffff", weight=2, fill=True, fill_color=color,
                            fill_opacity=0.95, tooltip=folium.Tooltip(tip)).add_to(m)
        folium.Marker([cen.y, cen.x], icon=folium.DivIcon(
            icon_size=(24, 24), icon_anchor=(12, 12), class_name="fp-label",
            html=f'<div style="width:24px;height:24px;text-align:center;font:600 10px/24px sans-serif;'
                 f'color:#fff">{html.escape(str(r.Field_ID)[-3:])}</div>')).add_to(m)
    if z is None:
        m.fit_bounds([[miny, minx], [maxy, maxx]], padding=(40, 40), max_zoom=17 if len(target) == 1 else 15)
    return m


def show_map(m, height=560):
    html_doc = m.get_root().render()
    if hasattr(st, "iframe"):                      # current Streamlit
        st.iframe(html_doc, height=height)
    else:                                          # older Streamlit
        components.html(html_doc, height=height)


# ---------------------------------------------------------------- charts
def trend_chart(monthly, variable, field, title, ytitle, year, bars=False):
    d = monthly[(monthly["variable"] == variable) & (monthly["month"] > 0)].copy()
    if d.empty:
        return None
    d["Month"] = d["month"].map(lambda m: f"{year}-{int(m):02d}")
    d["Field"] = d["Field_ID"]
    sel, oth = d[d.Field_ID == field], d[d.Field_ID != field]
    x = alt.X("Month:O", title=None, axis=alt.Axis(labelAngle=0))
    if bars:
        b = alt.Chart(sel).mark_bar(size=34).encode(
            x=x, y=alt.Y("mean:Q", title=ytitle),
            color=alt.condition(alt.datum["mean"] < 0, alt.value("#B3261E"), alt.value(REGIONAL_COLOR)),
            tooltip=["Field", "Month", alt.Tooltip("mean:Q", format=".1f", title=ytitle)])
        zero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color="#52606d").encode(y="y:Q")
        return (b + zero).properties(title=title, height=210)
    y = alt.Y("mean:Q", title=ytitle, scale=alt.Scale(zero=False))
    layers = []
    if len(oth):
        layers.append(alt.Chart(oth).mark_line(color="#C5CAD0", strokeWidth=1.5).encode(x=x, y=y, detail="Field:N"))
    layers.append(alt.Chart(sel).mark_line(point=alt.OverlayMarkDef(size=70, color=FIELD_COLOR, filled=True), color=FIELD_COLOR, strokeWidth=3).encode(
        x=x, y=y, tooltip=["Field", "Month", alt.Tooltip("mean:Q", format=".3f", title=ytitle)]))
    return alt.layer(*layers).properties(title=title, height=210)


def contribution_chart(row):
    rows = [{"Indicator": LABELS[c], "Contribution": float(row.get(f"contrib_{c}") or 0), "Evidence": EVIDENCE[c]}
            for c in COMPONENTS]
    return alt.Chart(pd.DataFrame(rows)).mark_bar(size=22).encode(
        x=alt.X("Contribution:Q", scale=alt.Scale(domain=[0, 0.25]), title="Contribution to score (each indicator can add up to 0.25)"),
        y=alt.Y("Indicator:N", sort=[LABELS[c] for c in COMPONENTS], title=None, axis=alt.Axis(labelLimit=220)),
        color=alt.Color("Evidence:N", scale=alt.Scale(domain=["Field-level", "Regional (shared cell)"],
                                                      range=[FIELD_COLOR, REGIONAL_COLOR]), legend=alt.Legend(orient="bottom", title=None)),
        tooltip=["Indicator", alt.Tooltip("Contribution:Q", format=".3f"), "Evidence"]).properties(height=250)
