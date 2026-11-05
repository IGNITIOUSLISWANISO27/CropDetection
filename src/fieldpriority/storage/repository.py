"""One interface for the dashboard, with two backends: Firebase (Firestore) or local output files.
The dashboard only ever calls get_repository(...).load()."""
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import shape


@dataclass
class DashboardData:
    source: str = "none"
    source_note: str = ""
    fields: gpd.GeoDataFrame = None
    assessments: pd.DataFrame = None
    monthly: pd.DataFrame = None
    season: pd.DataFrame = None
    queue: pd.DataFrame = None
    verifications: pd.DataFrame = None
    metrics: dict = field(default_factory=dict)
    report: dict = field(default_factory=dict)
    meta: dict = field(default_factory=dict)
    ledger: pd.DataFrame = None          # every prediction ever issued (alerts_issued, rule 10): field history


def latest_per_field(docs):
    """One assessment per field: the most recent run. Firestore keeps the documents of earlier seasons (their id
    includes the period), so without this a field would appear once per season it was ever assessed."""
    best = {}
    for d in docs:
        k = (str(d.get("assessed_at") or ""), str(d.get("assessment_date") or ""), str(d.get("period") or ""))
        f = d.get("field_id")
        if f not in best or k >= best[f][0]:
            best[f] = (k, d)
    return [best[f][1] for f in sorted(best, key=str)]


def flatten_assessments(docs):
    rows = []
    for d in docs:
        r = {k: d.get(k) for k in ["id", "alert_id", "alert_date", "alert_level", "requires_verification", "field_id",
                                   "period", "assessed_at", "model_version", "method", "priority", "integrated_score",
                                   "regional_share", "confidence", "confidence_label",
                                   "outcome", "outcome_code", "risk_level", "data_confidence", "verification_status",
                                   "assessment_date", "data_end_date", "growth_stage", "growth_stage_label",
                                   "growth_stage_source", "next_action", "water_deficit", "vegetation_decline"]}
        r["data_confidence_issues"] = d.get("data_confidence_issues") or []
        r["missing_data"] = d.get("missing_data") or []
        r["explanation"] = d.get("explanation") or {}
        r["issued_prediction"] = d.get("issued_prediction") or {}
        for c, v in (d.get("components") or {}).items():
            r[f"score_{c}"] = v
        for c, v in (d.get("contributions") or {}).items():
            r[f"contrib_{c}"] = v
        for c, v in (d.get("confidence_parts") or {}).items():
            r[f"conf_{c}"] = v
        cells = d.get("climate_cells") or {}
        r.update(rain_cell=cells.get("rainfall"), sm_cell=cells.get("soil_moisture"), temp_cell=cells.get("temperature"),
                 rain_shared_with=cells.get("rainfall_shared_with"))
        e = d.get("experimental_fixed_reference") or {}
        r.update(exp_score=e.get("score"), exp_priority=e.get("priority"), exp_components=e.get("components_used"))
        v1 = d.get("v1_reference") or {}
        r.update(v1_priority=v1.get("priority"), v1_score=v1.get("integrated_score"))
        r["reasons"] = d.get("reasons") or []
        rows.append(r)
    return pd.DataFrame(rows)


def _empty(cols):
    return pd.DataFrame(columns=cols)


class LocalRepository:
    def __init__(self, outputs_dir):
        self.dir = Path(outputs_dir)

    def _csv(self, name, cols=()):
        p = self.dir / name
        return pd.read_csv(p) if p.exists() else _empty(cols)

    def _json(self, name, default):
        p = self.dir / name
        return json.loads(p.read_text()) if p.exists() else default

    def load(self):
        if not (self.dir / "risk_assessments.json").exists():
            raise FileNotFoundError(f"No pipeline outputs in {self.dir}. Run: python -m fieldpriority.pipeline")
        fields = gpd.read_file(self.dir / "fields_assessed.geojson")[["Field_ID", "area_ha", "geometry"]]
        docs = self._json("risk_assessments.json", [])
        ver = self._json("verification_records.json", None)
        ver = pd.DataFrame(ver) if ver is not None else self._csv("verification_records.csv")
        a0 = docs[0] if docs else {}
        a0 = {**a0, "assessment_date": a0.get("assessment_date")}
        return DashboardData(
            source="local", source_note=f"Local files in {self.dir}",
            fields=fields, assessments=flatten_assessments(docs),
            monthly=self._csv("indicators_monthly.csv"), season=self._csv("indicators_season.csv"),
            queue=self._csv("verification_queue.csv"), verifications=ver,
            metrics=self._json("validation_metrics.json", {}), report=self._json("pipeline_report.json", {}),
            ledger=self._csv("alerts_issued.csv"),
            meta={"period": a0.get("period"), "assessed_at": a0.get("assessed_at"),
                  "model_version": a0.get("model_version"), "alert_date": a0.get("alert_date"),
                  "assessment_date": a0.get("assessment_date")})


def _current_queue(rows, docs):
    """Verification queue of the latest run only (older alerts stay in the ledger, alerts_issued)."""
    q = pd.DataFrame(rows).drop(columns=["_doc_id"], errors="ignore")
    ids = {d.get("alert_id") for d in docs if d.get("alert_id")}
    return q[q["alert_id"].isin(ids)].reset_index(drop=True) if len(q) and "alert_id" in q and ids else q


class FirebaseRepository:
    def __init__(self, store):
        self.store = store

    def load(self):
        s = self.store
        fdocs = s.read("fields")
        if not fdocs:
            raise FileNotFoundError("Firestore has no data yet. Run: python -m fieldpriority.sync_firebase")
        fields = gpd.GeoDataFrame(
            [{"Field_ID": d["Field_ID"], "area_ha": d.get("area_ha"),
              "geometry": shape(json.loads(d["geometry_geojson"]))} for d in fdocs],
            geometry="geometry", crs=4326).sort_values("Field_ID").reset_index(drop=True)
        docs = latest_per_field(s.read("risk_assessments"))
        runs = s.read("runs")
        ver = s.read("verifications")
        return DashboardData(
            source="firebase", source_note="Firebase (Firestore)" + (f", collections {s.prefix}*" if getattr(s, "prefix", "") else ""),
            fields=fields, assessments=flatten_assessments(docs),
            monthly=pd.DataFrame(s.read("indicators")).drop(columns=["_doc_id"], errors="ignore"),
            season=pd.DataFrame(s.read("season_features")).drop(columns=["_doc_id"], errors="ignore").sort_values("Field_ID"),
            queue=_current_queue(s.read("alerts"), docs),
            verifications=pd.DataFrame(ver).drop(columns=["_doc_id"], errors="ignore") if ver else _empty([]),
            metrics=s.read_doc("metrics", "validation_latest"),
            report=sorted(runs, key=lambda r: str(r.get("run_at")))[-1] if runs else {},
            ledger=pd.DataFrame(s.read("alerts_issued")).drop(columns=["_doc_id"], errors="ignore"),
            meta=s.read_doc("meta", "latest"))


def get_repository(source="auto", outputs_dir="outputs", cred=None, store=None, prefix=None):
    """source: 'local' | 'firebase' | 'auto' (Firebase if a key is configured and reachable, else local)."""
    if store is not None:
        return FirebaseRepository(store)
    from .firebase_client import find_credentials
    cred = find_credentials(cred)
    if source in ("firebase", "auto") and cred:
        try:
            from .firebase_client import FirebaseStore
            repo = FirebaseRepository(FirebaseStore.connect(cred, prefix))
            repo.load()      # fail early so 'auto' can fall back
            return repo
        except Exception:
            if source == "firebase":
                raise
    elif source == "firebase":
        raise RuntimeError("Firebase key not found. Online (Streamlit Cloud): add it under Manage app > Settings > "
                           "Secrets as a [firebase] section (make_streamlit_secrets.bat makes the text). On a PC: save "
                           "it as firebase-key.json in the project folder, or set FIREBASE_CRED_PATH.")
    return LocalRepository(outputs_dir)
