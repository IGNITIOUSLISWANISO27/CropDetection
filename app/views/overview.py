"""Overview: the key message first (map, six indicators, where attention is needed), details one click away."""
import streamlit as st
from _lib import (html_block, hero_landscape_svg, icon, footer, national, monitored_fields, national_summary,
                  intel_summary_html, zmd_banner, build_zambia_map, show_map, layer_available, location_records, link,
                  period_of, LAYERS, LEVELS, NCFG, E, interpret)

nd = national()
F = monitored_fields(nd)
per = period_of(nd)

# ---------------------------------------------------------------- heading (short)
html_block(f"""
<div class="fp-hero compact">{hero_landscape_svg()}<div class="shade"></div>
 <div class="inner">
  <span class="tag">{icon("pin", 14, "#F2C74E")} Zambia · Agricultural Intelligence</span>
  <h1>Understanding agricultural conditions.<br><span class="gold">Supporting better decisions.</span></h1>
  <p>Rainfall, temperature, water, crops and solar potential, brought together for each location.</p>
  <div class="chips"><span class="chip">MAIZE FIRST</span><span class="chip o">LOCATION-BASED</span></div>
  <div class="explore"><b>Explore by location:</b> districts · agricultural zones · individual fields</div>
 </div>
 <div class="script">Environmental change.<br>People's livelihoods.</div>
</div>""")
html_block(zmd_banner(nd))

# ---------------------------------------------------------------- six indicators (details on hover)
built = str(nd.report.get("built_at") or "")[:10]
html_block(intel_summary_html(national_summary(nd, F), updated=f"{per} · updated {built}" if built else
                              "District layers not built yet"))

# ---------------------------------------------------------------- map + where to look
left, right = st.columns([2.1, 1], gap="medium")
with left:
    with st.container(border=True):
        key = st.segmented_control("Map layer", list(LAYERS), default="rainfall", key="home_layer", width="stretch",
                                   format_func=lambda k: LAYERS[k]["short"] + ("" if layer_available(nd, k) else " (soon)"),
                                   label_visibility="collapsed") or "rainfall"
        show_map(build_zambia_map(nd, key, F, height=520), height=520)
        st.caption(LAYERS[key]["what"] + " Click a district to open its intelligence report.")

with right:
    with st.container(border=True):
        html_block(f'<div class="fp-panel-h"><span>{icon("pin", 18, "#1F4D3A")} Open a location</span></div>')
        D = nd.districts.sort_values("district")
        from fieldpriority.national.aggregate import zone_members
        from fieldpriority.national.zones import REGIONS as ZONES
        zc = [z for z in ["I", "IIa", "IIb", "II", "III"] if zone_members(nd, z)]
        opts = (["district:" + d for d in D["district_id"]] + ["zone:" + z for z in zc]
                + ["province:" + p for p in sorted(D["province"].unique())]
                + ["field:" + f"{r.pilot}|{r.field_id}" for r in F.itertuples()])
        names = dict(zip(D["district_id"], D["district"] + " · " + D["province"]))

        def _fmt(o):
            k, v = o.split(":", 1)
            return {"zone": lambda: f"Zone {ZONES[v]['name']} ({ZONES[v]['short']})",
                    "province": lambda: f"{v} Province", "district": lambda: names[v],
                    "field": lambda: f"Field {v.split('|')[1]} · {v.split('|')[0].title()} pilot"}[k]()
        pick = st.selectbox("Location", opts, index=None, placeholder="Search a district, zone, province or field",
                            format_func=_fmt, label_visibility="collapsed")
        if pick:
            k, v = pick.split(":", 1)
            if k == "field":
                p, fid = v.split("|")
                st.page_link("views/assessments.py", label=f"Open field {fid}", icon=":material/arrow_forward:",
                             query_params={"field": fid, "area": p})
            else:
                st.page_link("views/location.py", label="Open the intelligence report", icon=":material/arrow_forward:",
                             query_params={k: v})

    with st.container(border=True):
        html_block(f'<div class="fp-panel-h"><span>{icon("alert", 18, "#1F4D3A")} Where attention is needed</span></div>')
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
            short = lambda s: (s.replace("root-zone soil moisture", "soil moisture").replace(" below normal", "")
                               .replace("rainfall", "rain").replace("vegetation condition", "vegetation"))
            for _, _, d, it in rows[:6]:
                lab, col = LEVELS[it["level"]]
                sig = ", ".join(short(x) for x in it["concern"] if not x.startswith("temperatures")) or lab
                html_block(f'<div class="fp-watch"><i style="background:{col}"></i><a href="'
                           f'{link("/location", district=d.district_id)}" target="_self">{E(d.district)}</a>'
                           f'<span class="s">{E(sig)} below normal</span></div>')
            if len(rows) > 6:
                st.caption(f"+ {len(rows) - 6} more on the map")

html_block(f'<div class="fp-mini" style="text-align:right;margin-top:.6rem"><a href="{link("/about")}" '
           f'target="_self">About the platform, methods and accuracy →</a></div>')
html_block(footer())
