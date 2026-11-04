"""FieldPriority pipeline: Ingest -> Features -> Rules (+ legacy score) -> Explain -> Store.

The drought-stress rules (model/rules.py) decide the outcome and risk level of every field.
The v1 weighted score is still computed, but only as a relative ranking for comparison.

Run:  python -m fieldpriority.pipeline --data-dir /path/to/gee_qgis_exports
"""
import argparse
import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd

from .config import load_config
from .ingest.fields import load_fields
from .ingest.rasters import discover_rasters
from .features.indicators import build_monthly, build_season
from .features.tables import ensure_columns, add_table_inputs, annual_context, s1_context
from .model.scoring import (score_primary, score_reference, classify, COMPONENTS,
                            PRIMARY_INPUT)
from .model.normalise import cohort_minmax
from .model.confidence import compute_confidence
from .model.rules import assess_all, load_field_info, month_end
from .explain.reasons import build_reasons
from .storage.local import write_outputs, update_ledger, seed_ledger_from_legacy


def replication_check(ref, cfg):
    """Re-score the v1 reference values with the pipeline's scoring code and compare to the
    v1 'Integrated' column. Proves the pipeline reproduces the existing workflow."""
    d = ref.rename(columns={"ref_ndvi_composite": "greenness_seasonal",
                            "ref_rainfall_anomaly_mm": "rain_anom_mm_mean",
                            "ref_soil_moisture": "sm_mean",
                            "ref_temperature_c": "temp_c_mean"})
    need = ["Field_ID", "greenness_seasonal", "rain_anom_mm_mean", "sm_mean", "temp_c_mean",
            "ref_integrated_score"]
    if not set(need) <= set(d.columns):
        return {"available": False}
    s = score_primary(d, cfg)
    diff = (s["integrated_score"].values - d["ref_integrated_score"].values)
    return {"available": True, "max_abs_diff": float(np.nanmax(np.abs(diff))),
            "per_field": dict(zip(d["Field_ID"], np.round(diff, 6).tolist()))}


RISK_ORDER = {"High": 0, "Moderate": 1, "Not attributed": 2, "Watch": 3, "Low": 4, "Insufficient data": 5,
              "Not assessed": 6}
QUEUE_COLUMNS = ["alert_id", "field_id", "alert_date", "assessment_date", "visit_type", "outcome", "risk_level",
                 "data_confidence", "growth_stage", "contributing_indicators", "checks", "next_action", "area_ha",
                 "legacy_score"]


def visit_type(risk, cfg):
    a = cfg["alerts"]
    if risk in a["alert_levels"]:
        return "drought alert"
    if risk in a.get("check_levels", []):
        return "stress check (cause uncertain)"
    if risk in ("Watch", "Low"):
        return "control (optional)"
    return None                       # Insufficient data / Not assessed: fix data first, not a visit


def build_queue(full, docs, cfg):
    """The 'verification list' the SOP refers to: Alert ID + Field ID for each visit."""
    rows = []
    for d in docs:
        vt = visit_type(d["risk_level"], cfg)
        if vt is None or (vt.startswith("control") and not cfg["alerts"].get("include_controls", True)):
            continue
        f = full[full["Field_ID"] == d["field_id"]].iloc[0]
        rows.append({"alert_id": d["alert_id"], "field_id": d["field_id"], "alert_date": d["alert_date"],
                     "assessment_date": d["assessment_date"], "visit_type": vt, "outcome": d["outcome"],
                     "risk_level": d["risk_level"], "data_confidence": d["data_confidence"],
                     "growth_stage": d["growth_stage_label"],
                     "contributing_indicators": "; ".join(d["explanation"]["contributing_indicators"]),
                     "checks": " | ".join(d["explanation"]["checks"]), "next_action": d["next_action"],
                     "area_ha": round(float(f["area_ha"]), 2), "legacy_score": d["legacy"]["integrated_score"]})
    q = pd.DataFrame(rows, columns=QUEUE_COLUMNS)
    q["_o"] = q["risk_level"].map(RISK_ORDER)
    return q.sort_values(["_o", "legacy_score"], ascending=[True, False]).drop(columns="_o")


def reuse_unchanged_alerts(ledger_path, docs):
    """A rerun on the same data must not issue a new alert. If a field's most recent issued predictions have the
    same data end date, model version, outcome and risk level as this run, keep the alert ID that was issued
    first for that unchanged prediction, so field visits linked to it stay linked (rule 10)."""
    if not Path(ledger_path).exists():
        return []
    led = pd.read_csv(ledger_path, dtype=str).fillna("")
    notes = []
    for d in docs:
        key = (str(d.get("data_end_date") or ""), str(d.get("model_version") or ""), d["outcome"], d["risk_level"])
        rows = led[led["field_id"] == d["field_id"]].to_dict("records")
        first = None
        for row in reversed(rows):                 # walk back while the prediction is unchanged
            if (row.get("data_end_date", ""), row.get("model_version", ""), row["outcome"], row["risk_level"]) != key:
                break
            first = row
        if first and first["alert_id"] != d["alert_id"]:
            d["alert_id"], d["alert_date"] = first["alert_id"], first["alert_date"]
            notes.append(f"{d['field_id']}: same data and same result as alert {first['alert_id']}, so that alert "
                         f"is kept (no new alert issued)")
    for n in notes:
        print("NOTE:", n)
    return notes


def run(cfg, data_dir, out_dir, firebase=False, cred=None, alert_date=None, assessment_date=None):
    idc = cfg["fields"]["id_column"]
    notes = []

    # ---- Ingest
    fields, ref = load_fields(Path(data_dir) / cfg["paths"]["fields_shapefile"], idc)
    try:
        catalog, rnotes = discover_rasters(data_dir, cfg["year"], cfg["months"])
    except FileNotFoundError:
        catalog, rnotes = pd.DataFrame(columns=["variable", "month", "version", "path", "file"]), \
            [f"No monthly rasters for {cfg['year']} in {data_dir}"]
    if (Path(data_dir) / (cfg.get("tables") or {}).get("s1_vv_monthly", "s1_vv_monthly.csv")).exists():
        rnotes = [n for n in rnotes if "Sentinel-1" not in n]       # supplied as a table instead
    notes += rnotes
    for n in rnotes:
        print("NOTE:", n)
    core = ["ndvi", "rainfall_anomaly", "soil_moisture", "temperature"]
    absent = [v for v in core if not (catalog.variable == v).any()]
    if absent:
        # not fatal: missing inputs make the rules say "Insufficient data" (rule 7) and list what is missing
        notes.append(f"No monthly rasters for: {', '.join(absent)}")
    print(f"Found {len(catalog)} rasters in {data_dir}")

    # ---- Features (rasters, then tables imported from Earth Engine exports)
    monthly = build_monthly(fields, catalog, cfg)
    season = ensure_columns(build_season(monthly, fields, ref, cfg), cfg)
    season, monthly, tnotes = add_table_inputs(season, monthly, cfg, data_dir)
    notes += tnotes
    for r in monthly[(monthly.variable == "ndvi")].itertuples():
        if pd.notna(r.valid_fraction) and r.valid_fraction < cfg["extraction"]["min_valid_fraction"]:
            notes.append(f"LOW NDVI COVERAGE {r.Field_ID} month {r.month}: {r.valid_fraction*100:.0f}% valid")

    # ---- Scoring
    scored = score_primary(season, cfg)
    scored["priority"] = scored["integrated_score"].apply(lambda s: classify(s, cfg))
    exp = score_reference(season, cfg)
    exp["ref_method_priority"] = exp["ref_method_score"].apply(lambda s: classify(s, cfg))
    conf = compute_confidence(season, scored, cfg)

    for c in ("ref_priority", "ref_integrated_score"):
        if c not in ref.columns:
            ref[c] = np.nan
    full = (season.merge(scored, on="Field_ID").merge(conf, on="Field_ID")
                  .merge(exp, on="Field_ID").merge(ref[[idc, "ref_priority", "ref_integrated_score"]],
                                                    on=idc, how="left"))
    full["cohort_size"] = len(full)
    if len(full) < 2:
        # the legacy score ranks fields against each other; with one field it means nothing
        full["integrated_score"] = np.nan
        full["priority"] = "Unclassified"
        notes.append("Legacy relative score not computed: it needs at least two fields")

    # ---- Rules (decide outcome, risk level, data confidence; rules 1-9 and 12)
    data_end = month_end(int(cfg["year"]), sorted(cfg["months"])[-1])
    as_date = assessment_date or data_end
    finfo = load_field_info(Path(cfg["_root"]) / cfg["rules"]["field_info"])
    locs = {f: (g is not None and not g.is_empty) for f, g in zip(fields[idc], fields.geometry)}
    rules = {a["field_id"]: a for a in assess_all(season, cfg, as_date, finfo, locs)}
    for fid, a in rules.items():
        if a["missing_data"]:
            notes.append(f"INSUFFICIENT DATA {fid}: " + "; ".join(a["missing_data"]))

    # ---- Explain (legacy score reasons, kept as supporting context)
    reasons = {r[idc]: build_reasons(r, cfg) for r in full.to_dict("records")}
    for r in full.to_dict("records"):
        ctx = s1_context(r, sorted(cfg["months"])) + annual_context(r)
        rules[r[idc]]["explanation"]["context"] = ctx

    # ---- Assemble documents
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    a_date = alert_date or dt.date.today()
    a_cfg = cfg["alerts"]
    docs = []
    for r in full.to_dict("records"):
        fid = r[idc]
        ru = rules[fid]
        docs.append({
            "id": f"{fid}_{cfg['period_label']}",
            "alert_id": f"{a_cfg['id_prefix']}-{fid}-{a_date:%Y%m%d}",
            "alert_date": a_date.isoformat(),
            "field_id": fid,
            "period": cfg["period_label"],
            "assessed_at": now,
            "model_version": cfg["model_version"],
            "method": "drought-stress rules (config: rules)",
            # ---- rule outcome: three separate dimensions (rule 9)
            "outcome": ru["outcome"], "outcome_code": ru["outcome_code"],
            "risk_level": ru["risk_level"],
            "data_confidence": ru["data_confidence"],
            "data_confidence_issues": ru["data_confidence_issues"],
            "verification_status": "Not yet verified",
            "alert_level": ru["risk_level"],
            "requires_verification": ru["risk_level"] in a_cfg["alert_levels"] + a_cfg.get("check_levels", []),
            "missing_data": ru["missing_data"],
            "assessment_date": ru["assessment_date"], "data_end_date": ru["data_end_date"],
            "growth_stage": ru["growth_stage"], "growth_stage_label": ru["growth_stage_label"],
            "growth_stage_source": ru["growth_stage_source"], "days_after_planting": ru["days_after_planting"],
            "water_deficit": ru["water_deficit"], "vegetation_decline": ru["vegetation_decline"],
            "explanation": ru["explanation"], "next_action": ru["next_action"],
            # ---- legacy v1 relative score: comparison only, does not set the alert
            "legacy": {"priority": r["priority"], "integrated_score": round(float(r["integrated_score"]), 4),
                       "confidence": r["confidence"], "confidence_label": r["confidence_label"],
                       "note": "Relative ranking among pilot fields (v1 method). Not used for the alert."},
            "priority": r["priority"],
            "integrated_score": round(float(r["integrated_score"]), 4),
            "components": {c: round(float(r[f"{c}_score"]), 4) for c in COMPONENTS},
            "contributions": {c: round(float(r[f"{c}_contrib"]), 4) for c in COMPONENTS},
            "regional_share": round(float(r["regional_share"]), 3),
            "confidence": r["confidence"], "confidence_label": r["confidence_label"],
            "confidence_parts": {k: r.get(f"conf_{k}") for k in ("agreement", "data_quality", "size_support", "margin")},
            "climate_cells": {"rainfall": r["rain_cell"], "soil_moisture": r["sm_cell"],
                              "temperature": r["temp_cell"],
                              "rainfall_shared_with": r["rain_cell_shared_with"]},
            "experimental_fixed_reference": {"score": round(float(r["ref_method_score"]), 4),
                                             "priority": r["ref_method_priority"],
                                             "components_used": r["ref_method_components"]},
            "v1_reference": {"priority": r["ref_priority"], "integrated_score": r["ref_integrated_score"]},
            "reasons": reasons[fid],
        })

    full["outcome"] = full[idc].map(lambda f: rules[f]["outcome"])
    full["risk_level"] = full[idc].map(lambda f: rules[f]["risk_level"])
    full["data_confidence"] = full[idc].map(lambda f: rules[f]["data_confidence"])
    full["growth_stage"] = full[idc].map(lambda f: rules[f]["growth_stage"])
    keep = ["Field_ID", "area_ha", "outcome", "risk_level", "data_confidence", "growth_stage",
            "priority", "integrated_score", "confidence", "confidence_label",
            "regional_share", "greenness_score", "rainfall_score", "soil_moisture_score",
            "temperature_score", "ref_method_score", "ref_method_priority", "ref_priority",
            "ref_integrated_score", "rain_cell", "rain_cell_shared_with"]
    assess_df = full[keep]

    # ---- Rule 10: append-only ledger of issued predictions (never overwritten)
    ledger_path = Path(out_dir) / a_cfg.get("ledger", "alerts_issued.csv")
    if alert_date is None:
        notes += reuse_unchanged_alerts(ledger_path, docs)
    seeded = seed_ledger_from_legacy(ledger_path, Path(out_dir) / "risk_assessments.json")
    if seeded:
        notes.append(f"LEDGER: kept {seeded} alerts issued earlier by the v1 score exactly as issued")
    ledger_notes = update_ledger(ledger_path, docs, now)
    notes += ledger_notes
    for n in ledger_notes:
        print("NOTE:", n)

    report = {"run_at": now, "period": cfg["period_label"], "n_fields": len(full),
              "assessment_date": as_date.isoformat(), "data_end_date": data_end.isoformat(),
              "outcomes": {d["field_id"]: d["outcome"] for d in docs},
              "rasters_used": catalog[["variable", "month", "file"]].to_dict("records"),
              "notes": notes, "replication_check": replication_check(ref, cfg)}
    queue = build_queue(full, docs, cfg)
    write_outputs(out_dir, monthly, season, assess_df, docs, fields, report, queue)

    if firebase:
        from .storage.firebase_client import FirebaseStore
        report["firebase_documents"] = FirebaseStore.connect(cred).push_run(
            fields, season, monthly, docs, queue, report)
    return full, docs, report


def main():
    ap = argparse.ArgumentParser(description="FieldPriority pipeline")
    ap.add_argument("--config", default=None)
    ap.add_argument("--data-dir", default=None)
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--alert-date", default=None, help="date the alerts are issued, YYYY-MM-DD (default: today)")
    ap.add_argument("--assessment-date", default=None,
                    help="date the conditions are assessed for, YYYY-MM-DD (default: end of the latest data month). "
                         "Data ending more than rules.max_data_age_days before it gives 'Insufficient data'.")
    ap.add_argument("--firebase", action="store_true")
    ap.add_argument("--cred", default=None)
    a = ap.parse_args()
    cfg = load_config(a.config)
    root = Path(cfg["_root"])
    data_dir = Path(a.data_dir or root / cfg["paths"]["data_dir"])
    out_dir = Path(a.out_dir or root / cfg["paths"]["output_dir"])
    ad = dt.date.fromisoformat(a.alert_date) if a.alert_date else None
    asd = dt.date.fromisoformat(a.assessment_date) if a.assessment_date else None
    full, docs, rep = run(cfg, data_dir, out_dir, a.firebase, a.cred, ad, asd)

    pd.set_option("display.width", 200)
    cols = ["Field_ID", "outcome", "risk_level", "data_confidence", "growth_stage", "priority", "integrated_score"]
    print(full[cols].round(3).rename(columns={"priority": "legacy_priority",
                                              "integrated_score": "legacy_score"}).to_string(index=False))
    print("\nreplication check vs v1:", rep["replication_check"].get("max_abs_diff"))
    for n in rep["notes"]:
        print("NOTE:", n)
    print(f"\nOutputs written to {out_dir}")


if __name__ == "__main__":
    main()
