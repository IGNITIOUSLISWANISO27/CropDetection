"""Read KoboToolbox submissions from a CSV export or the Kobo API.

API settings come from config/settings.yaml (kobo: server, asset_uid) and the token from the
KOBO_TOKEN environment variable or the project's .env file (never from code or settings).

Check the connection:  python -m fieldpriority.ingest.kobo
"""
import datetime as dt
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]


def read_kobo_csv(path):
    """Kobo CSV exports may use ';' or ',' separators; detect it. Everything is read as text."""
    with open(path, encoding="utf-8-sig") as f:
        head = f.readline()
    sep = max([";", ",", "\t"], key=head.count)
    df = pd.read_csv(path, sep=sep, dtype=str, encoding="utf-8-sig")
    if df.shape[1] == 1 and ";" in str(df.columns[0]):
        # file re-saved by Excel or another tool: each ';'-separated row was wrapped as one quoted text cell
        import csv, io
        with open(path, encoding="utf-8-sig", newline="") as f:
            lines = [r[0] if r else "" for r in csv.reader(f)]
        df = pd.read_csv(io.StringIO("\n".join(lines)), sep=";", dtype=str)
    df.columns = [c.strip().strip('"') for c in df.columns]
    df = df.map(lambda v: v.strip() if isinstance(v, str) else v).replace({"": np.nan})
    return df.drop(columns=[c for c in ["form_intro"] if c in df.columns])


# ------------------------------------------------------------------ API
def load_dotenv(path=None):
    """Minimal .env reader (KEY=value lines). Existing environment variables win."""
    p = Path(path) if path else ROOT / ".env"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def kobo_settings(cfg=None):
    """(server, asset_uid, token). Environment variables override settings.yaml."""
    load_dotenv()
    k = (cfg or {}).get("kobo", {}) or {}
    server = os.environ.get("KOBO_SERVER") or k.get("server") or "https://eu.kobotoolbox.org"
    uid = os.environ.get("KOBO_ASSET_UID") or k.get("asset_uid")
    token = os.environ.get("KOBO_TOKEN")
    return server.rstrip("/"), uid, token


def _get(url, token):
    req = urllib.request.Request(url, headers={"Authorization": f"Token {token}", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        hint = {401: "the API token is wrong or missing (Kobo > Account settings > Security > API key)",
                403: "this account has no permission to view submissions of the form",
                404: "the form (asset UID) was not found on this server; check kobo: asset_uid and server "
                     "(eu.kobotoolbox.org and kf.kobotoolbox.org are separate servers)"}.get(e.code, e.reason)
        raise RuntimeError(f"Kobo API {e.code}: {hint}. URL: {url.split('?')[0]}") from None
    except urllib.error.URLError as e:
        raise RuntimeError(f"Could not reach Kobo ({e.reason}). Check the internet connection and server.") from None


def _flat_value(v):
    if isinstance(v, dict) and "uid" in v:            # _validation_status: {"uid": "validation_status_approved", ...}
        return v.get("uid")
    if isinstance(v, (list, dict)):
        return json.dumps(v, ensure_ascii=False) if v else np.nan
    return v


def submissions_to_frame(results):
    """API JSON -> one row per submission with the same column names as a CSV export
    ('XML values and headers', no group names): 'group_crop/leaf_rolling' -> 'leaf_rolling'."""
    rows, clashes = [], set()
    for s in results:
        row = {}
        for key, v in s.items():
            name = key if (key.startswith("_") or key.startswith("meta/") or key.startswith("formhub/")) \
                else key.split("/")[-1]
            if name in row and key != name:
                clashes.add(name)
                continue
            row[name] = _flat_value(v)
        rows.append(row)
    df = pd.DataFrame(rows).astype(object)
    df = df.map(lambda v: v.strip() if isinstance(v, str) else v).replace({"": np.nan})
    if clashes:
        print(f"NOTE: the same question name appears in two groups and only the first was kept: {sorted(clashes)}")
    return df.drop(columns=[c for c in ["form_intro"] if c in df.columns])


def fetch_kobo_raw(server, token, asset_uid, page_size=1000):
    """All submissions as the original API JSON (follows pagination)."""
    if not token:
        raise RuntimeError("No Kobo API token. Put KOBO_TOKEN=<your key> in the .env file in the project folder "
                           "(Kobo > Account settings > Security > API key).")
    if not asset_uid:
        raise RuntimeError("No form ID. Set kobo: asset_uid in config/settings.yaml.")
    url = f"{server}/api/v2/assets/{asset_uid}/data/?format=json&limit={page_size}"
    out = []
    while url:
        page = _get(url, token)
        out += page.get("results", [])
        url = page.get("next")
    return out


def fetch_kobo_api(server, token, asset_uid, raw_dir=None):
    """Pull submissions from the Kobo v2 API. The unchanged JSON is saved to raw_dir (SOP: keep originals)."""
    results = fetch_kobo_raw(server, token, asset_uid)
    if raw_dir:
        p = Path(raw_dir)
        p.mkdir(parents=True, exist_ok=True)
        f = p / f"kobo_{asset_uid}_{dt.datetime.now():%Y%m%d-%H%M%S}.json"
        f.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"Original Kobo download kept unchanged in {f}")
    return submissions_to_frame(results)


def check(cfg=None):
    """Confirm the token, the form and the columns the validation step needs."""
    server, uid, token = kobo_settings(cfg)
    print(f"Server: {server}\nForm (asset UID): {uid}\nToken: {'found' if token else 'MISSING'}")
    if not token:
        raise SystemExit("Add KOBO_TOKEN=<your API key> to the .env file in the project folder, then run this again.")
    asset = _get(f"{server}/api/v2/assets/{uid}/?format=json", token)
    print(f"Form name: {asset.get('name')}  (deployed: {asset.get('has_deployment')}, "
          f"submissions: {asset.get('deployment__submission_count')})")
    df = submissions_to_frame(fetch_kobo_raw(server, token, uid))
    need = ["record_type", "alert_id", "field_id", "visit_date", "permission", "maize_stage", "field_verdict",
            "verdict_reason", "main_cause"]
    missing = [c for c in need if c not in df.columns]
    print(f"Submissions downloaded: {len(df)}")
    if len(df):
        if "record_type" in df:
            print("Record types: " + ", ".join(f"{k} {v}" for k, v in df["record_type"].value_counts(dropna=False).items()))
        print("Columns needed by validation: " + ("all present" if not missing else f"MISSING {missing}"))
    print("OK: Kobo connection works.")
    return df


if __name__ == "__main__":
    from ..config import load_config
    try:
        check(load_config())
    except RuntimeError as e:
        raise SystemExit(f"FAILED: {e}")
