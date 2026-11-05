import pandas as pd
import streamlit as st
from _lib import (layer_table, page_title, html_block, national, monitored_fields, build_zambia_map, show_map, layer_available,
                  period_of, type_tag, conf_tag, evidence_line, icon, empty, LAYERS, E)

nd = national()
F = monitored_fields(nd)
page_title("Zambia Map", "Where conditions are changing. Click a district for its intelligence report.",
           eyebrow="Geographical overview", icon_name="layers")

with st.container(border=True):
    c1, c2, c3 = st.columns([3.2, 1.3, 1])
    key = c1.segmented_control("Indicator layer", list(LAYERS), default="overall", key="map_layer", width="stretch",
                               format_func=lambda k: LAYERS[k]["short"] + ("" if layer_available(nd, k) else " (soon)")) or "overall"
    prov = c2.selectbox("Province", ["All provinces"] + sorted(nd.districts["province"].unique()))
    show_f = c3.toggle("Fields and visits", value=True)

left, right = st.columns([2.3, 1], gap="medium")
with left:
    m = build_zambia_map(nd, key, F, show_fields=show_f)
    if prov != "All provinces":
        b = nd.districts[nd.districts["province"] == prov].total_bounds
        m.fit_bounds([[b[1], b[0]], [b[3], b[2]]], padding=(10, 10))
    show_map(m, height=650)
    st.caption("District averages; farms can differ. Boundaries: geoBoundaries.")

with right:
    L = LAYERS[key]
    html_block(f'<div class="fp-card"><h4>{icon(L["icon"], 18, "#1F4D3A")} {E(L["label"])}</h4>'
               f'<div class="fp-sub" style="margin:.3rem 0">{E(L["what"])}</div>'
               f'<div class="fp-sub">Period: <b>{E(period_of(nd) if key != "solar" else str(nd.report.get("solar_year", "")))}</b></div></div>')
    t = layer_table(nd, key).copy()
    if prov != "All provinces" and len(t):
        t = t[t["province"] == prov]
    if t.empty or not layer_available(nd, key):
        empty("This layer is not available yet. " + (
            "It needs the Earth Engine district export (gee/district_layers.js, run by Person 1)."
            if key in ("vegetation", "maize") else "Run monthly_update.bat on the project computer."))
    else:
        ok = t[t["status"] == "ok"]
        r0 = ok.iloc[0].to_dict()
        with st.popover("Source and quality", icon=":material/info:", width="stretch"):
            html_block(f'<div>{type_tag(r0["data_type"])}{conf_tag(r0["confidence"])}</div>'
                       f'<div class="fp-sub" style="margin-top:6px">{evidence_line(r0)}</div>'
                       + (f'<div class="fp-note" style="margin-top:8px">{E(r0["quality_note"])}</div>'
                          if r0.get("quality_note") else ""))
        show = ok[["location_name", "province", "display", "value"]].copy()
        show["value"] = pd.to_numeric(show["value"], errors="coerce")
        show = show.sort_values("value" if show["value"].notna().any() else "display")
        st.dataframe(show.rename(columns={"location_name": "District", "province": "Province", "display": L["label"],
                                          "value": "Value"}).drop(columns=["Value"] if key == "water" else []),
                     hide_index=True, width="stretch", height=330)
    if nd.available:
        st.download_button("Download all district indicators (CSV)", nd.indicators.to_csv(index=False).encode(),
                           "zambia_district_indicators.csv", "text/csv", icon=":material/download:", width="stretch")
