"""Overview: understood in 10 seconds. What the platform is (hero), Zambia this season (three answers), the map with
the condition of every district, a spotlight location, the field-to-intelligence pathway and the key signals."""
import streamlit as st
from _lib import (html_block, icon, footer, national, monitored_fields, national_summary, intel_summary_html,
                  zmd_banner, zmd_alerts, build_zambia_map, show_map, layer_available, location_records, link,
                  hero_photo_html, answer_cards_html, kobo_button, national_answers, signal_list_html, field_to_intel_html,
                  HOME_LAYERS, LAYERS, STATUS, NCFG, E,
                  interpret)

nd = national()
F = monitored_fields(nd)

# ---------------------------------------------------------------- hero (photo)
DEMO = "kitwe" if "kitwe" in set(nd.districts["district_id"]) else None
html_block(hero_photo_html(f"""
  <span class="tag">{icon("pin", 14, "#F2C74E")} Zambia · maize-growing areas</span>
  <h1>Zambia Agricultural Intelligence</h1>
  <p style="font-size:1.15rem;color:#fff">Understand what is happening in agricultural areas.</p>
  <div class="fp-flow4"><span>LOCATION</span><i>→</i><span>EVIDENCE</span><i>→</i><span>CONDITIONS</span><i>→</i>
  <span>INTELLIGENCE</span></div>
  <div><a class="fp-btn gold" href="{link('/location', district=DEMO) if DEMO else link('/location')}" target="_self">
  {icon("pin", 18)} Explore a location</a>
  <a class="fp-btn ghost" href="{link('/map')}" target="_self">{icon("layers", 18)} Zambia map</a></div>
  <div style="margin-top:.8rem">{kobo_button(small=True)}</div>"""))

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
why = "Climate and environmental conditions can significantly affect Zambia's food production and farmer incomes."
why_html = ("During the 2023/24 drought, <b>Zambia's maize production fell by more than 50%</b> compared with the "
            "previous season.<br><br>FieldPriority helps identify where changing conditions may be affecting crops, "
            "water availability and agricultural productivity before the picture becomes harder to respond to."
            '<div style="margin-top:.6rem"><a href="' + link("/map") + '" target="_self" style="font-weight:700">'
            "See what is happening across Zambia →</a></div>")
html_block(answer_cards_html(what, E(what_sub), why, why_html, nxt, colr))

# ---------------------------------------------------------------- map + spotlight
D = nd.districts.sort_values("district")
left, right = st.columns([1.75, 1], gap="medium")
with left:
    with st.container(border=True):
        key = st.segmented_control("Map layer", HOME_LAYERS, default="overall", key="home_layer", width="stretch",
                                   format_func=lambda k: LAYERS[k]["short"] + ("" if layer_available(nd, k) else " (soon)"),
                                   label_visibility="collapsed") or "overall"
        show_map(build_zambia_map(nd, key, F, height=560), height=560)
        st.caption(LAYERS[key]["what"] + " Click a district to open its intelligence summary.")

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
                # signals closer to the crop weigh more: vegetation 3, soil moisture 2, rainfall 1, warmth 0.5
                w = sum(3 if x.startswith("vegetation") else 2 if x.startswith("root-zone") else
                        1 if x.startswith("rainfall") else .5 for x in it["concern"])
                ranked.append(({"priority": 0, "attention": 1}.get(it["status"], 2), -w, d.district_id, d.district,
                               rec, it))
        ranked.sort(key=lambda x: (x[0], x[1], x[3]))
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
        lab, col = STATUS[sit["status"]]
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

# ---------------------------------------------------------------- field to intelligence + key signals
html_block(field_to_intel_html())
built = str(nd.report.get("built_at") or "")[:10]
html_block(intel_summary_html(national_summary(nd, F), updated=f"updated {built}" if built else
                              "District layers not built yet"))
html_block(f'<div class="fp-mini" style="text-align:right"><a href="{link("/about")}" target="_self">'
           f'About the platform, methods and accuracy →</a></div>')
html_block(footer())
