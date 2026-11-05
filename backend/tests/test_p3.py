import asyncio
import base64
import csv
import hashlib
import json
import shutil
import sqlite3
import tempfile
import uuid
import unittest
from pathlib import Path
from unittest.mock import patch

from Pramaan.backend import app as p1
from Pramaan.backend import p3
from Pramaan.backend import p3_dataset


class P3WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parent / ".runtime" / ("p3-" + uuid.uuid4().hex)
        self.root.mkdir(parents=True)
        self.patches = [patch.object(p1, "ROOT", self.root), patch.object(p1, "DB_PATH", self.root / "p1.sqlite3"), patch.object(p1, "VAULT", self.root / "vault")]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()

    def request(self, method, path, payload=None):
        if path == "/p3/datasets/import":
            from Pramaan.backend.tests.auth_support import offline_fixture_import
            return offline_fixture_import()
        body = json.dumps(payload or {}).encode()
        messages, sent = [{"type": "http.request", "body": body, "more_body": False}], []

        async def receive():
            return messages.pop(0) if messages else {"type": "http.disconnect"}

        async def send(message):
            sent.append(message)

        raw_path, _, query = path.partition("?")
        scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"}, "http_version": "1.1", "method": method, "scheme": "http", "path": raw_path, "raw_path": raw_path.encode(), "query_string": query.encode(), "root_path": "", "headers": [(b"content-type", b"application/json")], "client": ("test", 2345), "server": ("test", 80)}
        from Pramaan.backend.tests.auth_support import headers
        scope["headers"].extend(headers(scope))
        asyncio.run(p1.app(scope, receive, send))
        status = next(message["status"] for message in sent if message["type"] == "http.response.start")
        response_body = b"".join(message.get("body", b"") for message in sent if message["type"] == "http.response.body")
        return status, json.loads(response_body or b"{}")

    def seed_population(self):
        for customer_no in range(4):
            status, customer = self.request("POST", "/p2/customers", {"customer_id": f"P3-CUST-{customer_no}", "name": f"P3 Synthetic Customer {customer_no}", "gstin": f"29ABCDE1234F{customer_no}Z5"})
            self.assertEqual(status, 200, customer)
        for number in range(32):
            invoice_date = (f"2026-03-{number + 1:02}" if number < 20 else f"2026-04-{number - 19:02}")
            payload = {"order_id": f"P3-SO-{number:02}", "dispatch_id": f"P3-DSP-{number:02}", "invoice_id": f"P3-INV-{number:02}", "journal_id": f"P3-JRN-{number:02}", "customer_id": f"P3-CUST-{number % 4}", "order_date": invoice_date, "dispatch_date": invoice_date, "invoice_date": invoice_date, "bill_no": f"P3-{number:03}", "net_amount": ("150000.00" if number == 0 else "100.00"), "tax_amount": "5.00"}
            if number in (0, 1):
                payload["evidence"] = [{"evidence_id": f"P3-EV-{number}", "content_base64": base64.b64encode(b"same synthetic content").decode(), "content_type": "text/plain"}]
            if number == 0:
                payload["credit_note"] = {"credit_note_id": "P3-CN-POST", "credit_date": "2026-04-15", "amount": "2.50", "reason": "quality adjustment"}
            if number == 1:
                payload["credit_note"] = {"credit_note_id": "P3-CN-IN", "credit_date": "2026-03-15", "amount": "2.50", "reason": "in-period adjustment"}
            status, result = self.request("POST", "/p2/sales", payload)
            self.assertEqual(status, 200, result)
        rp_source = b"customer_id,related_party,valid_from,relationship_type\r\nP3-CUST-0,true,2025-04-01,disclosed director relation\r\n"
        status, uploaded = self.request("POST", "/p2/related-parties", {"period": "FY26", "source_base64": base64.b64encode(rp_source).decode(), "records": [{"customer_id": "P3-CUST-0", "related_party": True, "valid_from": "2025-04-01", "relationship_type": "disclosed director relation"}]})
        self.assertEqual(status, 200, uploaded)

    def test_versioned_tests_reproducible_samples_and_evidence_request_loop(self):
        self.seed_population()
        status, run = self.request("POST", "/p3/audit-runs", {"period_start": "2025-04-01", "period_end": "2026-03-31", "sampling_seed": "p3-test-seed-2026-0001"})
        self.assertEqual(status, 200, run)
        sales = [s for s in run["sample_items"] if s["sheet"] == "sales_tod"]
        cutoff = [s for s in run["sample_items"] if s["sheet"] == "cutoff_tod"]
        cn_sample = [s for s in run["sample_items"] if s["sheet"] == "credit_note_tod"]
        self.assertGreaterEqual(len(sales), 25)
        self.assertLessEqual(len(sales), 35)
        self.assertEqual(len({s["object_ref"] for s in sales}), len(sales))
        self.assertTrue(all(s["selection_reason"] for s in run["sample_items"]))
        self.assertTrue(any(s["stratum"] == "probability" and s["random_draw"] for s in sales))
        self.assertEqual(run["ruleset_version"], "p3-2026-02")
        status, reproduction = self.request("POST", f"/p3/audit-runs/{run['run_id']}/reproduce")
        self.assertEqual(status, 200, reproduction)
        self.assertTrue(reproduction["identical"])
        self.assertEqual(reproduction["result"]["findings"], run["findings"])
        self.assertEqual(run["sampler_version"], "p3-hash-ranked-v1")
        self.assertIn("then object reference", run["sampler_tie_break"])
        self.assertEqual(run["sampling_seed"], "p3-test-seed-2026-0001")
        self.assertEqual(run["coverage"]["sales_tod"]["population_projection_supported"], False)
        sales_coverage = run["coverage"]["sales_tod"]
        self.assertEqual(len(sales_coverage["selected_refs"]), sales_coverage["selected"])
        self.assertEqual(len(sales_coverage["not_selected_refs"]) + sales_coverage["selected"], sales_coverage["eligible_population"])
        self.assertEqual(len(sales_coverage["probability_selected_refs"]), sales_coverage["probability_selected"])
        self.assertEqual(len(sales_coverage["probability_not_selected_refs"]) + sales_coverage["probability_selected"], sales_coverage["probability_population"])
        self.assertEqual(len(sales_coverage["certainty_excluded_from_probability_refs"]), sales_coverage["certainty_excluded_from_probability_count"])
        self.assertEqual(run["coverage"]["cutoff_tod"]["before_selected"], 10)
        self.assertEqual(run["coverage"]["cutoff_tod"]["after_selected"], 12)
        self.assertEqual(len(run["coverage"]["cutoff_tod"]["before_excluded_refs"]), run["coverage"]["cutoff_tod"]["before_population"] - run["coverage"]["cutoff_tod"]["before_selected"])
        self.assertEqual(len(run["coverage"]["cutoff_tod"]["after_excluded_refs"]), run["coverage"]["cutoff_tod"]["after_population"] - run["coverage"]["cutoff_tod"]["after_selected"])
        self.assertEqual(run["coverage"]["sales_tod"]["related_party_eligible"], 8)
        selected_customer_numbers = {int(s["object_ref"].rsplit("-", 1)[1]) % 4 for s in sales}
        self.assertGreater(len(selected_customer_numbers), 1)
        self.assertGreater(run["coverage"]["sales_tod"]["related_party_selected"], 0)
        self.assertTrue(any(customer_no != 0 for customer_no in selected_customer_numbers))
        self.assertEqual(run["coverage"]["cutoff_tod"]["after_population"], 12)
        self.assertEqual(len(cutoff), run["coverage"]["cutoff_tod"]["before_selected"] + run["coverage"]["cutoff_tod"]["after_selected"])
        self.assertEqual(run["coverage"]["overlaps"]["sales_cutoff_invoice_refs"], sorted(set(s["object_ref"] for s in sales) & set(s["object_ref"] for s in cutoff)))
        self.assertEqual(run["coverage"]["credit_note_tod"]["post_period_census_population"], 1)
        self.assertEqual(len(run["coverage"]["credit_note_tod"]["in_period_not_selected_refs"]) + run["coverage"]["credit_note_tod"]["in_period_selected"], run["coverage"]["credit_note_tod"]["in_period_population"])
        self.assertEqual(run["rule_coverage"]["T02"]["status"], "not_evaluable")
        self.assertEqual(run["rule_coverage"]["T05"]["status"], "schema_limited")
        self.assertEqual(run["rule_coverage"]["T06"]["status"], "schema_limited")
        self.assertEqual(run["rule_coverage"]["T15"]["status"], "not_evaluable")
        self.assertEqual(run["rule_coverage"]["T03"]["status"], "review_required")
        self.assertEqual(run["rule_coverage"]["T04"]["status"], "evaluated_for_selected_samples")
        self.assertEqual(run["rule_coverage"]["T07"]["status"], "evaluated_hash_reuse_review_only")
        self.assertEqual(run["rule_coverage"]["T09"]["status"], "evaluated_post_period_90_day_window")
        self.assertEqual(run["rule_coverage"]["T10"]["status"], "not_evaluable")
        self.assertEqual(run["rule_coverage"]["T08"]["status"], "not_evaluable")
        self.assertEqual(run["rule_coverage"]["T11"]["status"], "not_evaluable")
        self.assertEqual(run["rule_coverage"]["T12"]["status"], "not_evaluable")
        self.assertEqual(run["rule_coverage"]["T13"]["status"], "not_evaluable")
        self.assertEqual(run["rule_coverage"]["T14"]["status"], "not_evaluable")

        findings = run["findings"]
        self.assertTrue(any(f["test_id"] == "T01" and f["state"] == "DISCLOSED_RELATED_PARTY" for f in findings))
        self.assertTrue(any(f["test_id"] == "T03" and f["state"] == "GAP" for f in findings))
        self.assertTrue(any(f["test_id"] == "T04" and f["state"] == "GAP" for f in findings))
        self.assertTrue(any(f["test_id"] == "T07" and f["state"] == "REVIEW" for f in findings))
        self.assertTrue(any(s["object_ref"] == "P3-CN-POST" and s["stratum"] == "post_period_census" for s in cn_sample))
        self.assertTrue(any(s["object_ref"] == "P3-CN-IN" for s in cn_sample))
        innocent_cn = next(f for f in findings if f["test_id"] == "T09" and f["object_ref"] == "P3-CN-POST")
        self.assertEqual(innocent_cn["state"], "REVIEW")
        self.assertFalse(innocent_cn["confirmed_exception"])

        status, reproduced = self.request("POST", f"/p3/audit-runs/{run['run_id']}/reproduce")
        self.assertEqual(status, 200, reproduced)
        self.assertTrue(reproduced["identical"])
        self.assertEqual(reproduced["result"]["sample_items"], run["sample_items"])
        self.assertEqual(reproduced["result"]["findings"], run["findings"])

        status, requests = self.request("GET", f"/p3/audit-runs/{run['run_id']}/evidence-requests")
        self.assertEqual(status, 200, requests)
        sales_request = next(req for req in requests["requests"] if req["sheet"] == "sales_tod")
        required = sales_request["required_docs"]
        self.assertEqual(required, ["invoice", "e_way_bill", "lorry_receipt"])
        for index, doc_type in enumerate(required):
            status, uploaded = self.request("POST", f"/p3/evidence-requests/{sales_request['request_id']}/evidence", {"evidence_id": f"P3-UP-{index}", "document_type": doc_type, "content_base64": base64.b64encode(("proof-" + doc_type).encode()).decode(), "content_type": "text/plain", "controller": "client", "acquisition_channel": "company_upload"})
            self.assertEqual(status, 200, uploaded)
            self.assertFalse(uploaded["independently_verified"])
            self.assertEqual(uploaded["status"], "fulfilled" if index == len(required) - 1 else "partially_fulfilled")
        db = sqlite3.connect(p1.DB_PATH)
        self.assertEqual(db.execute("SELECT sampling_seed,ruleset_version,sampler_version FROM p3_audit_runs WHERE run_id=?", (run["run_id"],)).fetchone(), ("p3-test-seed-2026-0001", "p3-2026-02", "p3-hash-ranked-v1"))
        self.assertGreater(db.execute("SELECT count(*) FROM p3_draws WHERE run_id=?", (run["run_id"],)).fetchone()[0], 0)
        self.assertEqual(db.execute("SELECT count(*) FROM p3_samples WHERE run_id=? AND selection_reason<>''", (run["run_id"],)).fetchone()[0], len(run["sample_items"]))
        self.assertEqual(db.execute("SELECT count(*) FROM p3_evidence WHERE request_id=? AND independently_verified=0 AND verification_method IS NULL", (sales_request["request_id"],)).fetchone()[0], 3)
        db.close()
        status, rerun = self.request("POST", f"/p3/audit-runs/{run['run_id']}/rerun")
        self.assertEqual(status, 200, rerun)
        self.assertNotEqual(rerun["snapshot_hash"], run["snapshot_hash"])
        self.assertNotEqual(rerun["run_id"], run["run_id"])
        self.assertFalse(any(f["test_id"] == "T04" and f["object_ref"] == sales_request["sample_ref"] and f.get("sample_sheet") == "sales_tod" for f in rerun["findings"]))

    def test_synthetic_data_pack_imports_and_drives_p3_findings(self):
        status, imported = self.request("POST", "/p3/datasets/import")
        self.assertEqual(status, 200, imported)
        self.assertTrue(imported["synthetic"])
        self.assertEqual(imported["file_count"], 13)
        self.assertEqual(imported["row_count"], 66)
        self.assertEqual(p3_dataset.validate_dataset(p3_dataset.DATA_DIR)[0]["data_classification"], "synthetic-fictional-not-real-taxpayer-data")
        ruleset = p3.load_ruleset()
        self.assertEqual(ruleset["version"], "p3-2026-02")
        self.assertEqual(ruleset["period_end_concentration"]["classification"], "synthetic_test_only")
        self.assertEqual(ruleset["pricing"]["mapping_classification"], "synthetic_test_only")
        status, idempotent = self.request("POST", "/p3/datasets/import")
        self.assertEqual(status, 200, idempotent)
        self.assertTrue(idempotent["already_imported"])

        db = sqlite3.connect(p1.DB_PATH)
        self.assertEqual(db.execute("SELECT count(*) FROM p3_dataset_files WHERE dataset_id=?", (imported["dataset_id"],)).fetchone()[0], 13)
        self.assertEqual(db.execute("SELECT count(*) FROM p3_dataset_rows WHERE dataset_id=?", (imported["dataset_id"],)).fetchone()[0], 66)
        invoice_hash = db.execute("SELECT sha256 FROM p3_dataset_files WHERE dataset_id=? AND file_name='invoices.csv'", (imported["dataset_id"],)).fetchone()[0]
        source_path = p1.VAULT / invoice_hash
        self.assertEqual(source_path.read_bytes(), (p3_dataset.DATA_DIR / "invoices.csv").read_bytes())
        db.close()

        status, run = self.request("POST", "/p3/audit-runs", {"period_start": "2025-04-01", "period_end": "2025-06-30", "sampling_seed": "fixture-seed-2026-001"})
        self.assertEqual(status, 200, run)
        findings = run["findings"]
        def found(test_id, ref):
            return [f for f in findings if f["test_id"] == test_id and f["object_ref"] == ref]
        self.assertTrue(all(f["confirmed_exception"] is False for f in findings))
        self.assertTrue(found("T01", "INV-001"))
        self.assertEqual(found("T02", "REL-002")[0]["state"], "REVIEW")
        self.assertFalse(found("T02", "REL-002")[0]["confirmed_exception"])
        self.assertFalse(found("T02", "REL-001"))
        # T02 directed graph cycle CUST-002 -> CUST-004 -> CUST-006 -> CUST-002
        cycle = found("T02", "CYCLE:CUST-002:CUST-004:CUST-006")
        self.assertEqual(cycle[0]["state"], "REVIEW")
        self.assertFalse(cycle[0]["confirmed_exception"])
        self.assertEqual(cycle[0]["cycle_length"], 3)
        self.assertEqual(set(cycle[0]["cycle_edge_ids"]), {"REL-003", "REL-004", "REL-005"})
        self.assertEqual(found("T05", "JRN-MAN-001")[0]["state"], "INCONSISTENT")
        self.assertFalse(found("T05", "JRN-MAN-001")[0]["confirmed_exception"])
        self.assertFalse(found("T05", "JRN-001"))
        self.assertTrue(found("T06", "INV-003"))
        self.assertFalse(found("T06", "INV-001"))
        self.assertIn("quantity", found("T06", "INV-005")[0]["differences"])
        self.assertTrue(found("T04", "INV-004"))
        self.assertFalse(found("T04", "INV-001"))
        self.assertTrue(found("T10", "INV-001:INV-004"))
        self.assertTrue(found("T10", "INV-003:INV-008"))
        self.assertFalse(found("T10", "INV-002"))
        # T11 physical plausibility P1-P5
        self.assertEqual(found("T11", "INV-005")[0]["state"], "REVIEW")           # P3 load
        self.assertEqual(found("T11", "INV-005")[0]["subcheck"], "P3_load_estimate")
        self.assertFalse(found("T11", "INV-001"))                                  # clean route
        p1route = found("T11", "INV-007")[0]                                       # P1 route/time
        self.assertEqual((p1route["state"], p1route["subcheck"]), ("IMPOSSIBLE", "P1_route_time"))
        self.assertFalse(p1route["inputs_independently_validated"])
        overlap = found("T11", "INV-004:INV-009")[0]                               # P2 vehicle overlap
        self.assertEqual((overlap["state"], overlap["subcheck"]), ("INCONSISTENT", "P2_vehicle_overlap"))
        self.assertEqual(found("T11", "INV-006")[0]["subcheck"], "P4_event_order") # P4 event order
        self.assertEqual(found("T11", "INV-006")[0]["state"], "INCONSISTENT")
        self.assertEqual(found("T11", "INV-003")[0]["subcheck"], "P5_pin_consignee")  # P5 consignee mismatch
        self.assertEqual(found("T11", "INV-003")[0]["state"], "INCONSISTENT")
        self.assertTrue(all(f.get("classification") == "synthetic_test_only" for f in findings if f["test_id"] == "T11"))
        # T13 signed-QR crypto adapter (DEMO key): verify + field cross-check + timing
        self.assertEqual(found("T13", "INV-001")[0]["state"], "UNVERIFIED")        # no signed payload
        self.assertEqual(found("T13", "INV-006")[0]["state"], "UNAVAILABLE")
        self.assertFalse(found("T13", "INV-001")[0]["externally_verified"])
        reg = found("T13", "INV-003")[0]                                           # valid sig, fields match
        self.assertEqual(reg["state"], "GOVERNMENT_REGISTERED_DEMO")
        self.assertTrue(reg["signature_valid"])
        self.assertFalse(reg["externally_verified"])                              # DEMO key: never official
        self.assertFalse(reg["government_registered"])
        self.assertFalse(reg["registration_timing_risk"])
        bad = found("T13", "INV-004")[0]                                           # valid sig, books disagree
        self.assertEqual(bad["state"], "INCONSISTENT")
        self.assertTrue(bad["signature_valid"])
        self.assertIn("gross_cents", bad["field_mismatches"])
        timing = found("T13", "INV-007")[0]                                        # valid sig, later ack
        self.assertEqual(timing["state"], "GOVERNMENT_REGISTERED_DEMO")
        self.assertTrue(timing["registration_timing_risk"])
        # Hero sale INV-009: one related-party sale that trips several independent checks at once
        self.assertTrue(found("T01", "INV-009"))                                   # disclosed related party
        self.assertTrue(found("T06", "INV-009"))                                   # invoice vs dispatch mismatch
        self.assertEqual(found("T11", "INV-009")[0]["subcheck"], "P5_pin_consignee")
        self.assertTrue(found("T11", "INV-004:INV-009"))                           # truck double-booked
        self.assertEqual(found("T13", "INV-009")[0]["state"], "GOVERNMENT_REGISTERED_DEMO")
        self.assertTrue(found("T13", "INV-009")[0]["registration_timing_risk"])
        self.assertTrue(found("T15", "INV-009"))                                   # GST return mismatch
        self.assertTrue(found("T14", "PROMO-002"))
        self.assertFalse(found("T14", "PROMO-001"))
        self.assertFalse(found("T14", "INV-001"))
        self.assertTrue(found("T15", "INV-003"))
        self.assertFalse(found("T15", "INV-001"))
        self.assertFalse(found("T15", "INV-005"))
        self.assertEqual(run["rule_coverage"]["T13"]["status"], "demo_signed_qr_adapter_evaluated")
        self.assertEqual(run["rule_coverage"]["T11"]["status"], "physical_plausibility_p1_p5_evaluated")
        self.assertEqual(run["rule_coverage"]["T02"]["status"], "candidate_edges_and_directed_cycles_evaluated")
        self.assertEqual(run["rule_coverage"]["T15"]["status"], "synthetic_row_comparison_only")
        self.assertEqual(run["rule_coverage"]["T06"]["status"], "evaluated_imported_taxable_value_quantity_gstin")
        self.assertEqual(run["ruleset_version"], "p3-2026-02")
        self.assertEqual(run["source_dataset_id"], imported["dataset_id"])
        self.assertEqual(run["source_manifest_sha256"], imported["manifest_sha256"])
        self.assertTrue(run["coverage"]["sales_tod"]["reduced_population"])
        self.assertEqual(run["coverage"]["sales_tod"]["eligible_population"], 9)
        self.assertEqual(run["coverage"]["sales_tod"]["selected"], 9)
        self.assertEqual(run["coverage"]["cutoff_tod"]["after_population"], 0)
        self.assertEqual(run["rule_coverage"]["T12"]["status"], "not_evaluable")

        status, concentration_run = self.request("POST", "/p3/audit-runs", {"period_start": "2025-04-01", "period_end": "2025-04-10", "sampling_seed": "fixture-seed-2026-002"})
        self.assertEqual(status, 200, concentration_run)
        self.assertTrue(any(f["test_id"] == "T08" and f["object_ref"] == "CUST-003" and f["threshold_classification"] == "synthetic_test_only" for f in concentration_run["findings"]))
        status, normal_concentration = self.request("POST", "/p3/audit-runs", {"period_start": "2025-04-01", "period_end": "2025-04-30", "sampling_seed": "fixture-seed-2026-003"})
        self.assertEqual(status, 200, normal_concentration)
        self.assertFalse(any(f["test_id"] == "T08" and f["object_ref"] == "CUST-001" for f in normal_concentration["findings"]))
        status, integrity = self.request("GET", "/integrity")
        self.assertEqual(status, 200, integrity)
        self.assertTrue(integrity["valid"])

    def _dataset_variant(self, name, edit, refresh_manifest=True):
        variant = self.root / ("variant-" + uuid.uuid4().hex)
        shutil.copytree(p3_dataset.DATA_DIR, variant)
        path = variant / name
        if edit is not None:
            with path.open("r", newline="", encoding="utf-8-sig") as stream:
                reader = csv.DictReader(stream)
                columns = reader.fieldnames
                rows = list(reader)
            edit(rows)
            with path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
                writer.writeheader()
                writer.writerows(rows)
        if refresh_manifest:
            manifest_path = variant / "source_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            for file_name, entry in manifest["files"].items():
                content = (variant / file_name).read_bytes()
                entry["sha256"] = hashlib.sha256(content).hexdigest()
                entry["bytes"] = len(content)
                import io
                entry["rows"] = sum(1 for _ in csv.DictReader(io.StringIO(content.decode("utf-8-sig"))))
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        return variant

    def test_dataset_import_rejects_corruption_and_bad_records_without_partial_rows(self):
        db = p1.connect()
        p3_dataset.init_dataset(db)
        db.commit()
        variants = []
        variants.append((self._dataset_variant("invoices.csv", lambda rows: rows[0].update(gross_amount="119000")), "gross_amount"))
        variants.append((self._dataset_variant("dispatches.csv", lambda rows: rows[0].update(invoice_id="INV-MISSING")), "unknown invoice"))
        variants.append((self._dataset_variant("journal_entries.csv", lambda rows: rows[4].update(credit="40000")), "not balanced"))
        variants.append((self._dataset_variant("invoices.csv", lambda rows: rows[0].update(invoice_date="not-a-date")), "ISO YYYY-MM-DD"))
        variants.append((self._dataset_variant("invoices.csv", lambda rows: rows[0].update(gross_amount="119000"), refresh_manifest=False), "manifest SHA-256"))
        missing = self._dataset_variant("invoices.csv", None)
        (missing / "gstr1_rows.csv").unlink()
        variants.append((missing, "file set mismatch"))
        for directory, error in variants:
            with self.subTest(error=error):
                with self.assertRaisesRegex(ValueError, error):
                    p3_dataset.import_dataset(directory, db, p1.VAULT)
                self.assertEqual(db.execute("SELECT count(*) FROM p3_dataset_imports").fetchone()[0], 0)
                self.assertEqual(db.execute("SELECT count(*) FROM p3_dataset_rows").fetchone()[0], 0)
        db.execute("CREATE TRIGGER forced_dataset_failure BEFORE INSERT ON p3_dataset_rows BEGIN SELECT RAISE(ABORT,'forced import failure'); END")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "forced import failure"):
            p3_dataset.import_dataset(p3_dataset.DATA_DIR, db, p1.VAULT)
        self.assertEqual(db.execute("SELECT count(*) FROM p3_dataset_imports").fetchone()[0], 0)
        self.assertEqual(db.execute("SELECT count(*) FROM p3_dataset_files").fetchone()[0], 0)
        self.assertEqual(db.execute("SELECT count(*) FROM p3_dataset_rows").fetchone()[0], 0)
        db.close()


if __name__ == "__main__":
    unittest.main()
