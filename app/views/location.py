"""Location report: one district, all six layers of evidence, in the brief's five sections."""
import altair as alt
import pandas as pd
import streamlit as st
from _lib import (html_block, icon, badge, national, monitored_fields, location_records, build_zambia_map, show_map,
                  period_of, type_tag, conf_tag, evidence_line, class_chip, empty, link, interpret, LEVELS, NCFG,
                  NMON, RISK, E, C)

nd = national()
F = monitored_fields(nd)
D = nd.districts.sort_values("district").reset_index(drop=True)
ids = D["district_id"].tolist()
names = dict(zip(D["district_id"], D["district"] + " · " + D["province"] + " Province"))
per = period_of(nd)

qp = st.query_params.get("district")
if "loc_pick" not in st.session_state or (qp in ids and qp != st.session_state.get("loc_pick")):
    st.session_state["loc_pick"] = qp if qp in ids else (F["district_id"].dropna().iloc[0] if len(F) and
                                                       F["district_id"].notna().any() else "solwezi")

html_block('<div class="fp-eyebrow">Location-specific intelligence report</div>')
s1, s2 = st.columns([2, 1.2], vertical_alignment="bottom")
did = s1.selectbox("Location", ids, key="loc_pick", format_func=names.get,
                   help="Every district of Zambia. Monitored pilot fields have their own field profile (Assessments).")
st.query_params["district"] = did
d = D[D["district_id"] == did].iloc[0]
recs = location_records(nd, did)
here = F[F["district_id"] == did] if len(F) else F

# monthly values for the charts and the per-month rainfall wording
M = nd.monthly[nd.monthly["district_id"] == did] if nd.available else \
    pd.DataFrame(columns=["district_id", "variable", "year", "month", "value"])
window = [tuple(map(int, w.split("-"))) for w in nd.report.get("window", [])]
nb = len(nd.report.get("baseline_seasons", []))


def month_table(var):
    t = M[M["variable"] == var].set_index(["year", "month"])["value"]
    rows = []
    for y, m in window:
        base = [t.get((y - k, m)) for k in range(1, nb + 1)]
        base = [b for b in base if b is not None and pd.notna(b)]
        rows.append({"Month": f"{NMON[m]} {y}", "order": len(rows), "m": m, "This season": t.get((y, m)),
                     "Normal": sum(base) / len(base) if base else None})
    return pd.DataFrame(rows)


rain_m = month_table("rainfall_mm")
monthly_rain = {r["m"]: ((r["This season"] - r["Normal"]) / r["Normal"] * 100
                         if r["Normal"] and pd.notna(r["This season"]) else None)
                for r in rain_m.to_dict("records")} if len(rain_m) else {}
flds = [{"field_id": r.field_id, "risk_level": r.risk_level} for r in here.itertuples()] if len(here) else []
it = interpret(d["district"], recs, NCFG["classes"], fields=flds, monthly_rain=monthly_rain, period_label=per)
lab, col = LEVELS[it["level"]]

with s2:
    if recs:
        ev = pd.DataFrame(recs.values())
        st.download_button("Download evidence (CSV)", ev.to_csv(index=False).encode(), f"FieldPriority_{did}_evidence.csv",
                           "text/csv", icon=":material/download:", width="stretch")

html_block(f"""<div class="fp-ph"><div style="width:58px;height:58px;border-radius:16px;background:#D9A21B;display:grid;
place-items:center">{icon("pin", 32, "#1F4D3A", 2.2)}</div><div style="flex:1"><div style="display:flex;gap:14px;
align-items:center;flex-wrap:wrap"><h1>{E(d["district"])}</h1><span class="fp-badge lg" style="background:{col};color:#fff;
padding:6px 15px;border-radius:999px;font-weight:600">{E(lab)}</span></div><div class="meta">
<span>{icon("layers", 15, "#F2C74E")}{E(d["province"])} Province, Zambia</span>
<span>{icon("clock", 15, "#F2C74E")}Season data: {E(per)}</span>
<span>{icon("field", 15, "#F2C74E")}{len(here)} monitored field(s)</span></div></div></div>""")
if not nd.available:
    empty("District layers have not been built yet. Run monthly_update.bat on the project computer, then "
          "sync_firebase.bat for the online dashboard.")
    st.stop()


def sec(n, title, sub=None):
    html_block(f'<div class="fp-rep-h"><span class="n">{n}</span><span>{E(title)}</span></div>'
               + (f'<div class="fp-sub" style="margin:-.3rem 0 .6rem">{sub}</div>' if sub else ""))


def card(title, rec, extra=""):
    if not rec or rec.get("status") != "ok":
        return (f'<div class="fp-ic"><div class="t">{E(title)}</div><div class="v" style="color:#7A8590;font-size:1.05rem">'
                f'Not yet available</div><div class="e">{E((rec or {}).get("quality_note") or "")}</div></div>')
    v = str(rec["display"]).split(" · ")[0]
    return (f'<div class="fp-ic"><div class="t">{E(title)}{class_chip(rec.get("class")) if rec.get("class") != v else ""}</div>'
            f'<div class="v">{E(v)}</div>{extra}'
            f'<div>{type_tag(rec["data_type"])}{conf_tag(rec["confidence"])}</div><div class="e">{evidence_line(rec)}</div>'
            + (f'<div class="e" style="color:#7A5300">{E(rec["quality_note"])}</div>' if rec.get("quality_note") else "")
            + '</div>')


# ================================================================ 1. location profile
sec(1, "Location profile")
p1, p2 = st.columns([1, 1.25], gap="medium")
with p1:
    maize = recs.get("maize_share_pct") or {}
    maize_txt = maize.get("display") if maize.get("status") == "ok" else "Not yet available (needs the WorldCereal maize map export)"
    fb = (f"{len(here)} monitored field(s) with digitised boundaries ({', '.join(sorted(set(here['pilot_short'])))} pilot)"
          if len(here) else "No field boundaries in the platform for this district yet")
    html_block(f"""<div class="fp-card"><div class="fp-kv">
<div>Province</div><div>{E(d["province"])}</div>
<div>District</div><div>{E(d["district"])}</div>
<div>Area</div><div>{d["area_km2"]:,.0f} km²</div>
<div>Central point</div><div>{d["lat"]:.4f}, {d["lon"]:.4f}</div>
<div>Agricultural zone</div><div style="color:#7A8590">Not yet in the platform (agro-ecological region map to be added)</div>
<div>Maize-growing status</div><div>{E(maize_txt)}</div>
<div>Field boundaries</div><div>{E(fb)}</div>
<div>Boundary source</div><div class="fp-sub">{E(nd.report.get("boundaries_source", ""))}</div>
</div></div>""")
with p2:
    show_map(build_zambia_map(nd, "rainfall", here, focus=did), height=330)

# ================================================================ 2. environmental conditions
sec(2, "Environmental conditions", f"Season to date ({E(per)}) compared with the same months of the previous "
    f"{nb} seasons. District averages: individual farms can differ.")
c = st.columns(3)
r_tot = recs.get("rainfall_total") or {}
c[0].markdown(card("Rainfall", recs.get("rainfall_anomaly_pct"),
                   f'<div class="fp-sub" style="margin-bottom:6px">{E(r_tot.get("display") or "")}</div>'),
              unsafe_allow_html=True)
tx = recs.get("tmax_mean") or {}
c[1].markdown(card("Temperature", recs.get("temperature_deviation"),
                   f'<div class="fp-sub" style="margin-bottom:6px">Mean {E((recs.get("temperature_mean") or {}).get("display") or "–")}'
                   f' · hottest of each month {E(tx.get("display") or "–")}</div>'), unsafe_allow_html=True)
c[2].markdown(card("Water stress", recs.get("water_stress")), unsafe_allow_html=True)
c = st.columns(3)
c[0].markdown(card("Vegetation condition", recs.get("vegetation_anomaly_pct")), unsafe_allow_html=True)
c[1].markdown(card("Root-zone soil moisture", recs.get("soil_moisture_anomaly_pct")), unsafe_allow_html=True)
c[2].markdown(card("Solar resource", recs.get("solar_resource")), unsafe_allow_html=True)


def _style(ch):
    return ch.configure_view(strokeWidth=0).configure_axis(labelFont="Inter", titleFont="Inter", labelColor="#5E6B63",
                                                            titleColor="#5E6B63", gridColor="#ECE7DB")


g1, g2, g3 = st.columns(3, gap="medium")
with g1:
    if len(rain_m) and rain_m["This season"].notna().any():
        order = list(rain_m["Month"])
        b = alt.Chart(rain_m).mark_bar(size=26, cornerRadiusEnd=4, color="#4C78A8").encode(
            x=alt.X("Month:O", sort=order, title=None, axis=alt.Axis(labelAngle=0)),
            y=alt.Y("This season:Q", title="Rainfall (mm)"),
            tooltip=["Month", alt.Tooltip("This season:Q", format=".0f"), alt.Tooltip("Normal:Q", format=".0f")])
        n = alt.Chart(rain_m).mark_tick(color="#1E2A24", thickness=3, size=30).encode(
            x=alt.X("Month:O", sort=order), y="Normal:Q")
        st.altair_chart(_style((b + n).properties(title="Monthly rainfall (bars) vs normal (black marks)", height=230)),
                        width="stretch")
with g2:
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
        st.altair_chart(_style(ch.properties(title="Monthly temperature vs normal", height=230)), width="stretch")
with g3:
    S = nd.seasons[(nd.seasons["district_id"] == did)].dropna(subset=["rainfall_mm"]) if nd.seasons is not None else pd.DataFrame()
    if len(S):
        S = S.sort_values("season_start")
        S["Season"] = S["season"]
        S["current"] = S["current"].astype(str).str.lower().isin(["true", "1"])
        S["Which"] = S["current"].map({True: "This season", False: "Earlier seasons"})
        ch = alt.Chart(S).mark_bar(cornerRadiusEnd=3).encode(
            x=alt.X("Season:O", title=None, sort=list(S["Season"]), axis=alt.Axis(labelAngle=-45)),
            y=alt.Y("rainfall_mm:Q", title="Rainfall, same months (mm)"),
            color=alt.Color("Which:N", scale=alt.Scale(domain=["This season", "Earlier seasons"],
                                                       range=["#D9A21B", "#9DB8A5"]), legend=None),
            tooltip=["Season", alt.Tooltip("rainfall_mm:Q", format=".0f", title="Rainfall (mm)"),
                     alt.Tooltip("t2m:Q", format=".1f", title="Mean temp (°C)")])
        st.altair_chart(_style(ch.properties(title="Seasonal comparison: the same months in each season", height=230)),
                        width="stretch")
        rank = S.sort_values("rainfall_mm").reset_index(drop=True)
        pos = int(rank.index[rank["current"]][0]) + 1 if rank["current"].any() else None
        if pos:
            st.caption(f"This season ranks {pos} of {len(S)} from driest to wettest for these months.")

# ================================================================ 3. crop condition and verification
sec(3, "Crop condition and verification", "Ground evidence and satellite observations of the crop itself.")
if len(here):
    rows = ""
    for r in here.itertuples():
        rows += (f'<tr><td><a href="{link("/assessments", area=r.pilot, field=str(r.field_id))}" target="_self">'
                 f'<b>{E(str(r.field_id))}</b></a><div class="fp-sub">{E(r.pilot_short)} pilot · {r.area_ha:.2f} ha</div></td>'
                 f'<td>Maize {type_tag("field_observation") if r.visits else ""}</td>'
                 f'<td>{E(str(r.growth_stage or "Unknown"))}</td><td>{badge(r.risk_level)}</td>'
                 f'<td>{E(str(r.data_confidence))}</td><td>{E(str(r.verification))}</td>'
                 f'<td>{r.visits} visit(s) · {r.photos} photo(s)</td></tr>')
    html_block('<div class="fp-card" style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;font-size:.88rem">'
               '<tr style="text-align:left;color:#5E6B63"><th>Field</th><th>Crop</th><th>Growth stage</th>'
               '<th>Field risk class</th><th>Data confidence</th><th>Verification</th><th>Photographic evidence</th></tr>'
               + rows + '</table><div class="fp-sub" style="margin-top:8px">Field risk classes come from Sentinel-2 '
               'greenness (10 m) and the drought-stress rules for the field period '
               + E(", ".join(sorted(set(str(p) for p in here["period"])))) + '. Open a field for its photos, satellite '
               'trends and visit records.</div></div>')
else:
    empty(f"No monitored fields and no field reports in {E(d['district'])} yet. Crop identification, growth stage and "
          "photographic evidence come from field visits (KoboToolbox) to monitored fields.")
veg = recs.get("vegetation_anomaly_pct") or {}
st.caption("District satellite vegetation: " + (veg.get("display") if veg.get("status") == "ok" else
           "not yet available (MODIS NDVI district export pending).") + " Crop type at district level: "
           + ("see maize-growing status above." if (recs.get("maize_share_pct") or {}).get("status") == "ok"
              else "not yet mapped."))

# ================================================================ 4. integrated interpretation
sec(4, "Integrated interpretation", "How the indicators relate. Cautious by design: evidence of possible stress, "
    "not proof of crop damage.")
html_block(f'<div class="fp-interp"><div style="font:700 1.05rem var(--fh);margin-bottom:.4rem;color:{col}">'
           f'{E(it["headline"])}</div>' + "".join(f"<p style='margin:.35rem 0'>{E(p)}</p>" for p in it["paragraphs"])
           + '</div>')
i1, i2 = st.columns(2, gap="medium")
with i1:
    html_block('<div class="fp-card"><h4>How this may affect maize</h4><ul class="fp-att">'
               + "".join(f"<li>{E(x)}</li>" for x in it["maize"]) + "</ul></div>")
with i2:
    html_block('<div class="fp-card"><h4>What the assessment does not include yet</h4><ul class="fp-att">'
               + ("".join(f"<li>{E(x)}</li>" for x in it["gaps"]) or "<li>All layers are included.</li>")
               + "</ul></div>")

# ================================================================ 5. practical considerations
sec(5, "Practical considerations", "Possible next steps to discuss. The platform supports decisions; it does not "
    "make them.")
html_block('<div class="fp-card"><ul class="fp-act-list" style="margin:0;padding:0">'
           + "".join(f"<li>{E(x)}</li>" for x in it["considerations"]) + "</ul></div>")

# ================================================================ evidence register
with st.expander("Evidence register: every indicator with its source, date, coverage and confidence"):
    ev = pd.DataFrame(recs.values())
    if len(ev):
        from fieldpriority.evidence import DATA_TYPES
        ev["Kind of data"] = ev["data_type"].map(lambda t: DATA_TYPES.get(t, (t,))[0])
        cols = {"label": "Indicator", "display": "Value", "Kind of data": "Kind of data", "confidence": "Confidence",
                "source": "Source", "period_label": "Period", "resolution": "Resolution", "coverage": "Coverage",
                "baseline": "Normal (baseline)", "quality_note": "Notes"}
        st.dataframe(ev[list(cols)].rename(columns=cols), hide_index=True, width="stretch")
        st.caption("Kinds of data: " + "; ".join(f"{v[0]} = {v[1]}" for v in DATA_TYPES.values()))
