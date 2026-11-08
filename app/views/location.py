"""Explore a location: the current agricultural condition first, then what is happening / why it matters / what to
consider, the evidence behind it (field, satellite, model, derived), crop evidence, map and charts. Detail in expanders."""
import altair as alt
import pandas as pd
import streamlit as st
from _lib import (html_block, icon, badge, national, monitored_fields, location_records, build_zambia_map, show_map,
                  period_of, type_tag, empty, link, interpret, kobo_photo, signal_chain_html, answer_cards_html, kobo_button,
                  condition_signals, condition_strip_html, field_to_intel_html, conf_tag, signin_link_html,
                  zmd_seasonal, zmd_alerts, zmd_cat_chip, ZMD, STATUS, NCFG, NMON, E)

nd = national()
F = monitored_fields(nd)
F_ALL = monitored_fields(nd, everyone=True)      # counts only, for the protected-evidence notice
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
# a link (?district=...) only wins when it is NEW; otherwise the user's own choice in the box stays
if "loc_pick" not in st.session_state or st.session_state["loc_pick"] not in OPTS:
    st.session_state["loc_pick"] = want or ("d:" + (F["district_id"].dropna().iloc[0] if len(F) and
                                                    F["district_id"].notna().any() else "solwezi"))
elif want and want != st.session_state.get("_loc_seen"):
    st.session_state["loc_pick"] = want

s1, s2 = st.columns([3, 1], vertical_alignment="bottom")
pick = s1.selectbox("Location", OPTS, key="loc_pick", format_func=names.get, label_visibility="collapsed")
st.session_state["_loc_seen"] = pick
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
    here_all = F_ALL[F_ALL["district_id"].isin(members)] if len(F_ALL) else F_ALL
    name = f"Zone {ZONES[zc]['name']}: {ZONES[zc]['short']}"
    rows_d = D[D["district_id"].isin(members)]
elif is_prov:
    prov = pick[2:]
    st.query_params["province"] = prov
    from fieldpriority.national.aggregate import province_view, province_id
    recs, M, S_prov, members = province_view(nd, NCFG, prov)
    did = province_id(prov)
    here = F[F["province"] == prov] if len(F) else F
    here_all = F_ALL[F_ALL["province"] == prov] if len(F_ALL) else F_ALL
    name = f"{prov} Province"
    rows_d = D[D["province"] == prov]
else:
    did = pick[2:]
    st.query_params["district"] = did
    recs = location_records(nd, did)
    here = F[F["district_id"] == did] if len(F) else F
    here_all = F_ALL[F_ALL["district_id"] == did] if len(F_ALL) else F_ALL
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
locked = max(len(here_all) - len(here), 0)     # fields here that this visitor may not see
flds = [{"field_id": r.field_id, "risk_level": r.risk_level, "visits": r.visits} for r in here.itertuples()] if len(here) else []
it = interpret(name, recs, NCFG["classes"], fields=flds, monthly_rain=monthly_rain, period_label=per)
lab, col = STATUS[it["status"]]

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
if len(here) or locked:
    chips.append(f"{len(here) + locked} monitored field(s)" + (" · protected" if locked and not len(here) else ""))
html_block(f'<div class="fp-loc"><div style="width:52px;height:52px;border-radius:14px;background:#D9A21B;display:grid;'
           f'place-items:center">{icon("field" if is_zone else "layers" if is_prov else "pin", 28, "#1F4D3A", 2.2)}'
           f'</div><div><h1>{E(name)}</h1><div class="chips">{"".join(f"<span>{E(c)}</span>" for c in chips)}</div>'
           f'</div><span class="lvl" style="background:{col}">{E(lab)}</span></div>')
if not nd.available:
    empty("District layers have not been built yet. Run monthly_update.bat on the project computer, then "
          "sync_firebase.bat for the online dashboard.")
    st.stop()

# ---------------------------------------------------------------- 1. current agricultural condition (dominant)
html_block(condition_strip_html(it["status"], condition_signals(recs, here, locked), it.get("evidence"), it["short"]))

# ---------------------------------------------------------------- 2. the integrated interpretation (hero)
why_sub = (f"{mz['class']} {kind} ({float(mz['value']):.0f}% of land under maize)." if mz.get("status") == "ok" else "")
why_sub += (" " + it["why"][1]) if len(it["why"]) > 1 else ""
html_block(answer_cards_html(it["together"], "", it["why"][0], E(why_sub.strip()), it["next"] or
                             ["Continue routine monitoring"], col))

# ---------------------------------------------------------------- 3. the evidence behind it
with st.container(border=True):
    html_block(f'<div class="fp-panel-h"><span>{icon("layers", 18, "#1F4D3A")} The evidence behind this assessment</span>'
               f'<span style="display:flex;gap:10px;align-items:center"><span class="fp-mini fp-hint">Hover a box for source, '
               f'date and confidence</span>{kobo_button(small=True)}</span></div>')
    html_block(signal_chain_html(recs, here, locked=locked))

# ---------------------------------------------------------------- 4. crop evidence (one evidence layer)
def crop_card(r):
    pics = [(k, when, a) for k, when, a in (r.pics or [])]
    pics.sort(key=lambda x: x[0] != "Crop")
    img = kobo_photo(pics[0][2].get("download_medium_url") or pics[0][2].get("download_url")) if pics else None
    cond = {"High": "Crop stress (high)", "Moderate": "Crop stress (moderate)", "Watch": "Water deficit, crop still green",
            "Low": "Healthy", "Not attributed": "Below normal, cause unclear",
            "Insufficient data": "Awaiting the latest satellite pass"}.get(r.risk_level, r.risk_level)
    ok_ = lambda x: x is not None and str(x).strip().lower() not in ("", "nan", "none", "unknown")
    stage = r.last_stage if ok_(r.last_stage) else r.growth_stage if ok_(r.growth_stage) else "To be recorded at the next visit"
    ver = str(r.verification)
    if r.visits and ver.lower().startswith("not"):
        ver = f"Visited {r.last_visit}" if r.last_visit else "Visited"
    rows = [("Crop identified", r.crop), ("Condition", cond), ("Growth stage", str(stage).replace("_", " ").capitalize()),
            ("Location", f"{r.lat:.4f}, {r.lon:.4f} · {r.area_ha:.2f} ha"), ("Verification", ver),
            ("Field visits", f"{r.visits} visit(s), {r.photos} photo(s)"),
            ("Data quality", {"High": "High confidence", "Medium": "Moderate confidence"}.get(r.data_confidence,
                                                                                         "Limited evidence"))]
    c1, c2 = st.columns([1, 2.4], vertical_alignment="top")
    with c1:
        if img:
            st.image(img, caption=f"{pics[0][0]} photo · {pics[0][1]}", width="stretch")
        else:
            html_block(f'<div class="fp-crop"><div class="ph">{icon("camera", 34, "#9A927C")}</div></div>'
                       + (f'<div class="fp-mini">{len(pics)} photo(s) in KoboToolbox</div>' if pics else
                          '<div class="fp-mini">Photo arrives with the first field observation</div>'))
    with c2:
        html_block(f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">'
                   f'<a href="{link("/assessments", area=r.pilot, field=str(r.field_id))}" target="_self"><b>Field '
                   f'{E(str(r.field_id))} · {E(r.pilot_short)}</b></a><span>{type_tag("field_observation")} '
                   f'{type_tag("satellite_estimate")}</span></div><div class="fp-crop" '
                   f'style="grid-template-columns:1fr"><dl>' + "".join(f"<dt>{E(k)}</dt><dd>{E(str(v))}</dd>" for k, v in rows)
                   + '</dl></div>')


if len(here):
    with st.container(border=True):
        html_block(f'<div class="fp-panel-h"><span>{icon("camera", 18, "#1F4D3A")} Crop evidence from the field</span>'
                   f'<span class="fp-mini">We don\'t just identify the crop: we read the conditions around it</span></div>')
        for r in here.itertuples():
            crop_card(r)
elif locked:
    html_block(f'<div class="fp-zban" style="background:#EEF3EF;border:1px solid #C9D8CD;color:#1E2A24">'
               f'<div class="ic" style="background:var(--forest);color:#fff">{icon("lock", 20)}</div><div style="flex:1">'
               f'<b>{locked} monitored field{"s" if locked > 1 else ""} here.</b> Field observations, photos and exact '
               f'locations are shared only with the account that collected them.</div>{signin_link_html("Sign in")}</div>')
else:
    kb = kobo_button(small=True)
    if kb:
        html_block(f'<div class="fp-zban" style="background:#F3EEF8;border:1px solid #DCCFEA;color:#3B2A55">'
                   f'<div class="ic" style="background:#6A4C93;color:#fff">{icon("camera", 20)}</div><div style="flex:1">'
                   f'<b>Add ground evidence.</b> A field observation (crop, condition, photo) links straight to this '
                   f'location and strengthens the assessment.</div>{kb}</div>')

# ---------------------------------------------------------------- 5. visuals: map and charts


def _style(ch):
    return ch.configure_view(strokeWidth=0).configure_axis(labelFont="Inter", titleFont="Inter", labelColor="#5E6B63",
                                                            titleColor="#5E6B63", gridColor="#ECE7DB")


v1, v2 = st.columns([1, 1.35], gap="medium")
with v1:
    show_map(build_zambia_map(nd, "zones" if is_zone else "overall", here, focus=members), height=380)
with v2:
    S = S_prov.copy() if is_prov else (nd.seasons[nd.seasons["district_id"] == did].copy()
                                       if nd.seasons is not None else pd.DataFrame())
    tabs = st.tabs(["Vegetation", "Rainfall", "Temperature", "Soil moisture", "Past seasons"])
    with tabs[1]:
        if len(rain_m) and rain_m["This season"].notna().any():
            order = list(rain_m["Month"])
            b = alt.Chart(rain_m).mark_bar(size=26, cornerRadiusEnd=4, color="#4C78A8").encode(
                x=alt.X("Month:O", sort=order, title=None, axis=alt.Axis(labelAngle=0)),
                y=alt.Y("This season:Q", title="Rainfall (mm)"),
                tooltip=["Month", alt.Tooltip("This season:Q", format=".0f"), alt.Tooltip("Normal:Q", format=".0f")])
            n = alt.Chart(rain_m).mark_tick(color="#E8892B", thickness=3, size=34).encode(
                x=alt.X("Month:O", sort=order), y="Normal:Q")
            st.altair_chart(_style((b + n).properties(height=290)), width="stretch")
            st.caption("Bars: this season. Orange marks: normal.")
    def line_tab(tab, var, ytitle, fmt, colour, pad):
        tm = month_table(var)
        with tab:
            if not (len(tm) and tm["This season"].notna().any()):
                st.caption("This layer has no monthly series for this location in the current period.")
                return
            order = list(tm["Month"])
            lt = tm.melt(id_vars=["Month"], value_vars=["This season", "Normal"], var_name="Series", value_name="v")
            lo, hi = float(lt["v"].min()), float(lt["v"].max())
            ch = alt.Chart(lt).mark_line(point=True, strokeWidth=2.5).encode(
                x=alt.X("Month:O", sort=order, title=None, axis=alt.Axis(labelAngle=0)),
                y=alt.Y("v:Q", scale=alt.Scale(domain=[lo - pad * (hi - lo + 1e-9), hi + pad * (hi - lo + 1e-9)]),
                        title=ytitle),
                color=alt.Color("Series:N", scale=alt.Scale(domain=["This season", "Normal"], range=[colour, "#9AA39D"]),
                                legend=alt.Legend(orient="bottom", title=None)),
                tooltip=["Month", "Series", alt.Tooltip("v:Q", format=fmt, title=ytitle)])
            st.altair_chart(_style(ch.properties(height=290)), width="stretch")

    line_tab(tabs[0], "ndvi", "Vegetation greenness (NDVI)", ".2f", "#2E8B57", .4)
    line_tab(tabs[2], "t2m", "Mean temperature (°C)", ".1f", "#B9342B", .4)
    line_tab(tabs[3], "sm_rootzone", "Root-zone soil moisture (m³/m³)", ".3f", "#1F78B4", .4)
    if len(S):
        S = S.sort_values("season_start")
        S["current"] = S["current"].astype(str).str.lower().isin(["true", "1"])
        S["Which"] = S["current"].map({True: "This season", False: "Earlier seasons"})
        S["Season"] = S["season"]
        so = list(S["Season"])
        for tab, var, yt, fmt, colors in ((tabs[4], "rainfall_mm", "Rainfall (mm)", ".0f", ["#D9A21B", "#9DB8A5"]),):
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
                    color="#E8892B", strokeDash=[4, 3]).encode(y="y:Q")
                st.altair_chart(_style((ch + mean).properties(height=270)), width="stretch")
                rank = T.sort_values(var).reset_index(drop=True)
                if rank["current"].any():
                    pos = int(rank.index[rank["current"]][0]) + 1
                    st.caption(f"Same months each season. This season ranks {pos} of {len(T)} from "
                               + ("driest to wettest" if var == "rainfall_mm" else "coolest to warmest")
                               + ". Orange dashed line: normal.")

# ---------------------------------------------------------------- 6. official outlook (supports the picture)
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
    html_block(f'<div class="fp-zban" style="background:#EEF3F8;border:1px solid #CFDCE8;color:#14233A;margin:.2rem 0 .7rem">'
               f'<div class="ic" style="background:#1F4E80;color:#fff">{icon("storm", 20)}</div><div style="flex:1;'
               f'min-width:260px"><b>Official ZMD seasonal outlook {E(zspec["season"])}</b> &nbsp;{zline}'
               f'<div class="fp-mini" style="margin-top:3px">{warn}</div></div>'
               f'<a href="{link("/weather", district=None if is_prov else did)}" target="_self">Weather &amp; '
               f'warnings →</a></div>')


# ---------------------------------------------------------------- 7. details, one click away
html_block(field_to_intel_html(compact=True))

with st.expander("Details: full interpretation, maize impact and considerations"):
    for p in it["paragraphs"]:
        st.markdown(p)
    st.markdown("**How this may affect maize**\n" + "\n".join(f"- {x}" for x in it["maize"]))
    st.markdown("**Considerations**\n" + "\n".join(f"- {x}" for x in it["considerations"]))
    if zadv:
        st.markdown("**ZMD advice for farmers here** (seasonal forecast bulletin)\n" + "\n".join(f"- {x}" for x in zadv))
    if it["gaps"]:
        st.caption("Layers not used in this assessment: " + "; ".join(it["gaps"]) + ".")

if is_prov:
    with st.expander(f"Districts in {name} ({len(rows_d)})"):
        tab = []
        for r in rows_d.sort_values("district").itertuples():
            rr = location_records(nd, r.district_id)
            itd = interpret(r.district, rr, NCFG["classes"])
            cell = lambda k: str((rr.get(k) or {}).get("display") or "–").split(" · ")[0]
            tab.append({"District": r.district, "Condition": STATUS[itd["status"]][0],
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
