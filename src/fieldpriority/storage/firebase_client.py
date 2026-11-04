"""Firestore layer (the 'Firebase' box in the system diagram).

Collections
  fields             one doc per field: area_ha, geometry_geojson (string)
  indicators         one doc per field x variable x month (zonal mean, valid fraction, climate cell)
  season_features    one doc per field: all per-field features used by scoring and the dashboard
  risk_assessments   one doc per field and period: priority, scores, confidence, reasons
  alerts             verification queue, one doc per Alert ID
  alerts_issued      append-only ledger of ORIGINAL predictions per Alert ID (rule 10; never overwritten)
  verifications      one doc per Kobo submission, with quality flags and status
  metrics            validation_latest + dated history
  runs               pipeline run reports (data-quality notes)
  meta               'latest' pointer (period, model version, alert date)
The class takes any object with the Firestore client API, so it can be tested with an in-memory fake.

Each pilot area has its own set of collections: `firebase.collection_prefix` in settings.yaml (e.g. "solwezi_")
is put in front of every name above, so Solwezi data never mixes with the earlier Chongwe data, which stays in
the unprefixed collections (its original predictions are kept, rule 10).
"""
import datetime as dt
import json
import math
import os
import re

import numpy as np
import pandas as pd

from pathlib import Path

BATCH = 400  # Firestore limit is 500 writes per batch
ROOT = Path(__file__).resolve().parents[3]
KEY_NAMES = ["firebase-key.json", "keys/firebase-key.json"]


def cloud_credentials():
    """Service-account key supplied as a secret instead of a file (online dashboard): the [firebase] table of
    Streamlit secrets, or the FIREBASE_KEY_JSON environment variable. Returns a dict or None."""
    raw = os.environ.get("FIREBASE_KEY_JSON")
    if raw:
        try:
            return json.loads(raw)
        except ValueError:
            pass
    try:
        import streamlit as st
        if "firebase" in st.secrets:
            return {k: v for k, v in st.secrets["firebase"].items()}
    except Exception:                       # streamlit not installed, or no secrets file
        pass
    return None


def find_credentials(cred=None, search_dirs=None):
    """Service-account key: explicit argument (path or dict), then FIREBASE_CRED_PATH, then firebase-key.json
    in the project folder (or keys/), then a key stored as a secret (cloud_credentials). None if nothing found."""
    if isinstance(cred, dict):
        return cred
    for c in (cred, os.environ.get("FIREBASE_CRED_PATH")):
        if c and os.path.exists(c):
            return str(c)
    for d in (search_dirs or [ROOT]):
        for n in KEY_NAMES:
            if (Path(d) / n).exists():
                return str(Path(d) / n)
    return cloud_credentials()


def safe_key(k):
    """Firestore rejects field names like __name__ (reserved) and empty names. Kobo adds '__version__'."""
    k = str(k)
    if not k:
        return "_blank"
    if re.fullmatch(r"__.*__", k):
        return "kobo" + k            # '__version__' -> 'kobo__version__'
    return k


def clean(o):
    """Make any value Firestore/JSON safe: NaN -> None, numpy -> python, dates -> ISO strings,
    reserved field names renamed."""
    if isinstance(o, dict):
        return {safe_key(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple, set)):
        return [clean(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        return None if (o != o or math.isinf(o)) else float(o)
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, (pd.Timestamp, dt.datetime, dt.date)):
        return o.isoformat()
    if o is pd.NaT or o is pd.NA:
        return None
    return o


def default_prefix():
    try:
        from ..config import load_config
        return (load_config().get("firebase") or {}).get("collection_prefix", "") or ""
    except Exception:
        return ""


class FirebaseStore:
    def __init__(self, db, prefix=""):
        self.db = db
        self.prefix = prefix or ""

    def col(self, name):
        """Collection for this pilot area (prefix + name)."""
        return self.db.collection(self.prefix + name)

    @classmethod
    def connect(cls, cred_path=None, prefix=None):
        try:
            import firebase_admin
            from firebase_admin import credentials, firestore
        except ImportError as e:
            raise RuntimeError("pip install firebase-admin") from e
        cred_path = find_credentials(cred_path)
        if not cred_path:
            raise RuntimeError("Firebase key not found. Save it as firebase-key.json in the project folder, "
                               "or set FIREBASE_CRED_PATH, or pass --cred")
        if not firebase_admin._apps:
            firebase_admin.initialize_app(credentials.Certificate(cred_path))
        return cls(firestore.client(), default_prefix() if prefix is None else prefix)

    # ---- writes
    def _write(self, coll, docs):
        docs = list(docs)
        for i in range(0, len(docs), BATCH):
            batch = self.db.batch()
            for doc_id, data in docs[i:i + BATCH]:
                batch.set(self.col(coll).document(str(doc_id)), clean(data), merge=True)
            batch.commit()
        return len(docs)

    def push_run(self, fields, season, monthly, assessments, queue, report):
        n = 0
        n += self._write("fields", [(r.Field_ID, {"Field_ID": r.Field_ID, "area_ha": float(r.area_ha),
                                                  "geometry_geojson": json.dumps(r.geometry.__geo_interface__)})
                                    for r in fields.itertuples()])
        n += self._write("indicators", [(f"{r['Field_ID']}_{r['variable']}_{int(r['month']):02d}", r)
                                        for r in monthly.to_dict("records")])
        n += self._write("season_features", [(r["Field_ID"], r) for r in season.to_dict("records")])
        n += self._write("risk_assessments", [(a["id"], a) for a in assessments])
        n += self._write("alerts", [(r["alert_id"], r) for r in queue.to_dict("records")])
        run_id = str(report.get("run_at", dt.datetime.now(dt.timezone.utc).isoformat()))
        n += self._write("runs", [(run_id, report)])
        a0 = assessments[0]
        n += self._write("meta", [("latest", {"run_id": run_id, "period": a0["period"],
                                              "assessed_at": a0["assessed_at"], "model_version": a0["model_version"],
                                              "alert_date": a0["alert_date"],
                                              "assessment_date": a0.get("assessment_date")})])
        return n

    def push_ledger(self, rows):
        """Rule 10: write issued predictions only for alert IDs not already stored. Existing ones are kept."""
        coll = self.col("alerts_issued")
        have = {d.id for d in coll.stream()}
        new = [(r["alert_id"], r) for r in rows if str(r["alert_id"]) not in have]
        return self._write("alerts_issued", new) if new else 0

    def push_validation(self, records, metrics):
        """records: list of dicts from process_records(); metrics: dict from compute_metrics()."""
        now = dt.datetime.now(dt.timezone.utc)
        docs = []
        for r in records:
            doc_id = r.get("_id") or r.get("_uuid") or f"{r.get('alert_id')}_{r.get('visit_date')}"
            docs.append((doc_id, r))
        n = self._write("verifications", docs)
        n += self._write("metrics", [("validation_latest", {**metrics, "updated_at": now}),
                                     (f"validation_{now:%Y%m%d-%H%M%S}", {**metrics, "updated_at": now})])
        n += self._write("meta", [("latest_validation", {"updated_at": now, "records": len(docs)})])
        return n

    # ---- reads
    def read(self, coll):
        out = []
        for d in self.col(coll).stream():
            x = d.to_dict() or {}
            x["_doc_id"] = d.id
            out.append(x)
        return out

    def read_doc(self, coll, doc_id):
        d = self.col(coll).document(doc_id).get()
        return (d.to_dict() or {}) if getattr(d, "exists", True) else {}
