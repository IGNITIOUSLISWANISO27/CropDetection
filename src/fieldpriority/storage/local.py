"""Write pipeline outputs to disk (CSV / JSON / GeoJSON)."""
import json
from pathlib import Path
import pandas as pd


def write_outputs(out_dir, monthly, season, assessments_df, assessments, fields, report, queue=None):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    if queue is not None:
        queue.to_csv(out / "verification_queue.csv", index=False)
    monthly.to_csv(out / "indicators_monthly.csv", index=False)
    season.to_csv(out / "indicators_season.csv", index=False)
    assessments_df.to_csv(out / "risk_assessments.csv", index=False)
    (out / "risk_assessments.json").write_text(json.dumps(assessments, indent=2, default=_j))
    (out / "pipeline_report.json").write_text(json.dumps(report, indent=2, default=_j))
    # fields.geojson with latest assessment properties for map layers
    g = fields.merge(assessments_df[["Field_ID", "outcome", "risk_level", "data_confidence", "priority",
                                     "integrated_score", "confidence", "confidence_label", "regional_share"]],
                     on="Field_ID")
    g.to_file(out / "fields_assessed.geojson", driver="GeoJSON")
    return out


LEDGER_COLUMNS = ["alert_id", "field_id", "alert_date", "assessment_date", "data_end_date", "model_version",
                  "outcome", "risk_level", "data_confidence", "growth_stage", "contributing_indicators",
                  "issued_at"]


def seed_ledger_from_legacy(path, assessments_json):
    """First run of the rules version: alerts already issued by the v1 score are written to the ledger
    exactly as issued, so their original prediction is kept (rule 10). Returns the number of rows seeded."""
    path, src = Path(path), Path(assessments_json)
    if path.exists() or not src.exists():
        return 0
    docs = json.loads(src.read_text())
    legacy = [d for d in docs if "alert_id" in d and "risk_level" not in d]
    if not legacy:
        return 0
    lvl = {"High priority": "High", "Moderate priority": "Moderate", "Low priority": "Low"}
    rows = [{"alert_id": d["alert_id"], "field_id": d["field_id"], "alert_date": d.get("alert_date"),
             "assessment_date": None, "data_end_date": None, "model_version": d.get("model_version"),
             "outcome": f"Legacy v1 score: {d.get('priority')}", "risk_level": lvl.get(d.get("priority"), "Not assessed"),
             "data_confidence": d.get("confidence_label"), "growth_stage": None,
             "contributing_indicators": None, "issued_at": d.get("assessed_at")} for d in legacy]
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=LEDGER_COLUMNS).to_csv(path, index=False)
    return len(rows)


def update_ledger(path, docs, issued_at):
    """Rule 10: keep the ORIGINAL prediction for every alert ID. New alert IDs are appended; an existing
    alert ID is never rewritten. If a re-run gives a different prediction for an existing ID, the
    original stays and a note is returned (issue a new alert date to record a new prediction)."""
    path = Path(path)
    old = pd.read_csv(path, dtype=str) if path.exists() else pd.DataFrame(columns=LEDGER_COLUMNS)
    have = dict(zip(old["alert_id"], old.to_dict("records")))
    notes, new = [], []
    for d in docs:
        row = {"alert_id": d["alert_id"], "field_id": d["field_id"], "alert_date": d["alert_date"],
               "assessment_date": d.get("assessment_date"), "data_end_date": d.get("data_end_date"),
               "model_version": d.get("model_version"), "outcome": d["outcome"], "risk_level": d["risk_level"],
               "data_confidence": d["data_confidence"], "growth_stage": d.get("growth_stage"),
               "contributing_indicators": "; ".join(d["explanation"]["contributing_indicators"]),
               "issued_at": issued_at}
        prev = have.get(d["alert_id"])
        if prev is None:
            new.append(row)
            d["issued_prediction"] = {k: row[k] for k in ("outcome", "risk_level", "data_confidence", "model_version", "issued_at")}
        else:
            d["issued_prediction"] = {k: prev.get(k) for k in ("outcome", "risk_level", "data_confidence", "model_version", "issued_at")}
            if (prev.get("outcome"), prev.get("risk_level")) != (row["outcome"], row["risk_level"]):
                notes.append(f"LEDGER {d['alert_id']}: this run gives '{row['outcome']}' ({row['risk_level']}) but the "
                             f"issued prediction '{prev.get('outcome')}' ({prev.get('risk_level')}) is kept. "
                             f"Use a new --alert-date to issue a new prediction.")
    if new:
        path.parent.mkdir(parents=True, exist_ok=True)
        pd.concat([old, pd.DataFrame(new, columns=LEDGER_COLUMNS)], ignore_index=True).to_csv(path, index=False)
    return notes


def _j(o):
    try:
        import numpy as np
        if isinstance(o, (np.integer,)):
            return int(o)
        if isinstance(o, (np.floating,)):
            return None if o != o else float(o)
        if isinstance(o, np.ndarray):
            return o.tolist()
    except ImportError:
        pass
    if pd.isna(o):
        return None
    return str(o)
