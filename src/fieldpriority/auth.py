"""Accounts for the dashboard: each account sees only its own pilot areas' fields.

Accounts live in .streamlit/secrets.toml (never in GitHub) and, online, in the app's Settings > Secrets:

    [auth.users.liswaniso]
    name = "Ignitious Liswaniso"
    pilots = ["chongwe", "solwezi", "kitwe"]
    password = "pbkdf2_sha256$600000$<salt>$<hash>"

Only a salted PBKDF2 hash is stored, never the password. Add or change an account with set_password.bat
(python -m fieldpriority.auth add <username> --pilots chongwe,solwezi,kitwe --name "Full name").
"""
import argparse
import base64
import getpass
import hashlib
import hmac
import os
import re
from pathlib import Path

ITERATIONS = 600_000
ROOT = Path(__file__).resolve().parents[2]
SECRETS = ROOT / ".streamlit" / "secrets.toml"
USERNAME = re.compile(r"^[a-z0-9_]{3,32}$")


def hash_password(password, salt=None, iterations=ITERATIONS):
    salt = salt or os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    b = lambda x: base64.b64encode(x).decode("ascii")
    return f"pbkdf2_sha256${iterations}${b(salt)}${b(dk)}"


def check_password(password, stored):
    try:
        algo, it, salt, dk = str(stored).split("$")
        if algo != "pbkdf2_sha256":
            return False
        got = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), base64.b64decode(salt), int(it))
        return hmac.compare_digest(got, base64.b64decode(dk))
    except Exception:
        return False


def users_from(secrets):
    """{username: {"name", "pilots", "password"}} from a secrets mapping (st.secrets or a dict)."""
    try:
        raw = secrets["auth"]["users"]
    except Exception:
        return {}
    out = {}
    for u, d in dict(raw).items():
        d = dict(d)
        if not d.get("password"):
            continue
        p = d.get("pilots") or []
        out[str(u).lower()] = {"name": d.get("name") or u, "password": d["password"],
                               "pilots": [str(x).lower() for x in ([p] if isinstance(p, str) else p)]}
    return out


def authenticate(users, username, password):
    """The account dict if the username and password match, else None (same work either way)."""
    u = users.get(str(username or "").strip().lower())
    ok = check_password(password or "", u["password"] if u else hash_password("x", iterations=1000))
    return u if (u and ok) else None


def pilots_for(user, available):
    if not user:
        return []
    ps = user.get("pilots") or []
    return list(available) if "*" in ps else [p for p in available if p in ps]


# ------------------------------------------------------------------ writing an account into secrets.toml
def upsert_user(text, username, name, pilots, pw_hash):
    """Return secrets.toml text with [auth.users.<username>] replaced or added; other sections untouched."""
    import json
    block = (f"[auth.users.{username}]\nname = {json.dumps(name)}\npilots = {json.dumps(pilots)}\n"
             f"password = {json.dumps(pw_hash)}\n")
    lines, out, skip = text.splitlines(), [], False
    for ln in lines:
        s = ln.strip()
        if s.startswith("["):
            skip = s == f"[auth.users.{username}]"
        if not skip:
            out.append(ln)
    body = "\n".join(out).rstrip()
    return (body + "\n\n" if body else "") + block


def main(argv=None):
    ap = argparse.ArgumentParser(description="Add or change a dashboard account (stored as a hash in secrets.toml)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add", help="add an account or change its password")
    a.add_argument("username")
    a.add_argument("--pilots", default="*", help="comma-separated pilot areas, or * for all")
    a.add_argument("--name", default=None)
    sub.add_parser("list", help="list accounts (no passwords)")
    args = ap.parse_args(argv)
    text = SECRETS.read_text(encoding="utf-8") if SECRETS.exists() else ""
    if args.cmd == "list":
        names = re.findall(r"^\[auth\.users\.([a-z0-9_]+)\]", text, flags=re.M)
        print("\n".join(names) or "No accounts yet.")
        return
    user = args.username.strip().lower()
    if not USERNAME.match(user):
        raise SystemExit("Username: 3-32 characters, lowercase letters, digits or _")
    pw = getpass.getpass(f"New password for {user} (typing is hidden): ")
    if len(pw) < 10:
        raise SystemExit("Use at least 10 characters.")
    if getpass.getpass("Type it again: ") != pw:
        raise SystemExit("The two passwords did not match. Nothing was changed.")
    pilots = [p.strip().lower() for p in args.pilots.split(",") if p.strip()]
    SECRETS.parent.mkdir(exist_ok=True)
    SECRETS.write_text(upsert_user(text, user, args.name or user, pilots, hash_password(pw)), encoding="utf-8")
    print(f"Saved account '{user}' (pilot areas: {', '.join(pilots)}) in {SECRETS}.\n"
          "For the online app: open that file, copy the whole [auth.users." + user + "] block and paste it into "
          "Settings > Secrets on share.streamlit.io (below what is already there). Never upload secrets.toml.")


if __name__ == "__main__":
    main()
