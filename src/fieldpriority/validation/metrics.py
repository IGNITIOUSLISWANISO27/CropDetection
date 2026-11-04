"""Validation metrics: correct alerts, false alerts, verification lag, verification rate.

Definitions (agreed roles document: 'correct alerts, false alerts, warning time, verification rate'):
 alert           = issued prediction (ledger) with risk level in alert_levels (High / Moderate)
 cause check     = 'Crop stress - cause uncertain' (Not attributed); reported separately, not a drought alert
 control         = Watch / Low; Insufficient data and Not assessed are never controls
 correct alert   = alert whose accepted verification verdict is Confirmed
 false alert     = alert whose verdict is Rejected
 uncertain       = reported separately, never forced into yes/no (SOP)
 missed          = Low-priority (control) field verified as Confirmed
 verification rate = alerts with >= 1 accepted real verification / alerts issued
 verification lag  = visit date - alert date. This is NOT warning lead time: true lead time needs the
                     date stress began, which the form does not collect.
Only REAL, accepted, matched records are used. TEST and simulated records never count.
"""
import math
import numpy as np
import pandas as pd


def wilson(k, n, z=1.96):
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(max(0, c - h), 3), round(min(1, c + h), 3)]


def _rate(k, n):
    return {"k": int(k), "n": int(n), "value": round(k / n, 3) if n else None, "ci95": wilson(k, n)}


def compute_metrics(rec, issued, cfg):
    levels = cfg["alerts"]["alert_levels"]
    checks = cfg["alerts"].get("check_levels", [])
    control_levels = ["Watch", "Low"]
    alerts = issued[issued["alert_level"].isin(levels)]
    out = {"alerts_issued": int(len(alerts)),
           "cause_checks_listed": int(issued["alert_level"].isin(checks).sum()),
           "controls_listed": int(issued["alert_level"].isin(control_levels).sum()),
           "not_assessable": int(issued["alert_level"].isin(["Insufficient data", "Not assessed"]).sum()),
           "records_total": int(len(rec)),
           "records_test": int(rec["is_test"].astype(bool).sum()) if len(rec) and "is_test" in rec else 0,
           "records_real": int(((rec.get("record_type") == "real_visit") & ~rec["is_test"].astype(bool)).sum())
                           if len(rec) and "is_test" in rec else 0}
    if len(rec):
        out["status_counts"] = rec["validation_status_final"].value_counts().to_dict()
    el = rec[rec["analysis_eligible"]] if len(rec) else rec
    if len(el):
        el = el[el["matched_alert_id"].isin(issued["alert_id"])]      # only alerts in the evaluated set
    out["records_eligible"] = int(len(el))
    if not len(el):
        out["status"] = "no_eligible_verifications"
        out["message"] = ("No real, accepted, matched verification records yet. Test records are excluded by design. "
                          "Metrics will appear once real visits are accepted by the validation lead.")
        out["verification_rate"] = _rate(0, len(alerts))
        return out

    # latest eligible visit per alert
    el = el.assign(_v=pd.to_datetime(el["visit_date"])).sort_values("_v").groupby("matched_alert_id", as_index=False).last()
    el["alerted"] = el["alert_level"].isin(levels)
    el["verdict"] = el["field_verdict"]
    a, c = el[el.alerted], el[el["alert_level"].isin(control_levels)]
    ck = el[el["alert_level"].isin(checks)]
    out["cause_checks_visited"] = int(len(ck))
    out["cause_checks_found_drought"] = int((ck.verdict == "confirmed").sum())
    tp, fp = int((a.verdict == "confirmed").sum()), int((a.verdict == "rejected").sum())
    fn, tn = int((c.verdict == "confirmed").sum()), int((c.verdict == "rejected").sum())

    out["verification_rate"] = _rate(a["matched_alert_id"].nunique(), len(alerts))
    out["alerts_verified"] = int(len(a))
    out["correct_alerts"] = tp
    out["false_alerts"] = fp
    out["uncertain_alerts"] = int((a.verdict == "uncertain").sum())
    out["precision_correct_alert_rate"] = _rate(tp, tp + fp)
    out["false_alert_rate"] = _rate(fp, tp + fp)
    out["controls_verified"] = int(len(c))
    out["missed_detections"] = fn
    out["recall"] = _rate(tp, tp + fn) if (tp + fn) else None
    out["confusion"] = {"alert_confirmed": tp, "alert_rejected": fp, "no_alert_confirmed": fn, "no_alert_rejected": tn}
    lag = a["lag_days"].dropna() if "lag_days" in a else pd.Series(dtype=float)
    out["verification_lag_days"] = ({"n": int(len(lag)), "median": float(lag.median()), "min": float(lag.min()),
                                     "max": float(lag.max())} if len(lag) else None)
    out["by_alert_level"] = {lvl: {"confirmed": int(((a.alert_level == lvl) & (a.verdict == "confirmed")).sum()),
                                   "rejected": int(((a.alert_level == lvl) & (a.verdict == "rejected")).sum()),
                                   "uncertain": int(((a.alert_level == lvl) & (a.verdict == "uncertain")).sum())}
                             for lvl in levels}
    decided = tp + fp + fn + tn
    mn = cfg["validation"]["min_decided_for_metrics"]
    out["status"] = "ok" if decided >= mn else "descriptive_only"
    out["message"] = (f"{decided} decided verifications (minimum {mn} for reliable rates). "
                      "Treat rates as descriptive; the 95% intervals show how uncertain they are."
                      if decided < mn else "")
    return out
