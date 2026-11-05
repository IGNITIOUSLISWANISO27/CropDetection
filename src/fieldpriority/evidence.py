"""Indicator records: one standard shape for every number the platform shows.

Every indicator, at district or field level, is stored as a record with its value AND where it came from:
source, observation period, spatial resolution and coverage, the kind of data, and a confidence level.
The dashboard never shows a value without this information, so users can tell a measurement from an estimate,
a model output or a field observation.
"""
import datetime as dt
import math

COLUMNS = ["location_type", "location_id", "location_name", "province", "indicator", "label", "value", "unit",
           "display", "class", "period_start", "period_end", "period_label", "source", "source_url", "resolution",
           "coverage", "data_type", "method", "baseline", "confidence", "quality_note", "status", "computed_at"]

# kind of data (the brief: distinguish measurements, estimates, model predictions and field observations)
DATA_TYPES = {
    "measurement": ("Measured", "Direct instrument measurement (for example a rain gauge)."),
    "satellite_estimate": ("Satellite estimate", "Estimated from satellite observations, sometimes blended with gauges."),
    "model_output": ("Model estimate", "Computed by a weather or land-surface model (reanalysis), not measured on site."),
    "field_observation": ("Field observation", "Recorded on the ground by a verifier (KoboToolbox)."),
    "derived": ("Derived", "Calculated by this platform from the indicators above (rules or statistics)."),
    "official": ("Official (ZMD)", "Forecast or warning issued by the Zambia Meteorological Department, shown unchanged."),
}
CONFIDENCE = ("High", "Medium", "Low")

# indicator keys used across the platform, with their display label
INDICATORS = {
    "rainfall_total": "Rainfall, season to date",
    "rainfall_anomaly_pct": "Rainfall compared with normal",
    "rainfall_condition": "Rainfall condition",
    "temperature_mean": "Mean temperature",
    "temperature_deviation": "Temperature compared with normal",
    "tmax_mean": "Hottest temperature of the month (season average)",
    "heat_exposure": "Heat exposure",
    "vegetation_anomaly_pct": "Vegetation condition (NDVI vs normal)",
    "soil_moisture_anomaly_pct": "Root-zone soil moisture vs normal",
    "water_stress": "Water stress",
    "maize_share_pct": "Land under maize",
    "cropland_share_pct": "Cropland share",
    "solar_resource": "Solar resource",
    "field_reports": "Field reports (KoboToolbox)",
    "verified_reports": "Verified field reports",
    "monitored_fields": "Monitored fields",
    "crop_condition": "Crop condition (monitored fields)",
    "agro_zone": "Agricultural zone (agro-ecological region)",
    "annual_rainfall_normal": "Normal rainfall, October to May",
}


def _num(v):
    try:
        f = float(v)
        return None if math.isnan(f) or math.isinf(f) else f
    except (TypeError, ValueError):
        return None


def record(location_type, location_id, location_name, indicator, value=None, unit="", display=None, cls=None,
           period=(None, None), period_label="", source="", source_url="", resolution="", coverage="",
           data_type="derived", method="", baseline="", confidence="Medium", quality_note="", status="ok",
           province=""):
    """Build one indicator record (a dict with every column of COLUMNS)."""
    if data_type not in DATA_TYPES:
        raise ValueError(f"unknown data_type {data_type}")
    if confidence not in CONFIDENCE and status == "ok":
        raise ValueError(f"confidence must be one of {CONFIDENCE}")
    v = value if isinstance(value, str) else _num(value)
    return {"location_type": location_type, "location_id": str(location_id), "location_name": location_name,
            "province": province, "indicator": indicator, "label": INDICATORS.get(indicator, indicator),
            "value": v, "unit": unit, "display": display if display is not None else ("" if v is None else str(v)),
            "class": cls or "", "period_start": str(period[0] or ""), "period_end": str(period[1] or ""),
            "period_label": period_label, "source": source, "source_url": source_url, "resolution": resolution,
            "coverage": coverage, "data_type": data_type, "method": method, "baseline": baseline,
            "confidence": confidence if status == "ok" else "", "quality_note": quality_note, "status": status,
            "computed_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}


def pending(location_type, location_id, location_name, indicator, why, source="", province=""):
    """A placeholder record: the indicator is part of the platform but its data is not available yet.
    Shown as 'Not yet available' with the reason, never as a number."""
    return record(location_type, location_id, location_name, indicator, None, display="Not yet available",
                  source=source, quality_note=why, status="pending", province=province)


def check(rec):
    """Problems with one record (empty list = complete). Used by tests and the build step."""
    probs = [c for c in COLUMNS if c not in rec]
    if rec.get("status") == "ok":
        for c in ("source", "period_end", "resolution", "coverage", "data_type", "confidence"):
            if not rec.get(c):
                probs.append(f"{rec.get('indicator')}: {c} missing")
    return probs
