"""Zambia-wide district layers: rainfall, temperature, vegetation, water stress, cropland, solar, and the
integrated interpretation that turns them into a location report. Settings: config/national.yaml."""
import datetime as dt
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
MON = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def load_national_config(path=None):
    p = Path(path) if path else ROOT / "config" / "national.yaml"
    with open(p) as f:
        cfg = yaml.safe_load(f)
    cfg["_root"] = str(ROOT)
    return cfg


def month_end(y, m):
    return (dt.date(y + (m == 12), m % 12 + 1, 1) - dt.timedelta(days=1))


def season_months(start_year, months):
    """(year, month) pairs of one rainy season. Months from July onwards belong to the season's first year."""
    return [(start_year if m >= 7 else start_year + 1, m) for m in months]


def season_name(start_year):
    return f"{start_year}/{str(start_year + 1)[-2:]}"


def window_label(window):
    (y0, m0), (y1, m1) = window[0], window[-1]
    return f"{MON[m0]} {y0}" if (y0, m0) == (y1, m1) else f"{MON[m0]} {y0} to {MON[m1]} {y1}"


def season_of(y, m):
    return y if m >= 7 else y - 1


def parse_period(text):
    """'2025-01..2025-04' -> [(2025,1),...,(2025,4)] (consecutive months)."""
    a, _, b = str(text).partition("..")
    y0, m0 = map(int, a.split("-"))
    y1, m1 = map(int, (b or a).split("-"))
    out, y, m = [], y0, m0
    while (y, m) <= (y1, m1):
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def latest_window(today, cfg, available=None):
    """Months to show: the current season to date, or the last full season when fewer than min_months of the
    current season are complete. `available(y, m)` can veto months whose data is not published yet."""
    sc = cfg["season"]
    if cfg.get("period"):
        return parse_period(cfg["period"])
    lag = dt.timedelta(days=int(sc.get("data_lag_days", 20)))
    cur = season_of(today.year, today.month)
    for sy in (cur, cur - 1, cur - 2):
        done = []
        for y, m in season_months(sy, sc["months"]):
            if month_end(y, m) + lag > today or (available and not available(y, m)):
                break
            done.append((y, m))
        if len(done) >= int(sc.get("min_months", 1)):
            return done
    raise RuntimeError("No season with published data found")


def baseline_years(window, n):
    """Season start-years of the n seasons before the window's season."""
    sy = season_of(*window[0])
    return list(range(sy - n, sy))


def shift(window, seasons_back):
    return [(y - seasons_back, m) for y, m in window]
