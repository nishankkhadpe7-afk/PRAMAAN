"""Unit tests for the Groq/OpenAI-compatible MCP agent console plumbing.

These do not require network or a running LLM: the HTTP poster is mocked. Live
Groq calls are exercised by running `python -m Pramaan.backend.agent_llm "..."`.
"""
import asyncio
import unittest
from unittest.mock import patch

from Pramaan.backend import agent_llm


class AgentLlmTests(unittest.TestCase):
    def test_mcp_tools_convert_to_openai_function_schemas(self):
        mcp_tools = [{"name": "create_audit_run", "description": "create audit run",
                      "inputSchema": {"type": "object", "properties": {"payload": {"type": "object"}}, "required": ["payload"]}}]
        tools = agent_llm.to_openai_tools(mcp_tools)
        self.assertEqual(tools[0]["type"], "function")
        self.assertEqual(tools[0]["function"]["name"], "create_audit_run")
        self.assertEqual(tools[0]["function"]["parameters"]["required"], ["payload"])

    def test_tool_without_schema_gets_empty_object_params(self):
        tools = agent_llm.to_openai_tools([{"name": "verify_audit_log"}])
        self.assertEqual(tools[0]["function"]["parameters"], {"type": "object", "properties": {}})
        self.assertEqual(tools[0]["function"]["description"], "verify audit log")

    def test_complete_builds_tool_calling_request_and_returns_message(self):
        captured = {}

        async def fake_poster(cfg, body):
            captured.update(body)
            return {"choices": [{"message": {"role": "assistant", "content": "done"}}]}

        cfg = {"api_key": "k", "base_url": "https://api.groq.com/openai/v1", "model": "qwen/qwen3.8-27b"}
        message = asyncio.run(agent_llm.complete(cfg, [{"role": "user", "content": "hi"}], [{"type": "function"}], fake_poster))
        self.assertEqual(message["content"], "done")
        self.assertEqual(captured["model"], "qwen/qwen3.8-27b")
        self.assertEqual(captured["tool_choice"], "auto")
        self.assertEqual(captured["temperature"], 0)

    def test_run_agent_marks_final_answer_complete(self):
        async def fake_session(handler, credential=None):
            class FakeSession:
                async def list_tools(self):
                    return type("ToolList", (), {"model_dump": lambda self, mode: {"tools": []}})()

            return await handler(FakeSession())

        async def fake_poster(cfg, body):
            return {"choices": [{"message": {"role": "assistant", "content": "done"}}]}

        with patch.object(agent_llm, "config", return_value={
            "api_key": "test-key", "base_url": "https://example.test/v1", "model": "test-model"
        }), patch.object(agent_llm, "_session", side_effect=fake_session):
            result = asyncio.run(agent_llm.run_agent("Summarize", poster=fake_poster))

        self.assertTrue(result["complete"])

    def test_config_prefers_groq_key(self):
        import os
        with patch.dict(os.environ, {"GROQ_API_KEY": "gk", "LLM_API_KEY": "other", "OPENAI_API_KEY": "ok", "LLM_MODEL": "qwen/qwen3.8-27b", "LLM_BASE_URL": ""}, clear=False):
            cfg = agent_llm.config()
            self.assertEqual(cfg["api_key"], "gk")
            self.assertEqual(cfg["model"], "qwen/qwen3.8-27b")
            self.assertTrue(cfg["base_url"].startswith("https://api.groq.com"))

    def test_config_uses_the_openai_key_for_an_openai_endpoint(self):
        import os
        with patch.dict(os.environ, {"GROQ_API_KEY": "gk", "LLM_API_KEY": "stray", "OPENAI_API_KEY": "ok", "LLM_BASE_URL": "https://api.openai.com/v1"}, clear=False):
            self.assertEqual(agent_llm.config()["api_key"], "ok")
        with patch.dict(os.environ, {"GEMINI_API_KEY": "gem", "LLM_API_KEY": "stray", "OPENAI_API_KEY": "ok", "LLM_BASE_URL": "https://generativelanguage.googleapis.com/v1beta/openai"}, clear=False):
            self.assertEqual(agent_llm.config()["api_key"], "gem")

    def test_disallowed_model_tool_call_is_blocked_before_mcp_execution(self):
        called_tools = []
        responses = iter([
            {"choices": [{"message": {"role": "assistant", "tool_calls": [
                {"id": "write-1", "function": {"name": "create_audit_run", "arguments": "{}"}}
            ]}}]},
            {"choices": [{"message": {"role": "assistant", "content": "I could not perform that action."}}]},
        ])

        class FakeSession:
            async def list_tools(self):
                tools = [
                    {"name": "get_findings", "inputSchema": {"type": "object", "properties": {}}},
                    {"name": "create_audit_run", "inputSchema": {"type": "object", "properties": {}}},
                ]
                return type("ToolList", (), {"model_dump": lambda self, mode: {"tools": tools}})()

            async def call_tool(self, name, arguments):
                called_tools.append(name)
                raise AssertionError("disallowed tool must not be invoked")

        async def fake_session(handler, credential=None):
            return await handler(FakeSession())

        async def fake_poster(cfg, body):
            return next(responses)

        with patch.object(agent_llm, "config", return_value={
            "api_key": "test-key", "base_url": "https://example.test/v1", "model": "test-model"
        }), patch.object(agent_llm, "_session", side_effect=fake_session):
            result = asyncio.run(agent_llm.run_agent(
                "Summarize findings", poster=fake_poster, allowed_tools={"get_findings"}
            ))

        self.assertEqual(called_tools, [])
        self.assertEqual(result["tool_calls"], [{"tool": "create_audit_run", "arguments": {}, "is_error": True}])
        self.assertEqual(result["answer"], "I could not perform that action.")
        self.assertTrue(result["complete"])

    def test_tool_call_step_limit_returns_incomplete(self):
        async def fake_session(handler, credential=None):
            class FakeSession:
                async def list_tools(self):
                    tools = [{"name": "get_findings", "inputSchema": {"type": "object", "properties": {}}}]
                    return type("ToolList", (), {"model_dump": lambda self, mode: {"tools": tools}})()

                async def call_tool(self, name, arguments):
                    return type("ToolResult", (), {"model_dump": lambda self, mode: {"structuredContent": {"findings": []}}})()

            return await handler(FakeSession())

        async def fake_poster(cfg, body):
            return {"choices": [{"message": {"role": "assistant", "tool_calls": [
                {"id": "read-1", "function": {"name": "get_findings", "arguments": "{}"}}
            ]}}]}

        with patch.object(agent_llm, "config", return_value={
            "api_key": "test-key", "base_url": "https://example.test/v1", "model": "test-model"
        }), patch.object(agent_llm, "_session", side_effect=fake_session):
            result = asyncio.run(agent_llm.run_agent(
                "Summarize", max_steps=1, poster=fake_poster, allowed_tools={"get_findings"}
            ))

        self.assertFalse(result["complete"])
        self.assertIn("step limit", result["answer"])


if __name__ == "__main__":
    unittest.main()
