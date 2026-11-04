"""Push the latest local outputs to Firebase so the dashboard can read from it.

Run:  python -m fieldpriority.sync_firebase --cred C:\\keys\\firebase-key.json
"""
import argparse
import json
from pathlib import Path

import geopandas as gpd
import pandas as pd

from .storage.firebase_client import FirebaseStore


def sync(store, outputs_dir):
    d = Path(outputs_dir)
    fields = gpd.read_file(d / "fields_assessed.geojson")[["Field_ID", "area_ha", "geometry"]]
    docs = json.loads((d / "risk_assessments.json").read_text())
    report = json.loads((d / "pipeline_report.json").read_text())
    n = store.push_run(fields, pd.read_csv(d / "indicators_season.csv"), pd.read_csv(d / "indicators_monthly.csv"),
                       docs, pd.read_csv(d / "verification_queue.csv"), report)
    if (d / "alerts_issued.csv").exists():
        n += store.push_ledger(pd.read_csv(d / "alerts_issued.csv", dtype=str).to_dict("records"))
    ver = d / "verification_records.json"
    if ver.exists():
        metrics = json.loads((d / "validation_metrics.json").read_text())
        n += store.push_validation(json.loads(ver.read_text()), metrics)
    return n


def main():
    ap = argparse.ArgumentParser(description="Sync outputs/ to Firebase")
    ap.add_argument("--outputs", default=None, help="default: paths.output_dir in settings.yaml")
    ap.add_argument("--cred", default=None)
    a = ap.parse_args()
    from .config import load_config
    cfg = load_config()
    n = sync(FirebaseStore.connect(a.cred), a.outputs or Path(cfg["_root"]) / cfg["paths"]["output_dir"])
    print(f"Synced {n} documents to Firebase")


if __name__ == "__main__":
    main()
