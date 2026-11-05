"""Drought test: replay the district layers on the 2023/24 drought and on the good 2024/25 season.

For each run in config/drought_test_2024.yaml the district layers are rebuilt for that period only (the same code
and thresholds as the live platform), each district gets the platform's assessment (concern / watch / normal), and
the result is compared with what is known to have happened:
  - 2023/24: 84 districts in seven provinces were declared drought-affected (national disaster, 29 Feb 2024);
    Northern, Luapula and Muchinga were not.
  - 2024/25: a good season; the platform should stay quiet.

Run:  python -m fieldpriority.national.drought_test [--offline]     (or run_drought_test.bat)
Writes outputs/drought_test/: summary.json, district_results.csv, DROUGHT_TEST_RESULTS.md, and one folder per run.
The live district layers (outputs/national/) are not touched.
"""
import argparse
import datetime as dt
import hashlib
import json
import math
from pathlib import Path

import pandas as pd
import yaml

from . import load_national_config, month_end, parse_period
from .interpret import interpret

FLAG = ("concern", "watch")


def fingerprint(cfg):
    """Fingerprint of the thresholds and the interpretation rules: proves they were not tuned to this test."""
    h = hashlib.sha256(yaml.safe_dump(cfg["classes"], sort_keys=True).encode())
    h.update((Path(__file__).parent / "interpret.py").read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()[:12]


def wilson(k, n, z=1.96):
    if not n:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(max(0, c - h), 3), round(min(1, c + h), 3)]


def assess(out_dir, cfg, districts):
    """One row per district: level, rainfall/vegetation/soil moisture anomalies, from a built folder."""
    ind = pd.read_csv(Path(out_dir) / "district_indicators.csv")
    rows = []
    for d in districts.itertuples():
        t = ind[ind["location_id"] == d.district_id]
        recs = {r["indicator"]: {k: (None if isinstance(v, float) and v != v else v) for k, v in r.items()}
                for r in t.to_dict("records")}
        it = interpret(d.district, recs, cfg["classes"])
        val = lambda k: (recs.get(k) or {}).get("value") if (recs.get(k) or {}).get("status") == "ok" else None
        rows.append({"district_id": d.district_id, "district": d.district, "province": d.province,
                     "level": it["level"], "signals": "; ".join(it["concern"]),
                     "rain_pct": val("rainfall_anomaly_pct"), "veg_pct": val("vegetation_anomaly_pct"),
                     "sm_pct": val("soil_moisture_anomaly_pct"), "temp_dev": val("temperature_deviation")})
    return pd.DataFrame(rows)


def score(R, affected_provs, kind):
    R = R.copy()
    R["truth"] = R["province"].isin(affected_provs) if kind == "drought" else False
    R["flagged"] = R["level"].isin(FLAG)
    R["concern"] = R["level"] == "concern"
    known = R[R["level"] != "unknown"]
    out = {"districts": len(R), "assessed": len(known)}
    for key in ("flagged", "concern"):
        a, n = known[known["truth"]], known[~known["truth"]]
        tp, fp = int(a[key].sum()), int(n[key].sum())
        o = {"flagged": int(known[key].sum())}
        if len(a):
            o.update(hit=tp, of_affected=len(a), hit_rate=round(tp / len(a), 3), hit_ci95=wilson(tp, len(a)))
        if len(n):
            o.update(false_alarms=fp, of_not_affected=len(n), false_alarm_rate=round(fp / len(n), 3),
                     false_alarm_ci95=wilson(fp, len(n)))
        if len(a) and len(n):
            o["accuracy"] = round((tp + len(n) - fp) / len(known), 3)
        out[key] = o
    out["median_rain_pct"] = {
        "affected": _med(known[known["truth"]]["rain_pct"]), "not_affected": _med(known[~known["truth"]]["rain_pct"])}
    out["by_province"] = {p: {"flagged": int(g["flagged"].sum()), "districts": len(g),
                              "median_rain_pct": _med(g["rain_pct"])}
                          for p, g in known.groupby("province")}
    return out, R


def _med(s):
    s = pd.to_numeric(s, errors="coerce").dropna()
    return None if s.empty else round(float(s.median()), 1)


def run(offline=False, only=None, log=print):
    from .build import build, load_districts
    base = load_national_config()
    root = Path(base["_root"])
    spec = yaml.safe_load((root / "config" / "drought_test_2024.yaml").read_text(encoding="utf-8"))
    out_root = root / "outputs" / "drought_test"
    out_root.mkdir(parents=True, exist_ok=True)
    districts = load_districts(base)
    lag = int(base["season"].get("data_lag_days", 20))
    affected = spec["reference"]["affected_provinces"]
    fp = fingerprint(base)
    log(f"Drought test: thresholds and rules fingerprint {fp}")
    results, rows = [], []
    for r in spec["runs"]:
        if only and r["name"] not in only:
            continue
        cfg = load_national_config()
        cfg.update(period=r["period"], output_dir=f"outputs/drought_test/{r['name']}", skip_zones=True)
        log(f"\n===== {r['name']} ({r['period']}) =====")
        build(cfg, offline=offline, log=log)
        rep = json.loads((root / cfg["output_dir"] / "national_report.json").read_text())
        last = parse_period(r["period"])[-1]
        run_date = month_end(*last) + dt.timedelta(days=lag)
        R = assess(root / cfg["output_dir"], base, districts)
        s, R = score(R, affected, r["kind"])
        s.update(name=r["name"], period=r["period"], kind=r["kind"], period_label=rep.get("period_label"),
                 baseline_seasons=rep.get("baseline_seasons"), run_date=str(run_date),
                 before_declaration=run_date < dt.date.fromisoformat(spec["declared"]) if r["kind"] == "drought"
                 else None)
        results.append(s)
        rows.append(R.assign(run=r["name"], period=r["period"], kind=r["kind"]))
        f = s["flagged"]
        log(f"{r['name']}: flagged {f['flagged']} of {s['assessed']} districts"
            + (f"; affected caught {f['hit']}/{f['of_affected']}" if "hit" in f else "")
            + (f"; false alarms {f['false_alarms']}/{f['of_not_affected']}" if "false_alarms" in f else ""))
    summary = {"test": spec["event"], "declared": spec["declared"], "fingerprint": fp,
               "reference": spec["reference"], "generated": dt.datetime.now().isoformat(timespec="seconds"),
               "offline": offline, "runs": results}
    (out_root / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    # copy kept with the code, so the online dashboard's About page can show the result
    (root / "config" / "drought_test_results.json").write_text(json.dumps(summary, indent=1, default=str))
    if rows:
        pd.concat(rows).to_csv(out_root / "district_results.csv", index=False)
    (out_root / "DROUGHT_TEST_RESULTS.md").write_text(report_md(summary), encoding="utf-8")
    log(f"\nResults: {out_root / 'DROUGHT_TEST_RESULTS.md'}")
    return summary


def _pct(x):
    return "–" if x is None else f"{x * 100:.0f}%"


def _ci(c):
    return "" if not c else f" (95% range {c[0] * 100:.0f}–{c[1] * 100:.0f}%)"


def report_md(S):
    L = [f"# Drought test: {S['test']}", "",
         f"Generated {S['generated']} · thresholds and rules fingerprint `{S['fingerprint']}`"
         + (" · run offline on data already on disk" if S.get("offline") else ""), "",
         "The district layers were rebuilt for each period with the same code and thresholds as the live platform, "
         "and each district's assessment was compared with what happened. A district counts as **flagged** when the "
         "platform says *watch* or *concern*.", "",
         f"Reference: {S['reference']['note']}", "",
         "| Run | Data up to | Would have run on | Flagged | Affected districts caught | False alarms (not affected) | "
         "Median rainfall vs normal (affected / not) |", "|---|---|---|---|---|---|---|"]
    for r in S["runs"]:
        f = r["flagged"]
        caught = f"{f['hit']}/{f['of_affected']} = {_pct(f['hit_rate'])}" if "hit" in f else "–"
        fa = f"{f['false_alarms']}/{f['of_not_affected']} = {_pct(f['false_alarm_rate'])}" if "false_alarms" in f \
            else "–"
        mr = r["median_rain_pct"]
        rain = (f"{mr['affected']:+.0f}% / {mr['not_affected']:+.0f}%" if r["kind"] == "drought" and
                mr["affected"] is not None and mr["not_affected"] is not None else
                (f"{mr['not_affected']:+.0f}% (all)" if mr["not_affected"] is not None else "–"))
        when = r["run_date"] + (" (before the declaration)" if r.get("before_declaration") else "")
        L.append(f"| {r['name']} ({r['kind']}) | {r['period_label']} | {when} | {f['flagged']}/{r['assessed']} | "
                 f"{caught} | {fa} | {rain} |")
    L += ["", "## By province (flagged districts / districts)", ""]
    names = [r["name"] for r in S["runs"]]
    provs = sorted({p for r in S["runs"] for p in r["by_province"]})
    L.append("| Province | " + " | ".join(names) + " |")
    L.append("|---" * (len(names) + 1) + "|")
    for p in provs:
        L.append(f"| {p}{' *' if p in S['reference']['affected_provinces'] else ''} | " + " | ".join(
            f"{r['by_province'].get(p, {}).get('flagged', '–')}/{r['by_province'].get(p, {}).get('districts', '–')}"
            for r in S["runs"]) + " |")
    L += ["", "\\* province declared drought-affected in 2024.", "",
          "## Limits", "",
          "- The reference is province-level: the government did not publish severity per district, so every district "
          "in the seven provinces counts as affected even if some were hit less.",
          "- This tests the district layers (rainfall, temperature, satellite vegetation and soil moisture), not the "
          "field-level alerts. Field accuracy needs verified field visits.",
          "- The normal is the same months of up to 10 earlier seasons (fewer when older data is not on disk).", ""]
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description="Replay the district layers on the 2023/24 drought")
    ap.add_argument("--offline", action="store_true", help="use only data already on disk")
    ap.add_argument("--only", nargs="*", help="run names to replay (default: all)")
    a = ap.parse_args()
    run(offline=a.offline, only=a.only)


if __name__ == "__main__":
    main()
