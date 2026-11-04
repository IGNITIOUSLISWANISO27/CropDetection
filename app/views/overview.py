import pandas as pd
import streamlit as st
from _lib import (html_block, hero_landscape_svg, icon, footer, national, monitored_fields, national_summary,
                  intel_summary_html, build_zambia_map, show_map, layer_available, location_records, link, badge,
                  period_of, LAYERS, LEVELS, NCFG, E, interpret)

nd = national()
F = monitored_fields(nd)
per = period_of(nd)

# ---------------------------------------------------------------- A. heading
html_block(f"""
<div class="fp-hero">{hero_landscape_svg()}<div class="shade"></div>
 <div class="inner">
  <span class="tag">{icon("pin", 14, "#F2C74E")} Zambia · Agricultural Intelligence</span>
  <h1>Understanding agricultural conditions.<br><span class="gold">Supporting better decisions.</span></h1>
  <p>Connecting crop conditions, rainfall, temperature, water stress and solar potential to deliver
  location-specific agricultural intelligence.</p>
  <div class="chips"><span class="chip">MAIZE FIRST</span><span class="chip o">LOCATION-BASED</span></div>
  <div class="explore"><b>Explore agricultural conditions by location:</b> districts · individual fields
  <span style="opacity:.75">(agro-ecological zones next)</span></div>
  <a class="fp-btn gold" href="{link('/location')}" target="_self">{icon("doc", 18)} Open a location report →</a>
  <a class="fp-btn ghost" href="{link('/map')}" target="_self">{icon("layers", 18)} Explore the map</a>
 </div>
 <div class="script">Environmental change.<br>People's livelihoods.</div>
</div>""")

# ---------------------------------------------------------------- C. intelligence summary (live figures only)
built = str(nd.report.get("built_at") or "")[:10]
html_block(intel_summary_html(national_summary(nd, F),
                              updated=f"District layers: {per} · built {built}" if built else "District layers not built yet"))

# ---------------------------------------------------------------- B. geographical overview
left, right = st.columns([2.1, 1], gap="medium")
with left:
    with st.container(border=True):
        html_block(f'<div class="fp-panel-h"><span>{icon("layers", 18, "#1F4D3A")} Zambia: where conditions are '
                   f'changing</span><a href="{link("/map")}" target="_self">Open full map →</a></div>')
        keys = list(LAYERS)
        key = st.segmented_control("Map layer", keys, default="rainfall", key="home_layer", width="stretch",
                                   format_func=lambda k: LAYERS[k]["short"] + ("" if layer_available(nd, k) else " (soon)"),
                                   label_visibility="collapsed") or "rainfall"
        show_map(build_zambia_map(nd, key, F, height=500), height=500)
        avail = layer_available(nd, key)
        st.caption(LAYERS[key]["what"] + ("" if avail else " Not yet available: needs the Earth Engine district "
                                          "export (Person 1, gee/district_layers.js).") +
                   " Click a district for its location report. Purple squares: field visits; dots: monitored fields.")
with right:
    with st.container(border=True):
        html_block(f'<div class="fp-panel-h"><span>{icon("pin", 18, "#1F4D3A")} Explore by location</span></div>')
        D = nd.districts.sort_values("district")
        opts = ["district:" + d for d in D["district_id"]] + ["field:" + f"{r.pilot}|{r.field_id}" for r in F.itertuples()]
        names = dict(zip(D["district_id"], D["district"] + " · " + D["province"]))
        pick = st.selectbox("District or field", opts, index=None, placeholder="Type a district or field…",
                            format_func=lambda o: (names[o[9:]] + " (district)") if o.startswith("district:")
                            else f"Field {o.split('|')[1]} · {o[6:].split('|')[0].title()} pilot")
        if pick:
            if pick.startswith("district:"):
                st.page_link("views/location.py", label="Open the location report", icon=":material/arrow_forward:",
                             query_params={"district": pick[9:]})
            else:
                p, fid = pick[6:].split("|")
                st.page_link("views/assessments.py", label=f"Open the profile of field {fid}",
                             icon=":material/arrow_forward:", query_params={"field": fid, "area": p})
    with st.container(border=True):
        html_block(f'<div class="fp-panel-h"><span>{icon("alert", 18, "#1F4D3A")} Districts to watch</span>'
                   f'<span class="fp-sub" style="font-weight:500">{E(per)}</span></div>')
        if not nd.available:
            st.caption("District layers not built yet. Run monthly_update.bat.")
        else:
            rows = []
            for d in D.itertuples():
                rec = location_records(nd, d.district_id)
                it = interpret(d.district, rec, NCFG["classes"])
                if it["level"] in ("concern", "watch"):
                    rain = (rec.get("rainfall_anomaly_pct") or {}).get("value")
                    rows.append((0 if it["level"] == "concern" else 1, rain if isinstance(rain, (int, float)) else 0,
                                 d, it))
            rows.sort(key=lambda x: (x[0], x[1]))
            if not rows:
                st.caption("No district shows a departure from normal.")
            for _, _, d, it in rows[:6]:
                lab, col = LEVELS[it["level"]]
                html_block(f'<div class="fp-act"><div class="dot" style="background:{col}22;color:{col}">'
                           f'{icon("alert" if it["level"] == "concern" else "eye", 17)}</div><div style="flex:1;min-width:0">'
                           f'<div class="t"><a href="{link("/location", district=d.district_id)}" target="_self" '
                           f'style="color:inherit;text-decoration:none">{E(d.district)}</a> '
                           f'<span class="fp-sub" style="font-weight:500">· {E(d.province)}</span></div>'
                           f'<div class="m">{E(lab)}: {E("; ".join(it["concern"]))}</div></div></div>')
            if len(rows) > 6:
                st.caption(f"{len(rows) - 6} more on the map.")

# ---------------------------------------------------------------- the framework: six connected layers
html_block(f'<div class="fp-section">{icon("layers", 20, "#1F4D3A")}One location, six connected layers of evidence</div>'
           '<div class="fp-sub">Each layer feeds the same location report; none is a separate dashboard.</div>')
sm_ok = bool(nd.available and ((nd.indicators["indicator"] == "soil_moisture_anomaly_pct")
                               & (nd.indicators["status"] == "ok")).any())
status = {
    "Crop & vegetation": ("leaf", "Sentinel-2 field greenness (pilots) · MODIS district greenness",
                          layer_available(nd, "vegetation") or len(F) > 0, "Fields live · districts soon"
                          if not layer_available(nd, "vegetation") else "Live"),
    "Rainfall": ("drop", "CHIRPS v3.0, 5 km, monthly vs 10-season normal", layer_available(nd, "rainfall"), "Live"),
    "Temperature": ("thermo", "NASA POWER (districts) · ERA5-Land (fields)", layer_available(nd, "temperature"), "Live"),
    "Water stress": ("drop", "Rainfall + temperature now; SMAP soil moisture next", layer_available(nd, "water"),
                     "Live" if sm_ok else "Indication only"),
    "Local observations": ("camera", "KoboToolbox field visits and photos", len(F) > 0, "Live"),
    "Solar potential": ("sun", "NASA POWER solar radiation, annual mean", layer_available(nd, "solar"), "Live"),
}
cards = ""
for t, (ic, s, ok, lab) in status.items():
    col = ("#E6F0E9", "#1F4D3A") if ok and lab == "Live" else ("#FFF1D6", "#7A5300") if ok else ("#EEE", "#5E6B63")
    cards += (f'<div class="fp-layer"><div class="h">{icon(ic, 18, "#1F4D3A")}{E(t)}</div><div class="s">{E(s)}</div>'
              f'<span class="st" style="background:{col[0]};color:{col[1]}">{E(lab if ok else "Not yet available")}</span></div>')
html_block(f'<div class="fp-layers">{cards}</div>')
html_block('<div class="fp-flow"><div class="b"><b>Location-based intelligence</b>A district or a field, with every '
           'layer above</div><div class="a">→</div><div class="b"><b>Integrated analysis</b>Indicators connected, '
           'conditions assessed, relationships explained</div><div class="a">→</div><div class="b"><b>Practical '
           'intelligence</b>What is happening? Why does it matter? What should be considered next?</div></div>')

html_block('<div class="fp-story"><h3>Why it matters</h3>Changes in rainfall, temperature, vegetation and water '
           'availability affect maize production, household food security and income. Earlier, location-specific '
           'information helps farmers, extension officers and planners respond before losses happen. Every number '
           'on this platform shows its source, date, coverage and confidence, and separates measurements, '
           'satellite estimates, model outputs and field observations.</div>')
html_block(footer())
