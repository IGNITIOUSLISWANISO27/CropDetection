"""Plain-language reasons. Wording rules agreed with the team:
 - greenness is 'relative vegetation greenness', never 'NDVI anomaly'
 - low greenness never 'confirms drought' (planting date, stage, harvest, soil, crop, management)
 - rainfall / soil moisture / temperature are regional cell values, not field measurements
 - priority = priority for field verification, not confirmed drought
"""
import pandas as pd

MON = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

GREEN_CAVEAT = ("This can reflect crop growth stage, planting date, harvest, soil, crop type or "
                "management as well as water stress, so it needs field verification.")


def _f(x, nd=1, sign=False):
    return "n/a" if pd.isna(x) else (f"{x:+.{nd}f}" if sign else f"{x:.{nd}f}")


def _shared(txt):
    return f" (shared with {txt})" if isinstance(txt, str) and txt else ""


SM_DOWNLOAD = "ERA5-Land soil moisture 0-7 cm via Open-Meteo, about 11 km cell"


def sm_source(r, src):
    """Name of the soil moisture product actually used for this field: the multi-year table (sm_cell 'area series')
    or, when the table has no rows for the season, the monthly rasters downloaded by fetch_data (ERA5-Land)."""
    if str(r.get("sm_cell")) == "area series":
        return src["soil_moisture"]
    return src.get("soil_moisture_download") or SM_DOWNLOAD


def build_reasons(row, cfg):
    """row: merged season + score + confidence record (dict-like). Returns list of {code, text}."""
    r, out = row, []
    src = cfg["sources"]
    lm = cfg["months"][-1]

    n = int(r["cohort_size"]) if pd.notna(r.get("cohort_size")) else 0
    span = f"{MON[cfg['months'][0]]}-{MON[lm]}"
    months_txt = ", ".join(f"{MON[m]} {_f(r.get(f'ndvi_m{m:02d}'), 2)}" for m in cfg["months"])
    if n < 2 or pd.isna(r.get("integrated_score")):
        # one field: there is nothing to rank it against, so no relative score or comparison is given
        out.append({"code": "PRIORITY_NA",
                    "text": "No relative ranking: it needs at least two fields. The result above comes from "
                            "the drought rules, and it is a priority for field verification, not confirmed drought."})
        out.append({"code": "GREENNESS",
                    "text": f"Vegetation greenness ({span} mean NDVI {_f(r['greenness_seasonal'], 2)}; month values "
                            f"{months_txt}). " + GREEN_CAVEAT})
        gs = None
    else:
        out.append({"code": "PRIORITY",
                    "text": f"{r['priority']}: integrated score {_f(r['integrated_score'], 2)} "
                            f"(0-1, relative among the {n} pilot fields). "
                            f"This is a priority for field verification, not confirmed drought."})
        gs = r["greenness_score"]
    line = (f"Relative vegetation greenness ({span} NDVI {_f(r['greenness_seasonal'], 2)}; "
            f"month values {months_txt}) ")
    if gs is None:
        pass
    elif gs >= 0.5:
        out.append({"code": "GREENNESS_LOW", "text": line + "is low compared with the other pilot fields. " + GREEN_CAVEAT})
    elif gs < 0.25 and r["priority"] == "High priority":
        out.append({"code": "GREENNESS_OK", "text": line + "is among the highest of the pilot fields, "
                    "so this priority comes mainly from regional indicators, not from field-level greenness."})
    else:
        out.append({"code": "GREENNESS_MID", "text": line + "is intermediate compared with the other pilot fields."})

    # rainfall (regional)
    pct = _f(r.get("rain_anom_pct_latest"), 0, sign=True)
    txt = (f"Regional rainfall ({src['rainfall']}{_shared(r.get('rain_cell_shared_with'))}): "
           f"anomaly {_f(r['rain_anom_mm_mean'], 1, True)} mm/month averaged over the season versus "
           f"{src['rainfall_baseline']}")
    if pd.notna(r["rain_anom_mm_latest"]):
        txt += f"; latest month ({cfg['year']}-{lm:02d}) {_f(r['rain_anom_mm_latest'], 1, True)} mm ({pct}%)"
    txt += ". This is an area value, not rain measured at the field."
    code = "RAIN_LATE_DRY" if (r["rain_anom_mm_mean"] > 0 and r["rain_anom_mm_latest"] < 0) else "RAIN"
    if code == "RAIN_LATE_DRY":
        txt += " The seasonal mean is above the reference, but the latest month is below it."
    out.append({"code": code, "text": txt})

    # soil moisture and temperature (regional)
    out.append({"code": "SOIL_MOISTURE",
                "text": f"Regional soil moisture ({sm_source(r, src)}{_shared(r.get('sm_cell_shared_with'))}): "
                        f"seasonal mean {_f(r['sm_mean'], 3)}; change from the previous month to the latest "
                        f"{_f(r['sm_change_latest'], 3, True)}. Coarse cell value, not a field measurement."})
    out.append({"code": "TEMPERATURE",
                "text": f"Regional temperature ({src['temperature']}{_shared(r.get('temp_cell_shared_with'))}): "
                        f"seasonal mean {_f(r['temp_c_mean'], 2)} C; latest month change "
                        f"{_f(r['temp_c_change_latest'], 2, True)} C. Differences between pilot fields are small."})

    # radar context
    if pd.isna(r["s1_vv_db"]):
        out.append({"code": "S1_MISSING",
                    "text": "Sentinel-1 VV context was not available in this run (it does not affect the score)."})
    else:
        out.append({"code": "S1_CONTEXT",
                    "text": f"Sentinel-1 VV context: {_f(r['s1_vv_db'], 1)} dB ({r['s1_vv_context']}"
                            f"{'' if 'single field' in str(r['s1_vv_context']) else ', relative to other fields'}). "
                            f"Backscatter responds to roughness, canopy and moisture together; context only, not a stress score."})

    # structure of the score
    if r["regional_share"] >= cfg["confidence"]["regional_driven_share"]:
        out.append({"code": "REGIONAL_DRIVEN",
                    "text": f"{r['regional_share']*100:.0f}% of this score comes from coarse regional indicators "
                            f"shared with nearby fields, so the field-level evidence is limited."})

    # data quality
    if pd.notna(r["ndvi_valid_frac_min"]) and r["ndvi_valid_frac_min"] < cfg["extraction"]["min_valid_fraction"]:
        out.append({"code": "DQ_NDVI",
                    "text": f"Optical coverage is partial in at least one month "
                            f"(lowest valid-pixel share {r['ndvi_valid_frac_min']*100:.0f}%), lowering confidence."})
    gaps = [MON[m] for m in cfg["months"] if pd.isna(r.get(f"ndvi_m{m:02d}"))]
    if gaps and len(gaps) < len(cfg["months"]):
        out.append({"code": "DQ_NDVI_GAP",
                    "text": f"No cloud-free satellite image of the field for {', '.join(gaps)}, so greenness for "
                            f"{'that month' if len(gaps) == 1 else 'those months'} is unknown."})
    if pd.notna(r["n_pixels_10m"]) and r["n_pixels_10m"] < cfg["extraction"]["full_support_pixels"]:
        out.append({"code": "DQ_SMALL_FIELD",
                    "text": f"Small field ({_f(r['area_ha'], 2)} ha, about {int(r['n_pixels_10m'])} pixels at 10 m): "
                            f"edge effects can move its statistics."})
    return out
