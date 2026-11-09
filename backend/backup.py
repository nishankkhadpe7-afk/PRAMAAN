"""Encrypted backup and verified restore of a PRAMAAN data folder. Run from the PRAMAAN folder:

    python -m backend.backup create  --data .demo\\runtime --out D:\\PramaanBackups [--keep 14]
    python -m backend.backup verify  D:\\PramaanBackups\\pramaan-backup-20261109-181500.pramaan
    python -m backend.backup restore D:\\PramaanBackups\\pramaan-backup-20261109-181500.pramaan --to C:\\PramaanRestored

The passphrase comes from PRAMAAN_BACKUP_PASSPHRASE or is asked for (twice when creating); at least 12 characters.

What a backup holds: a consistent snapshot of every SQLite database (taken with SQLite's online backup API, so the app
can keep running), every evidence file exactly as stored (still encrypted if encryption at rest is on), the other files
of the data folder, and a manifest with the SHA-256 of each. The whole archive is encrypted with AES-256-GCM in 4 MiB
segments under a key derived from the passphrase (scrypt); segments are numbered and the last one is marked, so a
truncated, reordered or altered backup is refused. The vault key is NOT inside the backup: keep it separately. The
manifest records its fingerprint so a restore can tell you whether the key you hold is the right one.

Restore never overwrites: the target folder must be new or empty. It verifies everything first (manifest hashes,
SQLite integrity_check on each database, and each evidence file's SHA-256 when it can be read), then writes the files.
Point PRAMAAN_DATA at the restored folder to use it.
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import io
import json
import os
import secrets
import sqlite3
import struct
import sys
import tarfile
import tempfile
import time
from pathlib import Path

from . import vault_crypto

MAGIC = b"PRMB1\x00"
SEGMENT = 4 * 1024 * 1024
SCRYPT = {"n": 2 ** 15, "r": 8, "p": 1}
MIN_PASSPHRASE = 12
FORMAT = "pramaan-backup-v1"
_SKIP_SUFFIXES = ("-wal", "-shm", "-journal")


class BackupError(Exception):
    pass


def _key(passphrase: str, salt: bytes) -> bytes:
    if len(passphrase) < MIN_PASSPHRASE:
        raise BackupError(f"the backup passphrase must be at least {MIN_PASSPHRASE} characters")
    return hashlib.scrypt(passphrase.encode(), salt=salt, dklen=32, maxmem=128 * 1024 * 1024, **SCRYPT)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------- archive encryption (segmented AES-GCM)

def _encrypt_stream(source, target, passphrase: str) -> None:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    salt, base = secrets.token_bytes(16), secrets.token_bytes(8)
    header = MAGIC + salt + base
    target.write(header)
    aead = AESGCM(_key(passphrase, salt))
    index, chunk = 0, source.read(SEGMENT)
    while True:
        following = source.read(SEGMENT)
        final = not following
        aad = header + struct.pack(">I?", index, final)
        sealed = aead.encrypt(base + struct.pack(">I", index), chunk, aad)
        target.write(struct.pack(">I", len(sealed)) + sealed)
        if final:
            return
        index, chunk = index + 1, following


def _decrypt_stream(source, target, passphrase: str) -> None:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    header = source.read(len(MAGIC) + 24)
    if not header.startswith(MAGIC) or len(header) != len(MAGIC) + 24:
        raise BackupError("not a PRAMAAN backup file")
    salt, base = header[len(MAGIC):len(MAGIC) + 16], header[len(MAGIC) + 16:]
    aead = AESGCM(_key(passphrase, salt))
    index = 0
    while True:
        size = source.read(4)
        if len(size) != 4:
            raise BackupError("backup is truncated (the last segment is missing)")
        sealed = source.read(struct.unpack(">I", size)[0])
        for final in (False, True):
            try:
                plain = aead.decrypt(base + struct.pack(">I", index), sealed, header + struct.pack(">I?", index, final))
                break
            except InvalidTag:
                plain = None
        if plain is None:
            raise BackupError("wrong passphrase, or the backup was altered" if index == 0 else f"backup segment {index} was altered")
        target.write(plain)
        if final:
            if source.read(1):
                raise BackupError("unexpected data after the last segment")
            return
        index += 1


# ---------------------------------------------------------------- create

def _snapshot_db(path: Path) -> bytes:
    """Consistent copy of a live SQLite database via the online backup API."""
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "copy.sqlite3"
        src, dst = sqlite3.connect(f"file:{path}?mode=ro", uri=True), sqlite3.connect(copy)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        return copy.read_bytes()


def _members(data: Path):
    for path in sorted(data.rglob("*")):
        if not path.is_file() or path.name.endswith(_SKIP_SUFFIXES) or ".tmp-" in path.name:
            continue
        rel = path.relative_to(data).as_posix()
        yield rel, (_snapshot_db(path) if path.suffix == ".sqlite3" else path.read_bytes())


def create(data: Path, out_dir: Path, passphrase: str, keep: int | None = None) -> dict:
    data, out_dir = data.resolve(), out_dir.resolve()
    if not data.is_dir():
        raise BackupError(f"data folder not found: {data}")
    if out_dir == data or data in out_dir.parents:
        raise BackupError("store backups outside the data folder")
    _key(passphrase, b"0" * 16)  # passphrase rules checked before any work
    key = vault_crypto.configured_key(data)
    manifest = {"format": FORMAT, "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "files": [],
                "vault_key_fingerprint": vault_crypto.fingerprint(key) if key else None}
    out_dir.mkdir(parents=True, exist_ok=True)
    name = f"pramaan-backup-{time.strftime('%Y%m%d-%H%M%S')}.pramaan"
    target = out_dir / name
    if target.exists():
        raise BackupError(f"{name} already exists")
    with tempfile.TemporaryFile() as tar_file:
        with tarfile.open(fileobj=tar_file, mode="w") as tar:
            for rel, content in _members(data):
                manifest["files"].append({"path": rel, "sha256": _sha(content), "size": len(content)})
                info = tarfile.TarInfo("data/" + rel)
                info.size, info.mtime, info.mode = len(content), int(time.time()), 0o600
                tar.addfile(info, io.BytesIO(content))
            blob = json.dumps(manifest, indent=1).encode()
            info = tarfile.TarInfo("manifest.json")
            info.size, info.mtime = len(blob), int(time.time())
            tar.addfile(info, io.BytesIO(blob))
        tar_file.seek(0)
        partial = target.with_name(name + ".partial")
        with open(partial, "wb") as out:
            _encrypt_stream(tar_file, out, passphrase)
        os.replace(partial, target)
    removed = _rotate(out_dir, keep) if keep else []
    return {"backup": str(target), "files": len(manifest["files"]), "bytes": target.stat().st_size,
            "vault_key_fingerprint": manifest["vault_key_fingerprint"], "older_backups_removed": removed}


def _rotate(out_dir: Path, keep: int) -> list[str]:
    """Delete the oldest backups this tool made, keeping the newest `keep`. Only touches pramaan-backup-*.pramaan."""
    if keep < 1:
        raise BackupError("--keep must be at least 1")
    ours = sorted(out_dir.glob("pramaan-backup-*.pramaan"))
    old = ours[:-keep]
    for path in old:
        path.unlink()
    return [p.name for p in old]


# ---------------------------------------------------------------- verify / restore

def _open(backup: Path, passphrase: str, workdir: Path) -> tuple[dict, dict[str, bytes]]:
    tar_path = workdir / "backup.tar"
    with open(backup, "rb") as src, open(tar_path, "wb") as dst:
        _decrypt_stream(src, dst, passphrase)
    files: dict[str, bytes] = {}
    manifest = None
    with tarfile.open(tar_path, mode="r") as tar:
        for member in tar.getmembers():
            name = member.name
            if not member.isfile() or name.startswith("/") or ".." in Path(name).parts:
                raise BackupError(f"unsafe entry in backup: {name!r}")
            content = tar.extractfile(member).read()
            if name == "manifest.json":
                manifest = json.loads(content)
            elif name.startswith("data/"):
                files[name[5:]] = content
            else:
                raise BackupError(f"unexpected entry in backup: {name!r}")
    if not manifest or manifest.get("format") != FORMAT:
        raise BackupError("backup manifest missing or of an unknown format")
    return manifest, files


def _check(manifest: dict, files: dict[str, bytes], workdir: Path) -> dict:
    listed = {f["path"]: f for f in manifest["files"]}
    problems = [f"missing: {p}" for p in listed if p not in files] + [f"not in manifest: {p}" for p in files if p not in listed]
    problems += [f"hash differs: {p}" for p, c in files.items() if p in listed and _sha(c) != listed[p]["sha256"]]
    databases = 0
    for rel, content in files.items():
        if rel.endswith(".sqlite3"):
            databases += 1
            probe = workdir / ("probe-" + secrets.token_hex(4) + ".sqlite3")
            probe.write_bytes(content)
            db = sqlite3.connect(probe)
            try:
                result = db.execute("PRAGMA integrity_check").fetchone()[0]
            finally:
                db.close()
            if result != "ok":
                problems.append(f"database damaged: {rel} ({result})")
    key = None
    try:
        key = vault_crypto.configured_key()
    except vault_crypto.VaultKeyError:
        pass
    want = manifest.get("vault_key_fingerprint")
    key_matches = (key is not None and vault_crypto.fingerprint(key) == want) if want else None
    evidence, unverifiable = 0, 0
    for rel, content in files.items():
        name = rel.rsplit("/", 1)[-1]
        if rel.startswith("vault/") and len(name) == 64:
            evidence += 1
            if vault_crypto.is_sealed(content) and not key_matches:
                unverifiable += 1
                continue
            try:
                raw = vault_crypto.unseal(name, content, key)
            except vault_crypto.VaultKeyError:
                problems.append(f"evidence cannot be decrypted: {name[:12]}")
                continue
            if _sha(raw) != name:
                problems.append(f"evidence altered: {name[:12]}")
    return {"files": len(files), "databases": databases, "evidence_files": evidence, "problems": problems,
            "evidence_encrypted_without_matching_key": unverifiable, "vault_key_fingerprint": want,
            "your_key_matches": key_matches, "created": manifest.get("created")}


def verify(backup: Path, passphrase: str) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        manifest, files = _open(backup, passphrase, Path(tmp))
        report = _check(manifest, files, Path(tmp))
    report["ok"] = not report["problems"]
    return report


def restore(backup: Path, passphrase: str, target: Path) -> dict:
    target = target.resolve()
    if target.exists() and any(target.iterdir()):
        raise BackupError("restore target must be a new or empty folder; nothing was changed")
    with tempfile.TemporaryDirectory() as tmp:
        manifest, files = _open(backup, passphrase, Path(tmp))
        report = _check(manifest, files, Path(tmp))
        if report["problems"]:
            report["ok"] = False
            report["restored"] = False
            return report
        for rel, content in files.items():
            path = target / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
    report.update({"ok": True, "restored": True, "target": str(target)})
    return report


def _passphrase(confirm: bool) -> str:
    if os.environ.get("PRAMAAN_BACKUP_PASSPHRASE"):
        return os.environ["PRAMAAN_BACKUP_PASSPHRASE"]
    first = getpass.getpass("Backup passphrase: ")
    if confirm and getpass.getpass("Repeat passphrase: ") != first:
        raise BackupError("the passphrases do not match")
    return first


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PRAMAAN encrypted backup and verified restore")
    sub = parser.add_subparsers(dest="command", required=True)
    c = sub.add_parser("create")
    c.add_argument("--data", type=Path, default=Path(os.environ.get("PRAMAAN_DATA", "backend/data")))
    c.add_argument("--out", type=Path, required=True)
    c.add_argument("--keep", type=int, help="keep only the newest N backups in --out")
    v = sub.add_parser("verify")
    v.add_argument("backup", type=Path)
    r = sub.add_parser("restore")
    r.add_argument("backup", type=Path)
    r.add_argument("--to", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "create":
            result = create(args.data, args.out, _passphrase(True), args.keep)
        elif args.command == "verify":
            result = verify(args.backup, _passphrase(False))
        else:
            result = restore(args.backup, _passphrase(False), args.to)
    except (BackupError, vault_crypto.VaultKeyError, OSError) as exc:
        print(f"Refused: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=1))
    return 0 if result.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
