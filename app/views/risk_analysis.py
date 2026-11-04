import altair as alt
import pandas as pd
import streamlit as st
from _lib import (get_data, page_title, section, html_block, badge, risk_counts, risk_bar_chart, build_map, show_map,
                  field_location, period_text, empty, kpi, RISK, RISK_ORDER, CFG, E, _base)

data = get_data()
A = data.assessments
page_title("Risk Analysis", "How the assessed fields are spread across the drought-risk classes, where they are, and "
           "what each class means. Every class comes from the FieldPriority drought-stress rules; this page only "
           "presents them.", eyebrow="Drought-risk intelligence", icon_name="rise")

counts = risk_counts(A)
n = len(A)
section("Current situation", "gauge", f"Latest assessment run · {E(period_text(data))} · {n} field{'s' if n != 1 else ''}")
if not n:
    empty("No assessments yet.")
    st.stop()
show_levels = [k for k in RISK_ORDER if k != "Not assessed" or counts.get(k)]
cols = st.columns(len(show_levels))
for col, k in zip(cols, show_levels):
    v = counts.get(k, 0)
    col.markdown(f'<div class="fp-card" style="border-top:5px solid {RISK[k]["color"]}">'
                 f'<div style="margin-bottom:6px">{badge(k)}</div>'
                 f'<div style="font:800 1.8rem var(--fh)">{v}</div>'
                 f'<div class="fp-sub">{v / n * 100:.0f}% of fields</div></div>', unsafe_allow_html=True)

c1, c2 = st.columns([1, 1.2], gap="large")
with c1:
    section("Distribution across classes", "layers")
    st.altair_chart(risk_bar_chart(A, height=260), width="stretch")
with c2:
    section("Where the risk is", "pin")
    show_map(build_map(data, basemap="Satellite"), height=330)

# ---------------------------------------------------------------- comparisons (only with enough observations)
section("Comparisons", "rise", "Shown only when there are enough comparable fields; one field cannot show a pattern.")
A2 = A.copy()
A2["Location"] = A2["field_id"].map(lambda f: field_location(data, f)["district"])
A2["Stage"] = A2["growth_stage_label"].fillna("Unknown")
made = False
for by, label in [("Location", "location"), ("Stage", "crop growth stage")]:
    g = A2.groupby(by)
    if g.ngroups >= 2 and len(A2) >= 4:
        d = A2.groupby([by, "risk_level"]).size().reset_index(name="Fields")
        ch = alt.Chart(d).mark_bar().encode(
            y=alt.Y(f"{by}:N", title=None), x=alt.X("Fields:Q", stack="normalize", title="Share of fields", axis=alt.Axis(format="%")),
            color=alt.Color("risk_level:N", title="Risk class", scale=alt.Scale(domain=list(RISK), range=[RISK[k]["color"] for k in RISK])),
            tooltip=[by, "risk_level", "Fields"])
        st.markdown(f"**By {label}**")
        st.altair_chart(_base(ch.properties(height=40 * g.ngroups + 40)), width="stretch")
        made = True
if not made:
    empty(f"Comparisons by location and by growth stage appear once at least four fields in two or more groups are "
          f"assessed. Currently: {n} field{'s' if n != 1 else ''}, "
          f"{A2['Location'].nunique()} location, {A2['Stage'].nunique()} stage group.")

section("Change over time", "clock")
L = data.ledger if data.ledger is not None else pd.DataFrame()
if len(L) and L["data_end_date"].nunique() >= 2:
    d = L.groupby(["data_end_date", "risk_level"]).size().reset_index(name="Fields")
    ch = alt.Chart(d).mark_bar().encode(x=alt.X("data_end_date:N", title="Data up to"), y=alt.Y("Fields:Q"),
                                        color=alt.Color("risk_level:N", scale=alt.Scale(domain=list(RISK), range=[RISK[k]["color"] for k in RISK])))
    st.altair_chart(_base(ch.properties(height=240)), width="stretch")
else:
    empty("A trend needs assessments from at least two different data periods. All assessments so far use the same "
          "period, so no trend or prediction is shown.")

# ---------------------------------------------------------------- meanings and method
section("What each class means", "doc")
for k in [k for k in RISK_ORDER if k != "Not assessed"]:
    html_block(f'<div class="fp-card" style="margin-bottom:8px;display:flex;gap:14px;align-items:flex-start">'
               f'<div style="min-width:150px">{badge(k)}</div><div>{E(RISK[k]["means"])}</div></div>')

with st.expander("Method and thresholds (for technical users)"):
    r = CFG["rules"]
    w, veg = r["water_deficit"], r["vegetation"]
    st.markdown(f"""
FieldPriority flags **possible drought-related maize stress**. It never confirms drought; field verification does.

- **Water deficit** (rule 4): rainfall in the assessment month (or the month before) at least
  **{abs(w['rain_anomaly_pct_max']):.0f}% below** its CHIRPS 10-year normal, or root-zone soil moisture at least
  **{abs(w['soil_moisture_anomaly_pct_max']):.0f}% below** its multi-year same-month mean.
- **Vegetation decline**: Sentinel-2 NDVI down by at least **{abs(veg['decline_abs']):.2f}** and
  **{abs(veg['decline_rel'])*100:.0f}%** against the reference ({'this season’s earlier peak' if veg['baseline'] == 'within_season' else 'the multi-year same-month mean'}); a drop of
  **{abs(veg['severe_abs']):.2f}** or more is severe.
- Deficit **and** decline → Moderate; High when the growth stage is known and the drop is severe or the crop is at a
  sensitive stage ({', '.join(s.replace('_', ' ') for s in r['sensitive_stages'])}).
  Deficit only → Watch. Decline only → Cause uncertain. Neither → Low. Missing inputs → Insufficient data (rule 7).
- Drying at maturity is not counted as drought (rule 6). Risk level, data confidence and verification status are
  kept separate (rule 9).

All thresholds are **provisional** and set in `config/settings.yaml`; they still need agronomic review.
""")
