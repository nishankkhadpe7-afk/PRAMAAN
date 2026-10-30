"""Named fallback judge client: official SDK stdio console (no LLM required)."""
import argparse
import asyncio
import json
import os
import sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client


async def run(tool=None, arguments=None):
    if os.environ.get("PRAMAAN_MCP_URL"):
        import httpx
        async with httpx.AsyncClient(headers={"Authorization": "Bearer " + os.environ.get("PRAMAAN_TOKEN", "")}, trust_env=False) as client:
            async with streamable_http_client(os.environ["PRAMAAN_MCP_URL"], http_client=client) as (read, write, _):
                return await invoke(read, write, tool, arguments)
    params = StdioServerParameters(command=sys.executable, args=["-m", "Pramaan.backend.mcp_server"], env=dict(os.environ))
    async with stdio_client(params) as (read, write):
        return await invoke(read, write, tool, arguments)


async def invoke(read, write, tool, arguments):
    async with ClientSession(read, write) as session:
        await session.initialize()
        if tool:
            return (await session.call_tool(tool, arguments or {})).model_dump(mode="json")
        return (await session.list_tools()).model_dump(mode="json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("tool", nargs="?")
    parser.add_argument("--arguments", default="{}")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(args.tool, json.loads(args.arguments))), indent=2))
