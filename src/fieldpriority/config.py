"""Settings. config/settings.yaml holds the defaults (the Solwezi pilot). Each other pilot area has a small
config/pilots/<name>.yaml with only what differs; it is merged over the defaults.

Choose the area with load_config(pilot="chongwe") or the FIELDPRIORITY_PILOT environment variable
(the .bat files take it as their first argument, e.g. run_pipeline.bat chongwe)."""
import copy
import json
import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
PILOT_DIR = ROOT / "config" / "pilots"


def _merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict) and not v.get("_replace"):
            out[k] = _merge(out[k], v)
        else:
            out[k] = {kk: vv for kk, vv in v.items() if kk != "_replace"} if isinstance(v, dict) else copy.deepcopy(v)
    return out


def available_pilots():
    """Pilot names: the default one (settings.yaml) first, then config/pilots/*.yaml."""
    with open(ROOT / "config" / "settings.yaml") as f:
        default = (yaml.safe_load(f) or {}).get("pilot_name", "solwezi")
    extra = sorted(p.stem for p in PILOT_DIR.glob("*.yaml")) if PILOT_DIR.exists() else []
    return [default] + [p for p in extra if p != default]


def load_config(path=None, pilot=None):
    p = Path(path) if path else ROOT / "config" / "settings.yaml"
    with open(p) as f:
        cfg = yaml.safe_load(f)
    pilot = (pilot or os.environ.get("FIELDPRIORITY_PILOT") or "").strip().lower() or cfg.get("pilot_name", "solwezi")
    if pilot != cfg.get("pilot_name", "solwezi"):
        f2 = PILOT_DIR / f"{pilot}.yaml"
        if not f2.exists():
            raise SystemExit(f"Unknown pilot area '{pilot}'. Available: {', '.join(available_pilots())}")
        with open(f2) as f:
            cfg = _merge(cfg, yaml.safe_load(f))
    cfg["pilot_name"] = pilot
    cfg["_root"] = str(ROOT)
    # monthly_update.py moves a pilot to the newest season with data by writing <data_dir>/current_season.json.
    # Delete that file to go back to the season in the settings.
    sf = ROOT / cfg["paths"]["data_dir"] / "current_season.json"
    if sf.exists() and not os.environ.get("FIELDPRIORITY_IGNORE_SEASON_FILE"):
        s = json.loads(sf.read_text())
        cfg["year"], cfg["months"], cfg["period_label"] = int(s["year"]), [int(m) for m in s["months"]], s["period_label"]
        cfg["season_file"] = str(sf)
    return cfg
