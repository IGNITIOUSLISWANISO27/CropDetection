import pandas as pd
import streamlit as st
from _lib import (get_data, html_block, hero_landscape_svg, glance_band, section, risk_counts, build_map, show_map,
                  donut_chart, donut_legend, feature_cards, footer, visits, badge, icon, period_text, empty,
                  RISK, RISK_ORDER, CFG, E, profile_link, link)

data = get_data()
A = data.assessments
V = visits(data)
counts = risk_counts(A)
n_fields = len(data.fields)

# ---------------------------------------------------------------- hero
html_block(f"""
<div class="fp-hero">{hero_landscape_svg()}<div class="shade"></div>
 <div class="inner">
  <span class="tag">{icon("leaf", 14, "#F2C74E")} Maize drought-risk monitoring · {E(CFG["pilot_area"])}</span>
  <h1>Understand Your Fields.<br><span class="gold">Anticipate Drought Risk.</span><br><span class="gold">Act Early.</span></h1>
  <p>A geospatial decision-support platform for monitoring maize field conditions and assessing drought-related
  risks. It combines satellite crop greenness, rainfall and soil moisture with field visits from KoboToolbox,
  and shows verifiers which fields to visit first.</p>
  <a class="fp-btn gold" href="{link('/assessments')}" target="_self">{icon("pin", 18)} Explore Assessments →</a>
  <a class="fp-btn ghost" href="{link('/field-map')}" target="_self">{icon("layers", 18)} View Field Map</a>
 </div>
 <div class="script">Smart Agriculture.<br>Resilient Farmers.</div>
</div>""")

# ---------------------------------------------------------------- at a glance (live figures only)
approved = int(V["analysis_eligible"].fillna(False).astype(bool).sum()) if len(V) else 0
complete = int((A["missing_data"].map(len) == 0).sum()) if len(A) else 0
polys = int(data.fields.geometry.geom_type.isin(["Polygon", "MultiPolygon"]).sum())
total = max(1, sum(counts.values()))
dist_note = " ".join(f'<span style="white-space:nowrap"><i style="display:inline-block;width:9px;height:9px;'
                     f'border-radius:50%;background:{RISK[k]["color"]};margin-right:4px"></i>{counts[k] / total:.0%}</span>'
                     for k in RISK_ORDER if counts.get(k)) or "No assessments yet"
top = max(counts, key=counts.get) if counts else None
updated = str(data.meta.get("assessed_at") or "")[:16].replace("T", " ")
html_block(glance_band([
    ("clipboard", f"{len(V)}", "Assessments Received",
     f"Field visits from KoboToolbox · {approved} approved" if len(V) else "No field visits received yet",
     "#E6F0E9", "#2E8B57"),
    ("pin", f"{n_fields}", "Field Locations", f"{polys} with a boundary polygon (digitised, not yet field-checked)",
     "#E6F0E9", "#1F4D3A"),
    ("layers", f"{counts[top] / total:.0%}" if top else "–", "Risk Distribution",
     (f"{E(RISK[top]['short'])} is the largest class · " if top else "") + dist_note, "#FDF2D6", "#C8930F"),
    ("check", f"{complete / len(A):.0%}" if len(A) else "–", "Data Completeness",
     f"{complete} of {len(A)} fields have every input the rules need", "#E6F0E9", "#2E8B57"),
], updated=f"{updated} UTC" if updated else None))

# ---------------------------------------------------------------- map + distribution + activity
left, right = st.columns([1.75, 1], gap="medium")
with left:
    with st.container(border=True):
        html_block(f'<div class="fp-panel-h"><span>{icon("pin", 18, "#1F4D3A")} Geographical Field Overview</span>'
                   f'<a href="{link("/field-map")}" target="_self">Open full map →</a></div>')
        show_map(build_map(data, basemap="Satellite"), height=470)
with right:
    with st.container(border=True):
        html_block(f'<div class="fp-panel-h"><span>{icon("rise", 18, "#1F4D3A")} Risk Distribution</span>'
                   f'<a href="{link("/risk-analysis")}" target="_self">Details →</a></div>')
        ch = donut_chart(A, height=170)
        if ch is None:
            empty("No assessments yet.")
        else:
            d1, d2 = st.columns([1, 1.15])
            d1.altair_chart(ch, width="content")
            d2.markdown(donut_legend(A), unsafe_allow_html=True)
    with st.container(border=True):
        html_block(f'<div class="fp-panel-h"><span>{icon("clock", 18, "#1F4D3A")} Recent Activity</span>'
                   f'<a href="{link("/assessments")}" target="_self">View all →</a></div>')
        events = []
        for r in V.to_dict("records") if len(V) else []:
            fid = r.get("field_id_pipeline") or r.get("field_id")
            events.append({"when": str(r.get("_submission_time") or r.get("visit_date") or "")[:16].replace("T", " "),
                           "title": f"Field {fid} – {r.get('district') or 'visit'}",
                           "meta": f"Field visit · {r.get('validation_status_final') or 'received'}",
                           "level": None, "fid": fid, "ic": "clipboard"})
        L = data.ledger if data.ledger is not None else pd.DataFrame()
        for r in L.to_dict("records") if len(L) else []:
            events.append({"when": str(r.get("issued_at") or r.get("alert_date") or "")[:16].replace("T", " "),
                           "title": f"Field {r.get('field_id')} – assessed", "meta": f"Data up to {r.get('data_end_date')}",
                           "level": r.get("risk_level"), "fid": r.get("field_id"), "ic": "sat"})
        events = sorted(events, key=lambda e: e["when"], reverse=True)[:4]
        if not events:
            empty("No activity yet.")
        else:
            html_block("".join(
                f'<div class="fp-act"><div class="dot">{icon(e["ic"], 17)}</div><div style="flex:1;min-width:0">'
                f'<div class="t"><a href="{profile_link(e["fid"])}" target="_self" style="color:inherit;text-decoration:none">'
                f'{E(e["title"])}</a></div><div class="m">{E(e["meta"])} · {E(e["when"])}</div></div>'
                f'<div>{badge(e["level"]) if e["level"] in RISK else ""}</div></div>' for e in events))

# ---------------------------------------------------------------- sections + footer
html_block(feature_cards())
html_block('<p class="fp-sub" style="margin-top:.8rem">Risk classes are screening results from satellite and climate '
           'data under the FieldPriority drought-stress rules. They are not confirmed drought: field verification '
           f'decides. Satellite assessment period: {E(period_text(data))}.</p>')
html_block(footer())
