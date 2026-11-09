"""Operator commands for encryption at rest. Run from the PRAMAAN folder:

    python -m backend.vault_tools new-key  C:\\Users\\me\\PramaanKeys\\vault.key    # creates a key file (never inside the data folder)
    python -m backend.vault_tools status   --data .demo\\runtime
    python -m backend.vault_tools encrypt  --data .demo\\runtime                       # encrypts plaintext evidence files in place
    python -m backend.vault_tools decrypt  --data .demo\\runtime                       # the reverse, if you stop using encryption

encrypt/decrypt need PRAMAAN_VAULT_KEY_FILE (or PRAMAAN_VAULT_KEY) set. Each file is rewritten atomically and only after
its decrypted bytes are checked against the SHA-256 it is named by; a file that fails that check is reported, not changed.
Back up first (python -m backend.backup create ...): losing the key makes encrypted evidence unreadable.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path

from . import vault_crypto

_SHA = set("0123456789abcdef")


def _files(vault: Path):
    return sorted(p for p in vault.iterdir() if p.is_file() and len(p.name) == 64 and set(p.name) <= _SHA) if vault.is_dir() else []


def status(data: Path) -> dict:
    vault = data / "vault"
    files = _files(vault)
    sealed = sum(vault_crypto.is_sealed(p.read_bytes()[:len(vault_crypto.MAGIC)]) for p in files)
    key = vault_crypto.configured_key(data)
    return {"files": len(files), "encrypted": sealed, "plaintext": len(files) - sealed, "key_configured": key is not None,
            "key_fingerprint": vault_crypto.fingerprint(key) if key else None}


def convert(data: Path, encrypt: bool) -> dict:
    key = vault_crypto.configured_key(data)
    if key is None:
        raise vault_crypto.VaultKeyError("set PRAMAAN_VAULT_KEY_FILE to the key file first")
    changed, skipped, failed = 0, 0, []
    for path in _files(data / "vault"):
        stored = path.read_bytes()
        if vault_crypto.is_sealed(stored) == encrypt:
            skipped += 1
            continue
        raw = vault_crypto.unseal(path.name, stored, key)
        if hashlib.sha256(raw).hexdigest() != path.name:
            failed.append(path.name[:12])  # damaged or tampered: leave it exactly as it is
            continue
        temp = path.with_name(path.name + ".tmp-" + os.urandom(4).hex())
        temp.write_bytes(vault_crypto.seal(path.name, raw, key) if encrypt else raw)
        os.replace(temp, path)
        changed += 1
    return {"changed": changed, "already_done": skipped, "failed_integrity": failed}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PRAMAAN evidence vault encryption")
    sub = parser.add_subparsers(dest="command", required=True)
    new = sub.add_parser("new-key", help="create a new key file")
    new.add_argument("path", type=Path)
    for name in ("status", "encrypt", "decrypt"):
        sub.add_parser(name).add_argument("--data", type=Path, default=Path(os.environ.get("PRAMAAN_DATA", "backend/data")))
    args = parser.parse_args(argv)
    try:
        if args.command == "new-key":
            if args.path.exists():
                print(f"Refused: {args.path} already exists; a key is never overwritten", file=sys.stderr)
                return 2
            args.path.parent.mkdir(parents=True, exist_ok=True)
            args.path.write_text(vault_crypto.new_key_text() + "\n", encoding="ascii")
            try:
                os.chmod(args.path, 0o600)
            except OSError:
                pass
            print(f"Key written to {args.path}. Keep a copy somewhere safe and offline: without it, encrypted evidence cannot be read.")
            print(f"Then set PRAMAAN_VAULT_KEY_FILE={args.path} before starting PRAMAAN.")
            return 0
        result = status(args.data) if args.command == "status" else convert(args.data, args.command == "encrypt")
    except vault_crypto.VaultKeyError as exc:
        print(f"Refused: {exc}", file=sys.stderr)
        return 2
    print(result)
    return 1 if result.get("failed_integrity") else 0


if __name__ == "__main__":
    raise SystemExit(main())
