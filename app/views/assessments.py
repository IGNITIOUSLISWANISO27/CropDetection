import pandas as pd
import streamlit as st
from _lib import (kobo_button, get_data, page_title, section, kpi, html_block, badge, src_tag, visits, verification_status,
                  status_by_field, field_location, period_text, period_year, sort_by_risk, build_map, show_map,
                  trend_chart, issue_labels, empty, icon, attachments, kobo_photo, RISK, RISK_ORDER, CFG, E, C)

data = get_data()
A = data.assessments
V = visits(data)
status = status_by_field(data)
qp_field = st.query_params.get("field")


# ================================================================ field profile
def profile(fid):
    from _reports import build_pdf
    r = A[A["field_id"] == fid].iloc[0].to_dict()
    loc = field_location(data, fid)
    area = data.fields.set_index("Field_ID").loc[fid, "area_ha"]
    ex = r.get("explanation") or {}
    stat = verification_status(data, r["alert_id"])
    lvl = r["risk_level"]
    rk = RISK.get(lvl, {"color": "#7A8590", "text": "#fff", "icon": "dash", "short": lvl, "means": ""})
    mine = V[V["field_id_pipeline"] == fid] if len(V) and "field_id_pipeline" in V else pd.DataFrame()

    b1, b2 = st.columns([1, 5])
    if b1.button("Back", icon=":material/arrow_back:"):
        st.query_params.clear()
        st.rerun()
    b2.markdown('<div class="fp-sub" style="padding-top:.45rem">Assessments / Field profile</div>', unsafe_allow_html=True)

    # ---- header band
    h1, h2 = st.columns([4, 1.1], vertical_alignment="center")
    with h1:
        html_block(f"""<div class="fp-ph"><div style="width:58px;height:58px;border-radius:16px;background:#D9A21B;
display:grid;place-items:center;color:#1F4D3A">{icon("leaf", 32, "#1F4D3A", 2.2)}</div>
<div><div style="display:flex;gap:14px;align-items:center;flex-wrap:wrap"><h1>Field {E(fid)}</h1>{badge(lvl, large=True)}</div>
<div class="meta"><span>{icon("pin", 15, "#F2C74E")}{E(loc["district"])}, Zambia</span><span>{icon("leaf", 15, "#F2C74E")}Maize</span>
<span>{icon("clock", 15, "#F2C74E")}Season data {E(period_text(data))}</span>
<span>{icon("clipboard", 15, "#F2C74E")}Alert {E(str(r["alert_id"]))}</span></div></div></div>""")
    with h2:
        try:
            st.download_button("Download report", build_pdf(data, A[A["field_id"] == fid], {"Field": fid}),
                               f"FieldPriority_{fid}.pdf", "application/pdf", icon=":material/download:",
                               type="primary", width="stretch")
        except Exception as e:
            st.caption(f"PDF unavailable: {e}")

    # ---- link to the district's location report (crop, rainfall, temperature, water stress)
    try:
        from _lib import national
        nd = national()
        pt = data.fields.set_index("Field_ID").loc[fid].geometry.representative_point()
        hit = nd.districts[nd.districts.contains(pt)]
        if len(hit):
            h = hit.iloc[0]
            st.page_link("views/location.py", icon=":material/location_on:",
                         label=f"District context: {h['district']} location report (rainfall, temperature, water stress)",
                         query_params={"district": h["district_id"]})
    except Exception:
        pass

    # ---- boundary + information + risk card
    g1, g2 = st.columns([1.55, 1], gap="medium")
    with g1:
        with st.container(border=True):
            html_block(f'<div class="fp-panel-h"><span>{icon("layers", 18, "#1F4D3A")} Field Boundary &amp; Location</span>'
                       f'<span class="fp-sub" style="font-weight:500">{src_tag("est")}</span></div>')
            show_map(build_map(data, A=A[A["field_id"] == fid], basemap="Satellite", focus=fid, legend=False), height=380)
            st.caption("Boundary digitised from imagery: an estimate until it is checked on the ground.")
    with g2:
        with st.container(border=True):
            gtype = "Boundary polygon" if loc["geom_type"] in ("Polygon", "MultiPolygon") else "Location point only"
            html_block(f"""<div class="fp-panel-h"><span>{icon("doc", 18, "#1F4D3A")} Field Information</span></div>
<div class="fp-kv"><div>Field ID</div><div>{E(fid)}</div>
<div>Location</div><div>{E(loc["district"])}, Zambia</div>
<div>Coordinates</div><div>{abs(loc["lat"]):.4f}° {"S" if loc["lat"] < 0 else "N"}, {abs(loc["lon"]):.4f}° {"E" if loc["lon"] >= 0 else "W"} {src_tag("calc")}</div>
<div>Field area</div><div>{area:.2f} ha {src_tag("est")}</div>
<div>Geometry</div><div>{gtype}{"" if loc["valid"] else " (invalid shape)"}</div>
<div>Crop type</div><div>Maize</div>
<div>Crop period</div><div>{E(period_text(data))}</div>
<div>Assessed for</div><div>{E(str(r.get("assessment_date")))}</div></div><div style="height:6px"></div>""")
        tint = rk["color"] + "26"
        html_block(f"""<div class="fp-rc" style="background:{tint};border:1px solid {rk['color']}66;margin-top:12px">
<div style="width:52px;height:52px;border-radius:50%;background:{rk['color']};display:grid;place-items:center;flex:none">
{icon(rk["icon"], 28, rk["text"], 2.2)}</div><div><div class="fp-sub" style="font-weight:700;color:#1E2A24">Risk Classification</div>
<div class="big" style="color:#1E2A24">{E(rk["short"])}</div><div style="font-size:.86rem;color:#1E2A24">{E(rk["means"])}</div></div></div>""")

    # ---- summary + photos
    s1, s2 = st.columns([1, 1], gap="medium")
    with s1:
        with st.container(border=True):
            html_block(f'<div class="fp-panel-h"><span>{icon("clipboard", 18, "#1F4D3A")} Assessment Summary</span>{src_tag("calc")}</div>')
            ind = ex.get("indicators") or []
            rows = ""
            for i in ind:
                good = i.get("finding") in ("no decline", "normal or above", "normal or wetter", "no marked change")
                col = "#2E8B57" if good else ("#B9342B" if i.get("contributed") else "#DB7A1F")
                rows += (f'<div class="fp-ind"><div><b>{E(str(i["indicator"]))}</b><div class="fp-sub" style="font-size:.8rem">'
                         f'{E(str(i["value"]))} vs {E(str(i["baseline"]))}</div></div>'
                         f'<span class="fp-badge" style="background:{col}1F;color:{col};border:1px solid {col}55">'
                         f'{E(str(i["finding"]))}</span></div>')
            html_block(rows or '<div class="fp-sub">No indicators available.</div>')
            html_block(f'<div class="fp-kv" style="margin-top:.8rem"><div>Data confidence</div><div>{E(r["data_confidence"])}</div>'
                       f'<div>Growth stage</div><div>{E(str(r.get("growth_stage_label") or "Unknown"))}</div>'
                       f'<div>Field verification</div><div>{E(stat)}</div>'
                       f'<div>Assessed by</div><div>FieldPriority rules {E(str(r.get("model_version") or ""))}</div></div>')
            if r.get("missing_data"):
                st.warning("**Missing information:** " + "; ".join(r["missing_data"]))
    with s2:
        with st.container(border=True):
            html_block(f'<div class="fp-panel-h"><span>{icon("camera", 18, "#1F4D3A")} Field Photos</span>{src_tag("obs")}</div>')
            pics = []
            for v in mine.to_dict("records") if len(mine) else []:
                for a in attachments(v):
                    kind = "Crop" if a.get("media_file_basename") == v.get("crop_photo") else \
                        "Soil" if a.get("media_file_basename") == v.get("soil_photo") else "Photo"
                    pics.append((kind, v.get("visit_date"), a))
            if not pics:
                empty("No photographs yet. They appear here when a verifier submits a visit with photos in KoboToolbox.")
            else:
                pc = st.columns(2)
                shown = 0
                for i, (kind, when, a) in enumerate(pics[:4]):
                    img = kobo_photo(a.get("download_medium_url") or a.get("download_url"))
                    with pc[i % 2]:
                        if img:
                            st.image(img, caption=f"{kind} · {when}", width="stretch")
                            shown += 1
                        else:
                            html_block(f'<div class="fp-photo">{icon("camera", 20, "#1F4D3A")} <b>{kind} photo</b> · {E(str(when))}'
                                       f'<br><a href="{E(str(a.get("download_medium_url") or a.get("download_url")))}" target="_blank">'
                                       f'Open in KoboToolbox</a></div>')
                if not shown:
                    st.caption("Photos open in KoboToolbox (sign-in needed). To show them here, add KOBO_TOKEN to the "
                               "app's secrets.")

    # ---- history + actions
    hcol, acol = st.columns([1.7, 1], gap="medium")
    with hcol:
        with st.container(border=True):
            html_block(f'<div class="fp-panel-h"><span>{icon("clock", 18, "#1F4D3A")} Assessment History</span>'
                       f'<span class="fp-sub" style="font-weight:500">issued predictions, never changed</span></div>')
            L = data.ledger if data.ledger is not None else pd.DataFrame()
            h = L[L["field_id"] == fid].sort_values("issued_at", ascending=False) if len(L) and "field_id" in L else pd.DataFrame()
            if h.empty:
                empty("No history yet.")
            else:
                t = pd.DataFrame({"Date": h["alert_date"], "Risk level": h["risk_level"],
                                  "Status": h["alert_id"].map(lambda a: verification_status(data, a)),
                                  "Comments": h["outcome"], "Data up to": h["data_end_date"]})
                st.dataframe(t, hide_index=True, width="stretch")
    with acol:
        with st.container(border=True):
            html_block(f'<div class="fp-panel-h"><span>{icon("check", 18, "#2E8B57")} Recommended Actions</span></div>')
            acts = [r.get("next_action")] + list(ex.get("checks") or [])
            html_block('<ul class="fp-act-list" style="padding:0;margin:0">' +
                       "".join(f"<li>{E(str(a))}</li>" for a in acts if a) + "</ul>")
            st.caption("Follow-up for verification only; FieldPriority never recommends treatment (rule 12).")

    # ---- detail for technical users
    with st.expander("Indicators over time (charts)"):
        yr = period_year(data)
        cc = st.columns(2)
        for col, args in zip([cc[0], cc[1], cc[0], cc[1]], [
                ("ndvi", "Crop greenness (NDVI, Sentinel-2, 10 m)", "NDVI", False),
                ("rainfall_anomaly", "Rainfall versus its 10-year normal (regional cell)", "mm per month", True),
                ("soil_moisture", "Soil moisture (regional cell)", "Volumetric", False),
                ("temperature", "Temperature (regional cell)", "°C", False)]):
            ch = trend_chart(data.monthly, args[0], fid, args[1], args[2], yr, bars=args[3])
            if ch is not None:
                col.altair_chart(ch, width="stretch")
    with st.expander("Field-visit observations (as submitted in KoboToolbox)"):
        if mine.empty:
            st.write(f"No visit yet. Verifiers should use Field ID {fid} and Alert ID {r['alert_id']}.")
        for v in mine.sort_values("visit_date").to_dict("records") if len(mine) else []:
            nice = {"p0_25": "0 to 25%", "p25_50": "25 to 50%", "p50_75": "50 to 75%", "p75_100": "75 to 100%"}
            obs = [("Verifier", v.get("verifier_id")), ("Verdict", v.get("field_verdict")), ("Overall condition", v.get("overall_condition")),
                   ("Area affected", v.get("affected_area")), ("Leaf rolling", v.get("leaf_rolling")),
                   ("Leaf drying", v.get("leaf_drying")), ("Soil condition", v.get("soil_condition")),
                   ("Pests", v.get("pest_damage")), ("Disease", v.get("disease_symptoms")),
                   ("Weeds", v.get("weed_pressure")), ("Main cause", v.get("main_cause")),
                   ("Reason", v.get("verdict_reason"))]
            st.markdown(f"**Visit on {v.get('visit_date')}** · status {v.get('validation_status_final')}")
            html_block('<div class="fp-kv">' + "".join(
                f"<div>{E(k)}</div><div>{E(nice.get(str(x), str(x).replace('_', ' ')))}</div>"
                for k, x in obs if x not in (None, "") and str(x) != "nan") + "</div>")
            if v.get("flag_codes"):
                st.caption("Data checks: " + issue_labels(v.get("flag_codes")))
    with st.expander("Why data confidence is not higher, and context values"):
        for x in (r.get("data_confidence_issues") or []) + list(ex.get("context") or []):
            st.markdown(f"- {x}")


if qp_field and qp_field in set(A["field_id"]):
    profile(qp_field)
    st.stop()

# ================================================================ list of assessments
page_title("Assessments", "Each field's risk class, verification and visits. Open a field for its profile.",
           eyebrow="Field assessment records", icon_name="clipboard")
html_block(kobo_button())

stat = A["field_id"].map(status)
verified = int(stat.str.startswith("Verified").sum())
pending = int((stat == "Not yet verified").sum() + (stat == "Visit submitted, under review").sum())
needs = int((A["risk_level"] == "Insufficient data").sum() + (A["missing_data"].map(len) > 0).sum()
            - ((A["risk_level"] == "Insufficient data") & (A["missing_data"].map(len) > 0)).sum())
c = st.columns(4)
c[0].markdown(kpi("clipboard", "Fields assessed", f"{len(A)}", f"Satellite assessments in the latest run ({E(period_text(data))})."), unsafe_allow_html=True)
c[1].markdown(kpi("check", "Verified", f"{verified}", "With an approved field visit linked to the alert."), unsafe_allow_html=True)
c[2].markdown(kpi("clock", "Pending verification", f"{pending}", "No approved visit yet."), unsafe_allow_html=True)
c[3].markdown(kpi("dash", "Need more information", f"{needs}", "Missing inputs; shown as Insufficient data, never Low."), unsafe_allow_html=True)

tab1, tab2 = st.tabs(["System assessments", f"Field visits (KoboToolbox) · {len(V)}"])
with tab1:
    f1, f2, f3 = st.columns([1.4, 1.4, 1.2])
    q = f1.text_input("Search field ID", placeholder="e.g. F001", key="q_assess")
    risk_f = f2.multiselect("Risk class", [k for k in RISK_ORDER if (A["risk_level"] == k).any()],
                            format_func=lambda k: RISK[k]["short"], placeholder="All")
    stat_f = f3.selectbox("Verification", ["All", "Verified", "Pending", "Under review"])
    t = sort_by_risk(A).copy()
    t["Verification"] = t["field_id"].map(status)
    t["Location"] = t["field_id"].map(lambda f: field_location(data, f)["district"])
    if q:
        t = t[t["field_id"].str.contains(q.strip(), case=False, na=False)]
    if risk_f:
        t = t[t["risk_level"].isin(risk_f)]
    if stat_f != "All":
        t = t[t["Verification"].str.startswith({"Verified": "Verified", "Pending": "Not yet", "Under review": "Visit"}[stat_f])]
    show = t[["field_id", "risk_level", "outcome", "data_confidence", "Verification", "Location", "assessment_date", "alert_id"]]
    show.columns = ["Field ID", "Risk class", "Result", "Data confidence", "Verification", "Location", "Assessed for", "Alert ID"]
    if show.empty:
        empty("No assessment matches these filters.")
    else:
        ev = st.dataframe(show, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row",
                          key="tbl_assess")
        st.caption("Select a row to open the field profile.")
        rows = ev.selection.rows if ev and hasattr(ev, "selection") else []
        if rows:
            st.query_params["field"] = show.iloc[rows[0]]["Field ID"]
            st.rerun()

with tab2:
    if V.empty:
        empty("No field visits received yet. Test records are excluded by design.")
    else:
        q2 = st.text_input("Search field or alert ID", key="q_visit")
        t = V.copy()
        t["Field"] = t.get("field_id_pipeline", t.get("field_id"))
        if q2:
            m = t["Field"].astype(str).str.contains(q2, case=False) | t["alert_id"].astype(str).str.contains(q2, case=False)
            t = t[m]
        t["Verdict"] = t["field_verdict"].map({"confirmed": "Confirmed", "rejected": "Rejected", "uncertain": "Uncertain"}).fillna(t["field_verdict"])
        t["Checks"] = t["flag_codes"].map(issue_labels)
        cols = {"Field": "Field ID", "visit_date": "Visit date", "district": "Location", "verifier_id": "Verifier",
                "Verdict": "Verdict", "validation_status_final": "Status", "alert_id": "Alert ID (as typed)",
                "matched_alert_id": "Linked alert", "Checks": "Data checks"}
        show = t[[c for c in cols if c in t]].rename(columns=cols)
        ev = st.dataframe(show, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row", key="tbl_visit")
        st.caption("Original Kobo answers are kept unchanged; 'Linked alert' is the system's link to the issued prediction.")
        rows = ev.selection.rows if ev and hasattr(ev, "selection") else []
        if rows and show.iloc[rows[0]]["Field ID"] in set(A["field_id"]):
            st.query_params["field"] = show.iloc[rows[0]]["Field ID"]
            st.rerun()

with st.expander("What each risk class means, and the method"):
    for k in [k for k in RISK_ORDER if k != "Not assessed"]:
        html_block(f'<div style="display:flex;gap:14px;align-items:flex-start;margin:4px 0">'
                   f'<div style="min-width:150px">{badge(k)}</div><div>{E(RISK[k]["means"])}</div></div>')
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
