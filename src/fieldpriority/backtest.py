"""Backtest: replay past seasons month by month and compare with what is known to have happened.

This is the accuracy check that is possible BEFORE field visits exist. It answers:
  * In a known drought season, does the system flag possible drought stress, and how early?
  * In a known good season, does it stay quiet (no false drought alerts)?

It is NOT field-level accuracy. The reference is area-level (province / national reports), the pilot has
5 fields, and the field polygons were drawn for one season. Field verification (validate.py) remains the
real accuracy measure. Results are written to outputs/backtest/ only; the real alert ledger is never touched.

Run:  python -m fieldpriority.backtest                 (seasons listed in config/backtest_reference.csv)
"""
import argparse
import contextlib
import copy
import datetime as dt
import hashlib
import io
import json
from pathlib import Path

import pandas as pd
import yaml

from .config import load_config
from .model.rules import month_end

MON = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
DROUGHT_LEVELS = {"Critical", "High", "Moderate"}


def rules_fingerprint(cfg):
    """Short hash of the rules thresholds. Record it BEFORE running a test season, so anyone can check
    the thresholds were not tuned after seeing the answer."""
    blob = yaml.safe_dump({"rules": cfg["rules"], "alerts": cfg["alerts"]}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:12]


def run_season(cfg, year, months, data_dir, out_dir):
    """Run the pipeline as it would have run at the end of each month (needs >= 2 months of data)."""
    from .pipeline import run
    rows = []
    for k in range(2, len(months) + 1):
        c = copy.deepcopy(cfg)
        c["year"], c["months"] = int(year), list(months[:k])
        c["period_label"] = f"{year}-{months[0]:02d}..{year}-{months[k - 1]:02d}"
        end = month_end(int(year), months[k - 1])
        with contextlib.redirect_stdout(io.StringIO()):
            _, docs, _ = run(c, data_dir, Path(out_dir) / f"{year}-{months[k - 1]:02d}",
                             alert_date=end, assessment_date=end)
        for d in docs:
            rows.append({"season": int(year), "month_end": end.isoformat(), "month": f"{MON[months[k - 1]]} {year}",
                         "field_id": d["field_id"], "outcome": d["outcome"], "risk_level": d["risk_level"],
                         "data_confidence": d["data_confidence"],
                         "contributing": "; ".join(d["explanation"]["contributing_indicators"]),
                         "what_changed": " | ".join(d["explanation"]["what_changed"])})
    return pd.DataFrame(rows)


def score(res, ref):
    """Compare one season's month-by-month results with the known outcome for that season."""
    exp = ref["expected"]
    flagged = res[res["risk_level"].isin(DROUGHT_LEVELS)]
    deficit = res[res["outcome"].str.startswith("Water deficit") | res["risk_level"].isin(DROUGHT_LEVELS)]
    fields = sorted(res["field_id"].unique())
    first = flagged.sort_values("month_end").groupby("field_id")["month_end"].first().to_dict()
    out = {"season": int(ref["season"]), "label": ref.get("label") or "", "months": ref.get("months"), "expected": exp, "area": ref.get("area"), "evidence": ref.get("evidence"),
           "source": ref.get("source"), "fields": len(fields), "field_months": int(len(res)),
           "field_months_flagged_drought": int(len(flagged)),
           "fields_flagged_drought": int(flagged["field_id"].nunique()),
           "fields_with_water_deficit_signal": int(deficit["field_id"].nunique()),
           "first_drought_flag_by_field": first,
           "insufficient_data_field_months": int((res["risk_level"] == "Insufficient data").sum())}
    if exp == "drought":
        out["result"] = ("DETECTED" if out["fields_flagged_drought"] else
                         "PARTLY (water deficit seen, no vegetation decline flagged)" if out["fields_with_water_deficit_signal"]
                         else "MISSED")
        ref_date = ref.get("reference_date")
        if first and isinstance(ref_date, str) and ref_date:
            d0 = dt.date.fromisoformat(ref_date)
            out["days_before_reference_date"] = {f: (d0 - dt.date.fromisoformat(v)).days for f, v in first.items()}
            out["reference_date"] = ref_date
    else:
        out["result"] = "NO FALSE ALERTS" if not out["fields_flagged_drought"] else \
            f"FALSE ALERTS on {out['fields_flagged_drought']} of {len(fields)} fields"
    return out


def run_backtest(cfg, ref_csv, out_dir):
    root = Path(cfg["_root"])
    refs = pd.read_csv(ref_csv, dtype=str).fillna("")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    all_res, summary = [], {"run_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                            "model_version": cfg.get("model_version"), "rules_fingerprint": rules_fingerprint(cfg),
                            "seasons": [],
                            "caveat": ("Area-level reference, not field-level ground truth; 5 pilot fields; polygons drawn "
                                       "for one season. Field verification is the real accuracy measure.")}
    for ref in refs.to_dict("records"):
        months = [int(m) for m in str(ref["months"]).split(";") if m]
        data_dir = (root / ref["data_dir"]) if not Path(ref["data_dir"]).is_absolute() else Path(ref["data_dir"])
        if not data_dir.exists() or not any(data_dir.glob(f"*{ref['season']}*.tif")):
            summary["seasons"].append({"season": int(ref["season"]), "label": ref.get("label") or "",
                                       "expected": ref["expected"], "result": "NOT RUN: no data yet",
                                       "todo": f"Export {ref['season']} rasters with gee/export_season.js into {ref['data_dir']}"})
            print(f"{ref['season']}: no rasters in {data_dir}; skipped")
            continue
        # the field boundaries live with the project's main data; copy them in so the season folder is complete
        shp = Path(cfg["paths"]["fields_shapefile"])
        main = root / cfg["paths"]["data_dir"]
        for f in main.glob(shp.stem + ".*"):
            if not (data_dir / f.name).exists():
                (data_dir / f.name).write_bytes(f.read_bytes())
        try:
            res = run_season(cfg, ref["season"], months, data_dir, out / "runs")
        except Exception as e:                       # missing files, wrong names, etc.
            summary["seasons"].append({"season": int(ref["season"]), "label": ref.get("label") or "",
                                       "expected": ref["expected"], "result": f"NOT RUN: {e}"})
            print(f"{ref['season']}: failed: {e}")
            continue
        all_res.append(res)
        s = score(res, ref)
        summary["seasons"].append(s)
        print(f"{ref['season']} {ref.get('label') or ''} ({ref['expected']}): {s['result']}")
    if all_res:
        pd.concat(all_res).to_csv(out / "backtest_results.csv", index=False)
    (out / "backtest_summary.json").write_text(json.dumps(summary, indent=2, default=str))
    return summary


def main():
    ap = argparse.ArgumentParser(description="Replay past seasons and compare with known outcomes")
    ap.add_argument("--config", default=None)
    ap.add_argument("--reference", default=None, help="default: config/backtest_reference.csv")
    ap.add_argument("--out-dir", default=None, help="default: outputs/backtest")
    a = ap.parse_args()
    cfg = load_config(a.config)
    root = Path(cfg["_root"])
    s = run_backtest(cfg, a.reference or root / "config" / "backtest_reference.csv",
                     a.out_dir or root / cfg["paths"]["output_dir"] / "backtest")
    print(f"\nRules fingerprint {s['rules_fingerprint']} (note it down before running a new test season).")
    print(s["caveat"])


if __name__ == "__main__":
    main()
