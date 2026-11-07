"""AgentX investigation agent: F1-F5 acceptance tests on a fresh synthetic instance."""
import asyncio
import base64
import json
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from Pramaan.backend import app as p1, p3, p6_agent, security
from Pramaan.backend.evaluate_agent import build_instance
from Pramaan.backend.party_match import compare


class PartyMatchTests(unittest.TestCase):
    def test_bands(self):
        cases = [("Sharma Traders", "M/s Sharma Trdrs", "match"), ("Fictional Manufacturing Pvt Ltd", "FICTIONAL MFG", "match"),
                 ("Banyan Retail", "M/s BANYAN RETL", "match"), ("Sharma Traders", "Verma Traders", "possible_match"),
                 ("Sharma Traders", "Gupta Electricals", "no_match"), ("Cedar Retail 1 (synthetic)", "Cedar Retail 2 (synthetic)", "no_match"),
                 ("", "Anything", "no_match")]
        for a, b, band in cases:
            with self.subTest(a=a, b=b):
                self.assertEqual(compare(a, b)["band"], band)
        self.assertTrue(compare("Sharma Traders", "Verma Traders")["needs_human_confirmation"])


class AgentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parent / ".runtime" / ("p6-" + uuid.uuid4().hex)
        cls.root.mkdir(parents=True)
        cls.patches = [patch.object(p1, "ROOT", cls.root), patch.object(p1, "DB_PATH", cls.root / "p1.sqlite3"),
                       patch.object(p1, "VAULT", cls.root / "vault"), patch.dict("os.environ", {"PRAMAAN_DATA": str(cls.root)})]
        for item in cls.patches:
            item.start()
        cls.tokens = {"client": security.issue("employee", "client_employee"), "auditor": security.issue("agent-auditor", "auditor"),
                      "human": security.issue("human-reviewer", "auditor", human=True), "agent": security.issue("mcp-agent", "auditor", agent=True)}
        cls.client = TestClient(p1.app)
        p3.import_fixture_dataset()
        cls.data = build_instance(cls.request)
        cls.run_id = cls.data["run_id"]
        cls.by_kind = {}
        for invoice_id, label in cls.data["labels"].items():
            cls.by_kind.setdefault(label["kind"], []).append(invoice_id)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        for item in reversed(cls.patches):
            item.stop()

    @classmethod
    def request(cls, method, path, role="auditor", **kwargs):
        headers = {"Authorization": "Bearer " + cls.tokens[role], **kwargs.pop("headers", {})}
        return cls.client.request(method, path, headers=headers, **kwargs)

    def investigate(self, invoice_id, planner="baseline"):
        response = self.request("POST", f"/p6/runs/{self.run_id}/investigations", json={"invoice_id": invoice_id, "planner": planner})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    # F5 ---------------------------------------------------------------
    def test_bank_statement_is_append_only_and_validated(self):
        bad = self.request("POST", "/p6/bank-statements", "client", json={"period": "FY26", "source_base64": base64.b64encode(b"date,amount\n2026-01-01,5\n").decode()})
        self.assertEqual(bad.status_code, 422)
        self.assertEqual(self.request("POST", "/p6/bank-statements", "auditor", json={"period": "FY26", "source_base64": "eA=="}).status_code, 403)
        listed = self.request("GET", "/p6/bank-statements").json()["statements"]
        self.assertTrue(any(s["statement_id"] == self.data["statement_id"] for s in listed))

    def test_bank_matching_planted_cases(self):
        expect = {"exact": "exact", "near_date": "exact", "split": "split", "partial": "partial", "missing": "none", "duplicate": "tie"}
        for kind, status in expect.items():
            for invoice_id in self.by_kind[kind]:
                with self.subTest(kind=kind, invoice=invoice_id):
                    out = self.request("POST", f"/p6/runs/{self.run_id}/match/bank", json={"invoice_id": invoice_id}).json()
                    self.assertEqual(out["match_status"], status)
                    if status == "tie":
                        self.assertIsNone(out["unmatched_remainder"])
                    for candidate in out["candidates"]:
                        self.assertNotIn("counterparty", candidate)  # names never leave the server

    def test_party_tool_returns_band_not_names(self):
        invoice_id = self.by_kind["exact"][0]
        bank = self.request("POST", f"/p6/runs/{self.run_id}/match/bank", json={"invoice_id": invoice_id}).json()
        row = bank["matched_rows"][0]
        out = self.request("POST", f"/p6/runs/{self.run_id}/match/party", json={"invoice_id": invoice_id, **row}).json()
        self.assertEqual(out["band"], "match")
        self.assertNotIn("Synthetic", json.dumps(out))
        self.assertNotIn("synthetic", json.dumps(out).replace("invoice_party_ref", ""))

    # F1 / F3 ---------------------------------------------------------
    def test_baseline_outcomes_and_conflict_escalation(self):
        for kind, statuses in {"exact": {"explained"}, "split": {"explained"}, "duplicate": {"conflict"},
                               "register_variance": {"needs_confirmation", "unexplained"}, "missing": {"needs_confirmation"}}.items():
            report = self.investigate(self.by_kind[kind][0])
            with self.subTest(kind=kind):
                self.assertIn(report["status"], statuses)
                self.assertTrue(report["source_links"])
                self.assertEqual(report["narrative_check"]["invented_amounts"], [])
                if kind == "duplicate":
                    self.assertEqual(report["steps"][-1]["kind"], "escalation")
                    self.assertEqual(len(report["conflicts"][0]["records"]), 2)  # both records shown, none chosen
                    self.assertFalse(report["pending_actions"])
                if kind == "register_variance":
                    self.assertIsNotNone(report["variance_by_tools"])
                    self.assertEqual(report["unexplained_amount"], report["variance_by_tools"])

    def test_rerun_carries_the_pending_proposal_instead_of_duplicating_it(self):
        invoice_id = self.by_kind["missing"][3]
        first, second = self.investigate(invoice_id), self.investigate(invoice_id)
        self.assertEqual(first["status"], "needs_confirmation")
        self.assertEqual(second["pending_actions"], first["pending_actions"])
        actions = self.request("GET", f"/p6/runs/{self.run_id}/actions").json()["actions"]
        self.assertEqual(sum(a["action_id"] in first["pending_actions"] for a in actions), 1)

    def test_report_is_persisted_hash_checked_and_logged(self):
        report = self.investigate(self.by_kind["exact"][1])
        stored = self.request("GET", f"/p6/investigations/{report['investigation_id']}").json()
        self.assertEqual(stored["report_hash"], report["report_hash"])
        self.assertEqual(stored["status"], report["status"])
        listed = self.request("GET", f"/p6/runs/{self.run_id}/investigations").json()["investigations"]
        self.assertTrue(any(i["investigation_id"] == report["investigation_id"] for i in listed))
        self.assertTrue(self.request("GET", "/integrity").json()["valid"])

    def test_llm_planner_without_key_is_an_honest_error(self):
        with patch.dict("os.environ", {"GROQ_API_KEY": "", "LLM_API_KEY": "", "OPENAI_API_KEY": "", "GEMINI_API_KEY": "", "GOOGLE_API_KEY": ""}):
            response = self.request("POST", f"/p6/runs/{self.run_id}/investigations", json={"invoice_id": self.by_kind["exact"][0], "planner": "llm"})
        self.assertEqual(response.status_code, 409)
        self.assertIn("baseline", response.json()["detail"])

    def scripted(self, turns):
        """A recorded LLM: returns the given assistant messages in order."""
        queue = list(turns)
        async def poster(cfg, body):
            message = queue.pop(0)
            return {"choices": [{"message": {"role": "assistant", **message}}]}
        return poster

    def call(self, name, args, idx=0):
        return {"id": f"c{idx}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}

    def run_llm(self, invoice_id, turns):
        async def go():
            marker = security.identity.set({"subject": "agent-auditor", "role": "auditor", "human": False, "channel": "api"})
            try:
                return await p6_agent.run_investigation(self.run_id, None, "llm", poster=self.scripted(turns), cfg={"api_key": "x", "model": "recorded-test-model", "base_url": "http://local"}, invoice_id=invoice_id)
            finally:
                security.identity.reset(marker)
        return asyncio.run(go())

    def test_llm_deck_trace_unexplained_variance_with_proposal(self):
        invoice_id = self.by_kind["register_variance"][1]
        bill = self.data["labels"][invoice_id]["bill_no"]
        report = self.run_llm(invoice_id, [
            {"content": "Check sources first.", "tool_calls": [self.call("get_invoice_sources", {"invoice_id": invoice_id})]},
            {"content": "Register differs; look for the payment.", "tool_calls": [self.call("match_bank_transactions", {"invoice_id": invoice_id}, 1)]},
            {"content": None, "tool_calls": [self.call("propose_evidence_request", {"invoice_id": invoice_id, "documents": ["invoice"], "reason": "Register amount differs from invoice; bank supports the invoice amount."}, 2)]},
            {"content": None, "tool_calls": [self.call("finish", {"summary": f"Bank supports the invoice amount for {bill}; the register difference stays unexplained.", "open_questions": ["Why does the register differ?"]}, 3)]},
        ])
        self.assertEqual(report["status"], "needs_confirmation")
        self.assertEqual(report["planner"], "llm")
        self.assertEqual(report["summary_source"], "model")
        self.assertEqual([s["tool"] for s in report["steps"] if s["kind"] == "tool"], ["get_invoice_sources", "match_bank_transactions", "propose_evidence_request"])
        self.assertTrue(any(s["kind"] == "plan" for s in report["steps"]))
        self.assertEqual(len(report["pending_actions"]), 1)

    def test_llm_invented_amount_and_fraud_word_are_rejected(self):
        invoice_id = self.by_kind["partial"][0]
        report = self.run_llm(invoice_id, [
            {"content": None, "tool_calls": [self.call("match_bank_transactions", {"invoice_id": invoice_id})]},
            {"content": "This is fraud: ₹12,34,567.89 is missing.", "tool_calls": []},
        ])
        self.assertTrue(report["narrative_check"]["model_summary_rejected"])
        self.assertTrue(report["narrative_check"]["used_word_fraud"])
        self.assertIn("12,34,567.89", report["narrative_check"]["invented_amounts"])
        self.assertEqual(report["summary_source"], "deterministic")
        self.assertNotIn("fraud", report["summary"].lower())

    def test_llm_plan_and_question_text_get_the_same_amount_check(self):
        invoice_id = self.by_kind["exact"][0]
        report = self.run_llm(invoice_id, [
            {"content": "I expect about ₹9,99,999.00 here.", "tool_calls": [self.call("get_invoice_sources", {"invoice_id": invoice_id}), self.call("match_bank_transactions", {"invoice_id": invoice_id}, 5)]},
            {"content": None, "tool_calls": [self.call("finish", {"summary": "Traced to one matching credit.", "open_questions": ["Was ₹7,77,777.00 refunded?", "Who approved it?"], "recommended_next_action": "Treat as fraud."}, 1)]},
        ])
        plans = [s["summary"] for s in report["steps"] if s["kind"] == "plan"]
        self.assertTrue(plans[0].startswith("[withheld"))
        self.assertEqual(report["open_questions"], ["Who approved it?"])
        self.assertNotIn("fraud", report["recommended_next_action"].lower())
        self.assertEqual(report["narrative_check"]["model_texts_withheld"], 3)
        self.assertEqual(report["summary_source"], "model")  # the clean summary itself is kept

    def test_llm_cannot_continue_after_conflict_or_leave_scope(self):
        invoice_id = self.by_kind["duplicate"][1]
        other = self.by_kind["exact"][2]
        report = self.run_llm(invoice_id, [
            {"content": None, "tool_calls": [self.call("get_invoice_sources", {"invoice_id": other})]},
            {"content": None, "tool_calls": [self.call("match_bank_transactions", {"invoice_id": invoice_id}, 1)]},
            {"content": "Pick the first one.", "tool_calls": [self.call("finish", {"summary": "Matched."}, 2)]},
        ])
        self.assertEqual(report["status"], "conflict")
        self.assertEqual(report["steps"][-1]["kind"], "escalation")
        self.assertNotIn("get_invoice_sources", report.get("observed_tools", []))
        self.assertFalse(any(s.get("tool") == "get_invoice_sources" and s.get("arguments", {}).get("invoice_id") == other and s["source_refs"] for s in report["steps"]))

    def test_llm_is_asked_once_to_propose_when_a_gap_remains(self):
        invoice_id = self.by_kind["partial"][1]
        report = self.run_llm(invoice_id, [
            {"content": None, "tool_calls": [self.call("match_bank_transactions", {"invoice_id": invoice_id})]},
            {"content": None, "tool_calls": [self.call("finish", {"summary": "Part of the payment is not traced."}, 1)]},
            {"content": None, "tool_calls": [self.call("propose_evidence_request", {"invoice_id": invoice_id, "documents": ["payment_receipt"], "reason": "Remainder not traced to a payment."}, 2)]},
            {"content": None, "tool_calls": [self.call("finish", {"summary": "Part of the payment is not traced; a request was proposed."}, 3)]},
        ])
        self.assertEqual(report["status"], "needs_confirmation")
        self.assertEqual([s["kind"] for s in report["steps"]].count("check"), 1)
        self.assertEqual(len(report["pending_actions"]), 1)

    def test_llm_may_decline_with_a_reason_and_is_not_nagged_twice(self):
        invoice_id = self.by_kind["partial"][2]
        report = self.run_llm(invoice_id, [
            {"content": None, "tool_calls": [self.call("match_bank_transactions", {"invoice_id": invoice_id})]},
            {"content": None, "tool_calls": [self.call("finish", {"summary": "Part of the payment is not traced."}, 1)]},
            {"content": None, "tool_calls": [self.call("finish", {"summary": "Part of the payment is not traced.", "no_request_reason": "Auditor already asked the client by email."}, 2)]},
        ])
        self.assertEqual(report["status"], "unexplained")
        self.assertEqual(report["no_request_reason"], "Auditor already asked the client by email.")
        self.assertFalse(report["pending_actions"])

    def test_llm_falls_back_to_next_model_on_rate_limit(self):
        from Pramaan.backend import agent_llm
        invoice_id = self.by_kind["exact"][3]
        turns = [{"content": None, "tool_calls": [self.call("match_bank_transactions", {"invoice_id": invoice_id})]},
                 {"content": "Traced to one matching credit.", "tool_calls": []}]
        seen = []
        async def poster(cfg, body):
            seen.append(cfg["model"])
            if cfg["model"] == "primary-model":
                raise agent_llm.RateLimited(30, "quota")
            if cfg["model"] == "busy-model":
                raise RuntimeError("LLM endpoint error HTTP 503: high demand")
            return {"choices": [{"message": {"role": "assistant", **turns.pop(0)}}]}
        agent_llm._EXHAUSTED.clear()
        async def go():
            marker = security.identity.set({"subject": "agent-auditor", "role": "auditor", "human": False, "channel": "api"})
            try:
                return await p6_agent.run_investigation(self.run_id, None, "llm", poster=poster, invoice_id=invoice_id,
                                                        cfg={"api_key": "x", "model": "primary-model", "fallback_models": ["busy-model", "backup-model"], "base_url": "http://local"})
            finally:
                security.identity.reset(marker)
        report = asyncio.run(go())
        agent_llm._EXHAUSTED.clear()
        self.assertEqual(report["model"], "backup-model")
        self.assertEqual(seen[0], "primary-model")
        self.assertNotIn("primary-model", seen[1:])  # the limited model is skipped for the rest of the run
        self.assertEqual(seen.count("busy-model"), 1)  # an overloaded (HTTP 503) model is also skipped

    # F4 ---------------------------------------------------------------
    def test_confirmation_is_human_only_hash_checked_and_once(self):
        invoice_id = self.by_kind["missing"][1]
        proposed = self.request("POST", f"/p6/runs/{self.run_id}/actions", json={"invoice_id": invoice_id, "documents": ["payment_receipt"], "reason": "No payment traced."})
        self.assertEqual(proposed.status_code, 200, proposed.text)
        action = proposed.json()
        body = {"payload_hash": action["payload_hash"], "reason": ""}
        # The agent channel and non-human auditors cannot confirm.
        self.assertEqual(self.request("POST", f"/p6/actions/{action['action_id']}/confirm", "agent", json=body).status_code, 403)
        self.assertEqual(self.request("POST", f"/p6/actions/{action['action_id']}/confirm", "auditor", json=body).status_code, 403)
        self.assertEqual(self.request("POST", f"/p6/actions/{action['action_id']}/confirm", "human", json=body, headers={"X-Pramaan-Channel": "mcp"}).status_code, 403)
        # A stale or altered payload hash executes nothing.
        self.assertEqual(self.request("POST", f"/p6/actions/{action['action_id']}/confirm", "human", json={"payload_hash": "0" * 64}).status_code, 409)
        done = self.request("POST", f"/p6/actions/{action['action_id']}/confirm", "human", json=body)
        self.assertEqual(done.status_code, 200, done.text)
        self.assertEqual(done.json()["status"], "executed")
        request_id = done.json()["result"]["request_id"]
        self.assertEqual(self.request("POST", f"/p6/actions/{action['action_id']}/confirm", "human", json=body).status_code, 409)
        inbox = self.request("GET", f"/p3/audit-runs/{self.run_id}/evidence-requests", "client").json()["requests"]
        created = next(r for r in inbox if r["request_id"] == request_id)
        self.assertEqual(created["required_docs"], ["payment_receipt"])
        self.assertEqual(created["sheet"], "agent_followup")

    def test_rejection_needs_reason_and_unknown_documents_are_refused(self):
        bad = self.request("POST", f"/p6/runs/{self.run_id}/actions", json={"invoice_id": self.by_kind["missing"][2], "documents": ["password"], "reason": "x" * 5})
        self.assertEqual(bad.status_code, 422)
        action = self.request("POST", f"/p6/runs/{self.run_id}/actions", json={"invoice_id": self.by_kind["missing"][2], "documents": ["bank_advice"], "reason": "No payment traced."}).json()
        self.assertEqual(self.request("POST", f"/p6/actions/{action['action_id']}/reject", "human", json={"payload_hash": action["payload_hash"], "reason": ""}).status_code, 422)
        rejected = self.request("POST", f"/p6/actions/{action['action_id']}/reject", "human", json={"payload_hash": action["payload_hash"], "reason": "Already on file."})
        self.assertEqual(rejected.json()["status"], "rejected")
        self.assertIsNone(rejected.json()["result"])

    def test_mcp_tool_list_has_no_confirm_tool(self):
        from Pramaan.backend.mcp_server import TOOLS
        self.assertIn("investigate_finding", TOOLS)
        self.assertIn("propose_evidence_request", TOOLS)
        self.assertFalse(any("confirm" in name for name in TOOLS))


if __name__ == "__main__":
    unittest.main()
