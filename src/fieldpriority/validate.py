"""Kobo verification sync + validation metrics.

Run:  python -m fieldpriority.validate --kobo-api          (form and server from settings.yaml, token from .env)
      python -m fieldpriority.validate --kobo-csv export.csv
"""
import argparse
import datetime as dt
import json
import os
from pathlib import Path

import pandas as pd

from .config import load_config
from .ingest.kobo import read_kobo_csv, fetch_kobo_api, kobo_settings
from .validation.quality import load_field_map, load_alert_map, process_records
from .validation.metrics import compute_metrics
from .validation.register import to_register


def load_issued(assessments_json, ledger=None):
    """Issued alerts with their ORIGINAL prediction (rule 10). The append-only ledger
    (outputs/alerts_issued.csv) is the source of truth; risk_assessments.json is the fallback."""
    ledger = Path(ledger) if ledger else Path(assessments_json).with_name("alerts_issued.csv")
    if ledger.exists():
        d = pd.read_csv(ledger, dtype=str)
        return d.assign(alert_level=d["risk_level"])
    docs = json.load(open(assessments_json))
    if not docs or "alert_id" not in docs[0] or "risk_level" not in docs[0]:
        raise ValueError("assessments file has no rules outcome; re-run the pipeline (python -m fieldpriority.pipeline)")
    return pd.DataFrame([{"alert_id": d["alert_id"], "field_id": d["field_id"], "alert_date": d["alert_date"],
                          "outcome": d["outcome"], "risk_level": d["risk_level"], "alert_level": d["risk_level"],
                          "data_confidence": d["data_confidence"], "model_version": d.get("model_version")}
                         for d in docs])


def records_for_pilot(df, cfg, amap=None):
    """One Kobo form serves every pilot area. Keep the records that belong to this area: alert ID with this
    area's prefix (after an approved alias); otherwise, when the alert ID is not a FieldPriority ID, the Kobo
    'district' answer. Records without either stay with the default area (settings.yaml)."""
    from .validation.quality import exact_id
    if df is None or not len(df) or "alert_id" not in df:
        return df
    amap = amap or {}
    prefix = str(cfg["alerts"]["id_prefix"]).upper()
    district = str(cfg.get("pilot_district") or "").strip().lower()
    is_default = cfg.get("pilot_name") == "solwezi"

    def mine(r):
        aid = exact_id(r.get("alert_id"))
        aid = str(amap[aid]["alert_id"]).upper() if aid in amap else (aid or "")
        if aid.startswith(prefix + "-"):
            return True
        if aid.startswith("FP-"):
            return False
        d = str(r.get("district") or "").strip().lower()
        return d == district if d and d != "nan" else is_default
    keep = df.apply(mine, axis=1)
    return df[keep].reset_index(drop=True)


def run_validation(cfg, kobo_df, issued, out_dir, today=None):
    root = Path(cfg["_root"])
    fmap = load_field_map(root / cfg["validation"]["field_id_map"])
    amap = load_alert_map(root / cfg["validation"].get("alert_id_map", "config/alert_id_map.csv"))
    kobo_df = records_for_pilot(kobo_df, cfg, amap)
    rec = process_records(kobo_df, cfg, fmap, issued, today, amap)     # links visits to ANY issued alert
    # Evaluate the current model version only; older alerts keep their original prediction in the ledger.
    mv = cfg.get("model_version")
    scope = issued
    if "model_version" in issued and mv and (issued["model_version"] == mv).any():
        scope = issued[issued["model_version"] == mv]
    metrics = compute_metrics(rec, scope, cfg)
    metrics["model_version_evaluated"] = mv if scope is not issued else "all"
    metrics["alerts_in_ledger"] = int(len(issued))
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rec.drop(columns=["flags"], errors="ignore").to_csv(out / "verification_records.csv", index=False)
    from .storage.firebase_client import clean
    (out / "verification_records.json").write_text(json.dumps(clean(rec.to_dict("records")), indent=2))
    to_register(rec).to_csv(out / "validation_register.csv", index=False)
    (out / "validation_metrics.json").write_text(json.dumps(metrics, indent=2, default=str))
    return rec, metrics


def main():
    ap = argparse.ArgumentParser(description="FieldPriority Kobo validation")
    ap.add_argument("--config", default=None)
    ap.add_argument("--kobo-csv", default=None, help="Kobo CSV export (unchanged original)")
    ap.add_argument("--kobo-api", action="store_true",
                    help="download from Kobo (kobo: server/asset_uid in settings.yaml, KOBO_TOKEN in .env)")
    ap.add_argument("--assessments", default=None, help="default: <paths.output_dir>/risk_assessments.json")
    ap.add_argument("--out-dir", default=None, help="default: paths.output_dir in settings.yaml")
    ap.add_argument("--firebase", action="store_true", help="also push verifications and metrics to Firestore")
    ap.add_argument("--cred", default=None)
    a = ap.parse_args()
    cfg = load_config(a.config)
    out_default = Path(cfg["_root"]) / cfg["paths"]["output_dir"]
    a.out_dir = a.out_dir or str(out_default)
    a.assessments = a.assessments or str(Path(a.out_dir) / "risk_assessments.json")
    if a.kobo_api:
        server, uid, token = kobo_settings(cfg)
        try:
            df = fetch_kobo_api(server, token, uid, raw_dir=Path(a.out_dir) / "kobo_raw")
        except RuntimeError as e:
            raise SystemExit(f"Kobo download failed: {e}")
        print(f"Downloaded {len(df)} submissions from {server} form {uid}")
    elif a.kobo_csv:
        df = read_kobo_csv(a.kobo_csv)
    else:
        ap.error("give --kobo-csv or --kobo-api")
    rec, m = run_validation(cfg, df, load_issued(a.assessments), a.out_dir)

    if a.firebase:
        from .storage.firebase_client import FirebaseStore
        n = FirebaseStore.connect(a.cred).push_validation(rec.to_dict("records"), m)
        print(f"Pushed {n} verification records and metrics to Firebase")
    print(f"Records: {m['records_total']} (test, excluded {m['records_test']}; real {m['records_real']}); "
          f"eligible for metrics: {m['records_eligible']}")
    for r in rec.to_dict("records"):
        print(f"\n[{r.get('alert_id')}] {r.get('record_type')} -> {r['validation_status_final']} ({r['status_source']})")
        for f in r["flags"]:
            print(f"   {f['severity'].upper():7} {f['code']}: {f['text']}")
    print("\nMetrics:", json.dumps({k: v for k, v in m.items() if k in
          ("status", "message", "alerts_issued", "verification_rate", "correct_alerts", "false_alerts")}, indent=2, default=str))
    print(f"\nWritten to {a.out_dir}: verification_records.csv, validation_register.csv, validation_metrics.json")


if __name__ == "__main__":
    main()
