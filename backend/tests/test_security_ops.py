"""Encryption at rest for the evidence vault, and encrypted backup / verified restore."""
import base64
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from Pramaan.backend import app as p1, backup, security, vault_crypto, vault_tools

CSV = b"Bill No,Date,Customer,Gross Amt,GST No\r\nINV-1,01/04/2025,Synthetic Buyer,1180.00,\r\n"


class Env:
    """A fresh data folder (and a key folder outside it), with the app pointed at it."""

    def __init__(self, key: bool):
        self.tmp = Path(tempfile.mkdtemp(prefix="pramaan-sec-"))
        self.data, self.keys = self.tmp / "data", self.tmp / "keys"
        self.keys.mkdir()
        self.key_file = self.keys / "vault.key"
        self.key_file.write_text(vault_crypto.new_key_text())
        env = {"PRAMAAN_DATA": str(self.data)}
        if key:
            env["PRAMAAN_VAULT_KEY_FILE"] = str(self.key_file)
        self.patches = [patch.object(p1, "ROOT", self.data), patch.object(p1, "DB_PATH", self.data / "p1.sqlite3"),
                        patch.object(p1, "VAULT", self.data / "vault"), patch.dict(os.environ, env)]
        if not key:
            self.patches.append(patch.dict(os.environ, {}, clear=False))
            os.environ.pop("PRAMAAN_VAULT_KEY_FILE", None)

    def __enter__(self):
        for p in self.patches:
            p.start()
        self.client = TestClient(p1.app)
        return self

    def __exit__(self, *exc):
        for p in reversed(self.patches):
            p.stop()

    def upload(self) -> dict:
        token = security.issue("emp", "client_employee", ttl=600)
        r = self.client.post("/p2/registers", headers={"Authorization": "Bearer " + token},
                             json={"period": "FY26", "source_base64": base64.b64encode(CSV).decode()})
        assert r.status_code == 200, r.text
        return r.json()


class VaultEncryptionTests(unittest.TestCase):
    def test_evidence_is_encrypted_on_disk_and_read_back_intact(self):
        with Env(key=True) as env:
            sha = env.upload()["sha256"]
            stored = (env.data / "vault" / sha).read_bytes()
            self.assertTrue(stored.startswith(vault_crypto.MAGIC))
            self.assertNotIn(b"Synthetic Buyer", stored)
            self.assertEqual(p1.read_blob(sha), CSV)
            self.assertTrue(p1.blob_intact(sha))

    def test_without_the_key_encrypted_evidence_is_refused_not_misread(self):
        with Env(key=True) as env:
            sha = env.upload()["sha256"]
            with patch.dict(os.environ, {"PRAMAAN_VAULT_KEY_FILE": ""}):
                with self.assertRaises(vault_crypto.VaultKeyError):
                    p1.read_blob(sha)
            env.key_file.write_text(vault_crypto.new_key_text())  # a different key
            with self.assertRaises(vault_crypto.VaultKeyError):
                p1.read_blob(sha)

    def test_swapped_file_fails_because_the_name_is_bound_in(self):
        key = base64.urlsafe_b64decode(vault_crypto.new_key_text() + "=")
        sealed = vault_crypto.seal("a" * 64, b"one", key)
        with self.assertRaises(vault_crypto.VaultKeyError):
            vault_crypto.unseal("b" * 64, sealed, key)

    def test_key_file_inside_the_data_folder_is_refused(self):
        with Env(key=True) as env:
            inside = env.data / "vault.key"
            env.data.mkdir(parents=True, exist_ok=True)
            inside.write_text(vault_crypto.new_key_text())
            with patch.dict(os.environ, {"PRAMAAN_VAULT_KEY_FILE": str(inside)}):
                with self.assertRaises(vault_crypto.VaultKeyError):
                    vault_crypto.configured_key(env.data)

    def test_plaintext_vault_is_converted_both_ways_without_changing_content(self):
        with Env(key=False) as env:
            sha = env.upload()["sha256"]
            self.assertFalse((env.data / "vault" / sha).read_bytes().startswith(vault_crypto.MAGIC))
            with patch.dict(os.environ, {"PRAMAAN_VAULT_KEY_FILE": str(env.key_file)}):
                self.assertEqual(vault_tools.convert(env.data, encrypt=True)["changed"], 1)
                self.assertTrue((env.data / "vault" / sha).read_bytes().startswith(vault_crypto.MAGIC))
                self.assertEqual(p1.read_blob(sha), CSV)
                self.assertEqual(vault_tools.convert(env.data, encrypt=False)["changed"], 1)
            self.assertEqual((env.data / "vault" / sha).read_bytes(), CSV)

    def test_damaged_file_is_left_alone_by_the_converter(self):
        with Env(key=False) as env:
            sha = env.upload()["sha256"]
            (env.data / "vault" / sha).write_bytes(b"tampered")
            with patch.dict(os.environ, {"PRAMAAN_VAULT_KEY_FILE": str(env.key_file)}):
                result = vault_tools.convert(env.data, encrypt=True)
            self.assertEqual((result["changed"], result["failed_integrity"]), (0, [sha[:12]]))
            self.assertEqual((env.data / "vault" / sha).read_bytes(), b"tampered")


PASS = "correct horse battery staple"


class BackupTests(unittest.TestCase):
    def test_backup_verify_restore_round_trip(self):
        with Env(key=True) as env:
            sha = env.upload()["sha256"]
            made = backup.create(env.data, env.tmp / "backups", PASS)
            file = Path(made["backup"])
            self.assertNotIn(b"Synthetic Buyer", file.read_bytes())
            report = backup.verify(file, PASS)
            self.assertTrue(report["ok"], report)
            self.assertTrue(report["your_key_matches"])
            self.assertGreaterEqual(report["databases"], 2)
            restored = backup.restore(file, PASS, env.tmp / "restored")
            self.assertTrue(restored["restored"])
            self.assertEqual((env.tmp / "restored" / "vault" / sha).read_bytes(), (env.data / "vault" / sha).read_bytes())
            # the restored folder works as a data folder
            with patch.object(p1, "VAULT", env.tmp / "restored" / "vault"), patch.object(p1, "ROOT", env.tmp / "restored"):
                self.assertEqual(p1.read_blob(sha), CSV)

    def test_wrong_passphrase_truncation_and_tampering_are_refused(self):
        with Env(key=False) as env:
            env.upload()
            file = Path(backup.create(env.data, env.tmp / "b", PASS)["backup"])
            with self.assertRaises(backup.BackupError):
                backup.verify(file, "a different passphrase")
            raw = file.read_bytes()
            cut = env.tmp / "cut.pramaan"
            cut.write_bytes(raw[:-40])
            with self.assertRaises(backup.BackupError):
                backup.verify(cut, PASS)
            flipped = bytearray(raw)
            flipped[len(raw) // 2] ^= 1
            bad = env.tmp / "bad.pramaan"
            bad.write_bytes(bytes(flipped))
            with self.assertRaises(backup.BackupError):
                backup.verify(bad, PASS)

    def test_restore_never_writes_into_a_folder_with_files(self):
        with Env(key=False) as env:
            env.upload()
            file = Path(backup.create(env.data, env.tmp / "b", PASS)["backup"])
            target = env.tmp / "busy"
            target.mkdir()
            (target / "keep.txt").write_text("mine")
            with self.assertRaises(backup.BackupError):
                backup.restore(file, PASS, target)
            self.assertEqual(sorted(p.name for p in target.iterdir()), ["keep.txt"])

    def test_short_passphrase_and_backup_inside_data_folder_are_refused(self):
        with Env(key=False) as env:
            env.upload()
            with self.assertRaises(backup.BackupError):
                backup.create(env.data, env.tmp / "b", "short")
            with self.assertRaises(backup.BackupError):
                backup.create(env.data, env.data / "backups", PASS)

    def test_rotation_keeps_only_the_newest(self):
        with Env(key=False) as env:
            env.upload()
            out = env.tmp / "rot"
            out.mkdir()
            for stamp in ("20260101-000000", "20260102-000000", "20260103-000000"):
                (out / f"pramaan-backup-{stamp}.pramaan").write_bytes(b"x")
            (out / "unrelated.txt").write_text("keep")
            made = backup.create(env.data, out, PASS, keep=2)
            self.assertEqual(len(made["older_backups_removed"]), 2)
            self.assertEqual(sorted(p.name for p in out.glob("pramaan-backup-*")), sorted(["pramaan-backup-20260103-000000.pramaan", Path(made["backup"]).name]))
            self.assertTrue((out / "unrelated.txt").exists())


if __name__ == "__main__":
    unittest.main()
