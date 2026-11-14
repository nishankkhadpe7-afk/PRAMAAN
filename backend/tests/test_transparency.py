"""Verifiable event log: Merkle proofs, signed checkpoints and the offline verifier."""
import hashlib
import json
import subprocess
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from Pramaan.backend import app as p1, p3, security, transparency as t

REPO = Path(__file__).resolve().parents[2]


class MerkleTests(unittest.TestCase):
    def test_rfc6962_empty_and_single_leaf_roots(self):
        self.assertEqual(t.root([]).hex(), "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")
        leaf = hashlib.sha256(b"\x00").digest()  # RFC 6962 test vector: leaf with empty input
        self.assertEqual(leaf.hex(), "6e340b9cffb37a989ca544e6bb780a2c78901d3fb33738768511a30617afa01d")
        self.assertEqual(t.root([leaf]), leaf)

    def test_every_inclusion_and_consistency_proof_verifies_and_tampering_fails(self):
        for size in range(1, 34):
            leaves = [t.leaf_hash(hashlib.sha256(str(i).encode()).hexdigest()) for i in range(size)]
            top = t.root(leaves)
            for index in range(size):
                path = t.inclusion_path(index, leaves)
                self.assertTrue(t.verify_inclusion(leaves[index], index, size, path, top), (size, index))
                self.assertFalse(t.verify_inclusion(hashlib.sha256(b"forged").digest(), index, size, path, top))
            for first in range(0, size + 1):
                proof = t.consistency_path(first, leaves)
                self.assertTrue(t.verify_consistency(first, size, t.root(leaves[:first]), top, proof), (first, size))
                if 0 < first < size:
                    rewritten = [hashlib.sha256(b"rewritten").digest()] + leaves[1:first]
                    self.assertFalse(t.verify_consistency(first, size, t.root(rewritten), top, proof), (first, size))


class LogEndpointTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parent / ".runtime" / ("log-" + uuid.uuid4().hex)
        self.root.mkdir(parents=True)
        self.patches = [patch.object(p1, "ROOT", self.root), patch.object(p1, "DB_PATH", self.root / "p1.sqlite3"), patch.object(p1, "VAULT", self.root / "vault"), patch.dict("os.environ", {"PRAMAAN_LOG_SIGNING_KEY": ""})]
        for item in self.patches:
            item.start()
        self.tokens = {"client": security.issue("employee", "client_employee"), "auditor": security.issue("agent-auditor", "auditor")}
        self.client = TestClient(p1.app)
        p3.import_fixture_dataset()

    def tearDown(self):
        self.client.close()
        for item in reversed(self.patches):
            item.stop()

    def get(self, path, role="auditor"):
        return self.client.get(path, headers={"Authorization": "Bearer " + self.tokens[role]})

    def add_customer(self, n):
        response = self.client.post("/p2/customers", headers={"Authorization": "Bearer " + self.tokens["client"]}, json={"customer_id": f"LOG-C{n}", "name": f"Synthetic {n}"})
        self.assertEqual(response.status_code, 200, response.text)

    def test_checkpoints_proofs_and_offline_verifier(self):
        self.assertEqual(self.client.get("/log/checkpoint").status_code, 401)
        for n in range(5):
            self.add_customer(n)
        early = self.get("/log/checkpoint", "client").json()
        self.assertTrue(t.verify_checkpoint(early))
        self.assertGreaterEqual(early["tree_size"], 5)
        self.assertEqual(oct((self.root / "log-signing.key").stat().st_mode & 0o777), "0o600")
        for n in range(5, 12):
            self.add_customer(n)
        proof = self.get("/log/proof?seq=3").json()
        late = proof["checkpoint"]
        self.assertEqual(late["public_key"], early["public_key"])
        self.assertGreater(late["tree_size"], early["tree_size"])
        self.assertTrue(t.verify_inclusion(t.leaf_hash(proof["entry_hash"]), proof["leaf_index"], late["tree_size"], [bytes.fromhex(h) for h in proof["inclusion_path"]], bytes.fromhex(late["root_hash"])))
        self.assertEqual(self.get("/log/proof?seq=999999").status_code, 404)
        consistency = self.get(f"/log/consistency?first={early['tree_size']}").json()
        self.assertEqual(consistency["first_root_hash"], early["root_hash"])
        self.assertTrue(t.verify_consistency(early["tree_size"], consistency["checkpoint"]["tree_size"], bytes.fromhex(early["root_hash"]), bytes.fromhex(consistency["checkpoint"]["root_hash"]), [bytes.fromhex(h) for h in consistency["consistency_path"]]))
        self.assertEqual(self.get("/log/consistency?first=999999").status_code, 422)
        # A forged checkpoint (different root, old signature) is rejected; so is one checked against another key.
        self.assertFalse(t.verify_checkpoint({**late, "root_hash": "00" * 32}))
        self.assertFalse(t.verify_checkpoint(late, "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="))
        # The standalone script reaches the same verdicts from the saved JSON files alone.
        files = {name: self.root / f"{name}.json" for name in ("proof", "consistency", "early", "bad")}
        files["proof"].write_text(json.dumps(proof)); files["consistency"].write_text(json.dumps(consistency)); files["early"].write_text(json.dumps(early))
        files["bad"].write_text(json.dumps({**proof, "event_json": proof["event_json"].replace("customer", "CUSTOMER", 1) + " "}))
        script = [sys.executable, str(REPO / "scripts" / "verify_log_proof.py")]
        ok = subprocess.run(script + ["inclusion", str(files["proof"]), "--public-key", early["public_key"]], capture_output=True, text=True)
        self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
        self.assertNotIn("FAIL", ok.stdout)
        self.assertEqual(subprocess.run(script + ["consistency", str(files["consistency"]), "--earlier", str(files["early"])], capture_output=True, text=True).returncode, 0)
        bad = subprocess.run(script + ["inclusion", str(files["bad"])], capture_output=True, text=True)
        self.assertEqual(bad.returncode, 1)
        self.assertIn("FAIL", bad.stdout)


if __name__ == "__main__":
    unittest.main()
