"""Assistant behaviour under small provider quotas, and run-scoped grounding."""
import asyncio
import base64
from pathlib import Path
import unittest
import uuid
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient
from Pramaan.backend import agent_llm, app as p1, p3, security


class AgentQuotaTests(unittest.TestCase):
    def test_arguments_are_cleaned_against_the_tool_schema(self):
        schema = {"properties": {"run_id": {"type": "string"}, "limit": {"type": "integer"}, "offset": {"type": "integer"}}}
        self.assertEqual(agent_llm.sanitize_arguments({"run_id": "R1", "limit": "20", "test_id": "T03"}, schema), {"run_id": "R1", "limit": 20})
        self.assertEqual(agent_llm.sanitize_arguments("not a dict", schema), {})

    def test_reasoning_blocks_are_removed_from_answers(self):
        self.assertEqual(agent_llm.clean_answer("<think>internal\nplan</think>\n\nFinal answer."), "Final answer.")

    def test_select_tool_samples_survive_compaction_but_nested_noise_is_dropped(self):
        payload = {"untrusted_document_content": {"samples": [{"object_ref": "I1", "random_draw": "abc"}],
                                                  "findings": [{"finding_id": "F1", "samples": [{"x": 1}], "snapshot_hash": "h"}]}}
        compact = agent_llm.compact_payload(payload)
        self.assertEqual(compact["untrusted_document_content"]["samples"], [{"object_ref": "I1"}])
        self.assertEqual(compact["untrusted_document_content"]["findings"], [{"finding_id": "F1"}])

    def test_tool_budget_forces_an_answer_without_tools(self):
        bodies = []

        async def poster(cfg, body):
            bodies.append(body)
            if "tools" in body:
                return {"choices": [{"message": {"role": "assistant", "tool_calls": [{"id": f"c{len(bodies)}", "function": {"name": "get_findings", "arguments": "{}"}}]}}]}
            return {"choices": [{"message": {"role": "assistant", "content": "Answer from digest."}}]}

        class FakeSession:
            async def list_tools(self):
                return type("T", (), {"model_dump": lambda self, mode: {"tools": [{"name": "get_findings", "inputSchema": {"type": "object", "properties": {}}}]}})()

            async def call_tool(self, name, arguments):
                return type("R", (), {"model_dump": lambda self, mode: {"structuredContent": {"findings": []}}})()

        async def fake_session(handler, credential=None):
            return await handler(FakeSession())

        with patch.object(agent_llm, "config", return_value={"api_key": "k", "base_url": "https://example.test/v1", "model": "m"}), \
                patch.object(agent_llm, "_session", side_effect=fake_session):
            result = asyncio.run(agent_llm.run_agent("q", max_steps=12, poster=poster, allowed_tools={"get_findings"}, max_tool_calls=2))
        self.assertTrue(result["complete"])
        self.assertEqual(len(result["tool_calls"]), 2)
        self.assertNotIn("tools", bodies[-1])

    def test_short_rate_limits_are_waited_out_and_long_ones_raise(self):
        responses = [httpx.Response(429, json={"error": {"message": "Please try again in 0.01s."}}), httpx.Response(200, json={"choices": []})]

        def handler(request):
            return responses.pop(0)
        transport = httpx.MockTransport(handler)
        original = httpx.AsyncClient

        def client(*args, **kwargs):
            return original(*args, transport=transport, **kwargs)
        with patch.object(agent_llm.httpx, "AsyncClient", side_effect=client):
            data = asyncio.run(agent_llm._default_poster({"api_key": "k", "base_url": "https://example.test/v1"}, {}))
        self.assertEqual(data, {"choices": []})
        responses[:] = [httpx.Response(429, headers={"retry-after": "45"}, json={})]
        with patch.object(agent_llm.httpx, "AsyncClient", side_effect=client):
            with self.assertRaises(agent_llm.RateLimited) as caught:
                asyncio.run(agent_llm._default_poster({"api_key": "k", "base_url": "https://example.test/v1"}, {}))
        self.assertEqual(caught.exception.retry_after, 45)
        responses[:] = [httpx.Response(429, json={"error": {"type": "insufficient_quota", "code": "credit_balance_exhausted"}})]
        with patch.object(agent_llm.httpx, "AsyncClient", side_effect=client):
            with self.assertRaises(agent_llm.QuotaExhausted):
                asyncio.run(agent_llm._default_poster({"api_key": "k", "base_url": "https://example.test/v1"}, {}))


class ModelFallbackTests(unittest.TestCase):
    GEMINI_DAILY = {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message": "You exceeded your current quota, please check your plan and billing details. "
                              "Quota exceeded for metric: generate_content_free_tier_requests, limit: 20 Please retry in 20h1m48.2s."}}

    def setUp(self):
        agent_llm._EXHAUSTED.clear()

    def test_gemini_daily_cap_is_a_long_rate_limit_not_missing_credit(self):
        response = httpx.Response(429, json=self.GEMINI_DAILY)
        self.assertAlmostEqual(agent_llm._retry_after(response), 20 * 3600 + 60 + 48.2, places=1)
        transport = httpx.MockTransport(lambda request: httpx.Response(429, json=self.GEMINI_DAILY))
        original = httpx.AsyncClient
        with patch.object(agent_llm.httpx, "AsyncClient", side_effect=lambda *a, **k: original(*a, transport=transport, **k)):
            with self.assertRaises(agent_llm.RateLimited) as caught:
                asyncio.run(agent_llm._default_poster({"api_key": "k", "base_url": "https://example.test/v1"}, {}))
        self.assertGreater(caught.exception.retry_after, 3600)

    def test_exhausted_model_falls_back_and_is_skipped_next_time(self):
        calls = []

        async def once(prompt, max_steps, model=None, **kwargs):
            calls.append(model)
            if model == "main":
                raise agent_llm.RateLimited(72000, "daily cap")
            return {"answer": "ok", "tool_calls": [], "model": model, "complete": True}
        with patch.object(agent_llm, "config", return_value={"api_key": "k", "base_url": "https://example.test/v1", "model": "main", "fallback_models": ["backup"]}),                 patch.object(agent_llm, "_run_agent_once", side_effect=once):
            self.assertEqual(asyncio.run(agent_llm.run_agent("q"))["model"], "backup")
            self.assertEqual(asyncio.run(agent_llm.run_agent("q"))["model"], "backup")
        self.assertEqual(calls, ["main", "backup", "backup"])

    def test_all_models_exhausted_reports_the_soonest_reset(self):
        async def once(prompt, max_steps, model=None, **kwargs):
            raise agent_llm.RateLimited({"main": 72000, "backup": 600}[model], "cap")
        with patch.object(agent_llm, "config", return_value={"api_key": "k", "base_url": "https://example.test/v1", "model": "main", "fallback_models": ["backup"]}),                 patch.object(agent_llm, "_run_agent_once", side_effect=once):
            with self.assertRaises(agent_llm.RateLimited) as caught:
                asyncio.run(agent_llm.run_agent("q"))
        self.assertTrue(590 <= caught.exception.retry_after <= 600)


class AssistantEndpointTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).parent / ".runtime" / ("assistant-" + uuid.uuid4().hex)
        self.patches = [patch.object(p1, "ROOT", self.root), patch.object(p1, "DB_PATH", self.root / "p1.sqlite3"), patch.object(p1, "VAULT", self.root / "vault")]
        for item in self.patches:
            item.start()
        self.tokens = {"client": security.issue("as-client", "client_employee"), "auditor": security.issue("as-auditor", "auditor")}
        self.client = TestClient(p1.app)
        p3.import_fixture_dataset()
        self.request("POST", "/p2/customers", "client", {"customer_id": "AS-CO", "name": "Assistant synthetic company"})
        self.request("POST", "/p2/sales", "client", {"order_id": "AS-O", "dispatch_id": "AS-D", "invoice_id": "AS-I", "journal_id": "AS-J", "customer_id": "AS-CO", "bill_no": "AS-B",
                                                     "order_date": "2026-03-30", "dispatch_date": "2026-03-30", "invoice_date": "2026-03-30", "net_amount": "100.00"})
        source = b"Bill No,Date,Customer,Gross Amt,GST No\r\nAS-B,2026-03-30,Assistant synthetic company,150.00,\r\n"
        upload = self.request("POST", "/p2/registers", "client", {"period": "FY26", "source_base64": base64.b64encode(source).decode()}).json()["upload_id"]
        self.request("POST", f"/p2/registers/{upload}/reconcile")
        self.run = self.request("POST", "/p3/audit-runs", body={"audit_name": "Assistant grounding audit", "period_start": "2025-04-01", "period_end": "2026-03-31", "sampling_seed": "assistant-grounding-seed-2026"}).json()

    def tearDown(self):
        self.client.close()
        for item in reversed(self.patches):
            item.stop()

    def request(self, method, path, role="auditor", body=None):
        return self.client.request(method, path, headers={"Authorization": "Bearer " + self.tokens[role]}, **({} if body is None else {"json": body}))

    def test_prompt_carries_a_run_scoped_digest_and_tight_budgets(self):
        captured = {}

        async def fake_agent(prompt, **kwargs):
            captured.update(kwargs, prompt=prompt)
            return {"answer": "<think>x</think>Grounded answer.", "tool_calls": [], "model": "m", "complete": True}
        with patch.object(agent_llm, "run_agent", side_effect=fake_agent):
            response = self.request("POST", f"/ui/runs/{self.run['run_id']}/assistant", body={"question": "Explain the register differences."})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["audit_name"], "Assistant grounding audit")
        self.assertIn("RUN DIGEST — Assistant grounding audit", captured["prompt"])
        self.assertIn("AS-B", captured["prompt"])
        self.assertIn("₹150.00", captured["prompt"])
        self.assertEqual(captured["max_tool_calls"], 2)
        self.assertLessEqual(len(captured["prompt"]), 20000)

    def test_digest_only_carries_the_parts_a_question_needs(self):
        prompts = {}

        async def fake_agent(prompt, **kwargs):
            prompts[len(prompts)] = prompt
            return {"answer": "ok", "tool_calls": [], "model": "m", "complete": True}
        questions = ["Summarize this audit run.", "Explain the register differences.", "Which cut-off samples fall after the period end?", "Why was AS-B selected?"]
        with patch.object(agent_llm, "run_agent", side_effect=fake_agent):
            for question in questions:
                self.assertEqual(self.request("POST", f"/ui/runs/{self.run['run_id']}/assistant", body={"question": question}).status_code, 200)
        summary, register, cutoff, named = (prompts[i] for i in range(4))
        self.assertIn("Key findings (most serious first):", summary)
        self.assertNotIn("Cut-off samples (", summary)
        self.assertIn("[T00", register)
        self.assertNotIn("Cut-off samples (", register)
        self.assertNotIn("[T01", register)
        self.assertIn("Cut-off samples (", cutoff)
        self.assertIn("Named samples:", named)
        self.assertNotIn("Sales samples drawn at random", named)
        self.assertLess(len(register), len(summary))

    def test_provider_rate_limit_becomes_429_with_retry_after(self):
        async def limited(prompt, **kwargs):
            raise agent_llm.RateLimited(37, "quota")
        with patch.object(agent_llm, "run_agent", side_effect=limited):
            response = self.request("POST", f"/ui/runs/{self.run['run_id']}/assistant", body={"question": "Summarize."})
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers["retry-after"], "38")

    def test_exhausted_provider_credit_is_reported_as_402(self):
        async def broke(prompt, **kwargs):
            raise agent_llm.QuotaExhausted("no credits")
        with patch.object(agent_llm, "run_agent", side_effect=broke):
            response = self.request("POST", f"/ui/runs/{self.run['run_id']}/assistant", body={"question": "Summarize."})
        self.assertEqual(response.status_code, 402)
        self.assertIn("no credits", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
