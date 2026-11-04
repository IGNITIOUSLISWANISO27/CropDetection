"""Check the Firebase connection before syncing.

Run:  python -m fieldpriority.firebase_check [--cred path\\to\\firebase-key.json]
Steps: key file looks right -> connect -> write, read back and delete a test document -> count stored data.
Each failure prints what to do about it in plain language."""
import argparse
import datetime as dt
import json
import sys

from .storage.firebase_client import FirebaseStore, find_credentials

COLLECTIONS = ["fields", "risk_assessments", "alerts", "verifications"]


def validate_key_file(path):
    """Return {project_id, client_email}. Raise ValueError with a plain-language message if it is not a service-account key."""
    try:
        info = json.load(open(path, encoding="utf-8"))
    except Exception:
        raise ValueError(f"{path} is not a valid JSON file. Download the key again from Firebase.")
    if "apiKey" in info or "appId" in info:
        raise ValueError("This looks like the web app configuration, not the private key. In Project settings, open "
                         "'Service accounts' and click 'Generate new private key'.")
    missing = [k for k in ("type", "project_id", "client_email", "private_key") if k not in info]
    if info.get("type") != "service_account" or missing:
        raise ValueError("This is not a service-account key file (missing: "
                         + ", ".join(missing or ["type=service_account"]) + "). Generate a new private key under "
                         "Project settings > Service accounts.")
    return {"project_id": info["project_id"], "client_email": info["client_email"]}


def explain_error(e):
    m = f"{type(e).__name__}: {e}"
    low = m.lower()
    if "database (default) does not exist" in low or ("notfound" in low and "database" in low):
        return ("The Firestore database has not been created. In the Firebase console open Build > Firestore Database "
                "and click 'Create database' (choose production mode).")
    if "has not been used" in low or "service_disabled" in low or "api is not enabled" in low:
        return ("The Cloud Firestore API is switched off for this project. Create the Firestore database in the Firebase "
                "console first. If it already exists, enable the API at "
                "https://console.cloud.google.com/apis/library/firestore.googleapis.com")
    if "permissiondenied" in low or "403" in low or "permission" in low:
        return ("The key does not have permission to use Firestore. Use the key generated under Firebase Project settings "
                "> Service accounts, from the same project that holds your database.")
    if "unauthenticated" in low or "invalid_grant" in low or "invalid jwt" in low or "could not deserialize" in low:
        return ("Firebase rejected the key. It may be revoked, edited, or your computer clock may be wrong. Generate a "
                "new private key and check the date and time on this PC.")
    if any(w in low for w in ("unavailable", "deadline", "connection", "timed out", "resolve")):
        return "Could not reach Firebase. Check the internet connection and that no firewall or proxy blocks Google services."
    return m


def check_store(store):
    """Write, read back and delete a test document, then count stored data."""
    ref = store.col("meta").document("_healthcheck")
    stamp = dt.datetime.now(dt.timezone.utc).isoformat()
    ref.set({"checked_at": stamp})
    got = ref.get().to_dict() or {}
    ref.delete()
    counts = {c: len(list(store.col(c).stream())) for c in COLLECTIONS}
    return {"write_read_ok": got.get("checked_at") == stamp, "counts": counts}


def main():
    ap = argparse.ArgumentParser(description="Check the Firebase connection")
    ap.add_argument("--cred", default=None)
    a = ap.parse_args()
    path = find_credentials(a.cred)
    if not path:
        print("FAIL  No key file found. Save the downloaded key as firebase-key.json in the project folder,\n"
              "      or set FIREBASE_CRED_PATH, or pass --cred.")
        return 1
    try:
        info = validate_key_file(path)
    except ValueError as e:
        print("FAIL ", e)
        return 1
    print(f"OK    Key file: {path}\n      Project: {info['project_id']}\n      Service account: {info['client_email']}")
    try:
        store = FirebaseStore.connect(path)
        res = check_store(store)
    except Exception as e:
        print("FAIL ", explain_error(e))
        return 1
    if not res["write_read_ok"]:
        print("FAIL  Wrote a test document but could not read it back.")
        return 1
    print("OK    Connected. Wrote, read and deleted a test document.")
    print("      Stored so far: " + ", ".join(f"{k} {v}" for k, v in res["counts"].items()))
    if not res["counts"]["fields"]:
        print("      Nothing synced yet. Next: python -m fieldpriority.sync_firebase")
    return 0


if __name__ == "__main__":
    sys.exit(main())
