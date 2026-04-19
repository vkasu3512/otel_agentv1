"""
CLI runner — smoke-test the orchestrator without HTTP.

Usage (from repo root):
    python otel_agent_v2/cli.py "What is 100 - 37?"

Preconditions:
    - `python otel_agent_v2/mcp_server.py add_sub` running (port 8081)
    - `python otel_agent_v2/mcp_server.py mul_div` running (port 8082)
    - API_KEY env var set (Groq, Bedrock-proxy key, etc.)
"""
from __future__ import annotations

import asyncio
import os
import sys

from dotenv import load_dotenv

load_dotenv()
os.environ.setdefault("OPENAI_API_KEY", "not-used-routing-elsewhere")

# ── 1. OTel bootstrap — MUST run before importing orchestrator ───────────────
# (orchestrator.py calls wd_otel.tracer()/meter() at module level, which
# raise WdOtelConfigError unless init() has been called first.)
import wd_otel

wd_otel.init("otel_agent_v2/wd-otel-orchestrator.yaml")

# ── 2. Agents SDK auto-instrumentation — produces `generation` spans ─────────
from openinference.instrumentation.openai_agents import OpenAIAgentsInstrumentor

OpenAIAgentsInstrumentor().instrument()

# ── 3. Import orchestrator (safe — OTel is live) ─────────────────────────────
from otel_agent_v2.orchestrator import add_sub_server, mul_div_server, orchestrator


async def _main(question: str) -> None:
    # MCPServerStreamableHttp needs to be entered as an async context manager
    # so its internal httpx pool + tool list are initialised.
    async with add_sub_server, mul_div_server:
        await add_sub_server.list_tools()
        await mul_div_server.list_tools()
        answer = await orchestrator.execute(question)
        print(f"\n=== ANSWER ===\n{answer}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python otel_agent_v2/cli.py '<question>'", file=sys.stderr)
        sys.exit(1)
    try:
        asyncio.run(_main(sys.argv[1]))
    finally:
        # NOTE: spans in-flight at Ctrl+C are best-effort; force_flush may not complete.
        wd_otel.shutdown()
