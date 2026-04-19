"""
FastAPI wrapper for the multi-agent calculator.

Keeps the process alive so Prometheus can scrape metrics continuously.

Endpoints:
  POST /run    { "question": "What is 100 - 37?" }  -> { "answer": "63.0", ... }
  GET  /health -> { "status": "ok" }

Run (from otel_agent/):
    python agent_api.py

Then send a request:
    curl -X POST http://localhost:8080/run -H "Content-Type: application/json" -d "{\"question\": \"What is 100 - 37?\"}"
"""

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from dotenv import load_dotenv

load_dotenv()

os.environ.setdefault("OPENAI_API_KEY", "not-used-routing-to-groq")

# ── 1. OTel bootstrap (MUST be first) ────────────────────────────────────────
from otel_setup import init_otel, get_tracer, get_meter

trace_provider, metrics_provider = init_otel("multi-agent-calculator", prometheus_port=8000)

tracer = get_tracer("otel_agent.multi_agent")
meter  = get_meter("otel_agent.multi_agent")
logger = logging.getLogger(__name__)

# ── 2. Auto-instrumentation ───────────────────────────────────────────────────
from openinference.instrumentation.openai_agents import OpenAIAgentsInstrumentor

OpenAIAgentsInstrumentor().instrument()

import httpx
from opentelemetry import context as otel_context
from opentelemetry.propagate import inject as otel_inject

_mcp_trace_context = None

_original_send = httpx.AsyncClient.send

async def _send_with_trace(self, request, **kwargs):
    carrier = {}
    otel_inject(carrier, context=_mcp_trace_context)
    for k, v in carrier.items():
        request.headers[k] = v
    return await _original_send(self, request, **kwargs)

httpx.AsyncClient.send = _send_with_trace

# ── 3. Metrics ────────────────────────────────────────────────────────────────
session_counter = meter.create_counter(
    "multi_agent.sessions.total",
    unit="1",
    description="Total multi-agent sessions run",
)
session_duration = meter.create_histogram(
    "multi_agent.session.duration",
    unit="s",
    description="Wall-clock duration of each multi-agent session",
)
active_workers = meter.create_up_down_counter(
    "orchestrator.active.workers",
    unit="1",
    description="Currently active workers (sub-agents)",
)
state_transitions = meter.create_counter(
    "orchestrator.state.transitions",
    unit="1",
    description="Worker state transitions",
)
orchestration_errors = meter.create_counter(
    "orchestrator.errors",
    unit="1",
    description="Total orchestration errors",
)
sync_failures = meter.create_counter(
    "orchestrator.sync.failures",
    unit="1",
    description="Status sync failures between orchestrator and API",
)

# ── 4. LLM client + Agents ────────────────────────────────────────────────────
from pydantic import BaseModel
from agents import AsyncOpenAI, OpenAIChatCompletionsModel, Agent, Runner, handoff
from agents import trace as agents_trace
from agents.mcp import MCPServerStreamableHttp


class HandoffReason(BaseModel):
    reason: str


def make_on_handoff(worker_name: str):
    def on_handoff(ctx, input: HandoffReason) -> None:
        with tracer.start_as_current_span("orchestrator.transition", attributes={
            "worker.type": worker_name,
            "worker.from_state": "idle",
            "worker.to_state": "running",
            "handoff.reason": input.reason,
        }) as span:
            state_transitions.add(1, {"worker_type": worker_name, "from_state": "idle", "to_state": "running"})
            active_workers.add(1, {"worker_type": worker_name})
            span.add_event("state_changed", {"previous": "idle", "current": "running"})
            logger.info(f"[Handoff] {worker_name}: idle->running, reason='{input.reason}'")
    return on_handoff


client = AsyncOpenAI(
    api_key=os.environ["API_KEY"],
    base_url="https://api.groq.com/openai/v1/",
)
model = OpenAIChatCompletionsModel(
    model="openai/gpt-oss-120b",
    openai_client=client,
)

add_sub_server = MCPServerStreamableHttp(
    name="add_sub_server",
    params={"url": "http://localhost:8081/mcp"},
    cache_tools_list=True,
)
mul_div_server = MCPServerStreamableHttp(
    name="mul_div_server",
    params={"url": "http://localhost:8082/mcp"},
    cache_tools_list=True,
)

add_sub_agent = Agent(
    name="AddSubAgent",
    instructions=(
        "You only handle addition and subtraction. "
        "Always use the add or subtract tool -- never calculate mentally. "
        "Return just the numeric result."
    ),
    model=model,
    mcp_servers=[add_sub_server],
)

solver_agent = Agent(
    name="SolverAgent",
    instructions=(
        "You handle complex arithmetic expressions with multiple operations. "
        "Always use the solve_steps tool -- never calculate mentally. "
        "Return the full step-by-step breakdown."
    ),
    model=model,
    mcp_servers=[mul_div_server],
)

orchestrator = Agent(
    name="OrchestratorAgent",
    instructions=(
        "You are a routing orchestrator for a calculator system. "
        "Given a math question, hand off to the correct specialist:\n"
        "  - AddSubAgent  -> simple addition or subtraction only\n"
        "  - SolverAgent  -> complex expressions with *, /, ** or parentheses\n"
        "Always include a brief reason when handing off. "
        "Never calculate yourself -- always hand off."
    ),
    model=model,
    handoffs=[
        handoff(add_sub_agent, on_handoff=make_on_handoff("AddSubAgent"), input_type=HandoffReason),
        handoff(solver_agent,  on_handoff=make_on_handoff("SolverAgent"),  input_type=HandoffReason),
    ],
)

# ── 5. Core agent logic ───────────────────────────────────────────────────────
async def _sync_status_to_api(worker_name: str, status: str) -> None:
    with tracer.start_as_current_span("orchestrator.sync", attributes={
        "worker.type": worker_name,
        "sync.status": status,
    }) as span:
        try:
            logger.info(f"[Sync] {worker_name} status='{status}' synced to API")
            span.set_attribute("sync.success", True)
        except Exception as e:
            sync_failures.add(1, {"failure_type": type(e).__name__, "worker_type": worker_name})
            span.record_exception(e)
            span.set_attribute("sync.success", False)
            raise


async def run_multi_agent(user_message: str) -> dict:
    global _mcp_trace_context
    start = time.perf_counter()

    with tracer.start_as_current_span("orchestrator.worker.lifecycle") as lifecycle_span:
        lifecycle_span.set_attribute("workflow.name", "multi-agent-calculator")
        lifecycle_span.set_attribute("agent.input", user_message)

        with tracer.start_as_current_span("multi-agent-run") as span:
            span.set_attribute("workflow.name", "multi-agent-calculator")
            span.set_attribute("agent.input", user_message)
            _mcp_trace_context = otel_context.get_current()

            final_agent_name = "OrchestratorAgent"
            lifecycle_status = "unknown"

            try:
                with tracer.start_as_current_span("runner.run") as inner:
                    inner.set_attribute("entry.agent", "OrchestratorAgent")
                    with agents_trace(workflow_name="multi-agent-calculator"):
                        result = await Runner.run(orchestrator, input=user_message)

                elapsed = time.perf_counter() - start
                final_output = result.final_output
                final_agent_name = result.last_agent.name if result.last_agent else "OrchestratorAgent"

                with tracer.start_as_current_span("orchestrator.transition", attributes={
                    "worker.type": final_agent_name,
                    "worker.from_state": "running",
                    "worker.to_state": "completed",
                }) as t_span:
                    state_transitions.add(1, {"worker_type": final_agent_name, "from_state": "running", "to_state": "completed"})
                    active_workers.add(-1, {"worker_type": final_agent_name})
                    t_span.add_event("state_changed", {"previous": "running", "current": "completed"})

                span.set_attribute("agent.output", final_output)
                span.set_attribute("duration_seconds", round(elapsed, 3))
                session_counter.add(1, {"workflow": "multi-agent-calculator"})
                session_duration.record(elapsed, {"workflow": "multi-agent-calculator"})

                lifecycle_status = "completed"
                lifecycle_span.set_attribute("lifecycle.status", lifecycle_status)
                lifecycle_span.set_attribute("lifecycle.final_agent", final_agent_name)
                lifecycle_span.set_attribute("lifecycle.duration_s", round(elapsed, 3))
                logger.info(f"[Orchestrator] Done ({elapsed:.3f}s): {final_output}")

            except Exception as e:
                elapsed = time.perf_counter() - start

                with tracer.start_as_current_span("orchestrator.transition", attributes={
                    "worker.type": final_agent_name,
                    "worker.from_state": "running",
                    "worker.to_state": "error",
                }) as t_span:
                    state_transitions.add(1, {"worker_type": final_agent_name, "from_state": "running", "to_state": "error"})
                    active_workers.add(-1, {"worker_type": final_agent_name})
                    t_span.add_event("state_changed", {"previous": "running", "current": "error"})

                orchestration_errors.add(1, {"error_type": type(e).__name__, "worker_type": final_agent_name})
                span.record_exception(e)
                lifecycle_status = "error"
                lifecycle_span.set_attribute("lifecycle.status", lifecycle_status)
                lifecycle_span.set_attribute("lifecycle.error", str(e))
                logger.error(f"[Orchestrator] Error ({elapsed:.3f}s): {e}")
                final_output = f"Error: {e}"

        await _sync_status_to_api(final_agent_name, lifecycle_status)

    return {
        "answer": final_output,
        "agent": final_agent_name,
        "status": lifecycle_status,
        "duration_s": round(elapsed, 3),
    }


# ── 6. FastAPI app ────────────────────────────────────────────────────────────
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel as PydanticBaseModel

class QuestionRequest(PydanticBaseModel):
    question: str

class AgentResponse(PydanticBaseModel):
    answer: str
    agent: str
    status: str
    duration_s: float


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start MCP server connections on startup
    async with add_sub_server, mul_div_server:
        await add_sub_server.list_tools()
        await mul_div_server.list_tools()
        logger.info("MCP servers connected and ready")
        yield
    # Flush telemetry on shutdown
    trace_provider.force_flush()
    metrics_provider.shutdown()
    logger.info("Telemetry flushed")


app = FastAPI(
    title="Multi-Agent Calculator",
    description="OTel-instrumented calculator with DW Orchestrator KPI metrics",
    lifespan=lifespan,
)


@app.get("/health")
async def health():
    return {"status": "ok", "metrics": "http://localhost:8000/metrics"}


@app.post("/run", response_model=AgentResponse)
async def run(request: QuestionRequest):
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="question cannot be empty")
    result = await run_multi_agent(request.question)
    return result


# ── 7. Entry point ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    print("Starting agent API on http://localhost:8080")
    print("Metrics endpoint:  http://localhost:8000/metrics")
    print("Health check:      http://localhost:8080/health")
    uvicorn.run(app, host="0.0.0.0", port=8080)
