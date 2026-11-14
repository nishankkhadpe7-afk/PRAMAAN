"""Auditor workflow gaps closed after the UI/UX audit: bulk review, auditor-raised evidence
requests (UI-11) and linking documents already received when a run is repeated (UI-03)."""
import base64
import json
import sqlite3
import unittest
import uuid
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from Pramaan.backend import app as p1, p3, security


class WorkflowGapTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parent / ".runtime" / ("gaps-" + uuid.uuid4().hex)
        self.root.mkdir(parents=True)
        self.patches = [patch.object(p1, "ROOT", self.root), patch.object(p1, "DB_PATH", self.root / "p1.sqlite3"), patch.object(p1, "VAULT", self.root / "vault")]
        for item in self.patches:
            item.start()
        self.tokens = {"client": security.issue("employee", "client_employee"), "auditor": security.issue("agent-auditor", "auditor"), "human": security.issue("human-reviewer", "auditor", human=True)}
        self.client = TestClient(p1.app)
        p3.import_fixture_dataset()
        self.assertEqual(self.request("POST", "/p2/customers", "client", json={"customer_id": "WG-C", "name": "Synthetic Client"}).status_code, 200)
        for number, date in ((1, "2026-03-30"), (2, "2026-04-02")):
            sale = {"order_id": f"WG-O{number}", "dispatch_id": f"WG-D{number}", "invoice_id": f"WG-I{number}", "journal_id": f"WG-J{number}", "customer_id": "WG-C", "order_date": date, "dispatch_date": date, "invoice_date": date, "bill_no": f"WG-B{number}", "net_amount": "100.00"}
            self.assertEqual(self.request("POST", "/p2/sales", "client", json=sale).status_code, 200)
        response = self.request("POST", "/p3/audit-runs", json={"period_start": "2025-04-01", "period_end": "2026-03-31", "sampling_seed": "workflow-gaps-seed"})
        self.assertEqual(response.status_code, 200, response.text)
        self.run = response.json()
        self.run_id = self.run["run_id"]

    def tearDown(self):
        self.client.close()
        for item in reversed(self.patches):
            item.stop()

    def request(self, method, path, role="auditor", **kwargs):
        extra = kwargs.pop("headers", {})
        return self.client.request(method, path, headers={"Authorization": "Bearer " + self.tokens[role], **extra}, **kwargs)

    def events(self, event_type):
        with closing(sqlite3.connect(self.root / "p1.sqlite3")) as db:
            return [e for e in (json.loads(r[0]) for r in db.execute("SELECT event_json FROM events")) if e.get("event_type") == event_type or e.get("type") == event_type or e.get("action") == event_type]

    def upload(self, request_id, document_type, evidence_id):
        return self.request("POST", f"/p3/evidence-requests/{request_id}/evidence", "client", json={"evidence_id": evidence_id, "document_type": document_type, "content_base64": base64.b64encode(b"synthetic proof").decode(), "content_type": "text/plain", "controller": "client", "acquisition_channel": "company_upload"})

    def test_bulk_review_is_human_only_atomic_per_item_and_keeps_history(self):
        queue = self.request("GET", f"/p5/runs/{self.run_id}/reviews").json()["items"]
        ids = [i["finding_id"] for i in queue]
        self.assertGreater(len(ids), 1)
        body = {"outcome": "EXPLAINED", "reason": "Reviewed together against the same source documents.", "items": [{"finding_id": i, "expected_revision": 0} for i in ids]}
        path = f"/p5/runs/{self.run_id}/reviews/bulk"
        for role in ("client", "auditor"):
            self.assertEqual(self.request("POST", path, role, json=body).status_code, 403)
        self.assertEqual(self.request("POST", path, "human", json=body, headers={"X-Pramaan-Channel": "mcp"}).status_code, 403)
        # A non-human auditor can only propose; proposals never count as decisions.
        proposed = self.request("POST", f"/p5/runs/{self.run_id}/proposals/bulk", json=body)
        self.assertEqual(proposed.status_code, 200, proposed.text)
        self.assertEqual((proposed.json()["saved"], proposed.json()["failed"]), (len(ids), 0))
        self.assertTrue(all(i["human_decision"] is None for i in self.request("GET", f"/p5/runs/{self.run_id}/reviews").json()["items"]))
        self.assertEqual(self.request("POST", path, "human", json={**body, "items": body["items"] + body["items"][:1]}).status_code, 422)
        self.assertEqual(self.request("POST", path, "human", json={**body, "reason": "   "}).status_code, 422)
        # One unknown finding is reported; the rest are saved.
        mixed = self.request("POST", path, "human", json={**body, "items": body["items"] + [{"finding_id": "NOT-A-FINDING", "expected_revision": 0}]})
        self.assertEqual(mixed.status_code, 200, mixed.text)
        result = mixed.json()
        self.assertEqual((result["saved"], result["failed"]), (len(ids), 1))
        self.assertEqual([r["status"] for r in result["results"] if not r["ok"]], [404])
        after = {i["finding_id"]: i for i in self.request("GET", f"/p5/runs/{self.run_id}/reviews").json()["items"]}
        self.assertTrue(all(after[i]["human_decision"]["outcome"] == "EXPLAINED" and after[i]["human_decision"]["revision"] == 1 for i in ids))
        # Same shape as a per-finding decision, and one log entry per finding.
        single_keys = {"outcome", "reason", "expected_revision", "impact_inr", "impact_basis_evidence_ids", "impact_group", "proposed_adjustment", "run_id", "finding_id", "decided_by", "decided_at", "revision", "human_conclusion"}
        self.assertEqual(set(after[ids[0]]["human_decision"]), single_keys)
        self.assertEqual(len(self.events("human_review_recorded")), len(ids))
        # A stale revision fails per item and changes nothing; the right revision supersedes.
        stale = self.request("POST", path, "human", json=body).json()
        self.assertEqual((stale["saved"], stale["failed"]), (0, len(ids)))
        self.assertTrue(all(r["status"] == 409 for r in stale["results"]))
        fresh = self.request("POST", path, "human", json={**body, "outcome": "DATA_ERROR", "items": [{"finding_id": ids[0], "expected_revision": 1}]}).json()
        self.assertEqual((fresh["saved"], fresh["results"][0]["revision"]), (1, 2))

    def test_rerun_links_documents_already_received(self):
        requests = self.request("GET", f"/p3/audit-runs/{self.run_id}/evidence-requests").json()["requests"]
        self.assertTrue(all(r["uploaded_docs"] == [] and r["status"] == "pending" for r in requests))
        target = requests[0]
        document = target["required_docs"][0]
        self.assertEqual(self.upload(target["request_id"], document, "WG-EV-1").status_code, 200)
        rerun = self.request("POST", f"/p3/audit-runs/{self.run_id}/rerun")
        self.assertEqual(rerun.status_code, 200, rerun.text)
        new_id = rerun.json()["run_id"]
        self.assertNotEqual(new_id, self.run_id)
        again = self.request("GET", f"/p3/audit-runs/{new_id}/evidence-requests").json()["requests"]
        linked = [r for r in again if r["sample_ref"] == target["sample_ref"] and r["object_type"] == target["object_type"] and document in r["required_docs"]]
        self.assertTrue(linked)
        for request in linked:
            self.assertIn(document, request["uploaded_docs"])
            self.assertEqual(request["status"], "fulfilled" if set(request["required_docs"]) <= set(request["uploaded_docs"]) else "partially_fulfilled")
            # The client is not asked for the same file twice.
            self.assertEqual(self.upload(request["request_id"], document, "WG-EV-" + request["request_id"]).status_code, 409)
        untouched = [r for r in again if r["sample_ref"] != target["sample_ref"]]
        self.assertTrue(all(r["uploaded_docs"] == [] for r in untouched))
        self.assertEqual(len(self.events("evidence_requests_prefilled")), 1)

    def test_human_reviewer_raises_custom_evidence_requests(self):
        path = f"/p3/audit-runs/{self.run_id}/evidence-requests"
        body = {"invoice_ids": ["WG-I1", "WG-I2", "WG-I1"], "documents": ["bank_advice", "payment_receipt"], "reason": "Receipt not traced to the bank statement."}
        for role in ("client", "auditor"):
            self.assertEqual(self.request("POST", path, role, json=body).status_code, 403)
        self.assertEqual(self.request("POST", path, "human", json=body, headers={"X-Pramaan-Channel": "mcp"}).status_code, 403)
        self.assertEqual(self.request("POST", path, "human", json={**body, "invoice_ids": ["NOT-IN-RUN"]}).status_code, 422)
        self.assertEqual(self.request("POST", path, "human", json={**body, "documents": ["passport"]}).status_code, 422)
        self.assertEqual(self.request("POST", "/p3/audit-runs/NOPE/evidence-requests", "human", json=body).status_code, 404)
        created = self.request("POST", path, "human", json=body)
        self.assertEqual(created.status_code, 200, created.text)
        made = created.json()["created"]
        self.assertEqual([m["invoice_id"] for m in made], ["WG-I1", "WG-I2"])
        self.assertTrue(all(m["status"] == "pending" and m["request_id"].startswith("ER-CU-") for m in made))
        repeat = self.request("POST", path, "human", json=body).json()
        self.assertEqual((repeat["created"], sorted(repeat["already_requested"])), ([], sorted(m["request_id"] for m in made)))
        self.assertEqual(len(self.events("evidence_requests_created")), 1)
        listed = {r["request_id"]: r for r in self.request("GET", path).json()["requests"]}
        custom = listed[made[0]["request_id"]]
        self.assertEqual((custom["sheet"], custom["reason"], custom["requested_by"]), ("custom", body["reason"], "human-reviewer"))
        # The client sees the request with its reason and can answer it like any other.
        inbox = self.request("GET", "/ui/inbox", "client").json()
        self.assertEqual(next(r for r in inbox["requests"] if r["request_id"] == made[0]["request_id"])["reason"], body["reason"])
        answered = self.upload(made[0]["request_id"], "bank_advice", "WG-EV-BANK")
        self.assertEqual(answered.status_code, 200, answered.text)
        self.assertEqual(answered.json()["status"], "partially_fulfilled")
        # A later request for the same document starts from what is already held.
        more = self.request("POST", path, "human", json={"invoice_ids": ["WG-I1"], "documents": ["bank_advice"], "reason": "Second look at the same receipt."}).json()["created"][0]
        self.assertEqual((more["uploaded_docs"], more["status"]), (["bank_advice"], "fulfilled"))
        # Reasons are append-only.
        with closing(sqlite3.connect(self.root / "p1.sqlite3")) as db:
            with self.assertRaises(sqlite3.DatabaseError):
                db.execute("UPDATE p3_request_reasons SET reason='changed'")
            with self.assertRaises(sqlite3.DatabaseError):
                db.execute("DELETE FROM p3_request_reasons")


if __name__ == "__main__":
    unittest.main()
