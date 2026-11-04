"""Remove the old Chongwe pilot data from Firebase (the unprefixed collections).

Safe by design:
  1. It first saves everything it will remove to outputs/chongwe_archive/firebase_export_<date>.json,
     so the original Chongwe predictions (rule 10) are still kept, on this PC.
  2. Without --delete it only shows what it would remove (a dry run).
  3. With --delete it asks you to type DELETE before removing anything.
Solwezi data lives in the collections that start with `firebase.collection_prefix` (solwezi_) and is never touched.

Run:  python -m fieldpriority.firebase_remove_chongwe            (dry run)
      python -m fieldpriority.firebase_remove_chongwe --delete   (export, confirm, then delete)
"""
import argparse
import datetime as dt
import json
from pathlib import Path

from .storage.firebase_client import FirebaseStore, clean, default_prefix

CHONGWE_COLLECTIONS = ["fields", "indicators", "season_features", "risk_assessments", "alerts", "alerts_issued",
                       "verifications", "metrics", "runs", "meta"]


def export_and_remove(db, export_path, delete=False):
    """Returns {collection: number of documents}. Writes the export file before deleting anything."""
    old = FirebaseStore(db, "")                  # unprefixed = the Chongwe pilot
    dump, counts = {}, {}
    for c in CHONGWE_COLLECTIONS:
        docs = list(old.col(c).stream())
        dump[c] = {d.id: d.to_dict() for d in docs}
        counts[c] = len(docs)
    total = sum(counts.values())
    if total == 0:
        return counts
    export_path = Path(export_path)
    export_path.parent.mkdir(parents=True, exist_ok=True)
    export_path.write_text(json.dumps(clean(dump), indent=1, default=str))
    if delete:
        for c in CHONGWE_COLLECTIONS:
            for doc_id in dump[c]:
                old.col(c).document(doc_id).delete()
    return counts


def main():
    from .config import load_config
    ap = argparse.ArgumentParser(description="Remove the old Chongwe data from Firebase (exports it first)")
    ap.add_argument("--delete", action="store_true", help="actually delete (default: dry run)")
    ap.add_argument("--yes", action="store_true", help="skip the typed confirmation")
    ap.add_argument("--cred", default=None)
    a = ap.parse_args()
    if not default_prefix():
        print("Stopped: settings.yaml has no firebase.collection_prefix, so the current pilot also uses the "
              "unprefixed collections. Nothing removed.")
        return 1
    cfg = load_config()
    out = Path(cfg["_root"]) / "outputs" / "chongwe_archive" / f"firebase_export_{dt.date.today():%Y-%m-%d}.json"
    store = FirebaseStore.connect(a.cred)

    counts = export_and_remove(store.db, out, delete=False)
    total = sum(counts.values())
    print("Chongwe data in Firebase (unprefixed collections):")
    for c, n in counts.items():
        print(f"  {c:18s} {n}")
    if total == 0:
        print("Nothing to remove.")
        return 0
    print(f"Saved a full copy to {out}")
    if not a.delete:
        print("Dry run: nothing deleted. Run remove_chongwe_firebase.bat and choose to delete, or add --delete.")
        return 0
    if not a.yes and input(f"Type DELETE to remove these {total} documents from Firebase: ").strip() != "DELETE":
        print("Cancelled. Nothing deleted.")
        return 0
    export_and_remove(store.db, out, delete=True)
    print(f"Removed {total} Chongwe documents. Solwezi collections ({default_prefix()}*) were not touched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
