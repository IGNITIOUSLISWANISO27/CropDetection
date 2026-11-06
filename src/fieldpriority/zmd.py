"""Official weather information from the Zambia Meteorological Department (ZMD), arranged per district.

Two ZMD products are used, both unchanged:
  1. The seasonal rainfall forecast (config/zmd_seasonal_forecast.yaml, transcribed from the ZMD bulletin each
     season). Each statement of the bulletin ("Southern Province", "northern parts of Solwezi", ...) is placed on the
     districts it names.
  2. ZMD weather warnings and advisories, read live from ZMD's public CAP alert feed
     (https://zmd.gov.zm/api/cap/rss.xml). Each alert's area (the polygon drawn by ZMD, else the place names) is
     matched to districts. The last successful download is kept in data/zmd/alerts.json, so the page still shows
     something (with its retrieval time) when the feed cannot be reached.

Run `python -m fieldpriority.zmd` to refresh the saved alerts.
"""
import datetime as dt
import json
import os
import re
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[2]
SEASONAL_FILE = ROOT / "config" / "zmd_seasonal_forecast.yaml"
CACHE_FILE = ROOT / "data" / "zmd" / "alerts.json"
RSS_URL = "https://zmd.gov.zm/api/cap/rss.xml"
ALERTS_PAGE = "https://zmd.gov.zm/alerts/"
USER_AGENT = "FieldPriority/1.0 (agricultural early-warning dashboard, Zambia)"

# ZMD's own product pages (what the page links to; nothing is copied from them)
PRODUCTS = [
    ("Weather warnings and advisories", "https://zmd.gov.zm/alerts/", "Live alerts (CAP feed used on this page)"),
    ("Nowcasting (2–6 hours)", "https://zmd.gov.zm/products/nowcasting-2-6-hour-forecasting/", "Storms in the next hours"),
    ("Daily forecast", "https://zmd.gov.zm/products/daily-forecast/", "Today and tomorrow, by town"),
    ("Weekly forecast", "https://zmd.gov.zm/products/weekly-forecast/", "The next 7 days"),
    ("Agrometeorological bulletin", "https://zmd.gov.zm/products/agrometeorological-bulletin/",
     "Every 10 days in the season: rainfall, soil water and crop advice"),
    ("Sub-seasonal forecast (2–4 weeks)", "https://zmd.gov.zm/products/sub-seasonal-2-4-weeks-forecast/",
     "Wetter or drier weeks ahead"),
    ("Seasonal forecast", "https://zmd.gov.zm/products/seasonal-forecast/", "The whole rain season"),
    ("Flash-flood and flood advisories", "https://zmd.gov.zm/products/flash-flood-and-floods-monitor-advisories/",
     "Flood risk"),
]

# rainfall categories of the seasonal forecast: order (1 = driest), label, colour
CATEGORIES = {
    "below_normal": (1, "Below normal", "#B9652B"),
    "normal_to_below": (2, "Normal to below normal", "#EBC46A"),
    "normal": (3, "Normal", "#E9E4D4"),
    "normal_to_above": (4, "Normal to above normal", "#8DB9DA"),
    "above_normal": (5, "Above normal", "#2E6FA8"),
}
PERIOD_ORDER = ["OND", "NDJ", "DJF", "JFM"]
SEVERITY = {"Extreme": (4, "#7A1F1A"), "Severe": (3, "#B9342B"), "Moderate": (2, "#E7932A"), "Minor": (1, "#D9B53A"),
            "Unknown": (0, "#7A8590")}

# bulletin spellings -> boundary file spellings
ALIASES = {"milenge": "milengi", "mushindamo": "mushindano", "chikankata": "chikankanta", "itezhitezhi": "itezhitezhi",
           "shiwangandu": "shiwangandu", "sengahill": "sengahill", "northwestern": "northwestern"}


def norm(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z]", "", s)
    return ALIASES.get(s, s)


# ---------------------------------------------------------------- placing bulletin statements on districts
def halves(D):
    """district_id -> 'north' or 'south': where the district's centre lies in its province (by latitude)."""
    out = {}
    for p, g in D.groupby("province"):
        b = g.total_bounds if hasattr(g, "total_bounds") else None
        mid = (b[1] + b[3]) / 2 if b is not None else float(g["lat"].median())
        for r in g.itertuples():
            out[r.district_id] = "north" if float(r.lat) >= mid else "south"
    return out


def _names(v):
    return v if isinstance(v, list) else [v]


# precedence of a statement for one district (lower wins)
LEVEL = {"district": 0, "district_part": 1, "province": 2, "province_half": 3, "province_much": 4, "province_parts": 5}


def place(statements, D):
    """statements: list of (value, entry) with entry = {province|district: name(s), extent, note}.
    Returns {district_id: [match, ...]}, match = dict(value, level, kind, part, note, said)."""
    by_name = {norm(n): i for n, i in zip(D["district"], D["district_id"])}
    prov_of = dict(zip(D["district_id"], D["province"]))
    provs = {norm(p): p for p in D["province"].unique()}
    half = halves(D)
    out, unknown = {}, []
    for value, e in statements:
        ext = e.get("extent", "all")
        note = e.get("note", "")
        if "district" in e:
            for n in _names(e["district"]):
                did = by_name.get(norm(n))
                if did is None:
                    unknown.append(n)
                    continue
                lvl = "district" if ext == "all" else "district_part"
                said = n if ext == "all" else f"{'northern' if ext == 'north' else 'southern' if ext == 'south' else 'some'} parts of {n}"
                out.setdefault(did, []).append(dict(value=value, level=LEVEL[lvl], kind=lvl, part=ext, note=note,
                                                    said=said))
        else:
            for n in _names(e["province"]):
                p = provs.get(norm(n))
                if p is None:
                    unknown.append(n)
                    continue
                for did in [d for d, pp in prov_of.items() if pp == p]:
                    if ext == "all":
                        lvl, said = "province", f"{p} Province"
                    elif ext in ("north", "south"):
                        if half[did] != ext:
                            continue
                        lvl, said = "province_half", f"{'northern' if ext == 'north' else 'southern'} parts of {p} Province"
                    elif ext == "much":
                        lvl, said = "province_much", f"much of {p} Province"
                    else:
                        lvl, said = "province_parts", f"parts of {p} Province"
                    out.setdefault(did, []).append(dict(value=value, level=LEVEL[lvl], kind=lvl, part=ext, note=note,
                                                        said=said))
    if unknown:
        out["_unknown"] = sorted(set(unknown))
    return out


def resolve(matches, label=lambda v: v):
    """One district's statements -> dict(values, text, basis, approximate, conflict, split)."""
    if not matches:
        return dict(values=[], text="Not stated in the bulletin", basis="", approximate=False, conflict=False,
                    split=False)
    whole = [m for m in matches if m["kind"] == "district"]
    parts = [m for m in matches if m["kind"] == "district_part"]
    prov = sorted([m for m in matches if m["level"] >= 2], key=lambda m: m["level"])
    best_prov = [m for m in prov if m["level"] == prov[0]["level"] and m["kind"] != "province_parts"] if prov else []

    def uniq(ms):
        seen, vals = set(), []
        for m in ms:
            if m["value"] not in seen:
                seen.add(m["value"])
                vals.append(m["value"])
        return vals

    if whole:
        vals = uniq(whole)
        text = " and ".join(label(v) for v in vals)
        extra = [f"{label(m['value'])} in the {m['part']}ern parts" for m in parts if m["value"] not in vals]
        if extra:
            text += " (" + "; ".join(extra) + ")"
        return dict(values=vals, text=text, basis="District named in the bulletin", approximate=False,
                    conflict=len(vals) > 1, split=bool(extra))
    if parts:
        got = {}
        for m in parts:
            got.setdefault(m["part"], m["value"])
        segs = [f"{label(v)} in the {d}ern parts" for d, v in got.items()]
        vals = list(dict.fromkeys(got.values()))
        if not ({"north", "south"} <= set(got)) and best_prov:
            rest = uniq(best_prov)
            segs.append(f"{' / '.join(label(v) for v in rest)} elsewhere")
            vals += [v for v in rest if v not in vals]
        return dict(values=vals, text="; ".join(segs), basis="Parts of the district named in the bulletin",
                    approximate=False, conflict=False, split=len(vals) > 1)
    if best_prov:
        vals = uniq(best_prov)
        k = best_prov[0]["kind"]
        basis = {"province": "Whole province named in the bulletin",
                 "province_half": "Part of the province named; placed by where the district lies (approximate)",
                 "province_much": "\"Much of\" the province (approximate)"}[k]
        note = "; ".join(sorted({m["note"] for m in best_prov if m["note"]}))
        return dict(values=vals, text=" / ".join(label(v) for v in vals), basis=basis + (f". {note}" if note else ""),
                    approximate=k != "province", conflict=len(vals) > 1, split=False)
    vals = uniq(prov)
    return dict(values=vals, text=" / ".join(label(v) for v in vals) + " (in parts of the province)",
                basis="Parts of the province named, without saying which (approximate)", approximate=True,
                conflict=False, split=False)


def load_seasonal(path=None):
    p = Path(path or os.environ.get("FIELDPRIORITY_ZMD_SEASONAL") or SEASONAL_FILE)
    if not p.exists():
        return None
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def seasonal_by_district(spec, D):
    """DataFrame district_id, period, period_label, code, category, rank, text, basis, approximate, conflict, said."""
    rows = []
    if not spec:
        return pd.DataFrame(columns=["district_id", "period", "period_label", "code", "category", "rank", "text",
                                     "basis", "approximate", "conflict", "said"])
    for per in PERIOD_ORDER:
        P = (spec.get("periods") or {}).get(per)
        if not P:
            continue
        st = [(cat, e) for cat in CATEGORIES for e in (P.get(cat) or [])]
        placed = place(st, D)
        for did in D["district_id"]:
            ms = placed.get(did, [])
            r = resolve(ms, lambda v: CATEGORIES[v][1])
            # colour of a district with two categories: the drier one (this is an early-warning platform)
            code = min(r["values"], key=lambda v: CATEGORIES[v][0]) if r["values"] else None
            rows.append(dict(district_id=did, period=per, period_label=P.get("label", per), code=code,
                             codes="|".join(r["values"]),
                             category=CATEGORIES[code][1] if code else "Not stated",
                             rank=CATEGORIES[code][0] if code else None, text=r["text"], basis=r["basis"],
                             approximate=r["approximate"], conflict=r["conflict"], split=r["split"],
                             said="; ".join(f"{CATEGORIES[m['value']][1]}: {m['said']}" for m in ms)))
    return pd.DataFrame(rows)


def timing_by_district(spec, D, key):
    """Onset or cessation per district: DataFrame district_id, text, basis, approximate."""
    st = [(blk["when"], e) for blk in (spec or {}).get(key, []) for e in blk.get("places", [])]
    placed = place(st, D)
    rows = []
    for did in D["district_id"]:
        r = resolve(placed.get(did, []))
        rows.append(dict(district_id=did, text=r["text"], basis=r["basis"], approximate=r["approximate"]))
    return pd.DataFrame(rows)


def advisories_for(spec, ranks):
    """Farmer advisories of the bulletin that apply: the 'drier' or 'wetter' set, whichever the district's
    forecast categories (ranks 1-5, one per period and category) lean to; both when they balance."""
    adv = (spec or {}).get("advisories") or {}
    ranks = [r for r in ranks if r]
    dry, wet = sum(r <= 2 for r in ranks), sum(r >= 4 for r in ranks)
    out = []
    if dry and dry >= wet:
        out += adv.get("drier", [])
    if wet and wet >= dry:
        out += adv.get("wetter", [])
    return out + adv.get("all", [])


def district_ranks(S, district_id):
    """Every category rank the forecast gives a district (a split period counts each of its categories)."""
    t = S[S["district_id"] == district_id]
    return [CATEGORIES[c][0] for cs in t["codes"] for c in str(cs).split("|") if c in CATEGORIES]


# ---------------------------------------------------------------- CAP alerts
CAP_NS = "urn:oasis:names:tc:emergency:cap:1.2"


def _t(el, tag):
    x = el.find(f"{{{CAP_NS}}}{tag}")
    if x is None:
        x = el.find(tag)
    return (x.text or "").strip() if x is not None and x.text else ""


def _all(el, tag):
    return el.findall(f"{{{CAP_NS}}}{tag}") or el.findall(tag)


def parse_rss(text):
    root = ET.fromstring(text.encode("utf-8") if isinstance(text, str) else text)
    items = []
    for it in root.iter("item"):
        g = lambda k: (it.findtext(k) or "").strip()
        items.append({"title": g("title"), "link": g("link"), "guid": g("guid"), "pubDate": g("pubDate"),
                      "summary": g("description")})
    return items


def parse_cap(text, url=""):
    """One CAP 1.2 alert -> dict (first English <info> block)."""
    root = ET.fromstring(text.encode("utf-8") if isinstance(text, str) else text)
    infos = _all(root, "info")
    info = next((i for i in infos if _t(i, "language").lower().startswith("en")), infos[0] if infos else None)
    a = {"identifier": _t(root, "identifier"), "sent": _t(root, "sent"), "status": _t(root, "status"),
         "msgType": _t(root, "msgType"), "references": _t(root, "references"), "cap_url": url}
    if info is None:
        return a
    for k in ("event", "urgency", "severity", "certainty", "effective", "onset", "expires", "senderName", "headline",
              "description", "instruction", "web", "audience"):
        a[k] = _t(info, k)
    a["areas"] = []
    for ar in _all(info, "area"):
        polys = []
        for p in _all(ar, "polygon"):
            pts = []
            for pair in (p.text or "").split():
                try:
                    lat, lon = pair.split(",")[:2]
                    pts.append((float(lon), float(lat)))
                except ValueError:
                    continue
            if len(pts) >= 4:
                polys.append(pts)
        a["areas"].append({"desc": _t(ar, "areaDesc"), "polygons": polys})
    return a


def _get(url, timeout):
    import requests
    r = requests.get(url, timeout=timeout, headers={"User-Agent": USER_AGENT})
    r.raise_for_status()
    return r.text


def fetch_alerts(timeout=8, max_items=25, get=None):
    """Download the ZMD CAP feed and every alert in it. Raises on failure of the feed itself."""
    get = get or (lambda u: _get(u, timeout))
    items = parse_rss(get(RSS_URL))[:max_items]
    alerts = []
    for it in items:
        try:
            a = parse_cap(get(it["link"]), it["link"])
        except Exception as e:                       # one broken alert must not hide the others
            a = {"headline": it["title"], "sent": it["pubDate"], "cap_url": it["link"], "error": str(e), "areas": []}
        a.setdefault("headline", it["title"])
        a["rss_title"] = it["title"]
        alerts.append(a)
    return alerts


def save_cache(alerts, path=None):
    p = Path(path or os.environ.get("FIELDPRIORITY_ZMD_CACHE") or CACHE_FILE)
    p.parent.mkdir(parents=True, exist_ok=True)
    doc = {"retrieved_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "source": RSS_URL,
           "alerts": alerts}
    p.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    return doc


def load_cache(path=None):
    p = Path(path or os.environ.get("FIELDPRIORITY_ZMD_CACHE") or CACHE_FILE)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def get_alerts(live=True, timeout=8, cache_path=None):
    """(doc, live_ok, error). doc = {retrieved_at, source, alerts}. Live download first, else the saved copy."""
    if live and not os.environ.get("FIELDPRIORITY_ZMD_OFFLINE"):
        try:
            return save_cache(fetch_alerts(timeout), cache_path), True, ""
        except Exception as e:  # network, site down, bad XML
            err = f"{type(e).__name__}: {e}"[:200]
    else:
        err = "Live download switched off"
    return load_cache(cache_path), False, err


def parse_time(s):
    if not s:
        return None
    try:
        t = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        try:
            from email.utils import parsedate_to_datetime
            t = parsedate_to_datetime(s)
        except (TypeError, ValueError):
            return None
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone(dt.timedelta(hours=2)))   # Zambia time (CAT)


def is_active(a, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    if a.get("status", "Actual") not in ("Actual", "") or a.get("msgType") == "Cancel":
        return False
    exp = parse_time(a.get("expires"))
    return bool(exp and exp > now)


def match_districts(a, D, min_share=0.08):
    """{district_id: basis} for one alert. D: GeoDataFrame with district_id, district, province, geometry."""
    from shapely.geometry import Polygon
    out = {}
    provs = {norm(p): p for p in D["province"].unique()}
    names = {norm(n): i for n, i in zip(D["district"], D["district_id"])}
    for ar in a.get("areas", []):
        for pts in ar.get("polygons", []):
            try:
                poly = Polygon(pts).buffer(0)
            except Exception:
                continue
            if poly.is_empty:
                continue
            for r in D[D.intersects(poly)].itertuples():
                g = r.geometry
                if g.area and g.intersection(poly).area / g.area >= min_share:
                    out.setdefault(r.district_id, "Inside the area drawn by ZMD for this alert")
    descs = [ar.get("desc", "") for ar in a.get("areas", [])]
    for d in descs:
        for tok in re.split(r",|;|/|\band\b", d):
            k = norm(re.sub(r"(?i)provinces?|districts?|parts of|surrounding areas", "", tok))
            if not k:
                continue
            if k in provs:
                for did in D[D["province"] == provs[k]]["district_id"]:
                    out.setdefault(did, f"{provs[k]} Province named by ZMD as the alert area")
            elif k in names:
                out.setdefault(names[k], "District named by ZMD as the alert area")
    if not out:                                     # no usable area: names in the headline and text
        txt = " ".join([a.get("headline", ""), a.get("description", "")])
        flat = norm_text(txt)
        for n, did in names.items():
            if re.search(rf"\b{re.escape(n)}\b", flat):
                out.setdefault(did, "District named in the alert text")
        for k, p in provs.items():
            if re.search(rf"\b{re.escape(k)}\s+province", flat):
                for did in D[D["province"] == p]["district_id"]:
                    out.setdefault(did, f"{p} Province named in the alert text")
    return out


def norm_text(s):
    """Lower-case text with each place name squashed like norm() (so 'Kapiri Mposhi' -> 'kapirimposhi')."""
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    for multi in ("kapiri mposhi", "senga hill", "itezhi-tezhi", "itezhi tezhi", "north-western", "north western",
                  "shiwang'andu", "shiwangandu"):
        s = s.replace(multi, re.sub(r"[^a-z]", "", multi))
    return re.sub(r"[^a-z ]", " ", s)


def alerts_table(doc, D, now=None):
    """DataFrame of alerts with active flag, severity rank and matched districts."""
    rows = []
    for a in (doc or {}).get("alerts", []):
        m = match_districts(a, D) if len(D) else {}
        sev = a.get("severity") or "Unknown"
        rows.append({**{k: a.get(k, "") for k in ("identifier", "event", "severity", "urgency", "certainty", "headline",
                                                   "description", "instruction", "web", "cap_url", "sent", "effective",
                                                   "onset", "expires", "msgType")},
                     "areas": ", ".join(ar.get("desc", "") for ar in a.get("areas", []) if ar.get("desc")),
                     "active": is_active(a, now), "sev_rank": SEVERITY.get(sev, SEVERITY["Unknown"])[0],
                     "districts": m, "n_districts": len(m),
                     "sent_t": parse_time(a.get("sent")), "expires_t": parse_time(a.get("expires"))})
    T = pd.DataFrame(rows)
    if len(T):
        T = T.sort_values(["active", "sent_t"], ascending=[False, False], na_position="last").reset_index(drop=True)
    return T


# ---------------------------------------------------------------- city forecasts (next 2-3 days)
CITY_URL = "https://zmd.gov.zm/api/forecasts"
CITY_CACHE = ROOT / "data" / "zmd" / "city_forecasts.json"
CITY_FIX = {"mukushi": "Mkushi"}
CAT = dt.timezone(dt.timedelta(hours=2))


def city_name(s):
    n = re.sub(r",\s*zambia\s*$", "", str(s).strip(), flags=re.I).strip()
    return CITY_FIX.get(n.lower(), n[:1].upper() + n[1:])


def get_city_forecasts(live=True, timeout=8, cache_path=None, get=None):
    """(doc, live_ok, error). doc = {retrieved_at, source, forecasts}: the city forecasts published on zmd.gov.zm
    (a list of GeoJSON FeatureCollections, one per date and time step). Live first, else the saved copy."""
    p = Path(cache_path or os.environ.get("FIELDPRIORITY_ZMD_CITY_CACHE") or CITY_CACHE)
    err = "Live download switched off"
    if live and not os.environ.get("FIELDPRIORITY_ZMD_OFFLINE"):
        try:
            raw = json.loads((get or (lambda u: _get(u, timeout)))(CITY_URL))
            if not isinstance(raw, list) or not raw:
                raise ValueError("unexpected answer from the forecast feed")
            doc = {"retrieved_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "source": CITY_URL,
                   "forecasts": raw}
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(doc), encoding="utf-8")
            return doc, True, ""
        except Exception as e:
            err = f"{type(e).__name__}: {e}"[:200]
    try:
        return json.loads(p.read_text(encoding="utf-8")), False, err
    except (OSError, ValueError):
        return None, False, err


def city_steps(doc):
    """One row per city and time step: city, lon, lat, date, label, whole_day, tmax, tmin, rain_mm, rh, condition."""
    rows = []
    for fc in (doc or {}).get("forecasts", []):
        for f in fc.get("features", []):
            p, (lon, lat) = f.get("properties", {}), f.get("geometry", {}).get("coordinates", [None, None])[:2]
            t = parse_time(p.get("date")) or parse_time(fc.get("datetime"))
            rows.append({"city": city_name(p.get("city")), "lon": lon, "lat": lat,
                         "date": str(fc.get("date") or (t.date() if t else "")), "time": t,
                         "label": p.get("effective_period_label", ""),
                         "whole_day": str(p.get("effective_period_label", "")).lower().startswith("whole"),
                         "tmax": p.get("air_temperature_max"), "tmin": p.get("air_temperature_min"),
                         "rain_mm": p.get("precipitation_amount"), "rh": p.get("relative_humidity"),
                         "condition": p.get("condition", ""), "condition_label": p.get("condition_label", ""),
                         "icon": p.get("condition_symbol_url", "")})
    return pd.DataFrame(rows)


def city_days(steps, today=None):
    """Per city and day: high, low, rain (largest amount in any period, periods with rain), daytime condition.
    Built from the individual time steps; the feed's 'Whole day' entry is a single midnight step, so it is only
    used when a day has no other steps."""
    if steps is None or not len(steps):
        return pd.DataFrame()
    today = today or dt.datetime.now(CAT).date().isoformat()
    out = []
    for (c, d), g in steps[steps["date"] >= today].groupby(["city", "date"], sort=False):
        s = g[~g["whole_day"]] if (~g["whole_day"]).any() else g
        num = lambda k: pd.to_numeric(s[k], errors="coerce")
        hours = s["time"].map(lambda t: t.astimezone(CAT).hour if t is not None and t == t else 12)
        day = s.assign(h=hours)
        pick = day.iloc[(day["h"] - 13).abs().argsort()].iloc[0]       # the step nearest early afternoon
        rain = num("rain_mm").fillna(0)
        out.append({"city": c, "date": d, "lon": g["lon"].iloc[0], "lat": g["lat"].iloc[0],
                    "high": float(num("tmax").max()), "low": float(num("tmin").min()),
                    "rain_max_mm": float(rain.max()), "rain_periods": int((rain > 0).sum()), "periods": len(s),
                    "condition_label": pick["condition_label"], "icon": pick["icon"],
                    "rh": float(num("rh").mean())})
    return pd.DataFrame(out)


def nearest_city(D, days):
    """district_id -> (city, distance in km) to the nearest ZMD forecast city."""
    import math
    cities = days.drop_duplicates("city")[["city", "lon", "lat"]].values.tolist() if len(days) else []
    out = {}
    for r in D.itertuples():
        best = None
        for c, lo, la in cities:
            p1, p2 = math.radians(float(r.lat)), math.radians(la)
            a = (math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2)
                 * math.sin(math.radians(lo - float(r.lon)) / 2) ** 2)
            km = 2 * 6371 * math.asin(math.sqrt(a))
            if best is None or km < best[1]:
                best = (c, km)
        if best:
            out[r.district_id] = best
    return out


def main():
    cd, cok, cerr = get_city_forecasts(live=True, timeout=20)
    print(f"ZMD city forecasts saved: {len((cd or {}).get('forecasts', []))} time steps" if cok else
          f"ZMD city forecasts not refreshed ({cerr}); the saved copy is kept.")
    doc, ok, err = get_alerts(live=True, timeout=20)
    if ok:
        print(f"ZMD alerts saved: {len(doc['alerts'])} in the feed, retrieved {doc['retrieved_at']}")
    else:
        print(f"ZMD alerts not refreshed ({err}); the saved copy is kept.")


if __name__ == "__main__":
    main()
