import base64
import hashlib
import json
import sqlite3
import uuid
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile
from xml.etree import ElementTree as ET
import io

from Pramaan.backend import app as p1


class P1AcceptanceTests(unittest.TestCase):
    def setUp(self):
        workspace_tmp = Path(__file__).resolve().parent / ".runtime"
        root = workspace_tmp / uuid.uuid4().hex
        root.mkdir(parents=True)
        self.temp_root = root
        self.ruleset_path = root / "ruleset.yaml"
        self.ruleset = {"version": "test-rules-v1", "tests": {"T06": {"value_absolute_tolerance": "1.00", "quantity_absolute_tolerance": "0", "exact_fields": ["gstin", "pin", "vehicle_no"]}}}
        self.ruleset_path.write_text(json.dumps(self.ruleset), encoding="utf-8")
        self.patches = [patch.object(p1, "ROOT", root), patch.object(p1, "DB_PATH", root / "p1.sqlite3"), patch.object(p1, "VAULT", root / "vault"), patch.object(p1, "RULESET_PATH", self.ruleset_path)]
        for item in self.patches:
            item.start()
        from Pramaan.backend.security import bootstrap
        bootstrap()
        self.payload = p1.SaleIn(sale_id="SALE-001", register_source_base64=base64.b64encode(b'Bill No,Gross Amt\r\nG/0001/26,1180.00\r\n').decode(), register_row={"Bill No": "G/0001/26", "Gross Amt": "1180.00"}, party={"party_id": "PTY-001", "name": "Synthetic Demo Customer"}, invoice={"value": 1180, "quantity": 2}, dispatch={"value": 1178, "quantity": 2}, evidence=[p1.EvidenceIn(evidence_id="EV-INV-001", content_type="text/plain", content_base64=base64.b64encode(b"synthetic invoice").decode(), controller="client", acquisition_channel="company_upload", independently_verified=False, assertions=["occurrence", "accuracy"])])

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        # Keep each isolated test run's small SQLite/vault fixture for post-failure inspection.

    def test_same_snapshot_rules_and_seed_reproduce_same_result(self):
        p1.import_sale(self.payload)
        snap = p1.create_snapshot("SALE-001")
        first = p1.run_audit("SALE-001", seed="seed-42")
        second = p1.run_audit("SALE-001", seed="seed-42")
        self.assertEqual(snap["snapshot_hash"], first["snapshot_hash"])
        self.assertEqual(first["findings"], second["findings"])
        self.assertEqual(first["run_id"], second["run_id"])
        sale = p1.get_sale("SALE-001")
        raw_source = b'Bill No,Gross Amt\r\nG/0001/26,1180.00\r\n'
        self.assertEqual((p1.VAULT / sale["register_source_sha256"]).read_bytes(), raw_source)
        self.assertEqual(sale["register_source_sha256"], hashlib.sha256(raw_source).hexdigest())
        evidence_ids = {e["evidence_id"] for e in sale["evidence"]}
        self.assertTrue(all(set(f["evidence_ids"]) <= evidence_ids for f in first["findings"]))
        evidence_hashes = {e["evidence_id"]: e["sha256"] for e in sale["evidence"]}
        self.assertTrue(all((p1.VAULT / evidence_hashes[eid]).is_file() for f in first["findings"] for eid in f["evidence_ids"]))
        self.ruleset_path.write_text(json.dumps({"version": "changed-after-run", "tests": {"T06": {"value_absolute_tolerance": "99", "quantity_absolute_tolerance": "99", "exact_fields": []}}}), encoding="utf-8")
        reproduced = p1.reproduce("SALE-001", first["run_id"])
        self.assertTrue(reproduced["identical"])
        self.assertEqual(reproduced["result"], {k: first[k] for k in ("run_id", "sale_id", "snapshot_hash", "ruleset_version", "ruleset_hash", "sampling_seed", "canonicalization_version", "findings")})
        self.assertEqual(first["ruleset_version"], "test-rules-v1")

    def test_change_after_snapshot_is_mapped_and_workpaper_has_resolvable_evidence(self):
        p1.import_sale(self.payload)
        p1.create_snapshot("SALE-001")
        run = p1.run_audit("SALE-001", seed="seed-42")
        p1.update_business_record("SALE-001", p1.RecordPatch(record="dispatch", field="value", value=999))
        change = p1.detect_changes("SALE-001")
        self.assertTrue(change["changed"])
        self.assertEqual(change["sale_id"], "SALE-001")
        self.assertEqual(change["affected_run_id"], run["run_id"])
        self.assertTrue(change["affected_finding_ids"])
        self.assertTrue(p1.reproduce("SALE-001", run["run_id"])["identical"])
        self.assertTrue(p1.verify_log()["valid"])
        response = p1.export_workpaper(run["run_id"])
        with ZipFile(io.BytesIO(response.body)) as book:
            workbook = ET.fromstring(book.read("xl/workbook.xml"))
            ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
            sheets = workbook.findall("m:sheets/m:sheet", ns)
            self.assertEqual([sheet.attrib["name"] for sheet in sheets], ["P1 Findings"])
            sheet = book.read("xl/worksheets/sheet1.xml").decode()
            self.assertIn("EV-INV-001", sheet)
            self.assertIn("T06", sheet)

    def test_caller_cannot_self_certify_evidence_and_all_assertions_are_evaluated(self):
        attack_evidence = self.payload.evidence[0].model_copy(update={"independently_verified": True})
        attack_payload = self.payload.model_copy(update={"invoice": {"value": 1180, "quantity": 2}, "dispatch": {"value": 1180, "quantity": 2}, "evidence": [attack_evidence]})
        p1.import_sale(attack_payload)
        p1.create_snapshot("SALE-001")
        result = p1.run_audit("SALE-001", seed="attack-test")
        findings = {(f["test_id"], f["assertion"]): f for f in result["findings"]}
        self.assertFalse(p1.get_sale("SALE-001")["evidence"][0]["independently_verified"])
        self.assertEqual(findings[("T12", "occurrence")]["state"], "INTERNAL_ONLY")
        self.assertEqual(findings[("T12", "accuracy")]["state"], "INTERNAL_ONLY")
        self.assertEqual(findings[("T12", "cutoff")]["state"], "GAP")
        self.assertEqual(findings[("T12", "classification")]["state"], "GAP")

    def test_empty_evidence_emits_gap_for_each_required_assertion(self):
        payload = self.payload.model_copy(update={"invoice": {"value": 1180, "quantity": 2}, "dispatch": {"value": 1180, "quantity": 2}, "evidence": []})
        p1.import_sale(payload)
        p1.create_snapshot("SALE-001")
        result = p1.run_audit("SALE-001", seed="empty-evidence")
        states = {(f["test_id"], f["assertion"]): f["state"] for f in result["findings"] if f["test_id"] == "T12"}
        self.assertEqual(states, {("T12", "occurrence"): "GAP", ("T12", "accuracy"): "GAP", ("T12", "cutoff"): "GAP", ("T12", "classification"): "GAP"})

    def test_t06_value_tolerance_inclusive_boundary(self):
        base = {"sale_id": "TOL", "invoice": {"quantity": 2}, "dispatch": {"quantity": 2}, "evidence": []}
        for delta, expected in (("0.99", False), ("1.00", False), ("1.01", True)):
            state = {**base, "invoice": {"value": "100.00", "quantity": 2}, "dispatch": {"value": str(Decimal("100.00") + Decimal(delta)), "quantity": 2}}
            result = p1.run_rules(state, "R-TOL", "a" * 64, "tol-seed", self.ruleset)
            self.assertEqual(any(f["test_id"] == "T06" for f in result["findings"]), expected, delta)
            accuracy = next(f for f in result["findings"] if f["test_id"] == "T12" and f["assertion"] == "accuracy")
            self.assertEqual(accuracy["state"], "INCONSISTENT" if expected else "GAP", delta)

    def test_t06_configured_identity_fields_are_exact(self):
        state = {"sale_id": "ID-MISMATCH", "invoice": {"gstin": "29ABCDE1234F1Z5"}, "dispatch": {"gstin": "29ABCDE1234F1Z6"}, "evidence": []}
        result = p1.run_rules(state, "R-ID", "b" * 64, "id-seed", self.ruleset)
        finding = next(f for f in result["findings"] if f["test_id"] == "T06")
        self.assertIn("gstin", finding["reason"])

    def test_integrity_verifier_detects_a_broken_predecessor_link(self):
        p1.import_sale(self.payload)
        self.assertTrue(p1.verify_log()["valid"])
        db = sqlite3.connect(p1.DB_PATH)
        db.execute("DROP TRIGGER events_no_update")
        db.execute("UPDATE events SET prev_hash=? WHERE seq=1", ("f" * 64,))
        db.commit()
        db.close()
        self.assertFalse(p1.verify_log()["valid"])


if __name__ == "__main__":
    unittest.main()
