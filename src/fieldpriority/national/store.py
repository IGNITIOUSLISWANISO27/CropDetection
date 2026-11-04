"""Read and write the district layers: local files (outputs/national) or Firebase (national_* collections).

Firestore layout (one document per district keeps the monthly write count small):
  national_indicators/<district_id>   {district_id, records: [indicator records]}
  national_monthly/<district_id>      {district_id, rows: [[variable, year, month, value], ...]}
  national_seasons/<district_id>      {district_id, rows: [season rows]}
  national_meta/latest                national_report.json
"""
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

import geopandas as gpd
import pandas as pd

from . import load_national_config


@dataclass
class NationalData:
    districts: gpd.GeoDataFrame = None
    indicators: pd.DataFrame = None
    monthly: pd.DataFrame = None
    seasons: pd.DataFrame = None
    report: dict = field(default_factory=dict)
    source_note: str = ""

    @property
    def available(self):
        return self.indicators is not None and len(self.indicators) > 0


def _clean(ind):
    """Text columns as text ('' when empty); value stays numeric (None when there is no number)."""
    if ind is None or ind.empty:
        return ind
    ind = ind.copy()
    for c in ind.columns:
        if c != "value":
            ind[c] = ind[c].where(ind[c].notna(), "").astype(str)
    ind["value"] = pd.to_numeric(ind["value"], errors="coerce")
    return ind


def _districts(cfg):
    from .build import load_districts
    return load_districts(cfg)


def load_local(cfg=None, out_dir=None):
    cfg = cfg or load_national_config()
    d = Path(out_dir or os.environ.get("FIELDPRIORITY_NATIONAL_OUTPUTS") or Path(cfg["_root"]) / cfg["output_dir"])
    if not (d / "district_indicators.csv").exists():
        return NationalData(_districts(cfg), source_note="No district layers yet (run monthly_update.bat)")
    return NationalData(_districts(cfg), _clean(pd.read_csv(d / "district_indicators.csv")),
                        pd.read_csv(d / "district_monthly.csv"), pd.read_csv(d / "district_seasons.csv"),
                        json.loads((d / "national_report.json").read_text()), f"Local files in {d}")


def push(store, cfg=None, out_dir=None):
    """Upload the latest district layers. `store` is a FieldPriority FirebaseStore with prefix 'national_'."""
    nd = load_local(cfg, out_dir)
    if not nd.available:
        raise FileNotFoundError("No district layers to upload: run python -m fieldpriority.national.build first")
    n = 0
    ind = nd.indicators.astype(object).where(nd.indicators.notna(), None)
    n += store._write("indicators", [(did, {"district_id": did, "records": g.to_dict("records")})
                                     for did, g in ind.groupby("location_id")])
    n += store._write("monthly", [(did, {"district_id": did,
                                         "rows": g[["variable", "year", "month", "value"]].values.tolist()})
                                  for did, g in nd.monthly.groupby("district_id")])
    s = nd.seasons.astype(object).where(nd.seasons.notna(), None)
    n += store._write("seasons", [(did, {"district_id": did, "rows": g.drop(columns="district_id").to_dict("records")})
                                  for did, g in s.groupby("district_id")])
    n += store._write("meta", [("latest", nd.report)])
    return n


def load_firebase(store, cfg=None):
    cfg = cfg or load_national_config()
    docs = store.read("indicators")
    if not docs:
        return NationalData(_districts(cfg), source_note="No district layers in Firebase yet")
    ind = pd.DataFrame([r for d in docs for r in (d.get("records") or [])])
    mon = pd.DataFrame([[d["district_id"], *r] for d in store.read("monthly") for r in (d.get("rows") or [])],
                       columns=["district_id", "variable", "year", "month", "value"])
    sea = pd.DataFrame([{"district_id": d["district_id"], **r} for d in store.read("seasons") for r in (d.get("rows") or [])])
    return NationalData(_districts(cfg), _clean(ind), mon, sea, store.read_doc("meta", "latest"),
                        "Firebase (Firestore), collections national_*")


def load(source="auto", cred=None, cfg=None, out_dir=None):
    """Same rule as the pilot data: Firebase when a key is configured (and it has district layers), else local."""
    cfg = cfg or load_national_config()
    from ..storage.firebase_client import find_credentials
    cred = find_credentials(cred)
    local = load_local(cfg, out_dir)
    if source in ("firebase", "auto") and cred:
        try:
            from ..storage.firebase_client import FirebaseStore
            nd = load_firebase(FirebaseStore.connect(cred, (cfg.get("firebase") or {}).get("collection_prefix",
                                                                                           "national_")), cfg)
            if nd.available and (source == "firebase" or not local.available or
                                 str(nd.report.get("built_at")) >= str(local.report.get("built_at"))):
                return nd
        except Exception:
            if source == "firebase":
                raise
    return local


def main():
    import argparse
    from ..storage.firebase_client import FirebaseStore
    ap = argparse.ArgumentParser(description="Upload the district layers to Firebase")
    ap.add_argument("--cred", default=None)
    a = ap.parse_args()
    cfg = load_national_config()
    n = push(FirebaseStore.connect(a.cred, (cfg.get("firebase") or {}).get("collection_prefix", "national_")), cfg)
    print(f"Synced {n} documents to Firebase (district layers, collections national_*)")


if __name__ == "__main__":
    main()
