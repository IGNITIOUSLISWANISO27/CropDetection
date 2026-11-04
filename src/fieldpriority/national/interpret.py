"""Integrated interpretation of one location's indicators (the brief's report sections 4 and 5).

Rules only, written in cautious language: the text says what the evidence MAY indicate and never claims that
drought has damaged crops. Thresholds come from config/national.yaml (classes).
"""
CLASS_COLORS = {
    # rainfall
    "Very dry": "#8C3B1E", "Drier than normal": "#D08C3A", "Near normal": "#E9E4D4", "Wetter than normal": "#3E7FB0",
    # temperature
    "Much warmer than normal": "#B9342B", "Warmer than normal": "#E7894F", "Cooler than normal": "#5E8FC0",
    # vegetation / soil moisture
    "Well below normal": "#8C3B1E", "Below normal": "#D08C3A", "Near or above normal": "#6FA85A",
    # water stress
    "Likely water stress": "#8C3B1E", "Possible water stress": "#D08C3A", "Early sign: rainfall deficit": "#EBC46A",
    "No sign of water stress": "#9CC79A",
}
STRESS_ORDER = ["Likely water stress", "Possible water stress", "Early sign: rainfall deficit", "No sign of water stress"]


def rain_class(pct, c):
    if pct is None:
        return None
    k = c["rainfall_pct"]
    return ("Very dry" if pct <= k["very_dry"] else "Drier than normal" if pct <= k["dry"]
            else "Wetter than normal" if pct >= k["wet"] else "Near normal")


def temp_class(dev, c):
    if dev is None:
        return None
    k = c["temperature_c"]
    return ("Much warmer than normal" if dev >= k["much_warmer"] else "Warmer than normal" if dev >= k["warmer"]
            else "Cooler than normal" if dev <= k["cooler"] else "Near normal")


def below_class(pct, k):
    if pct is None:
        return None
    return "Well below normal" if pct <= k["much_below"] else "Below normal" if pct <= k["below"] else "Near or above normal"


def water_stress(rain_pct, temp_dev, sm_pct, c):
    """(class, basis, confidence). With soil moisture when it exists; otherwise a rainfall-based indication only."""
    k = c["rainfall_pct"]
    if sm_pct is not None:
        s = c["soil_moisture_pct"]
        dry = rain_pct is not None and rain_pct <= k["dry"]
        if sm_pct <= s["much_below"] or (sm_pct <= s["below"] and dry):
            cls = "Likely water stress"
        elif sm_pct <= s["below"] or (rain_pct is not None and rain_pct <= k["very_dry"]):
            cls = "Possible water stress"
        elif dry:
            cls = "Early sign: rainfall deficit"
        else:
            cls = "No sign of water stress"
        return cls, "root-zone soil moisture and rainfall", "Medium"
    if rain_pct is None:
        return None, "", ""
    warm = temp_dev is not None and temp_dev >= c["temperature_c"]["warmer"]
    if rain_pct <= k["very_dry"] or (rain_pct <= k["dry"] and warm):
        cls = "Possible water stress"
    elif rain_pct <= k["dry"]:
        cls = "Early sign: rainfall deficit"
    else:
        cls = "No sign of water stress"
    return cls, "rainfall and temperature only (soil moisture not yet included)", "Low"


def _v(recs, k):
    r = recs.get(k)
    return r.get("value") if r and r.get("status") == "ok" and isinstance(r.get("value"), (int, float)) else None


def interpret(name, recs, c, fields=None, monthly_rain=None, period_label=""):
    """recs: {indicator: record}. fields: list of dicts for monitored fields in the location (field_id, risk_level,
    outcome, verified). monthly_rain: {month: pct anomaly}. Returns a dict with level, headline, paragraphs,
    maize, evidence_gaps and considerations."""
    fields = fields or []
    rain, temp = _v(recs, "rainfall_anomaly_pct"), _v(recs, "temperature_deviation")
    veg, sm = _v(recs, "vegetation_anomaly_pct"), _v(recs, "soil_moisture_anomaly_pct")
    solar = _v(recs, "solar_resource")
    ws = (recs.get("water_stress") or {}).get("class") or None
    rc, tc = rain_class(rain, c), temp_class(temp, c)
    vc, sc = below_class(veg, c["vegetation_pct"]), below_class(sm, c["soil_moisture_pct"])

    concern, calm = [], []
    if rc in ("Very dry", "Drier than normal"):
        concern.append(f"rainfall {abs(rain):.0f}% below normal")
    elif rc:
        calm.append("rainfall " + ("above normal" if rc == "Wetter than normal" else "close to normal"))
    if tc in ("Much warmer than normal", "Warmer than normal"):
        concern.append(f"temperatures {temp:+.1f} °C above normal")
    elif tc:
        calm.append("temperatures " + ("below normal" if tc == "Cooler than normal" else "close to normal"))
    if vc in ("Well below normal", "Below normal"):
        concern.append(f"vegetation condition {abs(veg):.0f}% below normal")
    elif vc:
        calm.append("vegetation condition near or above normal")
    if sc in ("Well below normal", "Below normal"):
        concern.append(f"root-zone soil moisture {abs(sm):.0f}% below normal")
    elif sc:
        calm.append("soil moisture near or above normal")
    flagged = [f for f in fields if f.get("risk_level") in ("High", "Moderate", "Not attributed", "Watch")]

    have = sum(x is not None for x in (rain, temp, veg, sm))
    # moisture signals decide the level; warmth only adds to a moisture signal (it raises crop water demand)
    moist = [x for x in concern if not x.startswith("temperatures")]
    if have == 0:
        level, head = "unknown", "Not enough data to assess conditions yet"
    elif len(moist) >= 2 or (moist and len(concern) >= 2):
        level, head = "concern", "Several indicators point to possible moisture stress"
    elif moist:
        level, head = "watch", "One indicator shows a departure from normal"
    else:
        level, head = "normal", ("Moisture indicators are close to or better than normal" + (
            "; temperatures are above normal" if concern else ""))

    paras = []
    when = f" during {period_label}" if period_label else ""
    if moist:
        joined = " combined with ".join([", ".join(concern[:-1]), concern[-1]]) if len(concern) > 1 else concern[0]
        joined = joined[0].upper() + joined[1:]
        if len(concern) >= 2:
            paras.append(f"{joined}{when} may indicate increasing moisture stress in {name}. "
                         "Further field verification is recommended before drawing conclusions about crop damage.")
        else:
            paras.append(f"{joined}{when}. On its own this is an early sign rather than evidence of crop stress; "
                         "it is worth watching in the coming months.")
    elif have:
        paras.append(f"In {name}, {', '.join(concern + calm)}{when}. The available indicators do not point to "
                     "moisture stress for this area as a whole" + (", although warmer weather increases crop water demand."
                                                            if concern else "."))
    if calm and moist:
        paras.append("Other indicators are reassuring: " + ", ".join(calm) + ".")
    if veg is None:
        paras.append("Satellite vegetation condition is not yet included for districts, so the effect on crops "
                     "cannot be seen directly; the assessment rests on weather indicators.")
    if fields:
        n = len(fields)
        if flagged:
            paras.append(f"{len(flagged)} of {n} monitored field(s) in {name} carry a field-level flag "
                         f"({', '.join(sorted({f['risk_level'] for f in flagged}))}); see the field assessments.")
        else:
            paras.append(f"None of the {n} monitored field(s) in {name} carries a drought flag.")

    maize = []
    dry_months = [m for m, p in (monthly_rain or {}).items() if p is not None and p <= c["rainfall_pct"]["dry"]]
    if any(m in (1, 2) for m in dry_months):
        maize.append("Rainfall was below normal in January or February, when maize planted in November or December "
                     "usually reaches tasselling and silking. Water shortage at this stage can reduce grain set "
                     "and yield.")
    elif any(m in (11, 12) for m in dry_months):
        maize.append("Rainfall was below normal early in the season (November or December). This can delay planting "
                     "or affect germination and early growth.")
    elif any(m in (3, 4) for m in dry_months):
        maize.append("Rainfall was below normal late in the season (March or April), during grain filling for "
                     "most maize. Late shortage mainly reduces grain weight; crops near maturity are less affected.")
    if tc in ("Much warmer than normal", "Warmer than normal"):
        maize.append("Higher temperatures increase crop water demand and, around flowering, can reduce pollination.")
    if not maize:
        maize.append("The indicators do not suggest a specific effect on maize at this time." if have else
                     "The effect on maize cannot be judged without data.")

    gaps = []
    for k, why in [("vegetation_anomaly_pct", "vegetation condition (MODIS NDVI district export)"),
                   ("soil_moisture_anomaly_pct", "root-zone soil moisture (SMAP district export)"),
                   ("maize_share_pct", "where maize is grown (cropland / maize map)")]:
        if _v(recs, k) is None:
            gaps.append(why)
    if not fields:
        gaps.append("ground observations (no monitored fields or field reports here yet)")

    cons = []
    stress = ws in ("Likely water stress", "Possible water stress")
    urgent = [f for f in flagged if f.get("risk_level") != "Watch"]
    if level in ("concern", "watch") and urgent:
        cons.append("Prioritise verification visits to the flagged monitored fields (High and Moderate first).")
    elif level in ("concern", "watch") and flagged:
        cons.append("Keep monitoring the field(s) on Watch; plan a repeat visit if their greenness starts to fall.")
    elif level in ("concern", "watch") and fields:
        cons.append("Plan field inspections of the monitored fields to check crop condition on the ground.")
    elif level in ("concern", "watch"):
        cons.append("No monitored fields here yet: ask extension officers for field reports, or add pilot fields "
                    "in maize-growing parts of the district.")
    if stress or ws == "Early sign: rainfall deficit":
        cons.append("Investigate water access for farms: boreholes, dams and streams, and how much irrigation is "
                    "used now.")
        cons.append("Review water-management practices with agricultural extension officers (for example mulching, "
                    "conservation agriculture, timely weeding).")
    if tc in ("Much warmer than normal", "Warmer than normal"):
        cons.append("During field visits, look for heat stress around tasselling and silking.")
    if vc in ("Well below normal", "Below normal"):
        cons.append("Check causes other than drought (fall armyworm, disease, nutrient shortage) during visits.")
    if stress and solar is not None:
        cons.append(f"Solar resource is about {solar:.1f} kWh per m² per day. Where a water source exists, "
                    "solar-powered irrigation may be worth assessing; technical and economic suitability is not "
                    "assessed by this platform.")
    if level in ("normal",):
        cons.append("Continue monthly monitoring; the current indicators do not call for action.")
    if level == "unknown":
        cons.append("Run the monthly update or import the Earth Engine district export to fill the missing layers.")
    cons.append("Review any decision with agricultural extension officers: the platform supports local judgement, "
                "it does not replace it.")
    return {"level": level, "headline": head, "paragraphs": paras, "maize": maize, "gaps": gaps,
            "considerations": cons, "concern": concern, "classes": {"rainfall": rc, "temperature": tc,
                                                                   "vegetation": vc, "soil_moisture": sc,
                                                                   "water_stress": ws}}


LEVELS = {"concern": ("Possible moisture stress", "#B9342B"), "watch": ("Watch", "#D9A21B"),
          "normal": ("No major concern", "#2E8B57"), "unknown": ("Not enough data", "#7A8590")}
