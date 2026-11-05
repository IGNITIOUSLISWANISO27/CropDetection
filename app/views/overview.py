"""Overview: understood in 15 seconds. Zambia this season (three answers), the map, one location spotlight showing
how the layers connect, then the key indicators. Everything else is one click away."""
import streamlit as st
from _lib import (html_block, icon, footer, national, monitored_fields, national_summary, intel_summary_html,
                  zmd_banner, zmd_alerts, build_zambia_map, show_map, layer_available, location_records, link,
                  hero_photo_html, answer_cards_html, national_answers, signal_list_html, LAYERS, LEVELS, NCFG, E,
                  interpret)

nd = national()
F = monitored_fields(nd)

# ---------------------------------------------------------------- hero (photo)
html_block(hero_photo_html(f"""
  <span class="tag">{icon("pin", 14, "#F2C74E")} Zambia · Agricultural Intelligence</span>
  <h1>Understanding agricultural conditions.<br><span class="gold">Supporting better decisions.</span></h1>
  <p>Rainfall, temperature, water, crops and solar potential, connected for every district and field.</p>
  <div class="chips"><span class="chip">MAIZE FIRST</span><span class="chip o">LOCATION-BASED</span></div>
  <div><a class="fp-btn gold" href="{link('/location')}" target="_self">{icon("pin", 18)} Open a location</a>
  <a class="fp-btn ghost" href="{link('/map')}" target="_self">{icon("layers", 18)} Explore the map</a></div>"""))

# official warnings only when something is in force
try:
    T, _ = zmd_alerts(nd)
    if len(T) and T["active"].any():
        html_block(zmd_banner(nd))
except Exception:
    pass

# ---------------------------------------------------------------- Zambia this season: one interpretation
what, what_sub, why, why_sub, nxt, colr = national_answers(nd, F)
html_block(f'<div class="fp-panel-h"><span>{icon("gauge", 18, "#1F4D3A")} Zambia this season</span>'
           f'<span class="fp-mini">{E(nd.report.get("period_label") or "")}</span></div>')
html_block(answer_cards_html(what, E(what_sub), why, E(why_sub), nxt, colr))

# ---------------------------------------------------------------- map + spotlight
D = nd.districts.sort_values("district")
left, right = st.columns([1.75, 1], gap="medium")
with left:
    with st.container(border=True):
        key = st.segmented_control("Map layer", list(LAYERS), default="rainfall", key="home_layer", width="stretch",
                                   format_func=lambda k: LAYERS[k]["short"] + ("" if layer_available(nd, k) else " (soon)"),
                                   label_visibility="collapsed") or "rainfall"
        show_map(build_zambia_map(nd, key, F, height=560), height=560)
        st.caption(LAYERS[key]["what"] + " Click a district for its full picture.")

with right:
    from fieldpriority.national.aggregate import zone_members
    from fieldpriority.national.zones import REGIONS as ZONES
    zc = [z for z in ["I", "IIa", "IIb", "II", "III"] if zone_members(nd, z)]
    opts = (["district:" + d for d in D["district_id"]] + ["zone:" + z for z in zc]
            + ["province:" + p for p in sorted(D["province"].unique())]
            + ["field:" + f"{r.pilot}|{r.field_id}" for r in F.itertuples()])
    names = dict(zip(D["district_id"], D["district"] + " · " + D["province"]))

    def _fmt(o):
        k, v = o.split(":", 1)
        return {"zone": lambda: f"Zone {ZONES[v]['name']} ({ZONES[v]['short']})", "province": lambda: f"{v} Province",
                "district": lambda: names[v],
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
            st.page_link("views/location.py", label="Open its full picture", icon=":material/arrow_forward:",
                         query_params={k: v})

    # spotlight: the district that most needs attention, with its layers connected
    ranked = []
    if nd.available:
        for d in D.itertuples():
            rec = location_records(nd, d.district_id)
            it = interpret(d.district, rec, NCFG["classes"])
            if it["level"] in ("concern", "watch"):
                rain = (rec.get("rainfall_anomaly_pct") or {}).get("value")
                ranked.append((0 if it["level"] == "concern" else 1, rain if isinstance(rain, (int, float)) else 0,
                               d.district_id, d.district, rec, it))
        ranked.sort(key=lambda x: (x[0], x[1]))
    if ranked:
        _, _, sid, sname, srec, sit = ranked[0]
        title = "Spotlight: most in need of attention"
    elif nd.available:
        sid = F["district_id"].dropna().iloc[0] if len(F) and F["district_id"].notna().any() else "solwezi"
        sname = D.set_index("district_id").loc[sid, "district"]
        srec = location_records(nd, sid)
        sit = interpret(sname, srec, NCFG["classes"])
        title = "Spotlight: pilot district"
    if nd.available:
        here = F[F["district_id"] == sid] if len(F) else F
        lab, col = LEVELS[sit["level"]]
        with st.container(border=True):
            html_block(f'<div class="fp-spot"><div class="fp-mini" style="text-transform:uppercase;letter-spacing:.08em;'
                       f'font-weight:700">{E(title)}</div><div style="display:flex;justify-content:space-between;'
                       f'align-items:center;gap:8px;margin:.2rem 0"><h3>{E(sname)}</h3><span class="fp-zc" '
                       f'style="background:{col};color:#fff">{E(lab)}</span></div>'
                       f'<div style="font-weight:700;color:{col}">{E(sit["short"])}</div>'
                       f'{signal_list_html(srec, here)}<div class="fp-mini" style="color:#1E2A24">'
                       f'{E(sit["together"])}</div></div>')
            st.page_link("views/location.py", label=f"Open {sname}'s full picture", icon=":material/arrow_forward:",
                         query_params={"district": sid})
            if len(ranked) > 1:
                html_block('<div class="fp-mini">Also to watch: ' + ", ".join(
                    f'<a href="{link("/location", district=r[2])}" target="_self">{E(r[3])}</a>' for r in ranked[1:6])
                    + '</div>')

# ---------------------------------------------------------------- key indicators (details on hover)
built = str(nd.report.get("built_at") or "")[:10]
html_block(intel_summary_html(national_summary(nd, F), updated=f"updated {built}" if built else
                              "District layers not built yet"))
html_block(f'<div class="fp-mini" style="text-align:right"><a href="{link("/about")}" target="_self">'
           f'About the platform, methods and accuracy →</a></div>')
html_block(footer())
