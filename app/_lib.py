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

from fieldpriority.config import available_pilots

PILOTS = available_pilots()


# ---------------------------------------------------------------- accounts: field evidence is per user
from fieldpriority import auth as _auth


def auth_users():
    try:
        return _auth.users_from(st.secrets)
    except Exception:
        return {}


def current_user():
    try:
        return st.session_state.get("fp_user")
    except Exception:
        return None


def user_pilots():
    """Pilot areas the signed-in account may see (none when signed out)."""
    return _auth.pilots_for(current_user(), PILOTS)


def signin_link_html(text="Sign in to view field evidence"):
    return (f'<a class="fp-btn" href="{link("/login")}" target="_self" style="background:var(--forest);color:#fff">'
            f'{icon("lock", 16, "#fff")} {E(text)}</a>')


def current_pilot():
    try:
        p = st.session_state.get("pilot")
    except Exception:
        p = None
    p = p or os.environ.get("FIELDPRIORITY_PILOT") or PILOTS[0]
    return p if p in PILOTS else PILOTS[0]


@st.cache_resource
def _cfg(pilot):
    return load_config(pilot=pilot)


class _PilotConfig(dict):
    """Settings of the pilot area chosen in this browser session (Solwezi, Chongwe, ...)."""
    def _c(self):
        return _cfg(current_pilot())

    def __getitem__(self, k):
        return self._c()[k]

    def get(self, k, d=None):
        return self._c().get(k, d)

    def __contains__(self, k):
        return k in self._c()


CFG = _PilotConfig()
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
    "lock": '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7.5a4 4 0 0 1 8 0V11"/>',
}


def icon(name, size=18, color="currentColor", stroke=1.8):
    return (f'<svg viewBox="0 0 24 24" width="{size}" height="{size}" fill="none" stroke="{color}" '
            f'stroke-width="{stroke}" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
            f'{ICONS.get(name, "")}</svg>')


LOGO = (  # original mark: a survey pin holding two maize leaves (same as app/assets/logo_icon.svg)
    '<svg viewBox="0 0 60 64" width="{s}" height="{s}" aria-label="FieldPriority logo">'
    '<rect x="2" y="4" width="56" height="56" rx="14" fill="#1F4D3A"/>'
    '<path d="M30 13c-9.4 0-16 6.8-16 15.4C14 39 30 51 30 51s16-12 16-22.6C46 19.8 39.4 13 30 13Z" fill="#D9A21B"/>'
    '<circle cx="30" cy="28.5" r="10" fill="#1F4D3A"/>'
    '<path d="M30 37c-.6-6.2 2-11 8-13.6-.6 6-3.2 10.4-8 13.6Z" fill="#7CC38A"/>'
    '<path d="M30 37c.6-6.2-2-11-8-13.6.6 6 3.2 10.4 8 13.6Z" fill="#3E8E5A"/></svg>')

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
.block-container{padding-top:5.4rem;padding-bottom:3rem;max-width:1320px}
header[data-testid="stHeader"]{background:#FFFFFF;border-bottom:1px solid var(--line);height:4.1rem}
header[data-testid="stHeader"] a, header[data-testid="stHeader"] p{color:var(--ink) !important;font-weight:600}
header[data-testid="stHeader"] a[aria-current="page"], header[data-testid="stHeader"] [aria-selected="true"]{background:#E6F0E9 !important;border-radius:10px}
header[data-testid="stHeader"] a[aria-current="page"] p, header[data-testid="stHeader"] a[aria-current="page"] span{color:var(--forest) !important}
[data-testid="stHeaderLogo"], [data-testid="stLogo"]{height:2.6rem !important;max-height:2.6rem}
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
from fieldpriority import offline as _offline   # noqa: E402
OFFLINE = _offline.is_offline()
if OFFLINE:   # pitch mode: bundled fonts instead of Google Fonts
    CSS = CSS.replace(CSS[CSS.index("@import url('https://fonts.googleapis.com"):CSS.index("display=swap');") + 15],
                      _offline.font_faces_css(), 1)


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
def _load(source, outputs_dir, cred, prefix=None):
    return get_repository(source, outputs_dir, cred, prefix=prefix).load()


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
    env_out = os.environ.get("FIELDPRIORITY_OUTPUTS")
    outputs = (env_out.replace("{pilot}", current_pilot()) if env_out else str(ROOT / CFG["paths"]["output_dir"]))
    try:
        data = _load(source, outputs, None, (CFG.get("firebase") or {}).get("collection_prefix", ""))
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


def link(path, area=None, **params):
    """In-app link that keeps the chosen pilot area (a plain link opens a new session)."""
    from urllib.parse import urlencode
    q = {**{k: v for k, v in params.items() if v is not None}, "area": area or current_pilot()}
    return E(f"{path}?{urlencode(q)}")


def profile_link(fid):
    return link("/assessments", field=str(fid))


# ================================================================ map
ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
VIEWS = {"Fit fields": None, "Field close-up": 18, "Neighbourhood (~2 km)": 15, "Town (~10 km)": 13,
         "District (~40 km)": 11, "Province (~200 km)": 8}


def build_map(data, A=None, basemap="Satellite", view="Fit fields", focus=None, height_hint=560, labels=True,
              legend=True):
    gdf = data.fields
    A_all = data.assessments if A is None else A
    A = A_all.set_index("field_id")
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
               f'<a href="{profile_link(r.Field_ID)}" target="_blank" rel="noopener" style="display:inline-block;margin-top:8px;'
               f'background:#1F4D3A;color:#fff;padding:6px 11px;border-radius:8px;text-decoration:none">'
               f'Open field profile ↗</a></div>')
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
    if legend:
        rows = "".join(f'<div style="display:flex;align-items:center;gap:7px;margin:3px 0"><span style="width:13px;height:13px;'
                       f'border-radius:3px;background:{RISK[k]["color"]}"></span>{E(RISK[k]["short"])}</div>'
                       for k in RISK_ORDER if k != "Not assessed")
        from branca.element import Element
        m.get_root().html.add_child(Element(
            f'<div style="position:absolute;left:12px;bottom:26px;z-index:999;background:rgba(255,255,255,.94);'
            f'border-radius:10px;padding:8px 11px;font:12px Inter,Segoe UI,sans-serif;color:#1E2A24;'
            f'box-shadow:0 2px 8px rgba(0,0,0,.25)"><b>Risk class</b>{rows}</div>'))
    if z is None:
        m.fit_bounds([[miny, minx], [maxy, maxx]], padding=(40, 40), max_zoom=17 if len(target) == 1 else 15)
    return m


def show_map(m, height=560):
    html_doc = m.get_root().render()
    if OFFLINE:
        html_doc = _offline.offline_map_html(html_doc)
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


# ================================================================ landing-page building blocks (design brief v2)
def hero_landscape_svg():
    """Sunset over a maize field with an acacia on the horizon. Drawn for this app (no photo licence needed)."""
    import random
    rnd = random.Random(11)
    out = ['<svg class="bg" viewBox="0 0 1400 460" preserveAspectRatio="xMidYMid slice" aria-hidden="true">'
           '<defs><linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">'
           '<stop offset="0" stop-color="#2E5A6B"/><stop offset=".45" stop-color="#C98B4B"/>'
           '<stop offset=".72" stop-color="#F3C46B"/><stop offset="1" stop-color="#F8DE97"/></linearGradient>'
           '<radialGradient id="sun" cx="0.5" cy="0.5" r="0.5"><stop offset="0" stop-color="#FFF6D2"/>'
           '<stop offset=".35" stop-color="#FFE08A" stop-opacity=".95"/><stop offset="1" stop-color="#FFC857" stop-opacity="0"/></radialGradient>'
           '<linearGradient id="field" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#6E8F3A"/>'
           '<stop offset=".4" stop-color="#3F7A33"/><stop offset="1" stop-color="#1D4A26"/></linearGradient></defs>'
           '<rect width="1400" height="460" fill="url(#sky)"/>'
           '<circle cx="1010" cy="205" r="150" fill="url(#sun)"/><circle cx="1010" cy="205" r="34" fill="#FFF3C4"/>'
           '<path d="M0 222 C 180 205, 330 214, 520 206 S 900 196, 1100 208 S 1320 214, 1400 206 V 250 H0Z" fill="#5C6E43" opacity=".75"/>']
    # acacia: trunk + layered flat canopy
    out.append('<g fill="#2B3524"><path d="M1121 214 C1117 180 1110 160 1098 146 L1103 144 C1113 156 1120 170 1125 186'
               ' C1130 168 1140 152 1156 141 L1160 145 C1146 158 1135 176 1131 214Z"/>'
               '<ellipse cx="1128" cy="139" rx="96" ry="15"/><ellipse cx="1092" cy="131" rx="50" ry="10"/>'
               '<ellipse cx="1166" cy="132" rx="46" ry="9"/><ellipse cx="1128" cy="125" rx="40" ry="8"/></g>')
    out.append('<path d="M0 238 C 300 228, 700 236, 1000 230 S 1300 228, 1400 232 V 460 H0Z" fill="url(#field)"/>')
    # maize plants: rows further down are bigger (perspective)
    for row in range(14):
        t = row / 13
        y = 240 + t ** 1.6 * 230
        h = 10 + t ** 1.5 * 120
        step = 18 + t * 46
        x = -rnd.random() * step
        while x < 1420:
            sway = rnd.uniform(-4, 4)
            g = int(70 + t * 30 + rnd.uniform(-12, 12))
            col = f"rgb({max(20, g - 35)},{min(150, g + 50)},{max(25, g - 30)})"
            lw = 1.2 + t * 3.2
            stalk = f'M{x:.0f} {y:.0f} Q{x + sway:.0f} {y - h * .6:.0f} {x + sway * 1.6:.0f} {y - h:.0f}'
            out.append(f'<path d="{stalk}" stroke="{col}" stroke-width="{lw:.1f}" fill="none" stroke-linecap="round"/>')
            for k in range(3):
                ly = y - h * (.3 + .2 * k)
                d = rnd.choice([-1, 1])
                out.append(f'<path d="M{x + sway * (.3 + .2 * k):.0f} {ly:.0f} q{d * h * .32:.0f} {-h * .1:.0f} {d * h * .45:.0f} {h * .12:.0f}"'
                           f' stroke="{col}" stroke-width="{lw * .9:.1f}" fill="none" stroke-linecap="round"/>')
            if t > .55 and rnd.random() < .5:   # tassel
                out.append(f'<path d="M{x + sway * 1.6:.0f} {y - h:.0f} l-4 -10 M{x + sway * 1.6:.0f} {y - h:.0f} l4 -11"'
                           f' stroke="#D8B45A" stroke-width="{lw * .6:.1f}" stroke-linecap="round"/>')
            x += step * rnd.uniform(.7, 1.25)
    out.append('</svg>')
    return "".join(out)


def glance_band(items, updated=None):
    """One banded card: dark header + up to four stats (icon, value, label, small note)."""
    cells = "".join(
        f'<div class="fp-gl-cell"><div class="fp-gl-ic" style="background:{bg};color:{fg}">{icon(ic, 26)}</div>'
        f'<div><div class="fp-gl-val">{val}</div><div class="fp-gl-lab">{E(lab)}</div>'
        f'<div class="fp-gl-note">{note}</div></div></div>'
        for ic, val, lab, note, bg, fg in items)
    up = f'<span class="fp-gl-upd">{icon("clock", 14, "#E8EFE9")} Last updated: {E(updated)}</span>' if updated else ""
    return (f'<div class="fp-gl"><div class="fp-gl-head"><span>{icon("gauge", 20, "#F2C74E")} FieldPriority at a Glance</span>'
            f'{up}</div><div class="fp-gl-row">{cells}</div></div>')


def donut_chart(A, height=210):
    counts = risk_counts(A)
    d = pd.DataFrame([{"Risk": RISK[k]["short"], "level": k, "Fields": counts.get(k, 0)}
                      for k in RISK_ORDER if counts.get(k)])
    if d.empty:
        return None
    total = d["Fields"].sum()
    d["Share"] = d["Fields"] / total
    top = d.sort_values("Fields", ascending=False).iloc[0]
    base = alt.Chart(d).encode(theta=alt.Theta("Fields:Q", stack=True),
                               color=alt.Color("level:N", legend=None, scale=alt.Scale(
                                   domain=list(RISK), range=[RISK[k]["color"] for k in RISK])),
                               tooltip=["Risk", "Fields", alt.Tooltip("Share:Q", format=".0%")])
    ring = base.mark_arc(innerRadius=58, outerRadius=88, stroke="#FFFFFF", strokeWidth=2)
    mid = alt.Chart(pd.DataFrame({"t": [f"{top['Share']:.0%}"], "s": [top["Risk"]]}))
    t1 = mid.mark_text(font="Inter", fontSize=26, fontWeight=800, color="#1E2A24", dy=-6).encode(text="t:N")
    t2 = mid.mark_text(font="Inter", fontSize=11, color="#5E6B63", dy=16).encode(text="s:N")
    return (ring + t1 + t2).properties(height=height, width=height).configure_view(strokeWidth=0)


def donut_legend(A):
    counts = risk_counts(A)
    total = max(1, sum(counts.values()))
    return "".join(f'<div class="fp-dl"><span><i style="background:{RISK[k]["color"]}"></i>{E(RISK[k]["short"])}</span>'
                   f'<b>{counts[k]} · {counts[k] / total:.0%}</b></div>' for k in RISK_ORDER if counts.get(k))


FEATURES = [  # (title, text, link, icon, gradient)
    ("Risk Analysis", "Explore drought-risk classes, where they are and what they mean.", "/risk-analysis", "rise",
     "linear-gradient(160deg,#2E6B45 0%,#1F4D3A 70%)"),
    ("Data Quality", "See which records are complete, valid and verified in the field.", "/data-quality", "check",
     "linear-gradient(160deg,#3E8E5A 0%,#1F4D3A 75%)"),
    ("Reports", "Download PDF reports, Excel data and field boundaries.", "/reports", "doc",
     "linear-gradient(160deg,#8B6B4A 0%,#4C3A26 80%)"),
    ("Supporting farmers for a food-secure future", "Early warning so verifiers reach the right fields first.",
     "/field-map", "leaf", "linear-gradient(160deg,#C8930F 0%,#7A5300 85%)"),
]


def feature_cards():
    cards = "".join(
        f'<a class="fp-feat" href="{link(href)}" target="_self" style="background:{grad}">'
        f'<div class="fp-feat-ic">{icon(ic, 30, "#FFFFFF")}</div><div class="fp-feat-t">{E(t)}</div>'
        f'<div class="fp-feat-d">{E(d)}</div><div class="fp-feat-l">Learn more →</div></a>'
        for t, d, href, ic, grad in FEATURES)
    return f'<div class="fp-feats">{cards}</div>'


def footer():
    return (f'<div class="fp-foot"><div style="display:flex;gap:12px;align-items:center">{LOGO.format(s=42)}'
            f'<div><div style="font:800 1.15rem var(--fh);color:#fff">FieldPriority</div>'
            f'<div style="color:#CFE0D3;font-size:.8rem">Agricultural &amp; Environmental Intelligence</div></div></div>'
            f'<div class="fp-foot-tag">Understanding conditions. Supporting better decisions.</div>'
            f'<div style="color:#CFE0D3;font-size:.82rem">Zambia · maize first · all 116 districts<br>Data: ZMD · '
            f'CHIRPS · NASA POWER · MODIS · ERA5-Land · ESA WorldCereal · Sentinel-2 · geoBoundaries · KoboToolbox</div>'
            + (f'<div style="margin-top:8px">{kobo_button("Submit Field Observation", small=True)}</div>'
               if kobo_form_url() else "") + '</div>')


CSS_V2 = """
<style>
.fp-hero{min-height:400px}
.fp-hero .shade{background:linear-gradient(95deg,rgba(14,38,26,.92) 0%,rgba(18,48,32,.78) 38%,rgba(18,48,32,.15) 70%,rgba(0,0,0,0) 100%)}
.fp-hero .script{position:absolute;right:42px;bottom:36px;font:italic 600 1.5rem/1.25 Georgia,'Times New Roman',serif;
  color:#FFF8E6;text-align:right;transform:rotate(-6deg);text-shadow:0 2px 10px rgba(0,0,0,.45)}
.fp-hero .script:after{content:"";display:block;height:3px;width:120px;margin:8px 0 0 auto;background:#F2C74E;border-radius:3px}
.fp-gl{background:#fff;border:1px solid var(--line);border-radius:16px;overflow:hidden;margin:-.3rem 0 1.2rem;
  box-shadow:0 6px 20px rgba(20,35,58,.08)}
.fp-gl-head{background:var(--forest);color:#fff;display:flex;justify-content:space-between;align-items:center;gap:10px;
  padding:12px 20px;font:700 1.12rem var(--fh);flex-wrap:wrap}
.fp-gl-head > span{display:flex;gap:9px;align-items:center}
.fp-gl-upd{font:500 .8rem var(--fb);color:#E8EFE9;display:flex;gap:6px;align-items:center}
.fp-gl-row{display:grid;grid-template-columns:repeat(4,1fr)}
.fp-gl-cell{display:flex;gap:14px;align-items:flex-start;padding:18px 20px;border-right:1px solid var(--line)}
.fp-gl-cell:last-child{border-right:0}
.fp-gl-ic{width:50px;height:50px;border-radius:14px;display:grid;place-items:center;flex:none}
.fp-gl-val{font:800 1.9rem/1.05 var(--fh);color:var(--ink)}
.fp-gl-lab{font-weight:600;color:var(--ink);font-size:.92rem;margin-top:2px}
.fp-gl-note{color:var(--muted);font-size:.8rem;margin-top:4px;line-height:1.35}
.fp-dl{display:flex;justify-content:space-between;gap:10px;font-size:.88rem;padding:5px 0;border-bottom:1px dashed var(--line)}
.fp-dl:last-child{border-bottom:0}
.fp-dl i{display:inline-block;width:11px;height:11px;border-radius:50%;margin-right:8px;vertical-align:-1px}
.fp-panel-h{display:flex;justify-content:space-between;align-items:center;font:700 1.02rem var(--fh);color:var(--ink);margin-bottom:.5rem}
.fp-panel-h a{font:600 .8rem var(--fb);color:var(--leaf) !important;text-decoration:none}
.fp-feats{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:1.4rem 0 .4rem}
.fp-feat{position:relative;display:flex;flex-direction:column;gap:6px;min-height:178px;border-radius:16px;padding:18px;
  color:#fff !important;text-decoration:none !important;overflow:hidden;box-shadow:0 6px 18px rgba(20,35,58,.12)}
.fp-feat:before{content:"";position:absolute;inset:auto -30px -40px auto;width:150px;height:150px;border-radius:50%;
  background:rgba(255,255,255,.08)}
.fp-feat-ic{width:48px;height:48px;border-radius:12px;background:rgba(255,255,255,.14);display:grid;place-items:center}
.fp-feat-t{font:700 1.08rem var(--fh);margin-top:auto}
.fp-feat-d{font-size:.86rem;color:#EAF1EA;line-height:1.35}
.fp-feat-l{font-weight:600;font-size:.84rem;color:#FFE7A3}
.fp-foot{background:var(--forest);border-radius:16px;padding:20px 24px;margin-top:1.6rem;display:flex;
  justify-content:space-between;align-items:center;gap:18px;flex-wrap:wrap}
.fp-foot-tag{font:italic 600 1.08rem var(--fh);color:#F2C74E}
/* field profile header band */
.fp-ph{background:var(--forest);border-radius:18px;padding:22px 26px;color:#fff;display:flex;gap:18px;align-items:center;
  flex-wrap:wrap;margin-bottom:1rem;box-shadow:0 8px 24px rgba(20,35,58,.14)}
.fp-ph h1{color:#fff !important;margin:0;font-size:2rem}
.fp-ph .meta{display:flex;gap:16px;flex-wrap:wrap;color:#DDE8DF;font-size:.9rem;margin-top:6px}
.fp-ph .meta span{display:flex;gap:6px;align-items:center}
.fp-rc{border-radius:16px;padding:16px 18px;display:flex;gap:14px;align-items:center}
.fp-rc .big{font:800 1.6rem var(--fh)}
.fp-ind{display:grid;grid-template-columns:1fr auto;gap:4px 12px;align-items:center;font-size:.9rem;padding:7px 0;
  border-bottom:1px solid var(--line)}
.fp-ind:last-child{border-bottom:0}
.fp-act-list li{margin:6px 0;list-style:none;padding-left:26px;position:relative}
.fp-act-list li:before{content:"";position:absolute;left:0;top:3px;width:16px;height:16px;border-radius:50%;
  background:#2E8B57 url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'><path d='m6 12.5 4 4 8-9' stroke='white' stroke-width='3' fill='none' stroke-linecap='round'/></svg>") center/12px no-repeat}
@media (max-width: 900px){
  .fp-gl-row{grid-template-columns:repeat(2,1fr)} .fp-gl-cell:nth-child(2){border-right:0}
  .fp-gl-cell{border-bottom:1px solid var(--line)}
  .fp-feats{grid-template-columns:repeat(2,1fr)}
  .fp-hero .script{display:none}
}
@media (max-width: 560px){ .fp-gl-row,.fp-feats{grid-template-columns:1fr} .fp-gl-cell{border-right:0} }
</style>
"""


# ---------------------------------------------------------------- Kobo photos (shown only with a Kobo token)
def kobo_token():
    tok = os.environ.get("KOBO_TOKEN")
    if tok:
        return tok
    try:
        if "KOBO_TOKEN" in st.secrets:
            return st.secrets["KOBO_TOKEN"]
    except Exception:
        pass
    try:
        from fieldpriority.ingest.kobo import load_dotenv
        load_dotenv()
        return os.environ.get("KOBO_TOKEN")
    except Exception:
        return None


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def kobo_photo(url):
    """Download one Kobo attachment with the API token (server side, never sent to the browser)."""
    import urllib.request
    if not url:
        return None
    got = _offline.cached_photo(url)          # saved copy first (prepare_offline.bat, or an earlier view)
    if got or OFFLINE:
        return got
    tok = kobo_token()
    if not tok:
        return None
    try:
        req = urllib.request.Request(url, headers={"Authorization": f"Token {tok}", "User-Agent": "FieldPriority"})
        with urllib.request.urlopen(req, timeout=20) as r:
            data = r.read()
        _offline.save_photo(url, data)
        return data
    except Exception:
        return None


# ================================================================ Zambia intelligence (district layers, all pilots)
from fieldpriority.evidence import DATA_TYPES                       # noqa: E402
from fieldpriority.national import load_national_config, MON as NMON  # noqa: E402
from fieldpriority.national.interpret import (CLASS_COLORS, LEVELS, STATUS, STRESS_ORDER, interpret)  # noqa: E402

NCFG = load_national_config()


@st.cache_data(ttl=300, show_spinner="Loading district layers")
def _load_national(source, out_dir=None):
    from fieldpriority.national.store import load
    return load(source, out_dir=out_dir)


def national():
    """District layers (NationalData). Same source rule as the pilot data (Firebase online, local files on a PC)."""
    try:
        return _load_national(st.session_state.get("source", os.environ.get("FIELDPRIORITY_SOURCE", "auto")),
                              os.environ.get("FIELDPRIORITY_NATIONAL_OUTPUTS"))
    except Exception as e:
        from fieldpriority.national.store import NationalData, _districts
        return NationalData(_districts(NCFG), source_note=f"District layers could not be loaded ({e})")


def pilot_data(p):
    """Data of one pilot area (cached), or None when it has no outputs yet."""
    c = _cfg(p)
    env_out = os.environ.get("FIELDPRIORITY_OUTPUTS")
    outputs = env_out.replace("{pilot}", p) if env_out else str(ROOT / c["paths"]["output_dir"])
    try:
        return _load(st.session_state.get("source", os.environ.get("FIELDPRIORITY_SOURCE", "auto")), outputs, None,
                     (c.get("firebase") or {}).get("collection_prefix", ""))
    except Exception:
        return None


def monitored_fields(nd=None, everyone=False):
    """Assessed fields of the signed-in account's pilot areas (everyone=True: all areas, for counts only), with
    their district (from the boundary file) and visits. Signed out: no fields."""
    import geopandas as gpd
    rows = []
    for p in (PILOTS if everyone else user_pilots()):
        d = pilot_data(p)
        if d is None or d.assessments is None or d.assessments.empty:
            continue
        stat = status_by_field(d)
        v = visits(d)
        geo = d.fields.set_index("Field_ID")
        for r in d.assessments.to_dict("records"):
            fid = r["field_id"]
            if fid not in geo.index:
                continue
            pt = geo.loc[fid].geometry.representative_point()
            mine = v[v["field_id_pipeline"] == fid] if len(v) and "field_id_pipeline" in v else pd.DataFrame()
            approved = int(mine["analysis_eligible"].fillna(False).astype(bool).sum()) if len(mine) else 0
            pics = [("Crop" if a.get("media_file_basename") == x.get("crop_photo") else
                     "Soil" if a.get("media_file_basename") == x.get("soil_photo") else "Photo", x.get("visit_date"), a)
                    for x in (mine.to_dict("records") if len(mine) else []) for a in attachments(x)]
            photos = len(pics)
            last = (mine.sort_values("visit_date").iloc[-1].to_dict() if len(mine) and "visit_date" in mine else {})
            crop = str(geo.loc[fid].get("crop") or "").strip() if "crop" in geo.columns else ""
            rows.append({"crop": (crop or _cfg(p).get("crop", "maize") or "maize").title(),
                         "last_visit": last.get("visit_date"), "last_stage": last.get("maize_stage"),
                         "last_verdict": last.get("field_verdict"), "last_cause": last.get("main_cause"),"pilot": p, "pilot_short": _cfg(p)["pilot_short"], "field_id": fid, "lat": pt.y,
                         "lon": pt.x, "risk_level": r["risk_level"], "outcome": r["outcome"],
                         "data_confidence": r["data_confidence"], "verification": stat.get(fid, "Not yet verified"),
                         "visits": len(mine), "approved": approved, "photos": photos, "pics": pics, "period": r.get("period"),
                         "area_ha": float(geo.loc[fid, "area_ha"]), "growth_stage": r.get("growth_stage_label"),
                         "water_deficit": r.get("water_deficit"), "vegetation_decline": r.get("vegetation_decline")})
    f = pd.DataFrame(rows)
    if f.empty:
        return f.assign(district_id=[], district=[])
    nd = nd or national()
    g = gpd.GeoDataFrame(f, geometry=gpd.points_from_xy(f["lon"], f["lat"]), crs=4326)
    j = gpd.sjoin(g, nd.districts[["district_id", "district", "province", "geometry"]], how="left", predicate="within")
    return pd.DataFrame(j.drop(columns=["geometry", "index_right"], errors="ignore"))


def location_records(nd, district_id):
    """{indicator: record} for one district."""
    if not nd.available:
        return {}
    t = nd.indicators[nd.indicators["location_id"] == district_id]
    return {r["indicator"]: {k: (None if (isinstance(v, float) and v != v) else v) for k, v in r.items()}
            for r in t.to_dict("records")}


def period_of(nd):
    return nd.report.get("period_label") or "the latest period"


TYPE_STYLE = {"measurement": ("#E3EEF9", "#1F4E80"), "satellite_estimate": ("#E3EEF9", "#1F4E80"),
              "model_output": ("#FFF1D6", "#7A5300"), "field_observation": ("#EDE6F7", "#4B2F7A"),
              "derived": ("#E8F1EA", "#1F4D3A"), "official": ("#FCE4DE", "#8A2A1C")}


def type_tag(data_type):
    bg, fg = TYPE_STYLE.get(data_type, ("#EEE", "#333"))
    lab = DATA_TYPES.get(data_type, (data_type, ""))[0]
    return f'<span class="fp-src" style="background:{bg};color:{fg}">{E(lab)}</span>'


def conf_tag(conf):
    col = {"High": "#2E8B57", "Medium": "#C8930F", "Low": "#B9342B"}.get(conf, "#7A8590")
    return (f'<span class="fp-src" style="background:{col}1A;color:{col}">Confidence: {E(conf)}</span>'
            if conf else "")


def evidence_line(rec):
    """Source · period · resolution · coverage, for under a value."""
    if not rec or rec.get("status") != "ok":
        return E((rec or {}).get("quality_note") or "Not yet available")
    parts = [rec.get("source"), rec.get("period_label") and f"Period: {rec['period_label']}",
             rec.get("resolution"), rec.get("coverage")]
    if rec.get("baseline"):
        parts.append("Normal = " + rec["baseline"])
    return E(" · ".join(str(x) for x in parts if x))


def class_chip(cls):
    if not cls:
        return ""
    col = CLASS_COLORS.get(cls, "#E9E4D4")
    dark = col in ("#E9E4D4", "#EBC46A", "#9CC79A", "#FFF3C4", "#FBD98A", "#F1F5E6", "#CFE3B0")
    return (f'<span style="display:inline-block;padding:2px 9px;border-radius:999px;font:600 .78rem Inter,sans-serif;'
            f'background:{col};color:{"#1E2A24" if dark else "#fff"}">{E(cls)}</span>')


# ---------------------------------------------------------------- map layers
SOLAR_COLORS = ["#FFF3C4", "#FBD98A", "#F5B94F", "#E7932A", "#C96F12"]
MAIZE_BINS, MAIZE_COLORS = [0, 2, 5, 10, 20], ["#F1F5E6", "#CFE3B0", "#9CC77A", "#5E9E4B", "#2E6B35"]
LAYERS = {
    "rainfall": {"label": "Rainfall anomaly", "short": "Rainfall", "ind": "rainfall_anomaly_pct", "icon": "drop",
                 "classes": ["Very dry", "Drier than normal", "Near normal", "Wetter than normal"],
                 "what": "Season-to-date rainfall compared with the same months of the 10 previous seasons."},
    "water": {"label": "Water stress", "short": "Water stress", "ind": "water_stress", "icon": "drop", "classes": STRESS_ORDER,
              "what": "Where water-related stress may be emerging. Until soil moisture is imported this is an "
                      "indication from rainfall and temperature only (low confidence)."},
    "temperature": {"label": "Temperature", "short": "Temperature", "ind": "temperature_deviation", "icon": "gauge",
                    "classes": ["Much warmer than normal", "Warmer than normal", "Near normal", "Cooler than normal"],
                    "what": "Mean temperature compared with the same months of the 10 previous seasons."},
    "vegetation": {"label": "Vegetation condition", "short": "Vegetation", "ind": "vegetation_anomaly_pct", "icon": "leaf",
                   "classes": ["Well below normal", "Below normal", "Near or above normal"],
                   "what": "Satellite greenness (MODIS NDVI) of cropland compared with earlier seasons."},
    "maize": {"label": "Maize-growing areas", "short": "Maize areas", "ind": "maize_share_pct", "icon": "field",
              "what": "Share of each district's land mapped as maize (ESA WorldCereal 2021)."},
    "solar": {"label": "Solar potential", "short": "Solar", "ind": "solar_resource", "icon": "sun",
              "what": "Average daily solar energy reaching the ground (resource only, not system suitability)."},
}
from fieldpriority.national.zones import REGIONS as ZONES  # noqa: E402
for _k, _r in ZONES.items():
    CLASS_COLORS.setdefault(_k, _r["color"])
LAYERS["zones"] = {"label": "Agricultural zones", "short": "Zones", "ind": "agro_zone", "icon": "field",
                   "classes": ["I", "II", "III"],
                   "labels": {k: f"{ZONES[k]['name']}: {ZONES[k]['rain']}" for k in ZONES},
                   "what": "Agro-ecological regions. Until the official map is loaded they are approximated from "
                           "rainfall: Region I below 800 mm a year, II 800 to 1,000 mm, III above 1,000 mm."}
OVERALL = [STATUS[k][0] for k in ("priority", "attention", "watch", "stable", "insufficient")]
for _k, (_lab, _col) in STATUS.items():
    CLASS_COLORS[_lab] = _col
LAYERS["overall"] = {"label": "Agricultural condition", "short": "Condition", "ind": "_overall", "icon": "gauge",
                     "classes": OVERALL[:4],
                     "what": "Crop greenness, soil water, rainfall and temperature read together: the platform's "
                             "assessment of each district."}
# solar is kept in the data pipeline but is not part of the intelligence experience
LAYERS = {k: LAYERS[k] for k in ["overall", "vegetation", "water", "rainfall", "temperature", "zones", "maize"]}
HOME_LAYERS = ["overall", "vegetation", "water", "rainfall", "temperature"]
ICONS["sun"] = ('<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2'
                'M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>')
ICONS["thermo"] = '<path d="M14 14.8V5a2 2 0 0 0-4 0v9.8a4 4 0 1 0 4 0Z"/><path d="M12 9v7"/>'


_LEVEL_CACHE = {}


def district_levels(nd):
    """{district_id: interpretation} for every district (all layers together), computed once per data build."""
    k = (str(nd.report.get("built_at")), len(nd.indicators) if nd.available else 0)
    if k not in _LEVEL_CACHE:
        out = {}
        if nd.available:
            for d in nd.districts.itertuples():
                out[d.district_id] = interpret(d.district, location_records(nd, d.district_id), NCFG["classes"])
        _LEVEL_CACHE.clear()
        _LEVEL_CACHE[k] = out
    return _LEVEL_CACHE[k]


def layer_table(nd, key):
    """Indicator rows behind a map layer; the overall layer is built from the interpretation of each district."""
    if not nd.available:
        return pd.DataFrame()
    if key != "overall":
        return nd.indicators[nd.indicators["indicator"] == LAYERS[key]["ind"]]
    D = nd.districts.set_index("district_id")
    rows = []
    for did, it in district_levels(nd).items():
        lab = STATUS[it["status"]][0]
        rows.append({"location_id": did, "location_name": D.loc[did, "district"], "province": D.loc[did, "province"],
                     "status": "ok" if it["level"] != "unknown" else "pending", "class": lab,
                     "value": {"priority": 0, "attention": 1, "watch": 2, "stable": 3}.get(it["status"], 4),
                     "display": lab if it["status"] in ("stable", "priority") else f"{lab}: {it['short']}".replace(
                         "Watch: Early sign: ", "Watch: "),
                     "data_type": "derived", "confidence": "Medium", "source": "FieldPriority, all layers together",
                     "source_url": "", "period_label": period_of(nd), "resolution": "District", "coverage": "District",
                     "baseline": "", "quality_note": "", "method": "Rules in src/fieldpriority/national/interpret.py"})
    return pd.DataFrame(rows)


def layer_values(nd, key):
    """district_id -> (color, display text, class/value). Pending districts are grey."""
    L = LAYERS[key]
    t = layer_table(nd, key)
    out = {}
    vals = pd.to_numeric(t[t["status"] == "ok"]["value"], errors="coerce").dropna() if len(t) else pd.Series(dtype=float)
    q = list(np.quantile(vals, [0.2, 0.4, 0.6, 0.8])) if key == "solar" and len(vals) else []
    for r in t.to_dict("records"):
        if r.get("status") != "ok":
            out[r["location_id"]] = ("#D9D9D9", "Not yet available", None)
            continue
        if "classes" in L:
            out[r["location_id"]] = (CLASS_COLORS.get(r.get("class"), "#E9E4D4"), r.get("display"), r.get("class"))
        elif key == "solar":
            i = int(np.searchsorted(q, float(r["value"]), side="right"))
            out[r["location_id"]] = (SOLAR_COLORS[i], r.get("display"), float(r["value"]))
        else:
            i = max(0, int(np.searchsorted(MAIZE_BINS, float(r["value"]), side="right")) - 1)
            out[r["location_id"]] = (MAIZE_COLORS[i], r.get("display"), float(r["value"]))
    return out, q


def layer_available(nd, key):
    t = layer_table(nd, key)
    return bool(len(t) and (t["status"] == "ok").any())


def layer_legend(key, q=None):
    L = LAYERS[key]
    if "classes" in L:
        items = [(CLASS_COLORS[c], (L.get("labels") or {}).get(c, c)) for c in L["classes"]]
    elif key == "solar":
        edges = [f"{x:.2f}" for x in (q or [])]
        labs = ([f"< {edges[0]}"] + [f"{a} to {b}" for a, b in zip(edges, edges[1:])] + [f"> {edges[-1]}"]) if edges else []
        items = list(zip(SOLAR_COLORS, [l + " kWh/m²/day" for l in labs]))
    else:
        labs = [f"{a} to {b}%" for a, b in zip(MAIZE_BINS, MAIZE_BINS[1:])] + [f"over {MAIZE_BINS[-1]}%"]
        items = list(zip(MAIZE_COLORS, labs))
    items.append(("#D9D9D9", "Not yet available"))
    return items


def build_zambia_map(nd, key, fields=None, focus=None, show_fields=True, height=520):
    """Districts coloured by one indicator layer, plus the monitored fields and field observations on top."""
    import json as _json
    from branca.element import Element
    vals, q = layer_values(nd, key)
    g = nd.districts.copy()
    g["color"] = g["district_id"].map(lambda d: vals.get(d, ("#D9D9D9",))[0])
    g["value"] = g["district_id"].map(lambda d: vals.get(d, (None, "Not yet available"))[1] or "")
    g["pop"] = [
        f'<div style="font:13px Inter,sans-serif;min-width:200px"><div style="font-weight:700;font-size:15px">'
        f'{E(r.district)}</div><div style="color:#5E6B63">{E(r.province)} Province</div>'
        f'<div style="margin:6px 0">{E(LAYERS[key]["label"])}: <b>{E(str(r.value))}</b></div>'
        f'<a href="{link("/location", district=r.district_id)}" target="_blank" rel="noopener" style="display:inline-block;'
        f'background:#1F4D3A;color:#fff;padding:6px 11px;border-radius:8px;text-decoration:none">Open location report ↗</a></div>'
        for r in g.itertuples()]
    m = folium.Map(location=[-13.4, 27.8], zoom_start=6, tiles=None, control_scale=True, max_zoom=18,
                   min_zoom=5)
    folium.TileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",
                     attr="Base map: Esri, HERE, Garmin, © OpenStreetMap contributors", name="Light map",
                     max_native_zoom=16, max_zoom=18).add_to(m)
    folium.TileLayer(ESRI, attr="Imagery: Esri, Maxar, Earthstar Geographics", name="Satellite", max_native_zoom=17,
                     max_zoom=18).add_to(m)
    zone_mode = key == "zones" and getattr(nd, "zones", None) is not None and len(nd.zones)
    if zone_mode:      # the zones themselves (they cross district borders), district outlines on top
        zg = nd.zones.copy()
        zg["color"] = zg["region"].map(lambda r: ZONES.get(r, {}).get("color", "#D9D9D9"))
        zg["label"] = zg["region"].map(lambda r: f"{ZONES[r]['name']} · {ZONES[r]['short']} · {ZONES[r]['rain']}")
        folium.GeoJson(_json.loads(zg[["region", "label", "color", "geometry"]].to_json()), name="Agricultural zones",
                       style_function=lambda f: {"fillColor": f["properties"]["color"], "color": "#8B6B4A",
                                                 "weight": 0.6, "fillOpacity": 0.85},
                       tooltip=folium.GeoJsonTooltip(["label"], labels=False)).add_to(m)
    focus = [focus] if isinstance(focus, str) else (list(focus) if focus is not None else None)
    g["sel"] = g["district_id"].isin(focus) if focus is not None else True
    fc = _json.loads(g[["district_id", "district", "province", "value", "color", "pop", "sel", "geometry"]].to_json())

    def _style(f):
        if zone_mode:
            return {"fillOpacity": 0.0, "color": "#1F4D3A", "weight": 0.7}
        if focus is None:
            return {"fillColor": f["properties"]["color"], "color": "#FFFFFF", "weight": 0.8, "fillOpacity": 0.82}
        # report map: colour only the selected area, see-through, so the land underneath stays visible
        if f["properties"]["sel"]:
            return {"fillColor": f["properties"]["color"], "color": "#FFFFFF", "weight": 0.6, "fillOpacity": 0.45}
        return {"fillOpacity": 0.0, "color": "#FFFFFF", "weight": 0.8, "opacity": 0.7}

    gj = folium.GeoJson(
        fc, name="Districts" if zone_mode else LAYERS[key]["label"], style_function=_style,
        highlight_function=lambda f: {"weight": 2.5, "color": "#1F4D3A", "fillOpacity": 0.9},
        tooltip=folium.GeoJsonTooltip(["district", "value"], aliases=["District", LAYERS[key]["label"]], sticky=True),
        popup=folium.GeoJsonPopup(["pop"], labels=False))
    gj.add_to(m)
    if focus is not None:       # outline readable on both the light map and satellite: white halo, gold line
        fg = _json.loads(g[g["district_id"].isin(focus)].dissolve()[["geometry"]].to_json())
        folium.GeoJson(fg, name="Selected area (halo)", control=False,
                       style_function=lambda f: {"fill": False, "color": "#FFFFFF", "weight": 6, "opacity": 0.9}).add_to(m)
        folium.GeoJson(fg, name="Selected area", control=False,
                       style_function=lambda f: {"fill": False, "color": "#D9A21B", "weight": 3}).add_to(m)
    if show_fields and fields is not None and len(fields):
        grp = folium.FeatureGroup(name="Monitored fields (risk class)", show=True)
        obs = folium.FeatureGroup(name="Field observations (KoboToolbox)", show=True)
        for r in fields.itertuples():
            rk = RISK.get(r.risk_level, {"color": "#7A8590", "short": r.risk_level})
            pop = (f'<div style="font:13px Inter,sans-serif;min-width:200px"><b>Field {E(str(r.field_id))}</b> · '
                   f'{E(r.pilot_short)} pilot<div style="margin:5px 0">{badge(r.risk_level)}</div>'
                   f'<div style="color:#5E6B63">{E(str(r.verification))} · {r.visits} visit(s), {r.photos} photo(s)</div>'
                   f'<a href="{link("/assessments", area=r.pilot, field=str(r.field_id))}" target="_blank" rel="noopener" '
                   f'style="display:inline-block;margin-top:6px;background:#1F4D3A;color:#fff;padding:5px 10px;'
                   f'border-radius:8px;text-decoration:none">Open field profile ↗</a></div>')
            folium.CircleMarker([r.lat, r.lon], radius=7, color="#FFFFFF", weight=2, fill=True, fill_color=rk["color"],
                                fill_opacity=1, tooltip=f"Field {r.field_id} · {rk['short']}",
                                popup=folium.Popup(pop, max_width=280)).add_to(grp)
            if r.visits:
                folium.Marker([r.lat, r.lon], tooltip=f"{r.visits} field visit(s), {r.approved} approved",
                              icon=folium.DivIcon(icon_size=(22, 22), icon_anchor=(-4, 24), html=(
                                  f'<div style="width:22px;height:22px;border-radius:6px;background:#6A4C93;color:#fff;'
                                  f'font:700 11px/22px Inter,sans-serif;text-align:center;border:1.5px solid #fff;'
                                  f'box-shadow:0 1px 3px rgba(0,0,0,.4)">{r.visits}</div>'))).add_to(obs)
        grp.add_to(m)
        obs.add_to(m)
    folium.LayerControl(position="topright", collapsed=True).add_to(m)
    rows = "".join(f'<div style="display:flex;align-items:center;gap:7px;margin:2px 0"><span style="width:13px;height:13px;'
                   f'border-radius:3px;background:{c};border:1px solid #CFC6B2"></span>{E(t)}</div>'
                   for c, t in layer_legend(key, q))
    extra = ('<div style="margin-top:5px;border-top:1px solid #E3DDCF;padding-top:4px"><span style="display:inline-block;'
             'width:11px;height:11px;border-radius:50%;background:#2E8B57;border:2px solid #fff;box-shadow:0 0 0 1px #999;'
             'vertical-align:-1px"></span> Monitored field &nbsp;<span style="display:inline-block;width:12px;height:12px;'
             'border-radius:3px;background:#6A4C93;vertical-align:-1px"></span> Field visits</div>') if show_fields else ""
    m.get_root().html.add_child(Element(
        f'<div style="position:absolute;left:10px;bottom:24px;z-index:999;background:rgba(255,255,255,.95);'
        f'border-radius:10px;padding:8px 11px;font:12px Inter,Segoe UI,sans-serif;color:#1E2A24;max-width:230px;'
        f'box-shadow:0 2px 8px rgba(0,0,0,.25)"><b>{E(LAYERS[key]["label"])}</b>{rows}{extra}</div>'))
    if focus is not None:
        b = g[g["district_id"].isin(focus)].total_bounds
        m.fit_bounds([[b[1], b[0]], [b[3], b[2]]], padding=(20, 20))
    else:
        m.fit_bounds([[-18.1, 21.99], [-8.2, 33.7]], padding=(6, 6))
    return m


# ---------------------------------------------------------------- headline numbers (live data only)
def national_summary(nd, fields):
    """The six intelligence indicators for the homepage: value, label, note, evidence tags. No invented figures."""
    I = nd.indicators if nd.available else pd.DataFrame(columns=["indicator", "status", "value", "class"])
    per = period_of(nd)

    def ok(ind):
        t = I[(I["indicator"] == ind) & (I["status"] == "ok")]
        return t.assign(value=pd.to_numeric(t["value"], errors="coerce")) if ind != "water_stress" else t

    n = len(nd.districts)
    out = []
    # crop condition
    veg = ok("vegetation_anomaly_pct")
    nf = len(fields)
    stress = int(fields["risk_level"].isin(["High", "Moderate", "Not attributed"]).sum()) if nf else 0
    watch = int((fields["risk_level"] == "Watch").sum()) if nf else 0
    if len(veg):
        below = int(veg["class"].isin(["Below normal", "Well below normal"]).sum())
        out.append(("leaf", f"{below}", f"of {len(veg)} districts with vegetation below normal", "Crop & vegetation",
                    f"Cropland greenness below normal, {per}. Monitored fields with a crop-stress flag: {stress} of {nf}.",
                    "satellite_estimate", "Medium"))
    else:
        out.append(("leaf", f"{stress}" if nf else "–", f"of {nf} monitored fields with crop stress" if nf
                    else "No fields yet", "Crop & vegetation",
                    f"High, Moderate or cause-uncertain from Sentinel-2 greenness and the drought rules. {watch} on "
                    "Watch (water shortage, crop not yet reacting). District greenness layer not yet imported.",
                    "derived", "Low"))
    rain = ok("rainfall_anomaly_pct")
    if len(rain):
        dry = int(rain["class"].isin(["Very dry", "Drier than normal"]).sum())
        wet = int((rain["class"] == "Wetter than normal").sum())
        out.append(("drop", f"{dry}", f"of {len(rain)} districts drier than normal", "Rainfall",
                    f"Season to date ({per}) vs the 10 previous seasons. Median {rain['value'].median():+.0f}%; "
                    f"{wet} wetter than normal.", "satellite_estimate", "High"))
    else:
        out.append(("drop", "–", "Not yet available", "Rainfall", "Run the monthly update.", "derived", ""))
    tmp = ok("temperature_deviation")
    if len(tmp):
        warm = int(tmp["class"].isin(["Warmer than normal", "Much warmer than normal"]).sum())
        out.append(("thermo", f"{warm}", f"of {len(tmp)} districts warmer than normal", "Temperature",
                    f"Median deviation {tmp['value'].median():+.1f} °C, {per}.", "model_output", "Medium"))
    else:
        out.append(("thermo", "–", "Not yet available", "Temperature", "Run the monthly update.", "derived", ""))
    ws = ok("water_stress")
    if len(ws):
        k = int(ws["class"].isin(["Likely water stress", "Possible water stress"]).sum())
        early = int((ws["class"] == "Early sign: rainfall deficit").sum())
        lowc = (ws["confidence"] == "Low").all()
        out.append(("drop", f"{k}", "districts with possible water stress", "Water stress",
                    f"{early} more with an early rainfall-deficit sign. "
                    + ("Rainfall and temperature only; soil moisture not yet included." if lowc else
                       "Soil moisture and rainfall."), "derived", "Low" if lowc else "Medium"))
    else:
        out.append(("drop", "–", "Not yet available", "Water stress", "", "derived", ""))
    vis = int(fields["visits"].sum()) if nf else 0
    appr = int(fields["approved"].sum()) if nf else 0
    ph = int(fields["photos"].sum()) if nf else 0
    out.append(("camera", f"{appr}", "verified field reports", "Local observations",
                f"{vis} real field visit(s) received through KoboToolbox, {ph} photo(s), across "
                f"{fields[fields['visits'] > 0]['pilot'].nunique() if nf else 0} pilot area(s).", "field_observation", "High" if appr else "Low"))
    return out


def intel_summary_html(items, updated=None):
    cells = "".join(
        f'<div class="fp-in-cell" title="{E(note)}{E(" · Confidence: " + conf) if conf else ""}">'
        f'<div class="fp-in-top"><span class="fp-in-ic">{icon(ic, 20)}</span>'
        f'<span class="fp-in-t">{E(title)}</span></div><div class="fp-in-v">{E(v)}</div>'
        f'<div class="fp-in-l">{E(lab)}</div><div style="margin-top:6px">{type_tag(dt_)}</div></div>'
        for ic, v, lab, title, note, dt_, conf in items)
    up = f'<span class="fp-gl-upd">{icon("clock", 14, "#E8EFE9")} {E(updated)}</span>' if updated else ""
    return (f'<div class="fp-gl"><div class="fp-gl-head"><span>{icon("gauge", 20, "#F2C74E")} Agricultural '
            f'Intelligence Summary · Zambia</span>{up}</div><div class="fp-in-row">{cells}</div></div>')


CSS_V3 = """
<style>
.fp-in-row{display:grid;grid-template-columns:repeat(6,1fr)}
.fp-in-cell{padding:16px 16px 14px;border-right:1px solid var(--line);display:flex;flex-direction:column}
.fp-in-cell:last-child{border-right:0}
.fp-in-top{display:flex;gap:8px;align-items:center;color:var(--forest);font:700 .86rem var(--fh)}
.fp-in-ic{width:32px;height:32px;border-radius:9px;display:grid;place-items:center;background:#E8F1EA;flex:none}
.fp-in-v{font:800 1.9rem/1.05 var(--fh);color:var(--ink);margin-top:10px}
.fp-in-l{font-weight:600;color:var(--ink);font-size:.86rem;margin-top:2px}
.fp-in-n{color:var(--muted);font-size:.78rem;margin-top:5px;line-height:1.35;flex:1}
.fp-in-cell .fp-src{margin:3px 4px 0 0}
.fp-hero .chips{display:flex;gap:8px;flex-wrap:wrap;margin:-.2rem 0 1rem}
.fp-hero .chip{font:700 .72rem var(--fb);letter-spacing:.1em;color:#1E2A24;background:#F2C74E;padding:4px 10px;border-radius:6px}
.fp-hero .chip.o{background:transparent;color:#F2C74E;border:1px solid rgba(242,199,78,.6)}
.fp-hero .explore{color:#E8EFE9;font-size:.92rem;margin:0 0 1.1rem}
.fp-hero .explore b{color:#fff}
.fp-layers{display:grid;grid-template-columns:repeat(6,1fr);gap:10px;margin:.6rem 0}
.fp-layer{background:#fff;border:1px solid var(--line);border-radius:14px;padding:12px 13px;font-size:.84rem}
.fp-layer .h{display:flex;gap:7px;align-items:center;font:700 .9rem var(--fh);color:var(--ink)}
.fp-layer .s{margin-top:6px;color:var(--muted);line-height:1.35}
.fp-layer .st{display:inline-block;margin-top:7px;font:600 .7rem var(--fb);text-transform:uppercase;letter-spacing:.06em;
  padding:2px 7px;border-radius:6px}
.fp-flow{display:grid;grid-template-columns:1fr auto 1fr auto 1fr;gap:10px;align-items:center;margin:.4rem 0 .2rem}
.fp-flow .b{background:var(--forest);color:#fff;border-radius:12px;padding:10px 14px;font-size:.84rem}
.fp-flow .b b{display:block;font:700 .92rem var(--fh);color:#F2C74E}
.fp-flow .a{color:var(--forest);font-size:1.4rem;font-weight:700}
.fp-ident{display:grid;grid-template-columns:1.5fr 1fr;gap:0;border-radius:18px;overflow:hidden;margin:1.4rem 0 .4rem;
  box-shadow:0 8px 24px rgba(20,35,58,.12)}
.fp-ident .l{background:var(--forest);color:#E8EFE9;padding:22px 26px}
.fp-ident h2{color:#fff !important;font:800 1.45rem/1.2 var(--fh);margin:.2rem 0 .6rem}
.fp-ident p{margin:0 0 1rem;line-height:1.5}
.fp-ident .foc{display:flex;gap:10px;flex-wrap:wrap}
.fp-ident .foc span{background:rgba(255,255,255,.08);border:1px solid rgba(242,199,78,.45);border-radius:10px;padding:7px 12px;
  font-size:.9rem;color:#fff}
.fp-ident .foc b{display:block;font:600 .68rem var(--fb);letter-spacing:.08em;text-transform:uppercase;color:#F2C74E}
.fp-ident .r{background:#fff;padding:20px 24px;border:1px solid var(--line);border-left:0}
.fp-ident .r .h{font:700 1rem var(--fh);color:var(--ink);margin-bottom:.5rem}
@media (max-width: 800px){ .fp-ident{grid-template-columns:1fr} .fp-ident .r{border-left:1px solid var(--line)} }
.fp-story{background:linear-gradient(120deg,#FFF8E6,#F6E7B8);border:1px solid #F0DCA4;border-radius:16px;padding:18px 22px;
  color:#4A3A10;margin-top:1.2rem}
.fp-story h3{margin:0 0 .3rem;color:#1E2A24}
.fp-rep-h{font:800 1.3rem var(--fh);color:var(--ink);margin:1.8rem 0 .5rem;display:flex;gap:10px;align-items:center}
.fp-rep-h .n{width:30px;height:30px;border-radius:9px;background:var(--forest);color:#F2C74E;display:grid;place-items:center;
  font-size:.95rem}
.fp-ic{background:#fff;border:1px solid var(--line);border-radius:14px;padding:14px 16px;height:100%}
.fp-ic .t{display:flex;justify-content:space-between;gap:8px;align-items:center;font:700 .92rem var(--fh);color:var(--ink)}
.fp-ic .v{font:800 1.45rem var(--fh);color:var(--ink);margin:6px 0 4px}
.fp-ic .e{color:var(--muted);font-size:.78rem;line-height:1.35;margin-top:6px}
.fp-interp{background:#fff;border-left:5px solid var(--forest);border-radius:12px;padding:14px 18px;font-size:.98rem;line-height:1.55}
.fp-att li{margin:6px 0}
@media (max-width: 1100px){ .fp-in-row,.fp-layers{grid-template-columns:repeat(3,1fr)} .fp-in-cell:nth-child(3){border-right:0}
  .fp-in-cell{border-bottom:1px solid var(--line)} }
@media (max-width: 640px){ .fp-in-row,.fp-layers{grid-template-columns:1fr 1fr} .fp-in-cell{border-right:0}
  .fp-flow{grid-template-columns:1fr} .fp-flow .a{transform:rotate(90deg);justify-self:center} }
</style>
"""


# ---------------------------------------------------------------- official weather information (ZMD)
from fieldpriority import zmd as ZMD  # noqa: E402
ICONS["storm"] = ('<path d="M7 17a5 5 0 1 1 .9-9.9A6 6 0 0 1 19 9a4 4 0 0 1-1 7.9"/><path d="m13 12-3 5h4l-3 5"/>')


@st.cache_data(ttl=1800, show_spinner="Checking ZMD weather warnings")
def _zmd_alert_doc():
    doc, ok, err = ZMD.get_alerts(live=True, timeout=6)
    return doc, ok, err, dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def zmd_alerts(nd=None):
    """(table of alerts with matched districts, status dict). Live ZMD feed, else the saved copy."""
    doc, ok, err, checked = _zmd_alert_doc()
    nd = nd or national()
    T = ZMD.alerts_table(doc, nd.districts)
    return T, {"live": ok, "error": err, "checked": checked, "retrieved": (doc or {}).get("retrieved_at"),
               "have": doc is not None}


@st.cache_data(ttl=3600, show_spinner=False)
def _zmd_seasonal(_key):
    spec = ZMD.load_seasonal()
    D = national().districts
    if not spec:
        return None, pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    return (spec, ZMD.seasonal_by_district(spec, D), ZMD.timing_by_district(spec, D, "onset"),
            ZMD.timing_by_district(spec, D, "cessation"))


def zmd_seasonal():
    """(spec, per-district categories, onset, cessation) of the ZMD seasonal forecast."""
    f = ZMD.SEASONAL_FILE
    return _zmd_seasonal(f"{f.stat().st_mtime if f.exists() else 0}")


def zmd_time(t, with_time=True):
    t = ZMD.parse_time(t) if isinstance(t, str) else t
    if t is None or (isinstance(t, float) and t != t):
        return "–"
    t = t.astimezone(dt.timezone(dt.timedelta(hours=2)))
    return t.strftime("%d %b %Y, %H:%M" if with_time else "%d %b %Y").lstrip("0")


def zmd_cat_chip(code, text=None, small=False):
    if not code or code not in ZMD.CATEGORIES:
        return (f'<span class="fp-zc" style="background:#EEE;color:#5E6B63">{E(text or "Not stated")}</span>')
    _, lab, col = ZMD.CATEGORIES[code]
    dark = code in ("normal_to_below", "normal", "normal_to_above")
    return (f'<span class="fp-zc{" s" if small else ""}" style="background:{col};color:{"#1E2A24" if dark else "#fff"}">'
            f'{E(text or lab)}</span>')


def zmd_sev_chip(sev):
    col = ZMD.SEVERITY.get(sev or "Unknown", ZMD.SEVERITY["Unknown"])[1]
    return f'<span class="fp-zc" style="background:{col};color:#fff">{E(sev or "Unknown")}</span>'


CSS_ZMD = """
<style>
.fp-zc{display:inline-block;padding:3px 10px;border-radius:999px;font:600 .8rem Inter,sans-serif;margin:2px 4px 2px 0}
.fp-zc.s{padding:1px 8px;font-size:.74rem}
.fp-zban{display:flex;gap:14px;align-items:center;border-radius:14px;padding:12px 18px;margin:.2rem 0 1rem;flex-wrap:wrap;
  font-size:.92rem}
.fp-zban .ic{width:40px;height:40px;border-radius:11px;display:grid;place-items:center;flex:none}
.fp-zban a{font-weight:600;white-space:nowrap}
.fp-zal{background:#fff;border:1px solid var(--line);border-left:6px solid #E7932A;border-radius:14px;padding:14px 18px;
  margin-bottom:.8rem}
.fp-zal h4{margin:.35rem 0 .3rem;font-size:1.05rem}
.fp-zal .meta{color:var(--muted);font-size:.82rem}
.fp-zal .do{background:#FFF8E6;border-radius:10px;padding:9px 12px;margin-top:.6rem;font-size:.9rem}
.fp-ztl{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}
.fp-ztl > div{background:#fff;border:1px solid var(--line);border-radius:12px;padding:10px 12px}
.fp-ztl .p{font:700 .8rem var(--fb);color:var(--muted);text-transform:uppercase;letter-spacing:.05em}
.fp-ztl .x{font-size:.78rem;color:var(--muted);margin-top:4px;line-height:1.35}
.fp-zprod{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}
.fp-zprod a{display:block;background:#fff;border:1px solid var(--line);border-radius:12px;padding:11px 13px;
  text-decoration:none !important;color:var(--ink) !important}
.fp-zprod a b{display:block;font:700 .92rem var(--fh);color:var(--forest)}
.fp-zprod a span{font-size:.8rem;color:var(--muted)}
@media (max-width: 900px){ .fp-ztl,.fp-zprod{grid-template-columns:1fr 1fr} }
</style>
"""


def zmd_banner(nd):
    """One line for the homepage: ZMD warnings in force, else the seasonal outlook in one sentence."""
    try:
        T, st_ = zmd_alerts(nd)
    except Exception:
        T, st_ = pd.DataFrame(), {"have": False, "live": False}
    act = T[T["active"]] if len(T) else T
    if len(act):
        top = act.sort_values("sev_rank", ascending=False).iloc[0]
        nd_ = len(set().union(*[set(d) for d in act["districts"]]))
        return (f'<div class="fp-zban" style="background:#FCE4DE;border:1px solid #F1B9AA;color:#5A1A10">'
                f'<div class="ic" style="background:#B9342B;color:#fff">{icon("storm", 22)}</div><div style="flex:1;'
                f'min-width:240px"><b>ZMD weather warnings in force: {len(act)}</b> · {nd_} district(s) · '
                f'{E(top["headline"])} (until {E(zmd_time(top["expires_t"]))})</div>'
                f'<a href="{link("/weather")}" target="_self">See warnings by district →</a></div>')
    spec, S, _, _ = zmd_seasonal()
    seas = ""
    if spec is not None and len(S):
        d = S[S["period"] == "DJF"]
        nb = int((d["rank"] <= 2).sum())
        seas = (f' · ZMD seasonal forecast {E(spec["season"])}: {nb} of {len(d)} districts normal-to-below or below '
                f'normal in December–February (issued {E(zmd_time(spec["issued"] + "T12:00:00+02:00", False))})')
    chk = ("No ZMD weather warnings in force" if st_.get("have") else "ZMD warnings could not be checked")
    return (f'<div class="fp-zban" style="background:#EEF3F8;border:1px solid #CFDCE8;color:#14233A">'
            f'<div class="ic" style="background:#1F4E80;color:#fff">{icon("storm", 22)}</div><div style="flex:1;'
            f'min-width:240px"><b>{chk}</b>{seas}</div>'
            f'<a href="{link("/weather")}" target="_self">Weather &amp; warnings →</a></div>')


# ---------------------------------------------------------------- connected evidence (location intelligence)
STATE = {"bad": ("#B9342B", "#FBE9E6"), "warn": ("#C8870F", "#FFF4DB"), "ok": ("#2E8B57", "#E8F3EC"),
         "info": ("#1F4E80", "#E8F0F8"), "none": ("#8A948E", "#F1F1EE")}
_BAD = {"Very dry", "Much warmer than normal", "Well below normal", "Likely water stress"}
_WARN = {"Drier than normal", "Warmer than normal", "Below normal", "Possible water stress",
         "Early sign: rainfall deficit"}


def _node(rec, title, ic, state=None, value=None, note=None, dtype=None):
    ok = bool(rec) and rec.get("status") == "ok"
    if value is None:
        value = str(rec.get("display")).split(" · ")[0] if ok else "–"
    cls = (rec or {}).get("class") if ok else None
    if state is None:
        state = "none" if not ok else "bad" if cls in _BAD else "warn" if cls in _WARN else "ok"
    fg, bg = STATE[state]
    note = note if note is not None else (cls if cls and cls != value else ("Not in this period" if not ok else ""))
    tip = E(evidence_line(rec)) if ok else E((rec or {}).get("quality_note") or "Not available for this period")
    dtype = dtype or (rec or {}).get("data_type")
    tag = f'<div class="t">{type_tag(dtype)}</div>' if dtype else ""
    return (f'<div class="fp-node" style="border-color:{fg}33;background:{bg}" title="{tip}">'
            f'<div class="h" style="color:{fg}">{icon(ic, 15, fg)} {E(title)}</div>'
            f'<div class="v">{E(value)}</div><div class="n" style="color:{fg}">{E(note or "")}</div>{tag}</div>')


def _field_node(fields, locked=0):
    f = fields if fields is not None else pd.DataFrame()
    if not len(f) and locked:
        return _node({"status": "ok"}, "Field evidence", "camera", "ok",
                     f"{locked} field{'s' if locked > 1 else ''}", "Protected: sign in to view",
                     dtype="field_observation")
    if len(f):
        hi = int(f["risk_level"].isin(["High", "Moderate", "Not attributed"]).sum())
        wa = int((f["risk_level"] == "Watch").sum())
        vis = int(f["visits"].sum()) if "visits" in f else 0
        return _node({"status": "ok"}, "Field evidence", "camera", "bad" if hi else "warn" if wa else "ok",
                     f"{len(f)} field{'s' if len(f) > 1 else ''} · {vis} visit{'s' if vis != 1 else ''}",
                     f"{hi} with crop stress" if hi else f"{wa} on watch" if wa else "No crop-stress flag",
                     dtype="field_observation")
    return _node(None, "Field evidence", "camera", "none", "None yet", "Submit a field observation",
                 dtype="field_observation")


def signal_chain_html(recs, fields=None, together="", locked=0):
    """The evidence behind an assessment, in the order the platform reads it: field & satellite evidence ->
    environmental conditions -> water -> integrated assessment. Every box says what kind of data it is."""
    groups = [
        ("Field & satellite evidence", [_field_node(fields, locked),
                                        _node(recs.get("vegetation_anomaly_pct"), "Crop greenness", "leaf")]),
        ("Environmental conditions", [_node(recs.get("rainfall_anomaly_pct"), "Rainfall", "drop"),
                                      _node(recs.get("temperature_deviation"), "Temperature", "thermo")]),
        ("Water", [_node(recs.get("soil_moisture_anomaly_pct"), "Soil moisture", "drop"),
                   _node(recs.get("water_stress"), "Water stress", "gauge",
                         value=(recs.get("water_stress") or {}).get("class") or "–", note="")]),
    ]
    cols = []
    for i, (g, nodes) in enumerate(groups):
        cols.append(f'<div class="fp-grp"><div class="gh">{E(g)}</div>{"".join(nodes)}</div>')
        cols.append('<div class="fp-arr"><span>→</span></div>')
    cols.append('<div class="fp-grp"><div class="gh">Integrated analysis</div><div class="fp-node fp-intel">'
                f'{icon("gauge", 22, "#F2C74E")}<b>Location intelligence</b><small>All layers read together</small>'
                '</div></div>')
    return (f'<div class="fp-chain">{"".join(cols)}</div>'
            + (f'<div class="fp-together"><b>Together:</b> {E(together)}</div>' if together else ""))


# ---------------------------------------------------------------- current agricultural condition (the dominant read)
def _arrow(v, near, up_bad):
    """(arrow, state) for a signed anomaly; 'near' is the band treated as steady."""
    if v is None or pd.isna(v):
        return "–", "none"
    if abs(v) < near:
        return "→", "ok"
    up = v > 0
    bad = up == up_bad
    return ("↑" if up else "↓"), ("warn" if bad else "ok")


def condition_signals(recs, fields=None, locked=0):
    """The five headline signals: (label, arrow, state, short text, data type)."""
    def val(k):
        r = recs.get(k) or {}
        try:
            return float(r["value"]) if r.get("status") == "ok" else None
        except (TypeError, ValueError):
            return None
    out = []
    for k, lab, near, up_bad in (("vegetation_anomaly_pct", "Crop / vegetation", 5, False),
                                 ("rainfall_anomaly_pct", "Rainfall", 10, False),
                                 ("temperature_deviation", "Temperature", .5, True)):
        r = recs.get(k) or {}
        a, st_ = _arrow(val(k), near, up_bad)
        if r.get("class") in _BAD:
            st_ = "bad"
        out.append((lab, a, st_, str(r.get("display") or "–").split(" · ")[0] if r.get("status") == "ok" else
                    "Not in this period", r.get("data_type") or "derived"))
    ws = recs.get("water_stress") or {}
    c = ws.get("class") if ws.get("status") == "ok" else None
    a, st_ = {"Likely water stress": ("↑", "bad"), "Possible water stress": ("↑", "warn"),
              "Early sign: rainfall deficit": ("↗", "warn")}.get(c, ("→", "ok") if c else ("–", "none"))
    out.append(("Water stress", a, st_, c or "Not in this period", "derived"))
    f = fields if fields is not None else pd.DataFrame()
    if len(f):
        vis = int(f["visits"].sum()) if "visits" in f else 0
        hi = int(f["risk_level"].isin(["High", "Moderate", "Not attributed"]).sum())
        out.append(("Field evidence", "✓" if vis else "○", ("bad" if hi else "ok") if vis else "warn",
                    f"{vis} visit{'s' if vis != 1 else ''}, {len(f)} field{'s' if len(f) > 1 else ''}"
                    if vis else f"{len(f)} field{'s' if len(f) > 1 else ''}, awaiting visit", "field_observation"))
    elif locked:
        out.append(("Field evidence", "🔒", "ok", f"{locked} field{'s' if locked > 1 else ''} · sign in to view",
                    "field_observation"))
    else:
        out.append(("Field evidence", "○", "none", "None yet", "field_observation"))
    return out


CONFIDENCE_WORDS = {"Strong": "High confidence", "Good": "Moderate confidence", "Partial": "Limited evidence",
                    "Limited": "Insufficient data"}


def condition_strip_html(status_key, sigs, evidence=None, sub=""):
    lab, col = STATUS[status_key]
    cells = "".join(
        f'<div class="c" title="{E(t)} · {E(DATA_TYPES.get(dt_, (dt_,))[0])}"><div class="l">{E(lab_)}</div>'
        f'<div class="a" style="color:{STATE[st_][0]}">{E(a)}</div><div class="t">{E(t)}</div></div>'
        for lab_, a, st_, t, dt_ in sigs)
    conf = CONFIDENCE_WORDS.get(evidence or "", "")
    return (f'<div class="fp-cond"><div class="s" style="background:{col}"><div class="k">Current agricultural condition'
            f'</div><div class="w">{E(lab)}</div><div class="x">{E(sub)}</div>'
            + (f'<div class="cf">{E(conf)}</div>' if conf else "") + f'</div><div class="g">{cells}</div></div>')


def field_to_intel_html(compact=False):
    steps = [("camera", "Observe", "Crop and conditions recorded in the field"),
             ("doc", "Submit", "Entered through KoboToolbox"),
             ("pin", "Connect", "Linked to its location"),
             ("layers", "Combine", "Satellite, rainfall, temperature, water"),
             ("gauge", "Interpret", "Evidence evaluated together"),
             ("leaf", "Understand", "Location-specific intelligence")]
    cells = "".join(f'<div class="st"><div class="n">{i}</div>{icon(ic, 22, "#1F4D3A")}<b>{E(t)}</b>'
                    + ("" if compact else f'<small>{E(d)}</small>') + '</div>'
                    + ('<div class="ar">→</div>' if i < len(steps) else "")
                    for i, (ic, t, d) in enumerate(steps, 1))
    return f'<div class="fp-f2i"><div class="hd">From the field to intelligence</div><div class="row">{cells}</div></div>'


def answer_cards_html(what, what_sub, why, why_sub, nxt, color):
    return (f'<div class="fp-q3"><div class="q" style="border-top-color:{color}"><div class="k">What is happening?</div>'
            f'<div class="a" style="color:{color}">{E(what)}</div><div class="s">{what_sub}</div></div>'
            f'<div class="q"><div class="k">Why does it matter?</div><div class="a">{E(why)}</div>'
            f'<div class="s">{why_sub}</div></div>'
            f'<div class="q"><div class="k">What should be considered next?</div><ol>'
            + "".join(f"<li>{E(x)}</li>" for x in nxt[:3]) + '</ol></div></div>')


CSS_V4 = """
<style>
.fp-hero.compact{min-height:250px}
.fp-hero.compact .inner{padding:30px 40px 28px}
.fp-hero.compact h1{font-size:2.1rem;margin:.3rem 0 .5rem}
.fp-hero.compact p{margin:0 0 .9rem;font-size:1rem}
.fp-hero.compact .script{font-size:1.25rem;bottom:26px}
.fp-in-cell{cursor:help}
.fp-loc{background:var(--forest);border-radius:18px;padding:18px 24px;color:#fff;display:flex;gap:16px;align-items:center;
  flex-wrap:wrap;margin:.2rem 0 .9rem}
.fp-loc h1{color:#fff !important;margin:0;font-size:2rem;line-height:1.1}
.fp-loc .chips{display:flex;gap:6px;flex-wrap:wrap;margin-top:6px}
.fp-loc .chips span{background:rgba(255,255,255,.1);border:1px solid rgba(255,255,255,.25);border-radius:999px;
  padding:2px 10px;font-size:.8rem;color:#E8EFE9}
.fp-loc .lvl{margin-left:auto;padding:8px 16px;border-radius:999px;font:700 .95rem var(--fb);color:#fff}
.fp-q3{display:grid;grid-template-columns:1.1fr 1fr 1fr;gap:12px;margin-bottom:.9rem}
.fp-q3 .q{background:#fff;border:1px solid var(--line);border-top:4px solid var(--forest);border-radius:14px;padding:14px 16px}
.fp-q3 .k{font:700 .72rem var(--fb);letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}
.fp-q3 .a{font:800 1.12rem/1.3 var(--fh);color:var(--ink);margin:.35rem 0 .3rem}
.fp-q3 .s{color:var(--muted);font-size:.86rem;line-height:1.4}
.fp-q3 ol{margin:.45rem 0 0 1.1rem;padding:0;font-weight:600;color:var(--ink);font-size:.93rem;line-height:1.45}
.fp-chain{display:grid;grid-template-columns:1fr auto 1fr auto 1fr auto .8fr;gap:8px;align-items:center}
.fp-grp{display:flex;flex-direction:column;gap:7px}
.fp-grp .gh{font:700 .7rem var(--fb);letter-spacing:.1em;text-transform:uppercase;color:var(--muted);text-align:center}
.fp-arr{display:flex;flex-direction:column;align-items:center;color:#B8B09A;margin-top:14px}
.fp-arr span{font:700 1.5rem/1 var(--fb)}
.fp-arr small{font:600 .62rem var(--fb);text-transform:uppercase;letter-spacing:.06em;color:#9A927C;white-space:nowrap}
.fp-node{border:1px solid;border-radius:12px;padding:8px 11px;cursor:help}
.fp-node .h{font:700 .78rem var(--fb);display:flex;gap:5px;align-items:center}
.fp-node .v{font:800 1.25rem/1.15 var(--fh);color:var(--ink);margin-top:2px}
.fp-node .n{font-size:.74rem;font-weight:600;min-height:1em}
.fp-together{margin-top:10px;background:#fff;border-left:4px solid var(--forest);border-radius:10px;padding:9px 14px;
  font-size:.93rem}
.fp-mini{color:var(--muted);font-size:.82rem}
.fp-watch{display:flex;gap:10px;align-items:center;padding:8px 2px;border-bottom:1px solid var(--line);font-size:.9rem}
.fp-watch:last-child{border-bottom:0}
.fp-watch i{width:10px;height:10px;border-radius:50%;flex:none}
.fp-watch a{color:var(--ink) !important;font-weight:700;text-decoration:none}
.fp-watch .s{color:var(--muted);font-size:.8rem;margin-left:auto;text-align:right}
@media (max-width: 1000px){ .fp-q3{grid-template-columns:1fr} .fp-chain{grid-template-columns:1fr} .fp-arr{transform:rotate(90deg);
  justify-self:center} }
</style>
"""



# ---------------------------------------------------------------- homepage pieces
@st.cache_data(show_spinner=False)
def _hero_b64():
    import base64
    p = ROOT / "app" / "assets" / "hero_farmer.jpg"
    return base64.b64encode(p.read_bytes()).decode() if p.exists() else ""


def hero_photo_html(inner):
    b = _hero_b64()
    img = (f'<div class="ph" style="background-image:url(data:image/jpeg;base64,{b})"></div>' if b else
           f'<div class="ph">{hero_landscape_svg()}</div>')
    return f'<div class="fp-hero2"><div class="tx">{inner}</div>{img}</div>'


def signal_list_html(recs, fields=None):
    """The connected layers as a compact vertical chain (homepage spotlight)."""
    rows = []
    f = fields if fields is not None else pd.DataFrame()
    items = [("Crop", "Vegetation", "leaf", recs.get("vegetation_anomaly_pct")),
             ("Conditions", "Rainfall", "drop", recs.get("rainfall_anomaly_pct")),
             ("", "Temperature", "thermo", recs.get("temperature_deviation")),
             ("Water", "Soil moisture", "drop", recs.get("soil_moisture_anomaly_pct")),
             ("", "Water stress", "gauge", recs.get("water_stress"))]
    for g, t, ic, rec in items:
        ok = bool(rec) and rec.get("status") == "ok"
        cls = (rec or {}).get("class") if ok else None
        st_ = "none" if not ok else "bad" if cls in _BAD else "warn" if cls in _WARN else "ok"
        v = ((rec.get("class") if t == "Water stress" else str(rec.get("display")).split(" · ")[0]) if ok else "–")
        rows.append((g, t, ic, v, st_))
    if len(f):
        hi = int(f["risk_level"].isin(["High", "Moderate", "Not attributed"]).sum())
        rows.append(("Field", "Monitored fields", "camera", f"{len(f)} · {hi} flagged", "bad" if hi else "ok"))
    out = ""
    for g, t, ic, v, st_ in rows:
        fg, bg = STATE[st_]
        out += ((f'<div class="g">{E(g)}</div>' if g else "")
                + f'<div class="r"><i style="background:{fg}"></i>{icon(ic, 14, fg)}<span>{E(t)}</span>'
                f'<b>{E(v)}</b></div>')
    return f'<div class="fp-vchain">{out}</div>'


def national_answers(nd, fields):
    """Zambia as a whole, all layers together: (what, what_sub, why, why_sub, next list, colour). Live data only."""
    if not nd.available:
        return ("District layers not built yet", "Run the monthly update.", "–", "", ["Run monthly_update.bat"], "#7A8590")
    I = nd.indicators
    ok = lambda ind: I[(I["indicator"] == ind) & (I["status"] == "ok")]
    lv = district_levels(nd)
    names = nd.districts.set_index("district_id")["district"]
    flag = [d for d, it in lv.items() if it["level"] in ("concern", "watch")]
    conc = [d for d in flag if lv[d]["level"] == "concern"]
    n = len([1 for it in lv.values() if it["level"] != "unknown"])
    watch_names = [names.get(d, d) for d in (conc + [d for d in flag if d not in conc])]
    def _list(xs):
        return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1]
    if not flag:
        what, colr = "Good growing conditions across Zambia", "#2E8B57"
    elif len(conc) > n / 4:
        what, colr = f"Crop moisture stress is building in {len(conc)} districts", "#B9342B"
    else:
        what, colr = (f"Conditions are mostly good, with early warnings in {len(flag)} "
                      f"district{'s' if len(flag) > 1 else ''}"), "#C8870F"
    # one plain sentence, crop first
    cl = []
    t = ok("vegetation_anomaly_pct")
    if len(t):
        b_ = int(t["class"].isin(["Below normal", "Well below normal"]).sum())
        cl.append("crops are as green as normal everywhere" if not b_ else
                  f"crops are less green than normal in {b_} district{'s' if b_ > 1 else ''}")
    t = ok("soil_moisture_anomaly_pct")
    if len(t):
        b_ = int(t["class"].isin(["Below normal", "Well below normal"]).sum())
        cl.append("soil moisture is normal" if not b_ else
                  f"the soil is drier than usual in only {b_} district{'s' if b_ > 1 else ''}" if b_ <= 5 else
                  f"the soil is drier than usual in {b_} districts")
    rain = ok("rainfall_anomaly_pct")
    if len(rain):
        med = float(pd.to_numeric(rain["value"], errors="coerce").median())
        cl.append(f"rainfall is {abs(med):.0f}% {'above' if med > 0 else 'below'} normal overall" if abs(med) >= 5
                  else "rainfall is close to normal")
    tmp = ok("temperature_deviation")
    if len(tmp):
        k = int(tmp["class"].isin(["Warmer than normal", "Much warmer than normal"]).sum())
        if k:
            cl.append(f"{k} district{'s are' if k > 1 else ' is'} warmer than usual")
    sub = (_list(cl) + ".") if cl else ""
    sub = sub[:1].upper() + sub[1:]
    if flag:
        sub += f" Early warning: {_list(watch_names[:4])}."
    nf = len(fields)
    if nf:
        v_ = int(fields["visits"].sum())
        sub += f" Field visits so far: {v_}." if v_ else ""
    mz = ok("maize_share_pct")
    mzd = set(mz[pd.to_numeric(mz["value"], errors="coerce") >= NCFG["classes"]["maize_share_pct"]]["location_id"])
    hit = sorted(set(flag) & mzd)
    if mzd:
        why = (f"{len(hit)} of Zambia's {len(mzd)} main maize districts show early signs of stress." if hit else
               f"Zambia's {len(mzd)} main maize districts are not under stress.")
    else:
        why = f"{len(flag)} district{'s show' if len(flag) != 1 else ' shows'} early signs of stress."
    why_sub = ("Maize is Zambia's staple food: stress in these districts would hit food supply and farm income "
               "first.")
    nxt = [f"Consider field checks in {_list(watch_names[:3])}" if len(flag) <= 3 else
           f"Consider field checks in the {len(flag)} early-warning districts"] if flag else []
    spec, S, _, _ = zmd_seasonal()
    if spec is not None and len(S):
        d = S[S["period"] == "DJF"]
        nb = int((d["rank"] <= 2).sum())
        if nb > len(d) / 2:
            nxt.append(f"Prepare for a drier December–February, which ZMD forecasts for {nb} districts")
    nxt.append("Add field observations to confirm conditions on the ground" if kobo_form_url() else
               "Open any district for its full picture")
    return what, sub, why, why_sub, nxt, colr


def kobo_form_url():
    """Public link of the KoboToolbox field form (config/settings.yaml kobo: form_url), or ''."""
    try:
        return str((CFG.get("kobo") or {}).get("form_url") or "").strip()
    except Exception:
        return ""


def kobo_button(label="Submit Field Observation", small=False):
    u = kobo_form_url()
    if not u:
        return ""
    return (f'<a class="fp-kobo{" s" if small else ""}" href="{E(u)}" target="_blank" rel="noopener">'
            f'{icon("camera", 16 if small else 18)} {E(label)} ↗</a>')


CSS_V5 = """
<style>
.fp-hero2{display:grid;grid-template-columns:1fr 1.15fr;border-radius:22px;overflow:hidden;min-height:330px;
  box-shadow:0 10px 30px rgba(20,35,58,.15);margin-bottom:1rem;background:var(--forest)}
.fp-hero2 .tx{padding:34px 40px;color:#E8EFE9;display:flex;flex-direction:column;justify-content:center}
.fp-hero2 .tx .tag{display:inline-flex;gap:8px;align-items:center;font:600 .74rem var(--fb);letter-spacing:.09em;
  text-transform:uppercase;color:#F2C74E;margin-bottom:.4rem}
.fp-hero2 h1{color:#fff !important;font-size:2.2rem;line-height:1.1;margin:.2rem 0 .7rem}
.fp-hero2 h1 .gold{color:#F2C74E !important}
.fp-hero2 p{margin:0 0 1rem;font-size:1rem;line-height:1.5}
.fp-hero2 .chips{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:1.1rem}
.fp-hero2 .chip{font:700 .7rem var(--fb);letter-spacing:.1em;color:#1E2A24;background:#F2C74E;padding:4px 10px;border-radius:6px}
.fp-hero2 .chip.o{background:transparent;color:#F2C74E;border:1px solid rgba(242,199,78,.6)}
.fp-hero2 .ph{background-size:cover;background-position:28% 30%;min-height:330px;position:relative}
.fp-hero2 .ph svg{width:100%;height:100%}
.fp-hero2 .ph:after{content:"Environmental change. People's livelihoods.";position:absolute;right:18px;bottom:16px;
  font:italic 600 1.05rem Georgia,serif;color:#fff;text-shadow:0 2px 8px rgba(0,0,0,.6)}
.fp-vchain{position:relative;margin:.2rem 0 .4rem}
.fp-vchain .g{font:700 .64rem var(--fb);letter-spacing:.1em;text-transform:uppercase;color:var(--muted);margin:7px 0 2px}
.fp-vchain .r{display:flex;align-items:center;gap:7px;padding:5px 8px;border-radius:8px;background:#fff;
  border:1px solid var(--line);margin-bottom:4px;font-size:.86rem}
.fp-vchain .r i{width:8px;height:8px;border-radius:50%;flex:none}
.fp-vchain .r b{margin-left:auto;font-weight:700}
.fp-spot h3{margin:0;font-size:1.3rem}
.fp-kobo{display:inline-flex;align-items:center;gap:7px;background:#6A4C93;color:#fff !important;text-decoration:none !important;
  padding:9px 16px;border-radius:12px;font:600 .92rem var(--fb)}
.fp-kobo:hover{background:#563C7A}
.fp-kobo.s{padding:5px 11px;border-radius:9px;font-size:.82rem}
@media (max-width: 900px){ .fp-hero2{grid-template-columns:1fr} .fp-hero2 .ph{min-height:220px} }
@media (max-width: 640px){ .fp-hero2 .tx{padding:22px 20px} .fp-hero2 h1{font-size:1.55rem} .fp-hero2 p{font-size:.92rem}
  .fp-loc h1{font-size:1.5rem} .fp-loc .lvl{margin-left:0} }
</style>
"""



@st.cache_data(ttl=1800, show_spinner="Checking ZMD city forecasts")
def _zmd_city_doc():
    doc, ok, err = ZMD.get_city_forecasts(live=True, timeout=8)
    return doc, ok, err, dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def zmd_city(nd=None):
    """(daily summary per city, all time steps, {district_id: (city, km)}, status) of the ZMD city forecasts."""
    doc, ok, err, checked = _zmd_city_doc()
    steps = ZMD.city_steps(doc)
    days = ZMD.city_days(steps)
    near = ZMD.nearest_city((nd or national()).districts, days) if len(days) else {}
    return days, steps, near, {"live": ok, "error": err, "checked": checked, "have": doc is not None,
                               "retrieved": (doc or {}).get("retrieved_at")}


def day_name(d):
    t = dt.date.fromisoformat(str(d))
    today = dt.datetime.now(ZMD.CAT).date()
    return "Today" if t == today else "Tomorrow" if t == today + dt.timedelta(days=1) else t.strftime("%a %d %b")


def city_day_card(r):
    rain = (f'<div class="rn wet">Rain: up to {r["rain_max_mm"]:.1f} mm in {r["rain_periods"]} period(s)</div>'
            if r["rain_max_mm"] > 0 else '<div class="rn">Dry</div>')
    return (f'<div class="fp-wday"><div class="d">{E(day_name(r["date"]))}</div>'
            f'<img src="{E(r["icon"])}" alt="" width="46" height="46" loading="lazy">'
            f'<div class="c">{E(str(r["condition_label"]).replace(" Night", "").replace(" Day", ""))}</div>'
            f'<div class="t"><b>{r["high"]:.0f}°</b> / {r["low"]:.0f}°C</div>{rain}</div>')


CSS_WX = """
<style>
.fp-wdays{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}
.fp-wday{background:#fff;border:1px solid var(--line);border-radius:14px;padding:12px;text-align:center}
.fp-wday .d{font:700 .78rem var(--fb);text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}
.fp-wday img{margin:6px auto 2px;display:block}
.fp-wday .c{font-weight:600;font-size:.9rem}
.fp-wday .t{font:800 1.2rem var(--fh);margin:2px 0}
.fp-wday .rn{font-size:.8rem;color:var(--muted)}
.fp-wday .rn.wet{color:#1F4E80;font-weight:600}
@media (max-width: 700px){ .fp-wdays{grid-template-columns:1fr} }
</style>
"""


CSS_V6 = """
<style>
.fp-cond{display:grid;grid-template-columns:minmax(220px,.9fr) 2.6fr;gap:0;border-radius:18px;overflow:hidden;
  border:1px solid var(--line);background:#fff;margin:.2rem 0 .9rem;box-shadow:0 4px 16px rgba(20,35,58,.06)}
.fp-cond .s{padding:16px 22px;color:#fff;display:flex;flex-direction:column;justify-content:center}
.fp-cond .s .k{font:700 .7rem var(--fb);letter-spacing:.12em;text-transform:uppercase;opacity:.9}
.fp-cond .s .w{font:800 2.3rem/1.05 var(--fh);margin:.25rem 0 .2rem;color:#fff;text-transform:uppercase;letter-spacing:.02em}
.fp-cond .s .x{font-size:.9rem;line-height:1.35;opacity:.95}
.fp-cond .s .cf{margin-top:.55rem;font:600 .72rem var(--fb);opacity:.8}
.fp-cond .g{display:grid;grid-template-columns:repeat(5,1fr)}
.fp-cond .c{padding:14px 10px;text-align:center;border-left:1px solid var(--line);cursor:help;display:flex;
  flex-direction:column;justify-content:center}
.fp-cond .c .l{font:700 .72rem var(--fb);letter-spacing:.06em;text-transform:uppercase;color:var(--muted)}
.fp-cond .c .a{font:800 2.3rem/1.1 var(--fb);margin:.15rem 0}
.fp-cond .c .t{font-size:.8rem;color:var(--ink);font-weight:600;line-height:1.25}
.fp-node .t{margin-top:4px}
.fp-panel-h a.fp-kobo,.fp-zban a.fp-kobo,a.fp-kobo{color:#fff !important}
.fp-node .t .fp-src{font-size:.66rem;padding:1px 7px}
.fp-intel{background:var(--forest) !important;border-color:var(--forest) !important;color:#fff;display:flex;
  flex-direction:column;align-items:center;gap:4px;padding:16px 10px !important;text-align:center;cursor:default}
.fp-intel b{font:800 1rem var(--fh);color:#fff}
.fp-intel small{color:#CFE0D3;font-size:.72rem}
.fp-f2i{background:#fff;border:1px solid var(--line);border-radius:16px;padding:12px 16px 14px;margin:.4rem 0 .9rem}
.fp-f2i .hd{font:700 .72rem var(--fb);letter-spacing:.12em;text-transform:uppercase;color:var(--muted);margin-bottom:8px}
.fp-f2i .row{display:flex;align-items:stretch;gap:6px}
.fp-f2i .st{flex:1;display:flex;flex-direction:column;align-items:center;text-align:center;gap:3px;background:#F6F3EA;
  border-radius:12px;padding:10px 6px;position:relative}
.fp-f2i .st .n{position:absolute;top:6px;left:8px;font:700 .7rem var(--fb);color:#B8B09A}
.fp-f2i .st b{font:800 .95rem var(--fh);color:var(--ink)}
.fp-f2i .st small{font-size:.74rem;color:var(--muted);line-height:1.25}
.fp-f2i .st:nth-child(1),.fp-f2i .st:nth-child(3){background:#EFE9F7}
.fp-f2i .ar{align-self:center;color:#B8B09A;font:700 1.2rem var(--fb)}
.fp-crop{display:grid;grid-template-columns:150px 1fr;gap:14px;align-items:start}
.fp-crop .ph{width:150px;height:150px;border-radius:12px;background:#EEE8D8 center/cover;display:grid;place-items:center}
.fp-crop dl{display:grid;grid-template-columns:auto 1fr;gap:3px 12px;margin:0;font-size:.88rem}
.fp-crop dt{color:var(--muted);font-weight:600}
.fp-crop dd{margin:0;font-weight:700;color:var(--ink)}
.fp-flow4{display:flex;gap:5px;align-items:center;flex-wrap:wrap;margin:.2rem 0 1.1rem}
.fp-flow4 span{font:700 .64rem var(--fb);letter-spacing:.08em;color:#F2C74E;border:1px solid rgba(242,199,78,.55);
  padding:3px 7px;border-radius:6px;white-space:nowrap}
.fp-flow4 i{color:#F2C74E;font-style:normal}
.fp-why4{display:grid;grid-template-columns:1fr 1fr 1.15fr .85fr;gap:12px;margin:.2rem 0 1rem}
.fp-why4 .c{background:#fff;border:1px solid var(--line);border-top:4px solid var(--forest);border-radius:14px;
  padding:16px 18px;display:flex;flex-direction:column;gap:8px}
.fp-why4 .c p{margin:0;font:600 1rem/1.4 var(--fb);color:var(--ink)}
.fp-why4 .stat{border-top-color:#B9342B}
.fp-why4 .stat .big{font:800 2.4rem/1 var(--fh);color:#B9342B}
.fp-why4 .cta{background:var(--forest);border-color:var(--forest);text-decoration:none !important;justify-content:center}
.fp-why4 .cta b{color:#fff;font:800 1.15rem/1.3 var(--fh)}
.fp-why4 .cta:hover{background:#163829}
@media (max-width: 1000px){ .fp-why4{grid-template-columns:1fr 1fr} }
@media (max-width: 640px){ .fp-why4{grid-template-columns:1fr} }
@media (max-width: 1000px){ .fp-cond{grid-template-columns:1fr} .fp-cond .g{grid-template-columns:repeat(3,1fr)}
  .fp-cond .c{border-top:1px solid var(--line)} .fp-f2i .row{flex-wrap:wrap} .fp-f2i .st{flex:1 1 30%}
  .fp-f2i .ar{display:none} }
@media (max-width: 640px){ .fp-panel-h{flex-wrap:wrap;gap:6px} .fp-hint{display:none} .fp-cond .g{grid-template-columns:repeat(2,1fr)} .fp-cond .s .w{font-size:1.8rem}
  .fp-crop{grid-template-columns:1fr} .fp-f2i .st{flex:1 1 45%} }
</style>
"""
