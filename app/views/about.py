"""About: the platform's purpose, layers, method and accuracy (for presentations and documentation)."""
import json

import pandas as pd
import streamlit as st
from _lib import (html_block, icon, footer, national, monitored_fields, layer_available, page_title, field_to_intel_html,
                  type_tag, kobo_button, STATUS, ROOT, E)

nd = national()
F = monitored_fields(nd, everyone=True)   # availability counts only
page_title("About / Methodology", "Purpose, evidence, method and accuracy.", eyebrow="FieldPriority", icon_name="doc")

caps = ["Geospatial agricultural monitoring", "Crop and vegetation condition assessment",
        "Rainfall and temperature analysis", "Water stress monitoring", "Ground-based observation and verification",
        "Integrated risk interpretation and decision support"]
html_block(f"""<div class="fp-ident"><div class="l"><div class="fp-eyebrow" style="color:#F2C74E">Identity</div>
<h2>Integrated Agricultural &amp; Environmental Intelligence Platform</h2>
<p>Transforms fragmented environmental and agricultural information into location-specific intelligence that supports
early awareness, agricultural planning and informed decision-making.</p>
<div class="foc"><span><b>Initial focus</b>Zambia</span><span><b>Primary agricultural focus</b>Maize-growing areas</span>
</div></div><div class="r"><div class="h">Core capabilities</div><ul class="fp-act-list" style="margin:0;padding:0">
{"".join(f"<li>{E(x)}</li>" for x in caps)}</ul></div></div>""")

tab0, tab1, tab2, tab3 = st.tabs(["What makes it different", "Layers of evidence", "How it works", "Accuracy"])
with tab0:
    html_block('<div class="fp-q3">'
               '<div class="q"><div class="k">Others show layers</div><div class="a">Separate maps and bulletins</div>'
               '<div class="s">Rainfall maps, vegetation indices and weather bulletins each answer one question; the '
               'user has to combine them.</div></div>'
               '<div class="q"><div class="k">FieldPriority connects them</div><div class="a">One answer per location'
               '</div><div class="s">Field and satellite crop evidence, rainfall, temperature and water stress read together '
               'for a district, zone, province or field: what is happening, why it matters, what to consider next.'
               '</div></div>'
               '<div class="q"><div class="k">And checks itself</div><div class="a">Evidence and verification</div>'
               '<div class="s">Every value carries its source, date and confidence; alerts are verified in the field '
               'and the 2023/24 drought was replayed to test it.</div></div></div>')
with tab1:
    sm_ok = bool(nd.available and ((nd.indicators["indicator"] == "soil_moisture_anomaly_pct")
                                   & (nd.indicators["status"] == "ok")).any())
    status = {
        "Crop & vegetation": ("leaf", "Sentinel-2 (fields), MODIS NDVI (districts)", layer_available(nd, "vegetation") or len(F) > 0),
        "Rainfall": ("drop", "CHIRPS v3.0, 5 km, vs 10-season normal", layer_available(nd, "rainfall")),
        "Temperature": ("thermo", "NASA POWER (districts), ERA5-Land (fields)", layer_available(nd, "temperature")),
        "Water stress": ("drop", "SMAP soil moisture + rainfall rules", sm_ok or layer_available(nd, "water")),
        "Local observations": ("camera", "KoboToolbox field visits and photos", len(F) > 0),
    }
    html_block('<div class="fp-layers">' + "".join(
        f'<div class="fp-layer"><div class="h">{icon(ic, 18, "#1F4D3A")}{E(t)}</div><div class="s">{E(s)}</div>'
        f'<span class="st" style="background:{"#E6F0E9" if ok else "#EEE"};color:{"#1F4D3A" if ok else "#5E6B63"}">'
        f'{"Live" if ok else "Not yet available"}</span></div>' for t, (ic, s, ok) in status.items()) + '</div>')
    html_block(field_to_intel_html())
    html_block('<div class="fp-flow"><div class="b"><b>Location-based intelligence</b>A district, zone, province or '
               'field, with every layer</div><div class="a">→</div><div class="b"><b>Integrated analysis</b>Indicators '
               'connected and explained together</div><div class="a">→</div><div class="b"><b>Practical intelligence'
               '</b>What is happening? Why does it matter? What next?</div></div>')
    html_block('<div class="fp-story"><h3>Why it matters</h3>Changes in rainfall, temperature, vegetation and water '
               'affect maize production, household food security and income. Earlier, location-specific information '
               'helps farmers, extension officers and planners respond before losses happen.</div>')
with tab2:
    html_block('<div class="fp-panel-h"><span>Condition status</span></div><div style="display:flex;gap:8px;'
               'flex-wrap:wrap;margin-bottom:.6rem">' + "".join(
                   f'<span class="fp-zc" style="background:{c};color:#fff">{E(l)}</span>' for l, c in STATUS.values())
               + '</div>')
    st.markdown("""
- **Stable**: crop greenness, soil water and rainfall close to or better than normal.
- **Watch**: an early moisture signal (for example soil drying) while the crop is still green.
- **Attention**: moisture stress in more than one signal.
- **Priority**: the crop itself is reacting (greenness below normal) or several signals agree on water stress:
  first in line for field checks.
- **Insufficient evidence**: not enough layers in this period to make a defensible call.
""")
    html_block('<div class="fp-panel-h" style="margin-top:.6rem"><span>Kinds of evidence</span></div><div style="display:'
               'flex;gap:6px;flex-wrap:wrap;margin-bottom:.4rem">' + " ".join(type_tag(t) for t in (
                   "field_observation", "satellite_estimate", "model_output", "derived", "official")) + '</div>')
    st.markdown("""
- **Every number is an indicator record** with its source, period, resolution, coverage, kind of data (measured,
  satellite estimate, model estimate, field observation, derived, official ZMD) and confidence. Hover over a value to
  see it; each location report has the full evidence register.
- **Normal** = the same months of the 10 previous seasons. Districts are compared with their own normal.
- **Cautious interpretation**: moisture signals (crop greenness, soil moisture, rainfall) set the status; warmth only
  adds to a moisture signal. The platform offers *considerations* (for example, a field check), never commands; it
  supports decisions, it does not make them.
- **Field level** (pilots): Sentinel-2 greenness at 10 m with drought-stress rules; alerts are verified by field
  visits through KoboToolbox, which give the field-level accuracy.
- **Official weather information** comes unchanged from the Zambia Meteorological Department.
- **Monthly update**: one scheduled run refreshes the district layers, the pilots and the ZMD warnings.
""")
with tab3:
    p = ROOT / "config" / "drought_test_results.json"
    if not p.exists():
        st.caption("Run run_drought_test.bat to replay the 2023/24 drought.")
    else:
        S = json.loads(p.read_text())
        st.markdown(f"**Replay of the 2023/24 drought** (national disaster declared {S['declared']}): the district "
                    "layers rebuilt with only the data available at each date, and compared with the 84 districts "
                    "declared affected. *Flagged* = watch or concern.")
        rows = []
        for r in S["runs"]:
            f = r["flagged"]
            rows.append({"Season": "2023/24 drought" if r["kind"] == "drought" else "2024/25 good season (control)",
                         "Data up to": r["period_label"].split(" to ")[-1], "Report ready": r["run_date"],
                         "Affected districts caught": f"{f['hit']}/{f['of_affected']} ({f['hit_rate']:.0%})"
                         if "hit" in f else "–",
                         "False alarms": f"{f['false_alarms']}/{f['of_not_affected']} ({f['false_alarm_rate']:.0%})"})
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        st.caption("Reading: the platform picked up the 2023/24 drought early and left the unaffected north mostly "
                   "quiet, but in the good 2024/25 season it flagged many districts that went on to harvest well "
                   "(over-sensitive). Field-level accuracy comes from verified field visits. Thresholds fingerprint "
                   f"{S['fingerprint']}.")
html_block(footer())
