"""Write .streamlit/secrets.toml from firebase-key.json, for the online (Streamlit Community Cloud) dashboard.

Run:  python -m fieldpriority.make_streamlit_secrets
It also adds KOBO_TOKEN from .env (if present), so the online field profiles can show verifiers' photos.
Then copy the WHOLE content of .streamlit/secrets.toml into the app's Settings > Secrets box on
share.streamlit.io. The file stays on this PC (it is in .gitignore): never upload it or the key to GitHub.
"""
import json
from pathlib import Path

from .storage.firebase_client import ROOT, find_credentials


def to_toml(key, kobo_token=None):
    # top-level keys must come before the [firebase] table in TOML
    lines = ([f"KOBO_TOKEN = {json.dumps(kobo_token)}", ""] if kobo_token else []) + ["[firebase]"]
    for k, v in key.items():
        lines.append(f"{k} = {json.dumps(v)}")          # JSON string escapes are valid TOML basic strings
    return "\n".join(lines) + "\n"


def main():
    path = find_credentials()
    if not isinstance(path, str):
        raise SystemExit("firebase-key.json not found in the project folder")
    key = json.loads(Path(path).read_text())
    out = ROOT / ".streamlit" / "secrets.toml"
    out.parent.mkdir(exist_ok=True)
    from .ingest.kobo import load_dotenv
    import os
    load_dotenv()
    out.write_text(to_toml(key, os.environ.get("KOBO_TOKEN")))
    print(f"Written {out}\nOpen it, copy everything, and paste it into Settings > Secrets of the app on "
          "share.streamlit.io.\nDo NOT upload this file or firebase-key.json to GitHub.")


if __name__ == "__main__":
    main()
