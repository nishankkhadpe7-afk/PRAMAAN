"""P1/P2 regression tests: access log outside the chain (H2/S3), SQLite concurrency (H3),
agent-bound credentials (H6), vault-referenced snapshots and cached verification (H7),
read-only change detection (B3) and immutability (B5/S2)."""
import base64
import sqlite3
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from Pramaan.backend import app as p1
from Pramaan.backend import p3, p5, security


def b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


REGISTER = b"Bill No,Date,Customer,Gross Amt,GST No\r\nBILL-0,2026-03-02,Synthetic Customer,118.00,\r\nBILL-1,2026-03-02,Synthetic Customer,118.00,\r\n"


class P1RegressionTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parent / ".runtime" / ("p1r-" + uuid.uuid4().hex)
        self.root.mkdir(parents=True)
        self.patches = [patch.object(p1, "ROOT", self.root), patch.object(p1, "DB_PATH", self.root / "p1.sqlite3"), patch.object(p1, "VAULT", self.root / "vault")]
        for item in self.patches:
            item.start()
        self.http = TestClient(p1.app, raise_server_exceptions=False)
        self.client = {"Authorization": "Bearer " + security.issue("r-client", "client_employee")}
        self.auditor = {"Authorization": "Bearer " + security.issue("r-auditor", "auditor")}
        self.human = {"Authorization": "Bearer " + security.issue("r-human", "auditor", human=True)}
        self.agent = {"Authorization": "Bearer " + security.issue("r-agent", "auditor", agent=True)}
        self.agent_client = {"Authorization": "Bearer " + security.issue("r-agent-client", "client_employee", agent=True)}
        self.ok(self.http.post("/p2/customers", headers=self.client, json={"customer_id": "C-1", "name": "Synthetic Customer"}))
        for number in range(3):
            self.ok(self.http.post("/p2/sales", headers=self.client, json={"order_id": f"SO-{number}", "dispatch_id": f"D-{number}", "invoice_id": f"I-{number}", "journal_id": f"J-{number}", "customer_id": "C-1", "order_date": "2026-03-01", "dispatch_date": "2026-03-02", "invoice_date": "2026-03-02", "bill_no": f"BILL-{number}", "net_amount": "100.00", "tax_amount": "18.00"}))
        self.upload = self.ok(self.http.post("/p2/registers", headers=self.client, json={"period": "FY26", "source_base64": b64(REGISTER)}))["upload_id"]
        self.ok(self.http.post(f"/p2/registers/{self.upload}/reconcile", headers=self.auditor))
        self.run = self.ok(self.http.post("/p3/audit-runs", headers=self.auditor, json={"period_start": "2025-04-01", "period_end": "2026-03-31", "upload_id": self.upload}))

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()

    def ok(self, response):
        self.assertLess(response.status_code, 300, response.text)
        return response.json()

    def db(self):
        db = sqlite3.connect(p1.DB_PATH)
        db.row_factory = sqlite3.Row
        return db

    # --- H2 / S3 ---------------------------------------------------------------------------
    def test_reads_do_not_grow_the_hash_chain(self):
        with self.db() as db:
            before_events = db.execute("SELECT count(*) FROM events").fetchone()[0]
            before_access = db.execute("SELECT count(*) FROM access_log").fetchone()[0]
        for _ in range(5):
            self.ok(self.http.get("/p4/identity", headers=self.auditor))
            self.ok(self.http.get(f"/ui/runs/{self.run['run_id']}/context", headers=self.auditor))
        with self.db() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM events").fetchone()[0], before_events)
            self.assertEqual(db.execute("SELECT count(*) FROM access_log").fetchone()[0], before_access + 10)
            with self.assertRaises(sqlite3.DatabaseError):
                db.execute("UPDATE access_log SET decision='allowed'")
            with self.assertRaises(sqlite3.DatabaseError):
                db.execute("DELETE FROM access_log")
        self.assertTrue(self.ok(self.http.get("/integrity", headers=self.auditor))["valid"])
        log = self.ok(self.http.get("/ui/access-log?decision=allowed&limit=3", headers=self.auditor))
        self.assertEqual(len(log["entries"]), 3)
        self.assertEqual(self.http.get("/ui/access-log", headers=self.client).status_code, 403)

    def test_unauthenticated_denials_are_rate_limited(self):
        with patch.object(security, "UNAUTHENTICATED_LOG_LIMIT", 3), patch.dict(security._unauth_window, {"start": 0.0, "written": 0, "suppressed": 0}):
            with self.db() as db:
                before = db.execute("SELECT count(*) FROM access_log WHERE subject IS NULL").fetchone()[0]
            for _ in range(10):
                self.assertEqual(self.http.get("/ui/runs").status_code, 401)
            with self.db() as db:
                after = db.execute("SELECT count(*) FROM access_log WHERE subject IS NULL").fetchone()[0]
            self.assertEqual(after - before, 3)

    # --- H6 --------------------------------------------------------------------------------
    def test_agent_bound_credentials_cannot_shed_the_agent_policy(self):
        journal = "J-0"
        # No channel header at all: still the agent policy, because the credential is bound to it.
        denied = self.http.post(f"/p2/journals/{journal}/reverse?reversal_id=REV-A", headers=self.agent_client, json={"reason": "agent attempted reversal"})
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(self.http.post("/p2/sales", headers=self.agent_client, json={}).status_code, 403)
        identity = self.ok(self.http.get("/p4/identity", headers={**self.agent, "X-Pramaan-Channel": "api"}))
        self.assertEqual(identity["channel"], "mcp")
        self.assertFalse(identity["human"])
        finding = self.run["findings"][0]["finding_id"]
        review = {"outcome": "EXPLAINED", "reason": "agent tries to conclude", "expected_revision": 0}
        self.assertEqual(self.http.post(f"/p5/runs/{self.run['run_id']}/findings/{finding}/review", headers=self.agent, json=review).status_code, 403)
        self.ok(self.http.post(f"/p5/runs/{self.run['run_id']}/findings/{finding}/proposal", headers=self.agent, json=review))
        with self.assertRaises(ValueError):
            security.issue("x", "auditor", human=True, agent=True)
        with self.assertRaises(ValueError):
            security.issue("x", "auditor", human=True, permanent=True)
        # The same journal reversal from a normal human session still works.
        self.ok(self.http.post(f"/p2/journals/{journal}/reverse?reversal_id=REV-H", headers=self.client, json={"reason": "human corrected posting"}))

    def test_credential_listing_never_exposes_tokens(self):
        listing = security.list_credentials()
        self.assertTrue(any(c["subject"] == "r-agent" and c["channel"] == "mcp" for c in listing))
        self.assertFalse(any("token" in key for c in listing for key in c))
        self.assertEqual(security.revoke_subject("r-agent"), 1)
        self.assertEqual(self.http.get("/p4/identity", headers=self.agent).status_code, 401)

    # --- H7 --------------------------------------------------------------------------------
    def test_snapshots_reference_vault_bytes_and_packages_stay_self_contained(self):
        with self.db() as db:
            snapshot = __import__("json").loads(db.execute("SELECT snapshot_json FROM p3_audit_runs WHERE run_id=?", (self.run["run_id"],)).fetchone()[0])
        register = snapshot["register_uploads"][0]
        self.assertNotIn("source_base64", register)
        self.assertEqual(p5.register_bytes(register), REGISTER)
        package = self.ok(self.http.post(f"/p5/runs/{self.run['run_id']}/packages", headers=self.auditor, json={"upload_id": self.upload}))
        (p1.VAULT / register["sha256"]).write_bytes(b"tampered after packaging")
        pack = self.http.get(f"/p5/packages/{package['package_id']}/defensibility.zip", headers=self.auditor)
        self.assertEqual(pack.status_code, 200, "frozen packages must not depend on the live vault")
        self.assertEqual(self.http.post(f"/p5/runs/{self.run['run_id']}/packages", headers=self.auditor, json={"upload_id": self.upload, "client_name": "Again"}).status_code, 409)

    def test_reproduction_verdict_is_cached_and_invalidated_by_engine_change(self):
        calls = []
        original = p3.calculate

        def counting(*args, **kwargs):
            calls.append(1)
            return original(*args, **kwargs)
        with patch.object(p3, "calculate", side_effect=counting):
            for _ in range(3):
                self.ok(self.http.get(f"/ui/runs/{self.run['run_id']}/context", headers=self.auditor))
            self.assertLessEqual(len(calls), 1)
            with patch.object(p3, "ENGINE_FINGERPRINT", "different-engine"):
                self.ok(self.http.get(f"/ui/runs/{self.run['run_id']}/context", headers=self.auditor))
            self.assertEqual(len(calls), 2)
            self.ok(self.http.get(f"/ui/runs/{self.run['run_id']}/integrity", headers=self.auditor))
            self.assertEqual(len(calls), 3, "the Integrity tab always recomputes")

    def test_legacy_inline_snapshot_is_not_reported_as_changed(self):
        db = p3.db_open()
        try:
            legacy = p3.build_snapshot(db, inline_sources=True)
            self.assertIn("source_base64", legacy["register_uploads"][0])
            result = p3.save_run(db, legacy, "2025-04-01", "2026-03-31", "legacy-format-seed-0001", p3.load_ruleset())
            db.commit()
        finally:
            db.close()
        report = self.ok(self.http.get(f"/p4/audit-runs/{result['run_id']}/changes", headers=self.auditor))
        self.assertFalse(report["changed"], report["changed_fields"][:5])

    # --- B3 --------------------------------------------------------------------------------
    def test_change_detection_get_is_read_only(self):
        self.ok(self.http.post("/p2/customers", headers=self.client, json={"customer_id": "C-2", "name": "Later customer"}))
        self.ok(self.http.post("/p2/sales", headers=self.client, json={"order_id": "SO-9", "dispatch_id": "D-9", "invoice_id": "I-9", "journal_id": "J-9", "customer_id": "C-2", "order_date": "2026-03-05", "dispatch_date": "2026-03-05", "invoice_date": "2026-03-05", "bill_no": "BILL-9", "net_amount": "10.00"}))
        with self.db() as db:
            events = db.execute("SELECT count(*) FROM events").fetchone()[0]
        for _ in range(3):
            self.assertTrue(self.ok(self.http.get(f"/p4/audit-runs/{self.run['run_id']}/changes", headers=self.auditor))["changed"])
        with self.db() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM p4_changes").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT count(*) FROM events").fetchone()[0], events)
        recorded = self.ok(self.http.post(f"/p4/audit-runs/{self.run['run_id']}/changes", headers=self.auditor))
        self.assertTrue(recorded["recorded"])
        with self.db() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM p4_changes").fetchone()[0], 1)

    # --- H3 --------------------------------------------------------------------------------
    def test_concurrent_reads_and_writes_do_not_lock_out(self):
        findings = [f["finding_id"] for f in self.run["findings"]][:4]
        run_id = self.run["run_id"]

        def read(_):
            return TestClient(p1.app, raise_server_exceptions=False).get(f"/ui/runs/{run_id}/context", headers=self.auditor).status_code

        def propose(finding):
            return TestClient(p1.app, raise_server_exceptions=False).post(f"/p5/runs/{run_id}/findings/{finding}/proposal", headers=self.auditor, json={"outcome": "EXPLAINED", "reason": "concurrency", "expected_revision": 0}).status_code
        with ThreadPoolExecutor(max_workers=8) as pool:
            statuses = list(pool.map(read, range(12))) + list(pool.map(propose, findings))
        self.assertEqual(set(statuses), {200}, statuses)
        with self.db() as db:
            self.assertEqual(db.execute("PRAGMA journal_mode").fetchone()[0], "wal")

    # --- B5 / S2 ---------------------------------------------------------------------------
    def test_identical_run_keeps_its_samples_and_tables_are_append_only(self):
        seeded = {"period_start": "2025-04-01", "period_end": "2026-03-31", "sampling_seed": "fixed-reperformance-seed", "upload_id": self.upload}
        first = self.ok(self.http.post("/p3/audit-runs", headers=self.auditor, json=seeded))
        with self.db() as db:
            samples = db.execute("SELECT rowid,* FROM p3_samples WHERE run_id=?", (first["run_id"],)).fetchall()
        second = self.ok(self.http.post("/p3/audit-runs", headers=self.auditor, json=seeded))
        self.assertEqual(first["run_id"], second["run_id"])
        with self.db() as db:
            self.assertEqual([tuple(r) for r in db.execute("SELECT rowid,* FROM p3_samples WHERE run_id=?", (first["run_id"],))], [tuple(r) for r in samples])
            for statement in ("DELETE FROM p3_samples", "UPDATE p3_draws SET selected=0", "DELETE FROM p2_register_rows", "UPDATE p2_register_uploads SET period='x'", "UPDATE p2_reconciliations SET findings_json='[]'", "DELETE FROM p3_evidence_requests"):
                with self.assertRaises(sqlite3.DatabaseError, msg=statement):
                    db.execute(statement)

    def test_client_sql_role_cannot_rewrite_business_records(self):
        marker = security.identity.set({"subject": "sql-client", "role": "client_employee"})
        db = p3.db_open()
        try:
            for statement in ("UPDATE p2_invoices SET gross_cents=1", "DELETE FROM p2_customers", "UPDATE p2_customers SET name='x'", "DELETE FROM links", "UPDATE sales SET snapshot_hash='x'"):
                with self.assertRaises(sqlite3.DatabaseError, msg=statement):
                    db.execute(statement)
            db.execute("INSERT INTO p2_customers VALUES('C-NEW','New',NULL)")
            db.rollback()
        finally:
            db.close()
            security.identity.reset(marker)


if __name__ == "__main__":
    unittest.main()


class MCPChildEnvironmentTests(unittest.TestCase):
    def test_llm_keys_never_reach_the_mcp_child(self):
        import asyncio
        import os
        from Pramaan.backend import agent_llm
        captured = {}

        class Stop(Exception):
            pass

        def fake_stdio(params):
            captured["env"] = params.env
            raise Stop()
        with patch.dict(os.environ, {"GEMINI_API_KEY": "secret-gemini", "OPENAI_API_KEY": "secret-openai", "PRAMAAN_MCP_URL": "", "PRAMAAN_API_URL": "http://127.0.0.1:8000"}), patch.object(agent_llm, "stdio_client", side_effect=fake_stdio):
            with self.assertRaises(Stop):
                asyncio.run(agent_llm._session(lambda session: None, credential="Bearer caller-token"))
        self.assertEqual(captured["env"]["PRAMAAN_TOKEN"], "caller-token")
        self.assertEqual(captured["env"]["PRAMAAN_API_URL"], "http://127.0.0.1:8000")
        self.assertNotIn("secret", " ".join(captured["env"].values()))


class BodyLimitTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parent / ".runtime" / ("body-" + uuid.uuid4().hex)
        self.root.mkdir(parents=True)
        self.patches = [patch.object(p1, "ROOT", self.root), patch.object(p1, "DB_PATH", self.root / "p1.sqlite3"), patch.object(p1, "VAULT", self.root / "vault"),
                        patch.dict("os.environ", {"PRAMAAN_MAX_UPLOAD_BYTES": "3000"})]
        for item in self.patches:
            item.start()
        self.http = TestClient(p1.app, raise_server_exceptions=False)
        self.client = {"Authorization": "Bearer " + security.issue("b-client", "client_employee")}

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()

    def test_oversized_bodies_are_rejected_before_parsing(self):
        from Pramaan.backend import body_limit
        limit = body_limit.max_body_bytes()
        big = {"period": "FY", "source_base64": "A" * (limit + 10)}
        declared = self.http.post("/p2/registers", headers=self.client, json=big)
        self.assertEqual(declared.status_code, 413)
        self.assertEqual(declared.json()["code"], "payload_too_large")

        def chunks():
            yield b'{"period":"FY","source_base64":"'
            for _ in range(limit // 4096 + 2):
                yield b"A" * 4096
            yield b'"}'
        streamed = self.http.post("/p2/registers", headers={**self.client, "Content-Type": "application/json"}, content=chunks())
        self.assertEqual(streamed.status_code, 413)
        unauthenticated = self.http.post("/p2/registers", json=big)
        self.assertEqual(unauthenticated.status_code, 413, "size is enforced before authentication work")
        normal = self.http.post("/p2/registers", headers=self.client, json={"period": "FY", "source_base64": base64.b64encode(b"Bill No\r\nB-1\r\n").decode()})
        self.assertEqual(normal.status_code, 200, normal.text)
