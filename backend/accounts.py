"""User accounts: username + password + authenticator-app code (TOTP, RFC 6238).

A successful login issues the same role credential the launcher issues (security.issue), so every permission rule,
the human-review gate and the access log apply unchanged; pasting a launcher credential keeps working too.

Stored in credentials.sqlite3 next to the bearer-token table:
- passwords: scrypt (n=2^15, r=8, p=1, 16-byte salt), compared in constant time; at least 12 characters
- TOTP secrets: encrypted with the vault key when encryption at rest is configured, otherwise stored as is
- 5 wrong attempts lock the account for 15 minutes; a code can be used once (replay of the same 30-second code is refused)
- unknown usernames take the same time and get the same answer as wrong passwords

Operator commands (run from the PRAMAAN folder, with PRAMAAN_DATA set like the server):
    python -m backend.accounts add priya --role auditor [--human]   # asks for a password, prints the authenticator setup key
    python -m backend.accounts list | disable NAME | enable NAME | unlock NAME | reset-mfa NAME | set-password NAME
"""
from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import hmac
import os
import re
import secrets
import struct
import sys
import time
from urllib.parse import quote

from . import security, vault_crypto

MIN_PASSWORD = 12
MAX_FAILURES = 5
LOCK_SECONDS = 15 * 60
SESSION_SECONDS = 8 * 3600
STEP = 30
_SCRYPT = {"n": 2 ** 15, "r": 8, "p": 1}
_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{1,39}$")
GENERIC = "Username, password or code not accepted."


class LoginRefused(Exception):
    """Always carries the generic message, so the reply never reveals which part was wrong."""


def _db():
    security.bootstrap()
    db = security.credential_db()
    return db


def init(db) -> None:
    db.execute("""CREATE TABLE IF NOT EXISTS users(username TEXT PRIMARY KEY, role TEXT NOT NULL, human INTEGER NOT NULL DEFAULT 0,
                  password_hash TEXT NOT NULL, totp_secret TEXT NOT NULL, totp_last_step INTEGER NOT NULL DEFAULT 0,
                  failed INTEGER NOT NULL DEFAULT 0, locked_until REAL NOT NULL DEFAULT 0, disabled INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL)""")


# ------------------------------------------------------------------ passwords

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, dklen=32, maxmem=128 * 1024 * 1024, **_SCRYPT)
    return "scrypt${n}${r}${p}${salt}${hash}".format(**_SCRYPT, salt=base64.b64encode(salt).decode(), hash=base64.b64encode(digest).decode())


def check_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, want = stored.split("$")
        got = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), dklen=32, n=int(n), r=int(r), p=int(p), maxmem=128 * 1024 * 1024)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got, base64.b64decode(want))


_DUMMY = None


def _dummy_hash() -> str:
    global _DUMMY
    if _DUMMY is None:
        _DUMMY = hash_password(secrets.token_urlsafe(16))
    return _DUMMY


def password_problem(username: str, password: str) -> str | None:
    if len(password) < MIN_PASSWORD:
        return f"the password must be at least {MIN_PASSWORD} characters"
    if username.lower() in password.lower():
        return "the password must not contain the username"
    if len(set(password)) < 6:
        return "the password needs more variety"
    return None


# ------------------------------------------------------------------ TOTP

def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def totp(secret: str, step: int) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    mac = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = mac[-1] & 0x0F
    return f"{(struct.unpack('>I', mac[offset:offset + 4])[0] & 0x7FFFFFFF) % 1_000_000:06d}"


def matching_step(secret: str, code: str, now: float, after_step: int) -> int | None:
    """The time step the code belongs to (current ±1 for clock drift), if it is newer than the last one used."""
    code = re.sub(r"\s", "", code or "")
    if not re.fullmatch(r"\d{6}", code):
        return None
    current = int(now // STEP)
    for step in (current - 1, current, current + 1):
        if step > after_step and hmac.compare_digest(totp(secret, step), code):
            return step
    return None


def _seal_secret(secret: str) -> str:
    key = vault_crypto.configured_key(_root())
    if not key:
        return secret
    return "enc:" + base64.b64encode(vault_crypto.seal("totp", secret.encode(), key)).decode()


def _open_secret(stored: str) -> str:
    if not stored.startswith("enc:"):
        return stored
    return vault_crypto.unseal("totp", base64.b64decode(stored[4:]), vault_crypto.configured_key(_root())).decode()


def _root():
    from . import app as p1
    return p1.ROOT


def setup_uri(username: str, secret: str) -> str:
    return f"otpauth://totp/PRAMAAN:{quote(username)}?secret={secret}&issuer=PRAMAAN&digits=6&period={STEP}"


# ------------------------------------------------------------------ accounts

def add_user(username: str, role: str, password: str, human: bool = False) -> tuple[str, str]:
    username = username.strip().lower()
    if not _NAME.fullmatch(username):
        raise ValueError("username: 2-40 characters, lowercase letters, digits, dot, dash or underscore")
    if role not in {"client_employee", "auditor"}:
        raise ValueError("role must be client_employee or auditor")
    if human and role != "auditor":
        raise ValueError("only auditors can have human-review rights")
    if problem := password_problem(username, password):
        raise ValueError(problem)
    secret = new_secret()
    with _db() as db:
        init(db)
        if db.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
            raise ValueError("that username already exists")
        db.execute("INSERT INTO users(username,role,human,password_hash,totp_secret,created) VALUES(?,?,?,?,?,?)",
                   (username, role, int(human), hash_password(password), _seal_secret(secret), time.time()))
    return secret, setup_uri(username, secret)


def is_account(username: str) -> bool:
    with _db() as db:
        init(db)
        return db.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone() is not None


def accounts_exist() -> bool:
    with _db() as db:
        init(db)
        return db.execute("SELECT 1 FROM users WHERE disabled=0 LIMIT 1").fetchone() is not None


def login(username: str, password: str, code: str, now: float | None = None) -> dict:
    """Returns {"token", "role", "human", "expires_in"}; raises LoginRefused with the generic message otherwise."""
    now = time.time() if now is None else now
    username = (username or "").strip().lower()
    with _db() as db:
        init(db)
        row = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if row is None:
            check_password(password or "", _dummy_hash())  # same work as a real check
            _event(None, "denied")
            raise LoginRefused(GENERIC)
        caller = {"subject": row["username"], "role": row["role"]}
        if row["disabled"] or row["locked_until"] > now:
            check_password(password or "", _dummy_hash())
            _event(caller, "denied")
            raise LoginRefused(GENERIC)
        step = None
        if check_password(password or "", row["password_hash"]):
            step = matching_step(_open_secret(row["totp_secret"]), code, now, row["totp_last_step"])
        if step is None:
            failed = row["failed"] + 1
            locked = now + LOCK_SECONDS if failed >= MAX_FAILURES else row["locked_until"]
            db.execute("UPDATE users SET failed=?, locked_until=? WHERE username=?", (0 if failed >= MAX_FAILURES else failed, locked, username))
            db.commit()  # keep the failure count: the raise below would otherwise roll it back
            _event(caller, "denied")
            raise LoginRefused(GENERIC)
        db.execute("UPDATE users SET failed=0, locked_until=0, totp_last_step=? WHERE username=?", (step, username))
    token = security.issue(row["username"], row["role"], ttl=SESSION_SECONDS, human=bool(row["human"]))
    _event(caller, "allowed")
    return {"token": token, "role": row["role"], "human": bool(row["human"]), "expires_in": SESSION_SECONDS}


def _event(caller, decision):
    try:
        security.security_event(caller, "auth_login", decision, "api")
    except Exception:  # logging must never decide a login
        pass


def _update(username: str, sql: str, args: tuple = ()) -> bool:
    with _db() as db:
        init(db)
        return db.execute(sql, (*args, username.strip().lower())).rowcount > 0


def list_users() -> list[dict]:
    with _db() as db:
        init(db)
        return [{"username": r["username"], "role": r["role"], "human": bool(r["human"]), "disabled": bool(r["disabled"]),
                 "locked": r["locked_until"] > time.time()} for r in db.execute("SELECT * FROM users ORDER BY username")]


def disable(username: str) -> bool:
    done = _update(username, "UPDATE users SET disabled=1 WHERE username=?")
    if done:
        security.revoke_subject(username.strip().lower())  # end any session it already has
    return done


def enable(username: str) -> bool:
    return _update(username, "UPDATE users SET disabled=0, failed=0, locked_until=0 WHERE username=?")


def unlock(username: str) -> bool:
    return _update(username, "UPDATE users SET failed=0, locked_until=0 WHERE username=?")


def reset_mfa(username: str) -> tuple[str, str] | None:
    secret = new_secret()
    if not _update(username, "UPDATE users SET totp_secret=?, totp_last_step=0 WHERE username=?", (_seal_secret(secret),)):
        return None
    security.revoke_subject(username.strip().lower())
    return secret, setup_uri(username.strip().lower(), secret)


def set_password(username: str, password: str) -> bool:
    if problem := password_problem(username, password):
        raise ValueError(problem)
    done = _update(username, "UPDATE users SET password_hash=?, failed=0, locked_until=0 WHERE username=?", (hash_password(password),))
    if done:
        security.revoke_subject(username.strip().lower())
    return done


def _ask_password(username: str) -> str:
    first = getpass.getpass(f"Password for {username}: ")
    if getpass.getpass("Repeat password: ") != first:
        raise ValueError("the passwords do not match")
    return first


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PRAMAAN user accounts (password + authenticator code)")
    sub = parser.add_subparsers(dest="command", required=True)
    add = sub.add_parser("add")
    add.add_argument("username")
    add.add_argument("--role", choices=["auditor", "client_employee"], required=True)
    add.add_argument("--human", action="store_true", help="auditor may record final human-review decisions")
    sub.add_parser("list")
    for name in ("disable", "enable", "unlock", "reset-mfa", "set-password"):
        sub.add_parser(name).add_argument("username")
    args = parser.parse_args(argv)
    try:
        if args.command == "add":
            secret, uri = add_user(args.username, args.role, os.environ.get("PRAMAAN_NEW_PASSWORD") or _ask_password(args.username), args.human)
            print(f"Account created. In your authenticator app add a key manually:\n  account: PRAMAAN:{args.username.lower()}\n  key:     {secret}\n  (or open {uri})")
        elif args.command == "list":
            for user in list_users():
                print(user)
        elif args.command == "reset-mfa":
            result = reset_mfa(args.username)
            if not result:
                raise ValueError("no such user")
            print(f"New authenticator key for {args.username}: {result[0]}\n  ({result[1]})")
        elif args.command == "set-password":
            if not set_password(args.username, os.environ.get("PRAMAAN_NEW_PASSWORD") or _ask_password(args.username)):
                raise ValueError("no such user")
            print("Password changed; existing sessions were ended.")
        else:
            if not {"disable": disable, "enable": enable, "unlock": unlock}[args.command](args.username):
                raise ValueError("no such user")
            print(f"{args.command}: done")
    except (ValueError, vault_crypto.VaultKeyError) as exc:
        print(f"Refused: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
