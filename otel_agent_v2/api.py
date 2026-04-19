"""
FastAPI transport for the multi-agent calculator.

Run:
    uvicorn otel_agent_v2.api:app --host 0.0.0.0 --port 8080

Preconditions:
    - `python otel_agent_v2/mcp_server.py add_sub` running (port 8081)
    - `python otel_agent_v2/mcp_server.py mul_div` running (port 8082)
    - API_KEY env var set
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

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

# ── 4. FastAPI app ───────────────────────────────────────────────────────────
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class QuestionRequest(BaseModel):
    question: str


class AnswerResponse(BaseModel):
    answer: str


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # Open MCP HTTP connections on startup; close cleanly on shutdown.
    async with add_sub_server, mul_div_server:
        await add_sub_server.list_tools()
        await mul_div_server.list_tools()
        logger.info("MCP servers connected and tool lists cached")
        yield
    wd_otel.shutdown()
    logger.info("wd_otel shut down")


app = FastAPI(
    title="otel_agent_v2 — Multi-Agent Calculator",
    description="OTel-instrumented calculator using wd-otel-* packages",
    lifespan=_lifespan,
)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "metrics": "http://localhost:8000/metrics"}


# NOTE: Under concurrent requests, traceparent headers for MCP calls may carry
# a different request's trace ID (known race in TracedOrchestrator._mcp_trace_context).
# See wd-otel-orchestrator/wd_otel_orchestrator/base.py for details and candidate fixes.
# This endpoint is safe for sequential / demo use.
@app.post("/run", response_model=AnswerResponse)
async def run(request: QuestionRequest) -> AnswerResponse:
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="question cannot be empty")
    answer = await orchestrator.execute(request.question)
    return AnswerResponse(answer=answer)
