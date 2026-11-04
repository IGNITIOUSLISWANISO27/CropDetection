"""Shared design system, data access and building blocks for the FieldPriority dashboard.

The app reads data only through the repository (Firebase or local output files); it never recomputes the
drought-risk rules. Every risk label shown comes from the rules engine (src/fieldpriority/model/rules.py).
"""
import html
import os
import sys
import datetime as dt
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import altair as alt
import folium
import numpy as np
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from fieldpriority.config import load_config
from fieldpriority.storage.repository import get_repository

CFG = load_config()
E = html.escape

# ================================================================ design tokens
C = {
    "forest": "#1F4D3A", "forest_dark": "#163829", "leaf": "#3E8E5A", "maize": "#D9A21B", "maize_soft": "#F6E7B8",
    "navy": "#14233A", "cream": "#FAF8F2", "paper": "#FFFFFF", "sand": "#F1ECE0", "earth": "#8B6B4A",
    "ink": "#1E2A24", "muted": "#5E6B63", "line": "#E3DDCF",
}
# Risk levels from the drought-stress rules. Kept separate from data confidence and verification status
# everywhere (rule 9). Every level has a colour AND a written label AND an icon (never colour alone).
RISK = {
    "High": {"color": "#B9342B", "text": "#FFFFFF", "icon": "alert", "short": "High risk",
             "means": "Water shortage and a fall in crop greenness together, with a severe drop or at a sensitive growth stage. "
                      "The field needs a verification visit soon."},
    "Moderate": {"color": "#DB7A1F", "text": "#FFFFFF", "icon": "rise", "short": "Moderate risk",
                 "means": "Water shortage and a fall in crop greenness together. Possible drought stress that needs "
                          "a field check."},
    "Not attributed": {"color": "#6A4C93", "text": "#FFFFFF", "icon": "question", "short": "Cause uncertain",
                       "means": "Crop greenness fell but there is no water shortage, so the cause is probably not "
                                "drought (pests, disease, nutrients or management). A field check finds out."},
    "Watch": {"color": "#D9A21B", "text": "#1E2A24", "icon": "eye", "short": "Watch",
              "means": "A water shortage is showing but the crop has not reacted yet. Continue monitoring field "
                       "conditions."},
    "Low": {"color": "#2E8B57", "text": "#FFFFFF", "icon": "check", "short": "Low risk",
            "means": "The indicators show no drought concern at the moment."},
    "Insufficient data": {"color": "#7A8590", "text": "#FFFFFF", "icon": "dash", "short": "Insufficient data",
                          "means": "Not enough usable data to judge drought risk. This is NOT the same as low risk: "
                                   "the profile lists what is missing."},
    "Not assessed": {"color": "#A7AFB7", "text": "#1E2A24", "icon": "dash", "short": "Not assessed",
                     "means": "Outside the system's scope (for example not a maize field)."},
}
RISK_ORDER = ["High", "Moderate", "Not attributed", "Watch", "Low", "Insufficient data", "Not assessed"]
RISK_COLORS = {k: v["color"] for k, v in RISK.items()}
FIELD_COLOR, REGIONAL_COLOR = C["leaf"], "#4C78A8"

ICONS = {   # 24x24 stroke icons, drawn for this app
    "alert": '<path d="M12 3 2.5 20h19L12 3Z"/><path d="M12 10v4.5M12 17.5v.01"/>',
    "rise": '<path d="M3 17l6-6 4 4 8-8"/><path d="M15 7h6v6"/>',
    "question": '<circle cx="12" cy="12" r="9"/><path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .9-1 1.6v.6M12 17v.01"/>',
    "eye": '<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/>',
    "check": '<circle cx="12" cy="12" r="9"/><path d="m8 12.5 2.6 2.6L16 9.5"/>',
    "dash": '<circle cx="12" cy="12" r="9"/><path d="M8 12h8"/>',
    "field": '<path d="M3 20 8 4h8l5 16Z"/><path d="M12 4v16M5.5 12h13"/>',
    "pin": '<path d="M12 21s7-6.2 7-11.5A7 7 0 0 0 5 9.5C5 14.8 12 21 12 21Z"/><circle cx="12" cy="9.5" r="2.5"/>',
    "clipboard": '<rect x="5" y="4" width="14" height="17" rx="2"/><path d="M9 4V3h6v1M9 10h6M9 14h6M9 18h3"/>',
    "layers": '<path d="m12 3 9 5-9 5-9-5 9-5Z"/><path d="m3 13 9 5 9-5"/>',
    "gauge": '<path d="M4 18a8 8 0 1 1 16 0"/><path d="m12 18 4-6"/>',
    "sat": '<path d="m6 14 4 4M4 16l4 4M14 6l4 4"/><rect x="8" y="8" width="6" height="6" rx="1" transform="rotate(45 11 11)"/>',
    "drop": '<path d="M12 3s6 6.5 6 11a6 6 0 0 1-12 0c0-4.5 6-11 6-11Z"/>',
    "leaf": '<path d="M5 19c0-8 5-13 15-14-1 10-6 15-14 15"/><path d="M5 19c3-4 6-7 10-9"/>',
    "camera": '<rect x="3" y="7" width="18" height="13" rx="2"/><path d="M8 7l1.5-3h5L16 7"/><circle cx="12" cy="13.5" r="3.5"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "doc": '<path d="M6 3h8l4 4v14H6Z"/><path d="M14 3v4h4M9 12h6M9 16h6"/>',
}


def icon(name, size=18, color="currentColor", stroke=1.8):
    return (f'<svg viewBox="0 0 24 24" width="{size}" height="{size}" fill="none" stroke="{color}" '
            f'stroke-width="{stroke}" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
            f'{ICONS.get(name, "")}</svg>')


LOGO = (  # original mark: a maize leaf rising from a field grid, with a survey point
    '<svg viewBox="0 0 48 48" width="{s}" height="{s}" aria-label="FieldPriority logo">'
    '<rect width="48" height="48" rx="12" fill="#1F4D3A"/>'
    '<path d="M8 38h32M8 31h32M15 24 12 41M24 24v17M33 24l3 17" stroke="#3E8E5A" stroke-width="2" '
    'stroke-linecap="round"/>'
    '<path d="M24 31c-1-10 3-18 13-22-1 10-5 17-13 22Z" fill="#D9A21B"/>'
    '<path d="M24 31c3-6 6-10 11-15" stroke="#1F4D3A" stroke-width="1.6" stroke-linecap="round" fill="none"/>'
    '<circle cx="15" cy="16" r="3.2" fill="none" stroke="#FAF8F2" stroke-width="2"/>'
    '<circle cx="15" cy="16" r="1" fill="#FAF8F2"/></svg>')

# ================================================================ CSS
CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@600;700;800&family=Inter:wght@400;500;600&display=swap');
:root{--forest:#1F4D3A;--leaf:#3E8E5A;--maize:#D9A21B;--navy:#14233A;--cream:#FAF8F2;--sand:#F1ECE0;
      --ink:#1E2A24;--muted:#5E6B63;--line:#E3DDCF;--paper:#FFFFFF;
      --fh:'Plus Jakarta Sans','Inter','Segoe UI',system-ui,-apple-system,sans-serif;--fb:'Inter','Segoe UI',system-ui,-apple-system,sans-serif}
html, body, .stMarkdown p, .stMarkdown li, label, input, textarea {font-family:var(--fb)}
h1,h2,h3,h4,.fp-h{font-family:var(--fh) !important;color:var(--ink);letter-spacing:-.01em}
.stApp{background:var(--cream)}
.block-container{padding-top:4.6rem;padding-bottom:3rem;max-width:1320px}
header[data-testid="stHeader"]{background:var(--forest)}
header[data-testid="stHeader"] a, header[data-testid="stHeader"] span, header[data-testid="stHeader"] p{color:#F4F1E8 !important}
[data-testid="stSidebar"]{background:var(--sand)}
/* page heading */
.fp-title{display:flex;align-items:center;gap:14px;margin:.4rem 0 .2rem}
.fp-title h1{font-size:2rem;margin:0;padding:0}
.fp-lead{color:var(--muted);font-size:1.02rem;max-width:860px;margin:.15rem 0 1.2rem}
.fp-eyebrow{font:600 .74rem/1 var(--fb);text-transform:uppercase;letter-spacing:.12em;color:var(--leaf);margin-bottom:.35rem}
/* hero */
.fp-hero{position:relative;border-radius:22px;overflow:hidden;min-height:340px;display:flex;align-items:flex-end;
         background:#1F4D3A;margin-bottom:1.4rem;box-shadow:0 10px 30px rgba(20,35,58,.18)}
.fp-hero svg.bg{position:absolute;inset:0;width:100%;height:100%}
.fp-hero .shade{position:absolute;inset:0;background:linear-gradient(100deg,rgba(18,44,33,.94) 0%,rgba(22,56,41,.82) 42%,rgba(22,56,41,.25) 100%)}
.fp-hero .inner{position:relative;padding:44px 48px 40px;max-width:760px}
.fp-hero h1{color:#FFFFFF !important;font-size:2.6rem;line-height:1.08;margin:.35rem 0 .8rem}
.fp-hero h1 .gold{color:#F2C74E !important}
.fp-hero p{color:#E8EFE9;font-size:1.06rem;line-height:1.55;margin:0 0 1.4rem}
.fp-hero .tag{display:inline-flex;gap:8px;align-items:center;font:600 .78rem var(--fb);letter-spacing:.08em;text-transform:uppercase;
              color:#F2C74E;background:rgba(242,199,78,.12);border:1px solid rgba(242,199,78,.35);padding:5px 11px;border-radius:999px}
.fp-btn{display:inline-flex;align-items:center;gap:8px;padding:11px 20px;border-radius:12px;font:600 .95rem var(--fb);
        text-decoration:none !important;margin:0 10px 8px 0;transition:transform .12s ease}
.fp-btn:hover{transform:translateY(-1px)}
.fp-btn.gold{background:#D9A21B;color:#1E2A24 !important}
.fp-btn.ghost{background:rgba(255,255,255,.08);color:#FFFFFF !important;border:1px solid rgba(255,255,255,.45)}
/* cards */
.fp-card{background:var(--paper);border:1px solid var(--line);border-radius:16px;padding:18px 20px;height:100%;
         box-shadow:0 1px 2px rgba(20,35,58,.04)}
.fp-card h4{margin:0 0 .3rem;font-size:1.02rem}
.fp-kpi{display:flex;flex-direction:column;gap:6px}
.fp-kpi .top{display:flex;justify-content:space-between;align-items:center;color:var(--muted);font:600 .82rem var(--fb);
             text-transform:uppercase;letter-spacing:.06em}
.fp-kpi .ic{width:36px;height:36px;border-radius:10px;display:grid;place-items:center;background:#E8F1EA;color:var(--forest)}
.fp-kpi .val{font:800 2.1rem/1.05 var(--fh);color:var(--ink)}
.fp-kpi .val small{font:600 1rem var(--fb);color:var(--muted);margin-left:4px}
.fp-kpi .lab{color:var(--muted);font-size:.9rem;line-height:1.35}
.fp-section{font:700 1.25rem var(--fh);color:var(--ink);margin:1.6rem 0 .2rem;display:flex;gap:10px;align-items:center}
.fp-sub{color:var(--muted);font-size:.92rem}
.fp-note{background:#FFF8E6;border:1px solid #F0DCA4;border-radius:12px;padding:10px 14px;color:#5A4510;font-size:.92rem}
.fp-empty{background:var(--paper);border:1px dashed #CFC6B2;border-radius:14px;padding:18px;color:var(--muted);text-align:center}
/* risk badge */
.fp-badge{display:inline-flex;align-items:center;gap:6px;padding:3px 11px 3px 8px;border-radius:999px;font:600 .82rem var(--fb);
          white-space:nowrap;vertical-align:middle}
.fp-badge.lg{font-size:.98rem;padding:6px 15px 6px 11px}
.fp-dist{display:flex;height:14px;border-radius:999px;overflow:hidden;background:#EEE9DD;margin:8px 0 6px}
.fp-legend{display:flex;flex-wrap:wrap;gap:8px 14px;font-size:.86rem;color:var(--ink)}
.fp-legend i{display:inline-block;width:12px;height:12px;border-radius:3px;margin-right:6px;vertical-align:-1px}
/* activity */
.fp-act{display:flex;gap:12px;padding:11px 0;border-bottom:1px solid var(--line)}
.fp-act:last-child{border-bottom:0}
.fp-act .dot{width:34px;height:34px;flex:none;border-radius:10px;display:grid;place-items:center;background:#E8F1EA;color:var(--forest)}
.fp-act .t{font-weight:600;color:var(--ink)}
.fp-act .m{color:var(--muted);font-size:.86rem}
/* source tags: observed / calculated / estimated / verified (scientific transparency) */
.fp-src{display:inline-block;font:600 .7rem var(--fb);letter-spacing:.06em;text-transform:uppercase;padding:2px 7px;border-radius:6px;margin-left:6px;vertical-align:middle}
.fp-src.obs{background:#E3EEF9;color:#1F4E80}.fp-src.calc{background:#E8F1EA;color:#1F4D3A}
.fp-src.est{background:#FFF1D6;color:#7A5300}.fp-src.ver{background:#EDE6F7;color:#4B2F7A}
.fp-kv{display:grid;grid-template-columns:minmax(120px,38%) 1fr;gap:7px 14px;font-size:.93rem}
.fp-kv div:nth-child(odd){color:var(--muted)}
.fp-kv div:nth-child(even){color:var(--ink);font-weight:500}
.fp-photo{border:1px solid var(--line);border-radius:12px;padding:12px;background:var(--paper)}
div[data-testid="stMetricValue"]{font-family:var(--fh);font-weight:800;font-size:1.55rem !important;color:var(--ink)}
div[data-testid="stMetric"]{background:var(--paper);border:1px solid var(--line);border-radius:14px;padding:12px 16px}
@media (max-width: 760px){
  .fp-hero .inner{padding:28px 22px}
  .fp-hero h1{font-size:1.85rem}
  .fp-title h1{font-size:1.5rem}
  .fp-kpi .val{font-size:1.7rem}
}
</style>
"""


# ================================================================ small components
def html_block(s):
    st.markdown(s, unsafe_allow_html=True)


def badge(level, large=False, label=None):
    r = RISK.get(level, {"color": "#7A8590", "text": "#FFFFFF", "icon": "dash", "short": str(level)})
    pad = "6px 15px 6px 11px;font-size:.98rem" if large else "3px 11px 3px 8px;font-size:.82rem"
    return (f'<span class="fp-badge{" lg" if large else ""}" style="background:{r["color"]};color:{r["text"]};'
            f'display:inline-flex;align-items:center;gap:6px;border-radius:999px;font-weight:600;padding:{pad};'
            f'white-space:nowrap;font-family:Inter,Segoe UI,sans-serif">'
            f'{icon(r["icon"], 15 if not large else 18, r["text"], 2.2)}{E(label or r["short"])}</span>')


chip = badge   # backwards compatible name


def src_tag(kind):
    lab = {"obs": "Observed", "calc": "Calculated", "est": "Estimated", "ver": "Field-verified"}[kind]
    return f'<span class="fp-src {kind}">{lab}</span>'


def page_title(title, lead, eyebrow=None, icon_name=None):
    ic = (f'<span style="width:44px;height:44px;border-radius:12px;display:grid;place-items:center;'
          f'background:{C["forest"]};color:#F2C74E">{icon(icon_name, 24)}</span>') if icon_name else ""
    eb = f'<div class="fp-eyebrow">{E(eyebrow)}</div>' if eyebrow else ""
    html_block(f'{eb}<div class="fp-title">{ic}<h1>{E(title)}</h1></div><p class="fp-lead">{lead}</p>')


def section(title, icon_name=None, sub=None):
    ic = icon(icon_name, 20, C["forest"]) if icon_name else ""
    html_block(f'<div class="fp-section">{ic}{E(title)}</div>' + (f'<div class="fp-sub">{sub}</div>' if sub else ""))


def kpi(icon_name, title, value, label, unit=None):
    u = f"<small>{E(unit)}</small>" if unit else ""
    return (f'<div class="fp-card fp-kpi"><div class="top">{E(title)}<span class="ic">{icon(icon_name, 20)}</span></div>'
            f'<div class="val">{value}{u}</div><div class="lab">{label}</div></div>')


def risk_distribution_html(counts, total=None):
    """Stacked bar + legend with counts; colour, text and order from RISK."""
    total = total or sum(counts.values())
    if not total:
        return '<div class="fp-sub">No fields assessed yet.</div>'
    bar = "".join(f'<span title="{E(k)}: {n}" style="width:{n / total * 100:.2f}%;background:{RISK[k]["color"]}"></span>'
                  for k in RISK_ORDER if (n := counts.get(k, 0)))
    leg = "".join(f'<span><i style="background:{RISK[k]["color"]}"></i>{E(RISK[k]["short"])} <b>{counts[k]}</b></span>'
                  for k in RISK_ORDER if counts.get(k))
    return f'<div class="fp-dist">{bar}</div><div class="fp-legend">{leg}</div>'


def legend_html(levels=None):
    levels = levels or RISK_ORDER
    return '<div class="fp-legend">' + "".join(
        f'<span>{badge(k)}</span>' for k in levels) + "</div>"


def empty(msg):
    html_block(f'<div class="fp-empty">{msg}</div>')


# ================================================================ issue labels (Kobo quality checks)
ISSUE_LABELS = {
    "ID_MISSING": "Alert ID or Field ID missing", "FIELD_UNMAPPED": "Field ID not recognised",
    "ALERT_NOT_FOUND": "Alert ID not found", "ALERT_FIELD_MISMATCH": "Alert ID belongs to a different field",
    "RISK_MISMATCH": "Risk level typed on the form differs from the issued alert",
    "PERMISSION_MISSING": "Permission not answered",
    "NO_PERMISSION_OBS": "Observations recorded without permission", "NOT_MAIZE": "Maize not the main crop",
    "STAGE_MISSING": "Growth stage missing", "EVIDENCE_MISSING": "Crop or soil observations missing",
    "ALT_CAUSES_MISSING": "Alternative causes not all checked", "VERDICT_MISSING": "No verdict",
    "REASON_SHORT": "Verdict reason too short", "PHOTO_MISSING": "Photo missing",
    "FLOWERING_STAGE": "Flowering concern at an early stage", "IRRIG_CONFLICT": "Irrigation answers conflict",
    "SOIL_WATERLOG": "Soil and waterlogging answers conflict", "VERDICT_CAUSE": "Verdict and main cause conflict",
    "CONFIRMED_NO_SIGNS": "Confirmed without any stress signs", "PRIVACY": "Possible personal contact details",
    "DATE_MISSING": "Visit date missing", "DATE_FUTURE": "Visit date in the future", "ALERT_DATE_MISSING": "No alert date",
    "DATE_ORDER": "Visit before alert date", "LATE_VISIT": "Visit long after the alert",
    "PLANTING_AFTER_VISIT": "Planting date after visit", "TEST_RECORD": "Test record",
    "NO_PERMISSION": "Permission refused", "ALERT_ID_ALIAS": "Linked through an approved alert-ID alias"}
ISSUE_KIND = {  # missing information / invalid information / not yet verified (brief section 7)
    "missing": {"ID_MISSING", "PERMISSION_MISSING", "STAGE_MISSING", "EVIDENCE_MISSING", "ALT_CAUSES_MISSING",
                "VERDICT_MISSING", "REASON_SHORT", "PHOTO_MISSING", "DATE_MISSING", "ALERT_DATE_MISSING"},
    "invalid": {"FIELD_UNMAPPED", "ALERT_NOT_FOUND", "ALERT_FIELD_MISMATCH", "NO_PERMISSION_OBS", "NOT_MAIZE",
                "FLOWERING_STAGE", "IRRIG_CONFLICT", "SOIL_WATERLOG", "VERDICT_CAUSE", "CONFIRMED_NO_SIGNS",
                "PRIVACY", "DATE_FUTURE", "DATE_ORDER", "PLANTING_AFTER_VISIT"},
}


def issue_label(code):
    return ISSUE_LABELS.get(code, code)


def issue_labels(codes):
    return "; ".join(issue_label(c) for c in str(codes).split(";") if c and c != "nan")


# ================================================================ data
@st.cache_data(ttl=120, show_spinner="Loading FieldPriority data")
def _load(source, outputs_dir, cred):
    return get_repository(source, outputs_dir, cred).load()


def load_data():
    """Sidebar data controls + cached load. Called once per run by the router (Home.py)."""
    default = os.environ.get("FIELDPRIORITY_SOURCE", "auto")
    opts = ["auto", "firebase", "local"]
    with st.sidebar:
        html_block(f'<div style="display:flex;gap:10px;align-items:center">{LOGO.format(s=40)}'
                   f'<div><div class="fp-h" style="font-weight:800;font-size:1.1rem">FieldPriority</div>'
                   f'<div class="fp-sub" style="font-size:.8rem">{E(CFG["pilot_area"])}</div></div></div>')
        st.divider()
        source = st.radio("Data source", opts, index=opts.index(default), key="source",
                          format_func={"auto": "Automatic", "firebase": "Firebase", "local": "Local files"}.get,
                          help="Automatic uses Firebase when a key is configured, otherwise the local outputs folder.")
        if st.button("Reload data", width="stretch", icon=":material/refresh:"):
            st.cache_data.clear()
    outputs = os.environ.get("FIELDPRIORITY_OUTPUTS") or str(ROOT / CFG["paths"]["output_dir"])
    try:
        data = _load(source, outputs, None)
    except Exception as e:
        st.error(f"Could not load data. {e}")
        st.stop()
    with st.sidebar:
        st.caption(f"Showing: {data.source_note}")
        if data.meta.get("assessed_at"):
            st.caption(f"Last assessment run {str(data.meta['assessed_at'])[:16].replace('T', ' ')} UTC")
    return data


def get_data():
    return st.session_state["fp_data"]


def period_text(data):
    p = str(data.meta.get("period") or CFG["period_label"])
    a, _, b = p.partition("..")
    return f"{pd.Period(a, 'M').strftime('%b %Y')} to {pd.Period(b or a, 'M').strftime('%b %Y')}"


def period_year(data):
    return int(str(data.meta.get("period") or CFG["period_label"])[:4])


def risk_counts(A):
    return A["risk_level"].value_counts().to_dict() if len(A) else {}


def sort_by_risk(A):
    return A.assign(_o=A["risk_level"].map({k: i for i, k in enumerate(RISK_ORDER)}).fillna(99)) \
            .sort_values(["_o", "field_id"]).drop(columns="_o")


# ---------------------------------------------------------------- field visits (KoboToolbox)
def visits(data, include_test=False):
    v = data.verifications
    if v is None or v.empty or "record_type" not in v:
        return pd.DataFrame()
    v = v.copy()
    if not include_test:
        v = v[(v["record_type"] == "real_visit") & ~v.get("is_test", pd.Series(False, index=v.index)).fillna(False).astype(bool)]
    return v


real_visits = visits


def attachments(v):
    """Kobo photo attachments of one visit record (list of dicts); stored as a JSON string in some exports."""
    import json
    a = v.get("_attachments") if isinstance(v, dict) else v
    if isinstance(a, str):
        try:
            a = json.loads(a)
        except ValueError:
            return []
    return [x for x in a if isinstance(x, dict) and not x.get("is_deleted")] if isinstance(a, list) else []


def verification_status(data, aid):
    """Field-verification status of one alert, from Kobo records only (never from the prediction)."""
    v = visits(data)
    verdicts = {"confirmed": "Confirmed", "rejected": "Rejected", "uncertain": "Uncertain"}
    if v.empty or "matched_alert_id" not in v:
        return "Not yet verified"
    r = v[v["matched_alert_id"] == aid]
    if r.empty:
        return "Not yet verified"
    ok = r[r["analysis_eligible"].fillna(False).astype(bool)]
    if len(ok):
        return "Verified: " + verdicts.get(str(ok.iloc[-1]["field_verdict"]), "n/a")
    return "Visit submitted, under review"


def status_by_field(data):
    return {r["field_id"]: verification_status(data, r["alert_id"]) for r in data.assessments.to_dict("records")}


def field_location(data, fid):
    g = data.fields.set_index("Field_ID").loc[fid].geometry
    c = g.centroid
    v = visits(data)
    district = None
    if len(v) and "field_id_pipeline" in v:
        d = v[v["field_id_pipeline"] == fid]
        if len(d) and "district" in d:
            district = d["district"].dropna().iloc[-1] if d["district"].notna().any() else None
    return {"lat": c.y, "lon": c.x, "district": district or CFG["pilot_area"].split(",")[0].replace(" pilot", ""),
            "geom_type": g.geom_type, "valid": bool(g.is_valid)}


def profile_link(fid):
    return f"/assessments?field={E(str(fid))}"


# ================================================================ map
ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
VIEWS = {"Fit fields": None, "Field close-up": 18, "Neighbourhood (~2 km)": 15, "Town (~10 km)": 13,
         "District (~40 km)": 11, "Province (~200 km)": 8}


def build_map(data, A=None, basemap="Satellite", view="Fit fields", focus=None, height_hint=560, labels=True):
    gdf = data.fields
    A = (data.assessments if A is None else A).set_index("field_id")
    gdf = gdf[gdf["Field_ID"].isin(A.index)]
    status = status_by_field(data)
    target = gdf[gdf["Field_ID"] == focus] if focus else gdf
    if target.empty:
        target = data.fields
    minx, miny, maxx, maxy = target.total_bounds
    z = VIEWS.get(view)
    m = folium.Map(location=[(miny + maxy) / 2, (minx + maxx) / 2], zoom_start=z or 10, tiles=None,
                   control_scale=True, zoom_control=True, max_zoom=20)
    sat = folium.TileLayer(ESRI, attr="Imagery: Esri, Maxar, Earthstar Geographics", name="Satellite",
                           max_native_zoom=17, max_zoom=20)
    osm = folium.TileLayer("OpenStreetMap", name="Street map", max_native_zoom=19, max_zoom=20)
    (sat if basemap == "Satellite" else osm).add_to(m)
    (osm if basemap == "Satellite" else sat).add_to(m)
    for r in gdf.itertuples():
        a = A.loc[r.Field_ID]
        lvl = a["risk_level"]
        col = RISK.get(lvl, {}).get("color", "#7A8590")
        loc = field_location(data, r.Field_ID)
        pop = (f'<div style="font:13px Inter,sans-serif;min-width:220px"><div style="font-weight:700;font-size:15px">'
               f'{E(str(r.Field_ID))}</div><div style="margin:4px 0 8px">{badge(lvl)}</div>'
               f'<div>{E(str(a["outcome"]))}</div><div style="color:#5E6B63;margin-top:6px">'
               f'{r.area_ha:.2f} ha · {loc["lat"]:.5f}, {loc["lon"]:.5f}<br>Data confidence: {E(str(a["data_confidence"]))}'
               f'<br>Verification: {E(status.get(r.Field_ID, "Not yet verified"))}</div>'
               f'<a href="{profile_link(r.Field_ID)}" target="_top" style="display:inline-block;margin-top:8px;'
               f'background:#1F4D3A;color:#fff;padding:6px 11px;border-radius:8px;text-decoration:none">'
               f'Open field profile</a></div>')
        folium.GeoJson(r.geometry.__geo_interface__, name=str(r.Field_ID),
                       tooltip=folium.Tooltip(f"<b>{E(str(r.Field_ID))}</b> · {E(RISK.get(lvl, {}).get('short', lvl))}"),
                       popup=folium.Popup(pop, max_width=300),
                       style_function=lambda _, c=col: {"color": "#FFFFFF", "weight": 2.5, "fillColor": c,
                                                        "fillOpacity": 0.55}).add_to(m)
        if labels:
            cen = r.geometry.centroid
            folium.Marker([cen.y, cen.x], popup=folium.Popup(pop, max_width=300), icon=folium.DivIcon(
                icon_size=(30, 30), icon_anchor=(15, 15), class_name="fp-label",
                html=f'<div style="width:30px;height:30px;border-radius:50%;background:{col};border:2px solid #fff;'
                     f'box-shadow:0 1px 4px rgba(0,0,0,.4);color:{RISK.get(lvl, {}).get("text", "#fff")};'
                     f'font:700 10px/26px Inter,sans-serif;text-align:center">{E(str(r.Field_ID)[-3:])}</div>')).add_to(m)
    folium.LayerControl(position="topright", collapsed=True).add_to(m)
    if z is None:
        m.fit_bounds([[miny, minx], [maxy, maxx]], padding=(40, 40), max_zoom=17 if len(target) == 1 else 15)
    return m


def show_map(m, height=560):
    html_doc = m.get_root().render()
    if hasattr(st, "iframe"):
        st.iframe(html_doc, height=height)
    else:
        components.html(html_doc, height=height)


# ================================================================ charts
def _base(ch):
    return ch.configure_view(strokeWidth=0).configure_axis(labelFont="Inter", titleFont="Inter", labelColor="#5E6B63",
                                                            titleColor="#5E6B63", gridColor="#ECE7DB", domainColor="#CFC6B2")


def risk_bar_chart(A, height=240):
    counts = risk_counts(A)
    rows = [{"Risk": RISK[k]["short"], "Fields": counts.get(k, 0), "order": i, "level": k}
            for i, k in enumerate(RISK_ORDER) if k != "Not assessed" or counts.get(k)]
    d = pd.DataFrame(rows)
    total = max(1, d["Fields"].sum())
    d["Share"] = d["Fields"] / total
    ch = alt.Chart(d).encode(
        y=alt.Y("Risk:N", sort=list(d["Risk"]), title=None, axis=alt.Axis(labelLimit=160)),
        x=alt.X("Fields:Q", title="Number of fields", axis=alt.Axis(tickMinStep=1)),
        tooltip=["Risk", "Fields", alt.Tooltip("Share:Q", format=".0%")])
    bars = ch.mark_bar(cornerRadiusEnd=6, height=22).encode(
        color=alt.Color("level:N", scale=alt.Scale(domain=list(RISK), range=[RISK[k]["color"] for k in RISK]), legend=None))
    text = ch.mark_text(align="left", dx=6, font="Inter", fontWeight=600, color="#1E2A24").encode(
        text=alt.Text("Fields:Q"))
    return _base((bars + text).properties(height=height))


def trend_chart(monthly, variable, field, title, ytitle, year, bars=False):
    d = monthly[(monthly["variable"] == variable) & (monthly["month"] > 0)].copy() if len(monthly) else pd.DataFrame()
    if d.empty:
        return None
    d["Month"] = d["month"].map(lambda m: pd.Period(f"{year}-{int(m):02d}", "M").strftime("%b %Y"))
    d["Field"] = d["Field_ID"]
    sel, oth = d[d.Field_ID == field], d[d.Field_ID != field]
    order = [pd.Period(f"{year}-{int(m):02d}", "M").strftime("%b %Y") for m in sorted(d["month"].unique())]
    x = alt.X("Month:O", title=None, sort=order, axis=alt.Axis(labelAngle=0))
    if bars:
        b = alt.Chart(sel).mark_bar(size=30, cornerRadiusEnd=4).encode(
            x=x, y=alt.Y("mean:Q", title=ytitle),
            color=alt.condition(alt.datum["mean"] < 0, alt.value("#B9342B"), alt.value(REGIONAL_COLOR)),
            tooltip=["Field", "Month", alt.Tooltip("mean:Q", format=".1f", title=ytitle)])
        zero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color="#5E6B63").encode(y="y:Q")
        return _base((b + zero).properties(title=title, height=210))
    y = alt.Y("mean:Q", title=ytitle, scale=alt.Scale(zero=False))
    layers = []
    if len(oth):
        layers.append(alt.Chart(oth).mark_line(color="#CFC6B2", strokeWidth=1.5).encode(x=x, y=y, detail="Field:N"))
    layers.append(alt.Chart(sel).mark_line(point=alt.OverlayMarkDef(size=70, color=FIELD_COLOR, filled=True),
                                           color=FIELD_COLOR, strokeWidth=3).encode(
        x=x, y=y, tooltip=["Field", "Month", alt.Tooltip("mean:Q", format=".3f", title=ytitle)]))
    return _base(alt.layer(*layers).properties(title=title, height=210))


def hero_svg():
    """Aerial view of cultivated parcels, drawn for this app (no photo licence needed)."""
    import random
    rnd = random.Random(7)
    fills = ["#2E6B45", "#3E8E5A", "#4F9A5E", "#6FA85A", "#9DB55A", "#C9A64B", "#A8834F", "#7F9E52", "#376F4A"]
    cells, x = [], 0
    while x < 1400:
        w = rnd.randint(90, 190)
        y = 0
        while y < 420:
            h = rnd.randint(60, 150)
            f = rnd.choice(fills)
            sk = rnd.randint(-14, 14)
            pts = f"{x + sk},{y} {x + w + sk},{y} {x + w},{y + h} {x},{y + h}"
            cells.append(f'<polygon points="{pts}" fill="{f}" stroke="#1B3B2B" stroke-width="2.5"/>')
            if rnd.random() < .55:   # crop rows
                for k in range(8, h, 9):
                    cells.append(f'<line x1="{x + 4}" y1="{y + k}" x2="{x + w - 4}" y2="{y + k}" stroke="rgba(255,255,255,.10)" stroke-width="2"/>')
            y += h
        x += w
    return ('<svg class="bg" viewBox="0 0 1400 420" preserveAspectRatio="xMidYMid slice" aria-hidden="true">'
            + "".join(cells) + '<path d="M-20 300 C 300 250, 520 380, 820 300 S 1300 230, 1440 270" '
            'stroke="#7C6A4D" stroke-width="10" fill="none" opacity=".75"/></svg>')
