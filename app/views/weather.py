"""Weather & warnings: official information from the Zambia Meteorological Department (ZMD), by district."""
import json

import folium
import pandas as pd
import streamlit as st
from branca.element import Element
from _lib import (html_block, icon, national, location_records, show_map, link, type_tag, class_chip, empty, footer,
                  zmd_alerts, zmd_seasonal, zmd_time, zmd_cat_chip, zmd_sev_chip, period_of, ZMD, E)

nd = national()
D = nd.districts.sort_values("district").reset_index(drop=True)
spec, S, ON, OFF = zmd_seasonal()
T, status = zmd_alerts(nd)
ACT = T[T["active"]] if len(T) else T

# ---------------------------------------------------------------- heading and location
html_block(f'<div class="fp-eyebrow">Official weather information</div>'
           f'<h1 style="margin:.1rem 0 .3rem">Weather &amp; warnings</h1>'
           f'<div class="fp-sub" style="max-width:62rem">Forecasts and warnings from the <b>Zambia Meteorological '
           f'Department (ZMD)</b>, arranged by district. FieldPriority does not issue forecasts or warnings: everything '
           f'on this page is ZMD\'s, unchanged, with a link to the original. {type_tag("official")}</div>')

ids = D["district_id"].tolist()
names = dict(zip(D["district_id"], D["district"] + " · " + D["province"] + " Province"))
OPTS = ["zambia"] + ids
qd = st.query_params.get("district")
if "wx_pick" not in st.session_state or (qd in ids and qd != st.session_state.get("wx_pick")):
    st.session_state["wx_pick"] = qd if qd in ids else "zambia"
c1, c2 = st.columns([2, 1.3], vertical_alignment="bottom")
pick = c1.selectbox("District", OPTS, key="wx_pick", format_func=lambda o: "All of Zambia" if o == "zambia" else names[o])
if pick == "zambia":
    st.query_params.pop("district", None)
else:
    st.query_params["district"] = pick
    c2.page_link("views/location.py", label="Open this district's location report", icon=":material/arrow_forward:",
                 query_params={"district": pick})
dname = None if pick == "zambia" else D.set_index("district_id").loc[pick, "district"]


def _lean(ranks):
    dry, wet = sum(r <= 2 for r in ranks), sum(r >= 4 for r in ranks)
    return "drier than normal" if dry > wet else "wetter than normal" if wet > dry else "mixed"


def sec(n, title, sub=None):
    html_block(f'<div class="fp-rep-h"><span class="n">{n}</span><span>{E(title)}</span></div>'
               + (f'<div class="fp-sub" style="margin:-.3rem 0 .6rem">{sub}</div>' if sub else ""))


def alert_card(a, here=False):
    col = ZMD.SEVERITY.get(a["severity"] or "Unknown", ZMD.SEVERITY["Unknown"])[1]
    ds = sorted(D.set_index("district_id").loc[list(a["districts"]), "district"]) if a["n_districts"] else []
    where = (f"{len(ds)} district(s): " + ", ".join(ds[:14]) + (f" and {len(ds) - 14} more" if len(ds) > 14 else "")
             if ds else "Area not matched to districts: see the ZMD alert")
    basis = sorted(set(a["districts"].values())) if a["n_districts"] else []
    valid = (f"From {zmd_time(a['onset'] or a['effective'])} until {zmd_time(a['expires'])}"
             if a["expires"] else f"Issued {zmd_time(a['sent'])}")
    link_ = a["web"] or a["cap_url"] or ZMD.ALERTS_PAGE
    return (f'<div class="fp-zal" style="border-left-color:{col}">'
            f'<div>{zmd_sev_chip(a["severity"])}<span class="fp-zc" style="background:#EEF3F8;color:#14233A">'
            f'{E(a["event"] or "Alert")}</span>'
            + ('<span class="fp-zc" style="background:#14233A;color:#fff">Covers this district</span>' if here else "")
            + f'</div><h4>{E(a["headline"])}</h4>'
            f'<div class="meta">{E(valid)} · Urgency: {E(a["urgency"] or "–")} · Certainty: {E(a["certainty"] or "–")}'
            f' · Issued {E(zmd_time(a["sent"]))}</div>'
            f'<div style="margin-top:.5rem;font-size:.92rem">{E(a["description"])}</div>'
            + (f'<div class="do"><b>What ZMD advises:</b> {E(a["instruction"])}</div>' if a["instruction"] else "")
            + f'<div class="meta" style="margin-top:.5rem"><b>Where:</b> {E(where)}'
            + (f' <span style="opacity:.8">({E("; ".join(basis))})</span>' if basis else "")
            + f' · <a href="{E(link_)}" target="_blank">Open the alert on zmd.gov.zm</a></div></div>')


# ================================================================ 1. warnings
sec(1, "Weather warnings and advisories", "Live from ZMD's public alert feed (Common Alerting Protocol). "
    "Each alert's area is matched to districts using the area ZMD drew, or the places it names.")
if status["live"]:
    st.caption(f"Checked {zmd_time(status['checked'])} (Zambia time). The feed is checked again every 30 minutes.")
elif status["have"]:
    st.warning(f"ZMD's alert feed could not be reached just now, so this shows the copy saved on "
               f"{zmd_time(status['retrieved'])}. Check [zmd.gov.zm/alerts]({ZMD.ALERTS_PAGE}) for anything newer.")
else:
    st.warning(f"ZMD's alert feed could not be reached and no saved copy exists yet. Open "
               f"[zmd.gov.zm/alerts]({ZMD.ALERTS_PAGE}) for the current warnings.")

if len(ACT):
    if pick != "zambia":
        mine = ACT[ACT["districts"].map(lambda d: pick in d)]
        others = ACT[~ACT.index.isin(mine.index)]
        html_block(f'<div class="fp-panel-h"><span>{icon("storm", 18, "#B9342B")} In force for {E(dname)}: '
                   f'{len(mine)}</span></div>')
        if len(mine):
            for a in mine.to_dict("records"):
                html_block(alert_card(a, here=True))
        else:
            st.caption(f"No ZMD warning in force covers {dname}.")
        if len(others):
            with st.expander(f"Other warnings in force in Zambia ({len(others)})"):
                for a in others.to_dict("records"):
                    html_block(alert_card(a))
    else:
        cnt = ACT["districts"].map(len).sum()
        html_block(f'<div class="fp-panel-h"><span>{icon("storm", 18, "#B9342B")} Warnings in force: {len(ACT)}'
                   f'</span></div>')
        a1, a2 = st.columns([1.25, 1], gap="medium")
        with a2:
            # districts coloured by the most severe warning in force
            worst = {}
            for a in ACT.to_dict("records"):
                for did in a["districts"]:
                    if a["sev_rank"] >= worst.get(did, (-1, ""))[0]:
                        worst[did] = (a["sev_rank"], a["severity"], a["headline"])
            g = D.copy()
            g["col"] = g["district_id"].map(lambda d: ZMD.SEVERITY.get(worst[d][1], ZMD.SEVERITY["Unknown"])[1]
                                            if d in worst else "#E4E7E3")
            g["txt"] = g["district_id"].map(lambda d: f"{worst[d][1]}: {worst[d][2]}" if d in worst else "No warning")
            m = folium.Map(location=[-13.4, 27.8], zoom_start=5, tiles="https://server.arcgisonline.com/ArcGIS/rest/"
                           "services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",
                           attr="Esri, HERE, Garmin, © OpenStreetMap contributors")
            folium.GeoJson(json.loads(g[["district", "txt", "col", "geometry"]].to_json()),
                           style_function=lambda f: {"fillColor": f["properties"]["col"], "color": "#fff", "weight": .7,
                                                     "fillOpacity": .85},
                           tooltip=folium.GeoJsonTooltip(["district", "txt"], aliases=["District", "ZMD"])).add_to(m)
            m.fit_bounds([[-18.1, 21.99], [-8.2, 33.7]])
            show_map(m, height=380)
        with a1:
            for a in ACT.to_dict("records"):
                html_block(alert_card(a))
else:
    if status["have"]:
        html_block(f'<div class="fp-zban" style="background:#E8F1EA;border:1px solid #CFE3D4;color:#1F4D3A">'
                   f'<div class="ic" style="background:#2E8B57;color:#fff">{icon("check", 20)}</div><div>'
                   f'<b>No ZMD weather warning is in force</b>{" for " + E(dname) if dname else ""}.</div></div>')

past = T[~T["active"]] if len(T) else T
if pick != "zambia" and len(past):
    past = past[past["districts"].map(lambda d: pick in d)]
with st.expander(f"Recent ZMD alerts that have ended{' for ' + dname if dname else ''} ({len(past)})"):
    if len(past):
        tab = pd.DataFrame({"Issued": past["sent_t"].map(lambda t: zmd_time(t, False)), "Type": past["event"],
                            "Severity": past["severity"], "Headline": past["headline"],
                            "Districts": past["n_districts"], "Areas named by ZMD": past["areas"],
                            "Link": past["web"].where(past["web"].astype(bool), past["cap_url"])})
        st.dataframe(tab, hide_index=True, width="stretch",
                     column_config={"Link": st.column_config.LinkColumn("Link", display_text="Open")})
        st.caption("The feed keeps ZMD's most recent alerts only. Older warnings are on zmd.gov.zm.")
    else:
        st.caption("None in ZMD's current feed.")

# ================================================================ 2. seasonal forecast
if spec is None or not len(S):
    sec(2, "Seasonal rainfall forecast")
    empty("The ZMD seasonal forecast has not been loaded (config/zmd_seasonal_forecast.yaml).")
else:
    sec(2, f"Seasonal rainfall forecast {spec['season']}",
        f"{E(spec['title'])}, issued {E(zmd_time(spec['issued'] + 'T12:00:00+02:00', False))} by the "
        f"{E(spec['issued_by'])}. Categories compare the expected rainfall with the normal for each three-month "
        f"period. <a href='{E(spec['pdf'])}' target='_blank'>Read the full bulletin (PDF)</a>.")
    html_block(f'<div class="fp-interp" style="border-left-color:#1F4E80;margin-bottom:.8rem">{E(spec["drivers"])}</div>')
    pers = [p for p in ZMD.PERIOD_ORDER if p in set(S["period"])]
    plabel = dict(zip(S["period"], S["period_label"]))

    if pick != "zambia":
        R = S[S["district_id"] == pick].set_index("period")
        cells = ""
        for p in pers:
            r = R.loc[p]
            chips = (" ".join(zmd_cat_chip(c, small=True) for c in str(r["codes"]).split("|"))
                     if r["split"] or r["conflict"] else zmd_cat_chip(r["code"], r["category"]))
            x = r["text"] if (r["split"] or r["conflict"]) else ""
            note = ("ZMD lists this district under two categories for this period." if r["conflict"] else
                    r["basis"])
            cells += (f'<div><div class="p">{E(p)} · {E(plabel[p])}</div><div style="margin-top:5px">{chips}</div>'
                      + (f'<div class="x" style="color:#1E2A24">{E(x)}</div>' if x else "")
                      + f'<div class="x">{E(note)}</div></div>')
        html_block(f'<div class="fp-panel-h"><span>{icon("drop", 18, "#1F4E80")} {E(dname)}: expected rainfall '
                   f'by period</span></div><div class="fp-ztl">{cells}</div>')
        on = ON.set_index("district_id").loc[pick]
        off = OFF.set_index("district_id").loc[pick]
        ranks = ZMD.district_ranks(S, pick)
        adv = ZMD.advisories_for(spec, ranks)
        k1, k2 = st.columns([1, 1.2], gap="medium")
        with k1:
            html_block(f'<div class="fp-card"><div class="fp-kv">'
                       f'<div>Start of the rains (onset)</div><div>{E(on["text"])}'
                       f'<div class="fp-sub">{E(on["basis"])}</div></div>'
                       f'<div>End of the rains (cessation)</div><div>{E(off["text"])}'
                       f'<div class="fp-sub">{E(off["basis"])}</div></div>'
                       f'<div>Dry spells</div><div>{E(spec["dry_spells"])}</div></div></div>')
        with k2:
            html_block('<div class="fp-card"><h4>ZMD advice for farmers in areas like this</h4><ul class="fp-att">'
                       + "".join(f"<li>{E(x)}</li>" for x in adv) + '</ul><div class="fp-sub">From the seasonal '
                       'bulletin. Shown because ZMD expects '
                       + E(" and ".join(sorted({"drier" if r <= 2 else "wetter" for r in ranks if r != 3})) or "normal")
                       + ' conditions in at least one period here.</div></div>')

    # national map of one period
    st.write("")
    p_sel = st.segmented_control("Period", pers, default="DJF" if "DJF" in pers else pers[0], key="wx_per",
                                 format_func=lambda p: f"{p} · {plabel[p]}", width="stretch") or pers[0]
    m1, m2 = st.columns([1.5, 1], gap="medium")
    P = S[S["period"] == p_sel].set_index("district_id")
    with m1:
        g = D.copy()
        g["col"] = g["district_id"].map(lambda d: ZMD.CATEGORIES[P.loc[d, "code"]][2] if P.loc[d, "code"] else "#D9D9D9")
        g["txt"] = g["district_id"].map(lambda d: P.loc[d, "text"])
        g["pop"] = [f'<div style="font:13px Inter,sans-serif;min-width:190px"><b>{E(r.district)}</b><div style="margin:5px 0">'
                    f'{E(P.loc[r.district_id, "text"])}</div><a href="{link("/weather", district=r.district_id)}" '
                    f'target="_top">Weather &amp; warnings for {E(r.district)}</a></div>' for r in g.itertuples()]
        m = folium.Map(location=[-13.4, 27.8], zoom_start=6, tiles="https://server.arcgisonline.com/ArcGIS/rest/"
                       "services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",
                       attr="Esri, HERE, Garmin, © OpenStreetMap contributors")
        folium.GeoJson(json.loads(g[["district", "txt", "col", "pop", "geometry"]].to_json()),
                       style_function=lambda f: {"fillColor": f["properties"]["col"], "color": "#fff", "weight": .8,
                                                 "fillOpacity": .85},
                       highlight_function=lambda f: {"weight": 2.5, "color": "#14233A"},
                       tooltip=folium.GeoJsonTooltip(["district", "txt"], aliases=["District", "ZMD forecast"]),
                       popup=folium.GeoJsonPopup(["pop"], labels=False)).add_to(m)
        if pick != "zambia":
            folium.GeoJson(json.loads(D[D["district_id"] == pick][["geometry"]].to_json()),
                           style_function=lambda f: {"fill": False, "color": "#14233A", "weight": 3}).add_to(m)
        rows = "".join(f'<div style="display:flex;align-items:center;gap:7px;margin:2px 0"><span style="width:13px;'
                       f'height:13px;border-radius:3px;background:{c[2]};border:1px solid #CFC6B2"></span>{E(c[1])}</div>'
                       for k, c in ZMD.CATEGORIES.items() if k != "normal")
        m.get_root().html.add_child(Element(
            f'<div style="position:absolute;left:10px;bottom:24px;z-index:999;background:rgba(255,255,255,.95);'
            f'border-radius:10px;padding:8px 11px;font:12px Inter,sans-serif;max-width:220px;box-shadow:0 2px 8px '
            f'rgba(0,0,0,.25)"><b>ZMD rainfall forecast, {E(p_sel)}</b>{rows}<div style="margin-top:4px;color:#5E6B63">'
            f'Districts with two categories are coloured by the drier one.</div></div>'))
        m.fit_bounds([[-18.1, 21.99], [-8.2, 33.7]], padding=(6, 6))
        show_map(m, height=470)
    with m2:
        cnt = P["code"].value_counts()
        html_block('<div class="fp-card"><h4>Districts by expected rainfall, ' + E(plabel[p_sel]) + '</h4>'
                   + "".join(f'<div class="fp-dl"><span><i style="background:{c[2]}"></i>{E(c[1])}</span>'
                             f'<b>{int(cnt.get(k, 0))}</b></div>' for k, c in ZMD.CATEGORIES.items() if k != "normal")
                   + (f'<div class="fp-dl"><span><i style="background:#D9D9D9"></i>Not stated</span>'
                      f'<b>{int(P["code"].isna().sum())}</b></div>' if P["code"].isna().any() else "")
                   + '<div class="fp-sub" style="margin-top:8px">Placed on districts by FieldPriority from the '
                   'bulletin\'s wording; where ZMD names only part of a province the placement is approximate. Check '
                   'the maps in the bulletin for exact boundaries.</div></div>')
        with st.expander("How the bulletin was placed on districts"):
            st.markdown("\n".join(f"- {x}" for x in spec.get("notes", [])))
            if pick != "zambia":
                st.markdown(f"**What the bulletin says that touches {dname}**")
                for p in pers:
                    st.markdown(f"- {p}: " + (S[(S['district_id'] == pick) & (S['period'] == p)]['said'].iloc[0]
                                             or "not mentioned"))

# ================================================================ 3. connection with the platform
sec(3, "Forecast and observations together", "ZMD's outlook says what is expected; the platform's satellite "
    "indicators say what has happened so far. Both are needed for early awareness.")
if pick != "zambia" and spec is not None and len(S):
    rec = location_records(nd, pick)
    rain, maize = rec.get("rainfall_anomaly_pct") or {}, rec.get("maize_share_pct") or {}
    djf = S[(S["district_id"] == pick) & (S["period"] == "DJF")]
    djf_rank = djf["rank"].iloc[0] if len(djf) else None
    pts = []
    if rain.get("status") == "ok":
        pts.append(f"Observed rainfall ({rain.get('period_label')}): {rain['display']}, CHIRPS satellite estimate.")
    else:
        pts.append("Observed rainfall: not yet available for this district.")
    if maize.get("status") == "ok":
        pts.append(f"Maize-growing status: {maize['display']} (ESA WorldCereal 2021).")
    if djf_rank is not None and djf_rank <= 2:
        pts.append("ZMD expects normal-to-below or below-normal rain from December to February, when maize planted in "
                   "November–December usually flowers. If maize is grown here, monitoring crop condition and field "
                   "visits through that period should be a priority.")
    elif djf_rank is not None and djf_rank >= 4:
        pts.append("ZMD expects normal-to-above or above-normal rain from December to February: waterlogging and "
                   "flood-prone fields deserve attention more than drought.")
    html_block('<div class="fp-card"><ul class="fp-act-list" style="margin:0;padding:0">'
               + "".join(f"<li>{E(x)}</li>" for x in pts) + '</ul><div style="margin-top:.4rem">'
               + type_tag("derived") + '<span class="fp-sub">Platform note combining ZMD\'s forecast with the '
               'district indicators. It is not a ZMD statement.</span></div></div>')
else:
    st.caption("Choose a district above to compare ZMD's forecast with what the satellites have observed there "
               f"({period_of(nd)}).")

# ================================================================ 4. more ZMD products
sec(4, "Latest forecasts on zmd.gov.zm", "Short-range forecasts and the 10-day agrometeorological bulletins are "
    "published by ZMD as web pages and documents; open them at the source.")
html_block('<div class="fp-zprod">' + "".join(f'<a href="{E(u)}" target="_blank"><b>{E(t)} ↗</b><span>{E(s)}</span></a>'
                                              for t, u, s in ZMD.PRODUCTS) + '</div>')
st.caption("Source: Zambia Meteorological Department, zmd.gov.zm. Warnings: ZMD's public CAP alert feed "
           f"({ZMD.RSS_URL}). Seasonal forecast: transcribed from the ZMD bulletin. In an emergency follow the "
           "instructions of ZMD and the Disaster Management and Mitigation Unit (DMMU).")
html_block(footer())
