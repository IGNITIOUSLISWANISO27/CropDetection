"""Monthly update: bring every layer up to the newest published data.

  1. Each pilot area with monitoring.auto_update: true moves to the newest Jan-Apr months with data: the field
     data is downloaded (Sentinel-2, CHIRPS, ERA5-Land; only what is missing), the season is recorded in
     <data_dir>/current_season.json and the assessment is rerun. Earlier alerts stay in the ledger (rule 10).
  2. Zambia district layers (rainfall, temperature, solar; vegetation, soil moisture and maize if the Earth
     Engine export is present) for the current season to date.

Run: monthly_update.bat (it also checks the Kobo visits and syncs Firebase), or
     python -m fieldpriority.monthly_update [--skip-national] [--skip-pilots]
"""
import argparse
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

from .config import available_pilots, load_config
from .national import month_end

FULL = ["", "January", "February", "March", "April"]
MON = ["", "Jan", "Feb", "Mar", "Apr"]


def pilot_window(today, lag_days=20):
    """Newest Jan-Apr months whose data should be published (a month counts lag_days after it ends)."""
    lag = dt.timedelta(days=lag_days)
    for y in (today.year, today.year - 1):
        months = [m for m in (1, 2, 3, 4) if month_end(y, m) + lag <= today]
        if months:
            return y, months
    raise RuntimeError("no complete month found")


def have_inputs(data_dir, y, months):
    d = Path(data_dir)
    return all((d / f"{FULL[m]}_NDVI_{y}.tif").exists() and (d / f"Rainfall_Anomaly_{MON[m]}{y}.tif").exists()
               and (d / f"Temperature_{MON[m]}{y}.tif").exists() for m in months)


def update_pilot(pilot, today, log=print, run=subprocess.run):
    os.environ["FIELDPRIORITY_IGNORE_SEASON_FILE"] = "1"       # read the settings as written, then decide
    try:
        cfg = load_config(pilot=pilot)
    finally:
        os.environ.pop("FIELDPRIORITY_IGNORE_SEASON_FILE", None)
    if not (cfg.get("monitoring") or {}).get("auto_update"):
        log(f"{cfg['pilot_short']}: kept on {cfg['period_label']} (monitoring.auto_update is off)")
        return "kept"
    root = Path(cfg["_root"])
    data_dir = root / cfg["paths"]["data_dir"]
    y, months = pilot_window(today)
    label = f"{y}-{months[0]:02d}..{y}-{months[-1]:02d}"
    sf = data_dir / "current_season.json"
    cur = json.loads(sf.read_text()) if sf.exists() else {}
    if cur.get("period_label") == label and (root / cfg["paths"]["output_dir"] / "risk_assessments.json").exists() \
            and have_inputs(data_dir, y, months):
        log(f"{cfg['pilot_short']}: already up to date ({label})")
        return "current"
    env = {**os.environ, "PYTHONPATH": str(root / "src"), "FIELDPRIORITY_PILOT": pilot}
    if not have_inputs(data_dir, y, months):
        log(f"{cfg['pilot_short']}: downloading field data for {label}")
        r = run([sys.executable, "-m", "fieldpriority.fetch_data", "--year", str(y), "--months", *map(str, months),
                 "--out-dir", str(data_dir)], env=env, cwd=root)
        if r.returncode != 0:
            log(f"{cfg['pilot_short']}: download failed; the assessment stays on {cur.get('period_label') or cfg['period_label']}")
            return "failed"
    sf.write_text(json.dumps({"year": y, "months": months, "period_label": label,
                              "set_by": "monthly_update", "set_at": dt.datetime.now().isoformat(timespec="seconds")},
                             indent=2))
    log(f"{cfg['pilot_short']}: assessing {label}")
    r = run([sys.executable, "-m", "fieldpriority.pipeline"], env=env, cwd=root)
    return "updated" if r.returncode == 0 else "failed"


def main():
    ap = argparse.ArgumentParser(description="Monthly update of the district layers and the pilot assessments")
    ap.add_argument("--skip-national", action="store_true")
    ap.add_argument("--skip-pilots", action="store_true")
    a = ap.parse_args()
    today = dt.date.today()
    print(f"FieldPriority monthly update, {today}")
    if not a.skip_pilots:              # pilots first: their CHIRPS downloads are reused by the district layers
        for p in available_pilots():
            print(f"\n===== {p} =====")
            update_pilot(p, today)
    if not a.skip_national:
        print("\n===== Zambia district layers =====")
        from .national.build import build
        try:
            build(today=today)
        except Exception as e:
            print(f"District layers not updated: {e}")


if __name__ == "__main__":
    main()
