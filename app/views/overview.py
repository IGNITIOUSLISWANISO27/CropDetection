import pandas as pd
import streamlit as st
from _lib import (get_data, html_block, hero_svg, kpi, section, risk_distribution_html, risk_counts, build_map,
                  show_map, risk_bar_chart, visits, badge, icon, period_text, empty, legend_html, RISK, CFG, E,
                  profile_link)

data = get_data()
A = data.assessments
V = visits(data)
counts = risk_counts(A)
n_fields = len(data.fields)

# ---------------------------------------------------------------- hero
html_block(f"""
<div class="fp-hero">{hero_svg()}<div class="shade"></div>
 <div class="inner">
  <span class="tag">{icon("leaf", 14, "#F2C74E")} Maize drought-risk monitoring · {E(CFG["pilot_area"])}</span>
  <h1>Understand Your Fields. <span class="gold">Anticipate Drought Risk.</span> Act Early.</h1>
  <p>FieldPriority is a geospatial decision-support platform. It combines satellite crop greenness, rainfall and
  soil-moisture records with field visits submitted through KoboToolbox, flags maize fields showing possible
  drought stress, and tells verifiers which fields to visit first.</p>
  <a class="fp-btn gold" href="/assessments" target="_self">{icon("clipboard", 18)} Explore Assessments</a>
  <a class="fp-btn ghost" href="/field-map" target="_self">{icon("pin", 18)} View Field Map</a>
 </div>
</div>""")

# ---------------------------------------------------------------- at a glance
section("FieldPriority at a Glance", "gauge",
        f"Live figures from the system's data. Satellite assessment period: {E(period_text(data))}.")
approved = int(V["analysis_eligible"].fillna(False).astype(bool).sum()) if len(V) else 0
complete = int((A["missing_data"].map(len) == 0).sum()) if len(A) else 0
polys = int(data.fields.geometry.geom_type.isin(["Polygon", "MultiPolygon"]).sum())
c = st.columns(4)
c[0].markdown(kpi("clipboard", "Assessments received", f"{len(V)}",
                  f"Field visits submitted through KoboToolbox ({approved} approved). "
                  f"Plus {len(A)} satellite assessment{'s' if len(A) != 1 else ''} in this run.")
              if len(V) or len(A) else kpi("clipboard", "Assessments received", "0", "No field visits received yet."),
              unsafe_allow_html=True)
c[1].markdown(kpi("pin", "Field locations", f"{n_fields}",
                  f"{polys} with a field-boundary polygon. Boundaries are digitised and not yet field-verified."),
              unsafe_allow_html=True)
c[2].markdown('<div class="fp-card fp-kpi"><div class="top">Drought-risk classes'
              f'<span class="ic">{icon("layers", 20)}</span></div>'
              f'{risk_distribution_html(counts) if counts else "<div class=fp-lab>No assessments yet.</div>"}'
              '<div class="lab">Fields per class in the latest run, from the drought-stress rules.</div></div>',
              unsafe_allow_html=True)
pct = f"{complete / len(A) * 100:.0f}" if len(A) else "–"
c[3].markdown(kpi("gauge", "Data completeness", pct, f"{complete} of {len(A)} fields have every input the rules "
                  "need. Incomplete fields show Insufficient data, never Low.", unit="%" if len(A) else None),
              unsafe_allow_html=True)

# ---------------------------------------------------------------- map + distribution
section("Geographical field overview", "pin", "Each field is drawn as its boundary, coloured by its risk class. "
        "Click a field for details.")
left, right = st.columns([1.75, 1], gap="large")
with left:
    show_map(build_map(data, basemap="Satellite"), height=430)
with right:
    html_block('<h4 style="margin:.2rem 0 0">Risk distribution</h4>'
               '<div class="fp-sub">Fields in each class in the latest assessment.</div>')
    if len(A):
        st.altair_chart(risk_bar_chart(A, height=200), width="stretch")
    else:
        empty("No assessments yet.")
    st.markdown(legend_html([k for k in RISK if counts.get(k)] or ["Insufficient data"]), unsafe_allow_html=True)
    st.page_link("views/risk_analysis.py", label="Open Risk Analysis", icon=":material/arrow_forward:")

# ---------------------------------------------------------------- recent activity
section("Recent activity", "clock", "Latest field visits and issued assessments.")
events = []
for r in V.to_dict("records") if len(V) else []:
    fid = r.get("field_id_pipeline") or r.get("field_id")
    events.append({"when": str(r.get("_submission_time") or r.get("visit_date") or "")[:16].replace("T", " "),
                   "icon": "clipboard", "title": f"Field visit to {fid}",
                   "meta": f"{r.get('district') or ''} · verifier {r.get('verifier_id') or 'n/a'} · "
                           f"status {r.get('validation_status_final') or 'n/a'}", "level": None, "fid": fid})
L = data.ledger if data.ledger is not None else pd.DataFrame()
for r in L.to_dict("records") if len(L) else []:
    events.append({"when": str(r.get("issued_at") or r.get("alert_date") or "")[:16].replace("T", " "),
                   "icon": "sat", "title": f"Assessment issued for {r.get('field_id')}",
                   "meta": f"{r.get('alert_id')} · data up to {r.get('data_end_date')}", "level": r.get("risk_level"),
                   "fid": r.get("field_id")})
events = sorted(events, key=lambda e: e["when"], reverse=True)[:6]
if not events:
    empty("No activity yet. Field visits and assessments will appear here as they arrive.")
else:
    rows = "".join(
        f'<div class="fp-act"><div class="dot">{icon(e["icon"], 18)}</div><div style="flex:1">'
        f'<div class="t"><a href="{profile_link(e["fid"])}" target="_self" style="color:inherit">{E(e["title"])}</a>'
        f' {badge(e["level"]) if e["level"] in RISK else ""}</div>'
        f'<div class="m">{E(e["when"])} · {E(e["meta"])}</div></div></div>' for e in events)
    html_block(f'<div class="fp-card">{rows}</div>')

html_block('<p class="fp-sub" style="margin-top:1.4rem">Risk classes are screening results from satellite and '
           'climate data under the FieldPriority drought-stress rules. They are not confirmed drought: field '
           'verification decides. Accuracy is reported on Data Quality once verified visits exist.</p>')
