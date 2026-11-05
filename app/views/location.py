"""Location intelligence: the key message first (what is happening, why it matters, what next), the connected
evidence as one picture, then charts, map and crop evidence. Full detail sits in expanders."""
import altair as alt
import pandas as pd
import streamlit as st
from _lib import (html_block, icon, badge, national, monitored_fields, location_records, build_zambia_map, show_map,
                  period_of, type_tag, empty, link, interpret, kobo_photo, signal_chain_html, answer_cards_html,
                  zmd_seasonal, zmd_alerts, zmd_cat_chip, ZMD, LEVELS, NCFG, NMON, E)

nd = national()
F = monitored_fields(nd)
D = nd.districts.sort_values("district").reset_index(drop=True)
ids = D["district_id"].tolist()
provs = sorted(D["province"].unique())
from fieldpriority.national.aggregate import zone_members
from fieldpriority.national.zones import REGIONS as ZONES
zcodes = [z for z in ["I", "IIa", "IIb", "II", "III"] if zone_members(nd, z)]
OPTS = ["d:" + i for i in ids] + ["z:" + z for z in zcodes] + ["p:" + p for p in provs]
names = {**{"z:" + z: f"Agricultural zone {ZONES[z]['name']} ({ZONES[z]['short']})" for z in zcodes},
         **{"p:" + p: f"{p} Province" for p in provs},
         **dict(zip("d:" + D["district_id"], D["district"] + " · " + D["province"]))}
per = period_of(nd)

qd, qprov, qz = st.query_params.get("district"), st.query_params.get("province"), st.query_params.get("zone")
want = ("d:" + qd) if qd in ids else ("p:" + qprov) if qprov in provs else ("z:" + qz) if qz in zcodes else None
if "loc_pick" not in st.session_state or (want and want != st.session_state.get("loc_pick")):
    st.session_state["loc_pick"] = want or ("d:" + (F["district_id"].dropna().iloc[0] if len(F) and
                                                    F["district_id"].notna().any() else "solwezi"))

s1, s2 = st.columns([3, 1], vertical_alignment="bottom")
pick = s1.selectbox("Location", OPTS, key="loc_pick", format_func=names.get, label_visibility="collapsed")
is_zone = pick.startswith("z:")
is_prov = pick.startswith("p:") or is_zone          # both are groups of districts
for k in ("district", "province", "zone"):
    st.query_params.pop(k, None)
if is_zone:
    zc = pick[2:]
    st.query_params["zone"] = zc
    from fieldpriority.national.aggregate import zone_view, zone_id
    recs, M, S_prov, members = zone_view(nd, NCFG, zc)
    did, prov = zone_id(zc), None
    here = F[F["district_id"].isin(members)] if len(F) else F
    name = f"Zone {ZONES[zc]['name']}: {ZONES[zc]['short']}"
    rows_d = D[D["district_id"].isin(members)]
elif is_prov:
    prov = pick[2:]
    st.query_params["province"] = prov
    from fieldpriority.national.aggregate import province_view, province_id
    recs, M, S_prov, members = province_view(nd, NCFG, prov)
    did = province_id(prov)
    here = F[F["province"] == prov] if len(F) else F
    name = f"{prov} Province"
    rows_d = D[D["province"] == prov]
else:
    did = pick[2:]
    st.query_params["district"] = did
    recs = location_records(nd, did)
    here = F[F["district_id"] == did] if len(F) else F
    members = [did]
    rows_d = D[D["district_id"] == did]
    name = rows_d.iloc[0]["district"]
kind = "zone" if is_zone else "province" if is_prov else "district"

if not is_prov:
    M = nd.monthly[nd.monthly["district_id"] == did] if nd.available else \
        pd.DataFrame(columns=["district_id", "variable", "year", "month", "value"])
if M is None or M.empty:
    M = pd.DataFrame(columns=["district_id", "variable", "year", "month", "value"])
window = [tuple(map(int, w.split("-"))) for w in nd.report.get("window", [])]
nb = len(nd.report.get("baseline_seasons", []))


def month_table(var):
    t = M[M["variable"] == var].set_index(["year", "month"])["value"]
    rows = []
    for y, m in window:
        base = [t.get((y - k, m)) for k in range(1, nb + 1)]
        base = [b for b in base if b is not None and pd.notna(b)]
        rows.append({"Month": f"{NMON[m]} {y}", "m": m, "This season": t.get((y, m)),
                     "Normal": sum(base) / len(base) if base else None})
    return pd.DataFrame(rows)


rain_m = month_table("rainfall_mm")
monthly_rain = {r["m"]: ((r["This season"] - r["Normal"]) / r["Normal"] * 100
                         if r["Normal"] and pd.notna(r["This season"]) else None)
                for r in rain_m.to_dict("records")} if len(rain_m) else {}
flds = [{"field_id": r.field_id, "risk_level": r.risk_level} for r in here.itertuples()] if len(here) else []
it = interpret(name, recs, NCFG["classes"], fields=flds, monthly_rain=monthly_rain, period_label=per)
lab, col = LEVELS[it["level"]]

with s2:
    if recs:
        st.download_button("Evidence (CSV)", pd.DataFrame(recs.values()).to_csv(index=False).encode(),
                           f"FieldPriority_{did.replace(':', '_')}_evidence.csv", "text/csv",
                           icon=":material/download:", width="stretch")

# ---------------------------------------------------------------- header
chips = []
if is_zone:
    chips += [f"{len(members)} districts", f"Rainfall {ZONES[zc]['rain']}"]
elif is_prov:
    chips += [f"{len(members)} districts"]
else:
    chips.append(f"{rows_d.iloc[0]['province']} Province")
    z = recs.get("agro_zone") or {}
    if z.get("status") == "ok":
        chips.append(f"Zone {ZONES.get(z['class'], {}).get('name', z['class'])}")
mz = recs.get("maize_share_pct") or {}
if mz.get("status") == "ok":
    chips.append(f"{mz['class']} · {float(mz['value']):.0f}% of land under maize")
chips.append(f"Season {per}")
if len(here):
    chips.append(f"{len(here)} monitored field(s)")
html_block(f'<div class="fp-loc"><div style="width:52px;height:52px;border-radius:14px;background:#D9A21B;display:grid;'
           f'place-items:center">{icon("field" if is_zone else "layers" if is_prov else "pin", 28, "#1F4D3A", 2.2)}'
           f'</div><div><h1>{E(name)}</h1><div class="chips">{"".join(f"<span>{E(c)}</span>" for c in chips)}</div>'
           f'</div><span class="lvl" style="background:{col}">{E(lab)}</span></div>')
if not nd.available:
    empty("District layers have not been built yet. Run monthly_update.bat on the project computer, then "
          "sync_firebase.bat for the online dashboard.")
    st.stop()

# ---------------------------------------------------------------- 1. the three answers
what_sub = it["together"]
why_sub = (f"{mz['class']} {kind} ({float(mz['value']):.0f}% of land under maize)." if mz.get("status") == "ok" else "")
why_sub += (" " + it["why"][1]) if len(it["why"]) > 1 else ""
html_block(answer_cards_html(it["short"], E(what_sub), it["why"][0], E(why_sub.strip()), it["next"] or
                             ["Keep monitoring monthly"], col))

# ---------------------------------------------------------------- 2. the connected evidence
with st.container(border=True):
    html_block(f'<div class="fp-panel-h"><span>{icon("layers", 18, "#1F4D3A")} Six layers, one picture</span>'
               f'<span class="fp-mini">Hover any box for its source, date and confidence</span></div>')
    html_block(signal_chain_html(recs, here))

# official outlook (ZMD), one line
zspec, ZS, ZON, _ = zmd_seasonal()
try:
    ZT, zst = zmd_alerts(nd)
except Exception:
    ZT, zst = pd.DataFrame(), {"have": False}
zact = ZT[ZT["active"] & ZT["districts"].map(lambda d: bool(set(d) & set(members)))] if len(ZT) else ZT
zadv = []
if zspec is not None and len(ZS):
    Zm = ZS[ZS["district_id"].isin(members)]
    if is_prov:
        djf = Zm[Zm["period"] == "DJF"]["code"].value_counts()
        zline = "Dec–Feb: " + " ".join(zmd_cat_chip(k, f"{ZMD.CATEGORIES[k][1]} · {n}", small=True)
                                       for k, n in djf.items())
    else:
        Zr = Zm.set_index("period")
        zline = " ".join(f'<span style="white-space:nowrap"><b>{p}</b> ' + "".join(
            zmd_cat_chip(c, small=True) for c in str(Zr.loc[p, "codes"]).split("|") if c) + '</span>'
            for p in ZMD.PERIOD_ORDER if p in Zr.index)
        zline += f' · Rains start: <b>{E(ZON.set_index("district_id").loc[members[0], "text"])}</b>'
        zadv = ZMD.advisories_for(zspec, ZMD.district_ranks(ZS, members[0]))
    warn = (f'<b style="color:#B9342B">{len(zact)} ZMD warning(s) in force</b>' if len(zact) else
            "No ZMD warning in force" if zst.get("have") else "")
    html_block(f'<div class="fp-zban" style="background:#EEF3F8;border:1px solid #CFDCE8;color:#14233A;margin:.7rem 0">'
               f'<div class="ic" style="background:#1F4E80;color:#fff">{icon("storm", 20)}</div><div style="flex:1;'
               f'min-width:260px"><b>ZMD rainfall outlook {E(zspec["season"])}</b> &nbsp;{zline}'
               f'<div class="fp-mini" style="margin-top:3px">{warn}</div></div>'
               f'<a href="{link("/weather", district=None if is_prov else did)}" target="_self">Weather &amp; '
               f'warnings →</a></div>')

# ---------------------------------------------------------------- 3. visuals: map and charts


def _style(ch):
    return ch.configure_view(strokeWidth=0).configure_axis(labelFont="Inter", titleFont="Inter", labelColor="#5E6B63",
                                                            titleColor="#5E6B63", gridColor="#ECE7DB")


v1, v2 = st.columns([1, 1.35], gap="medium")
with v1:
    show_map(build_zambia_map(nd, "zones" if is_zone else "rainfall", here, focus=members), height=380)
with v2:
    S = S_prov.copy() if is_prov else (nd.seasons[nd.seasons["district_id"] == did].copy()
                                       if nd.seasons is not None else pd.DataFrame())
    tabs = st.tabs(["Rainfall by month", "Temperature by month", "Rainfall by season", "Temperature by season"])
    with tabs[0]:
        if len(rain_m) and rain_m["This season"].notna().any():
            order = list(rain_m["Month"])
            b = alt.Chart(rain_m).mark_bar(size=26, cornerRadiusEnd=4, color="#4C78A8").encode(
                x=alt.X("Month:O", sort=order, title=None, axis=alt.Axis(labelAngle=0)),
                y=alt.Y("This season:Q", title="Rainfall (mm)"),
                tooltip=["Month", alt.Tooltip("This season:Q", format=".0f"), alt.Tooltip("Normal:Q", format=".0f")])
            n = alt.Chart(rain_m).mark_tick(color="#1E2A24", thickness=3, size=30).encode(
                x=alt.X("Month:O", sort=order), y="Normal:Q")
            st.altair_chart(_style((b + n).properties(height=290)), width="stretch")
            st.caption("Bars: this season. Black marks: normal.")
    with tabs[1]:
        tm = month_table("t2m")
        if len(tm) and tm["This season"].notna().any():
            order = list(tm["Month"])
            lt = tm.melt(id_vars=["Month"], value_vars=["This season", "Normal"], var_name="Series", value_name="°C")
            ch = alt.Chart(lt).mark_line(point=True, strokeWidth=2.5).encode(
                x=alt.X("Month:O", sort=order, title=None, axis=alt.Axis(labelAngle=0)),
                y=alt.Y("°C:Q", scale=alt.Scale(domain=[float(lt["°C"].min()) - 1, float(lt["°C"].max()) + 1]),
                        title="Mean temperature (°C)"),
                color=alt.Color("Series:N", scale=alt.Scale(domain=["This season", "Normal"], range=["#B9342B", "#9AA39D"]),
                                legend=alt.Legend(orient="bottom", title=None)),
                tooltip=["Month", "Series", alt.Tooltip("°C:Q", format=".1f")])
            st.altair_chart(_style(ch.properties(height=290)), width="stretch")
    if len(S):
        S = S.sort_values("season_start")
        S["current"] = S["current"].astype(str).str.lower().isin(["true", "1"])
        S["Which"] = S["current"].map({True: "This season", False: "Earlier seasons"})
        S["Season"] = S["season"]
        so = list(S["Season"])
        for tab, var, yt, fmt, colors in ((tabs[2], "rainfall_mm", "Rainfall (mm)", ".0f", ["#D9A21B", "#9DB8A5"]),
                                          (tabs[3], "t2m", "Mean temperature (°C)", ".1f", ["#B9342B", "#9AA39D"])):
            T = S.dropna(subset=[var])
            if T.empty:
                continue
            with tab:
                x = alt.X("Season:O", title=None, sort=so, axis=alt.Axis(labelAngle=-45, labelOverlap=False))
                color = alt.Color("Which:N", scale=alt.Scale(domain=["This season", "Earlier seasons"], range=colors),
                                  legend=None)
                tip = ["Season", alt.Tooltip(f"{var}:Q", format=fmt, title=yt)]
                if var == "rainfall_mm":
                    ch = alt.Chart(T).mark_bar(cornerRadiusEnd=3).encode(x=x, y=alt.Y(f"{var}:Q", title=yt),
                                                                         color=color, tooltip=tip)
                else:
                    y = alt.Y(f"{var}:Q", title=yt, scale=alt.Scale(domain=[float(T[var].min()) - .5,
                                                                          float(T[var].max()) + .5]))
                    ch = alt.Chart(T).mark_line(color="#CFC6B2", strokeWidth=2).encode(x=x, y=y) + \
                        alt.Chart(T).mark_point(filled=True, size=110).encode(x=x, y=y, color=color, tooltip=tip)
                mean = alt.Chart(pd.DataFrame({"y": [float(T[~T["current"]][var].mean())]})).mark_rule(
                    color="#1E2A24", strokeDash=[4, 3]).encode(y="y:Q")
                st.altair_chart(_style((ch + mean).properties(height=270)), width="stretch")
                rank = T.sort_values(var).reset_index(drop=True)
                if rank["current"].any():
                    pos = int(rank.index[rank["current"]][0]) + 1
                    st.caption(f"Same months each season. This season ranks {pos} of {len(T)} from "
                               + ("driest to wettest" if var == "rainfall_mm" else "coolest to warmest")
                               + ". Dashed line: normal.")

# ---------------------------------------------------------------- 4. crop evidence (only where fields exist)
if len(here):
    with st.container(border=True):
        html_block(f'<div class="fp-panel-h"><span>{icon("camera", 18, "#1F4D3A")} Crop evidence from monitored '
                   f'fields</span>{type_tag("field_observation")}</div>')
        fc = st.columns(min(len(here), 3))
        for i, r in enumerate(here.itertuples()):
            with fc[i % len(fc)]:
                html_block(f'<div class="fp-card" style="padding:12px 14px"><div style="display:flex;justify-content:'
                           f'space-between;align-items:center"><a href="{link("/assessments", area=r.pilot, field=str(r.field_id))}" '
                           f'target="_self"><b>Field {E(str(r.field_id))}</b></a>{badge(r.risk_level)}</div>'
                           f'<div class="fp-mini" style="margin-top:4px">{E(r.pilot_short)} pilot · {r.area_ha:.2f} ha · '
                           f'maize · stage: {E(str(r.growth_stage or "unknown"))}<br>{E(str(r.verification))} · '
                           f'{r.visits} visit(s), {r.photos} photo(s)</div></div>')
        pics = [(r.field_id, k, when, a) for r in here.itertuples() for k, when, a in (r.pics or [])]
        if pics:
            pc = st.columns(4)
            shown = 0
            for i, (fid, kind_, when, a) in enumerate(pics[:4]):
                img = kobo_photo(a.get("download_medium_url") or a.get("download_url"))
                with pc[i]:
                    if img:
                        st.image(img, caption=f"Field {fid} · {kind_} · {when}", width="stretch")
                        shown += 1
                    else:
                        html_block(f'<div class="fp-photo" style="font-size:.85rem">{icon("camera", 16, "#1F4D3A")} '
                                   f'<a href="{E(str(a.get("download_medium_url") or a.get("download_url")))}" '
                                   f'target="_blank">{E(kind_)} photo · field {E(str(fid))} · {E(str(when))}</a></div>')
            if not shown:
                st.caption("Photos open in KoboToolbox (add KOBO_TOKEN to the app secrets to show them here).")

# ---------------------------------------------------------------- details, one click away
with st.expander("Full interpretation and next steps"):
    for p in it["paragraphs"]:
        st.markdown(p)
    st.markdown("**How this may affect maize**\n" + "\n".join(f"- {x}" for x in it["maize"]))
    st.markdown("**Practical considerations**\n" + "\n".join(f"- {x}" for x in it["considerations"]))
    if zadv:
        st.markdown("**ZMD advice for farmers here** (seasonal forecast bulletin)\n" + "\n".join(f"- {x}" for x in zadv))
    if it["gaps"]:
        st.markdown("**Not yet included:** " + "; ".join(it["gaps"]) + ".")

if is_prov:
    with st.expander(f"Districts in {name} ({len(rows_d)})"):
        tab = []
        for r in rows_d.sort_values("district").itertuples():
            rr = location_records(nd, r.district_id)
            itd = interpret(r.district, rr, NCFG["classes"])
            cell = lambda k: str((rr.get(k) or {}).get("display") or "–").split(" · ")[0]
            tab.append({"District": r.district, "Assessment": LEVELS[itd["level"]][0],
                        "Rainfall": cell("rainfall_anomaly_pct"), "Soil moisture": cell("soil_moisture_anomaly_pct"),
                        "Vegetation": cell("vegetation_anomaly_pct"), "Temperature": cell("temperature_deviation"),
                        "Report": f"/location?district={r.district_id}"})
        st.dataframe(pd.DataFrame(tab), hide_index=True, width="stretch",
                     column_config={"Report": st.column_config.LinkColumn("Report", display_text="Open")})

with st.expander("Evidence register: source, date, coverage and confidence of every value"):
    ev = pd.DataFrame(recs.values())
    if len(ev):
        from fieldpriority.evidence import DATA_TYPES
        ev["Kind of data"] = ev["data_type"].map(lambda t: DATA_TYPES.get(t, (t,))[0])
        cols = {"label": "Indicator", "display": "Value", "Kind of data": "Kind of data", "confidence": "Confidence",
                "source": "Source", "period_label": "Period", "resolution": "Resolution", "coverage": "Coverage",
                "baseline": "Normal (baseline)", "quality_note": "Notes"}
        st.dataframe(ev[list(cols)].rename(columns=cols), hide_index=True, width="stretch")
st.caption("District values are averages: individual farms can differ. The platform supports local judgement; "
           "review decisions with agricultural extension officers.")
