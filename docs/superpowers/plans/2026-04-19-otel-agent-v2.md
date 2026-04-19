# otel_agent_v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a working, runnable rewrite of `otel_agent/` in a sibling `otel_agent_v2/` directory that uses `wd-otel-core`, `wd-otel-mcp`, and `wd-otel-orchestrator` packages. Artefact is editable working code, not a package.

**Architecture:** Five files split by responsibility: `mcp_server.py` (MCP tools via `@traced_tool`), `orchestrator.py` (pure multi-agent logic via `TracedOrchestrator`), `api.py` (FastAPI transport only), `cli.py` (asyncio smoke runner), `kpi_proxy.py` (unchanged). Each entry-point process calls `wd_otel.init()` with its own YAML on a dedicated Prometheus port.

**Tech Stack:** Python 3.10+, `wd-otel-core`, `wd-otel-mcp`, `wd-otel-orchestrator`, `openai-agents` (routed to Groq or any OpenAI-compatible endpoint), `fastmcp`, `langgraph`, `fastapi`, `uvicorn`.

**Convention for this plan:**
- The spec explicitly says "not adding tests". TDD steps are replaced with concrete **smoke-verify** steps using real commands the engineer runs.
- All paths are absolute-from-repo-root: `otel_agent_v2/<file>`.
- Each task ends in a commit. Commit from repo root.
- Shell examples use bash (forward slashes) per the session environment.

---

## File structure

```
otel_agentv1/
└── otel_agent_v2/
    ├── README.md                  # Task 7
    ├── requirements.txt           # Task 1
    ├── wd-otel-orchestrator.yaml  # Task 1
    ├── wd-otel-mcp-addsub.yaml    # Task 1
    ├── wd-otel-mcp-muldiv.yaml    # Task 1
    ├── mcp_server.py              # Task 2
    ├── orchestrator.py            # Task 3
    ├── cli.py                     # Task 4
    ├── api.py                     # Task 5
    └── kpi_proxy.py               # Task 1 (copied)
```

**Responsibilities:**
- `orchestrator.py` — agent definitions + `CalculatorOrchestrator(TracedOrchestrator)`. Never calls `wd_otel.init()`. Import-time side-effects: instantiates the orchestrator singleton.
- `api.py` — FastAPI only. Imports orchestrator after `wd_otel.init()`. Zero OTel imports beyond `wd_otel`.
- `cli.py` — single `asyncio.run(orchestrator.execute(q))` driver.
- `mcp_server.py` — standalone FastMCP server process, one of two modes (`add_sub` | `mul_div`). Keeps the 4 LangGraph metrics as locally-created instruments.

---

## Task 1: Scaffold directory, config YAMLs, requirements, copy kpi_proxy

**Files:**
- Create: `otel_agent_v2/requirements.txt`
- Create: `otel_agent_v2/wd-otel-orchestrator.yaml`
- Create: `otel_agent_v2/wd-otel-mcp-addsub.yaml`
- Create: `otel_agent_v2/wd-otel-mcp-muldiv.yaml`
- Create: `otel_agent_v2/kpi_proxy.py` (copied from `otel_agent/kpi_proxy.py`)

- [ ] **Step 1.1: Create the directory**

```bash
mkdir -p otel_agent_v2
```

- [ ] **Step 1.2: Create `otel_agent_v2/requirements.txt`**

```
# WD-OTel SDK packages (installed from local path with `pip install -e`)
wd-otel-core
wd-otel-mcp
wd-otel-orchestrator

# OpenAI Agents SDK (supports any OpenAI-compatible endpoint: Groq, Bedrock proxy, etc.)
openai-agents>=0.0.15

# Auto-instrumentation for Agents SDK — produces `generation` spans around LLM calls
openinference-instrumentation-openai-agents>=0.1.0

# MCP tool server transport
fastmcp>=2.0.0

# LangGraph for the multi-step solver
langgraph>=0.2.0

# FastAPI transport (api.py) and KPI proxy (kpi_proxy.py)
fastapi>=0.110.0
uvicorn[standard]>=0.29.0

# HTTP client used by MCP client + AsyncOpenAI + kpi_proxy
httpx>=0.27.0

# .env loading
python-dotenv>=1.0.0
```

- [ ] **Step 1.3: Create `otel_agent_v2/wd-otel-orchestrator.yaml`**

```yaml
# wd-otel config for the orchestrator FastAPI / CLI process.
# Prometheus scrapes 8000; traces go to Tempo on 4317; logs go to Loki.
service:
  name: "otel-agent-v2-orchestrator"
  version: "1.0.0"
  env: "local"

traces:
  endpoint: "localhost:4317"
  protocol: "grpc"
  filter_libraries:
    - "fastmcp"

metrics:
  prometheus_port: 8000

logs:
  loki_url: "http://localhost:3100/loki/api/v1/push"
```

- [ ] **Step 1.4: Create `otel_agent_v2/wd-otel-mcp-addsub.yaml`**

```yaml
# wd-otel config for the add/subtract MCP server process.
service:
  name: "otel-agent-v2-mcp-add-sub"
  version: "1.0.0"
  env: "local"

traces:
  endpoint: "localhost:4317"
  protocol: "grpc"
  filter_libraries:
    - "fastmcp"

metrics:
  prometheus_port: 8001

logs:
  loki_url: "http://localhost:3100/loki/api/v1/push"
```

- [ ] **Step 1.5: Create `otel_agent_v2/wd-otel-mcp-muldiv.yaml`**

```yaml
# wd-otel config for the multi-step solver MCP server process.
service:
  name: "otel-agent-v2-mcp-mul-div"
  version: "1.0.0"
  env: "local"

traces:
  endpoint: "localhost:4317"
  protocol: "grpc"
  filter_libraries:
    - "fastmcp"

metrics:
  prometheus_port: 8002

logs:
  loki_url: "http://localhost:3100/loki/api/v1/push"
```

- [ ] **Step 1.6: Copy `kpi_proxy.py` verbatim**

```bash
cp otel_agent/kpi_proxy.py otel_agent_v2/kpi_proxy.py
```

The query dict will be updated in Task 7 after the new metric names are confirmed in Prometheus.

- [ ] **Step 1.7: Verify the scaffold**

```bash
ls otel_agent_v2/
```

Expected output includes: `requirements.txt`, `wd-otel-orchestrator.yaml`, `wd-otel-mcp-addsub.yaml`, `wd-otel-mcp-muldiv.yaml`, `kpi_proxy.py`.

- [ ] **Step 1.8: Commit**

```bash
git add otel_agent_v2/
git commit -m "feat(otel_agent_v2): scaffold directory, YAML configs, requirements, kpi_proxy"
```

---

## Task 2: `mcp_server.py` — MCP tool server via `@traced_tool`

**Files:**
- Create: `otel_agent_v2/mcp_server.py`

**What this demonstrates:** `@traced_tool` replaces `@instrumented_tool` + `_get_parent_ctx` + manual thread/timeout plumbing (~80 lines → 1 decorator line per tool). The LangGraph-specific metrics are kept as local `meter.create_*` calls — explicitly called out as a future helper candidate.

- [ ] **Step 2.1: Write `otel_agent_v2/mcp_server.py`**

```python
"""
MCP Calculator Servers — instrumented via wd-otel-mcp.

Two sub-servers, each in its own process:
    python mcp_server.py add_sub   # → localhost:8081 ; Prometheus :8001
    python mcp_server.py mul_div   # → localhost:8082 ; Prometheus :8002

Shape mirrors `otel_agent/mcp_tool_instrumented.py` but swaps the hand-rolled
`@instrumented_tool` decorator for `@traced_tool` from `wd_otel_mcp`.

The 4 LangGraph KPI metrics (graph_build_time, step_total, execution_duration,
step_retries) are NOT covered by the wd-otel-* packages today, so they are
created locally. TODO: move to a future `wd-otel-langgraph` helper.
"""
from __future__ import annotations

import ast
import logging
import operator as op_module
import re
import sys
import time as _t
from typing import TypedDict

# ── 1. OTel bootstrap — MUST run before importing anything that touches OTel ──
import wd_otel

_MODE = sys.argv[1] if len(sys.argv) > 1 else "add_sub"
_CONFIG = {
    "add_sub": "otel_agent_v2/wd-otel-mcp-addsub.yaml",
    "mul_div": "otel_agent_v2/wd-otel-mcp-muldiv.yaml",
}.get(_MODE)
if _CONFIG is None:
    print(f"Unknown mode '{_MODE}'. Use: add_sub | mul_div", file=sys.stderr)
    sys.exit(1)

wd_otel.init(_CONFIG)

tracer = wd_otel.tracer("otel_agent_v2.mcp_server")
meter = wd_otel.meter("otel_agent_v2.mcp_server")
logger = logging.getLogger(__name__)

# ── 2. LangGraph-specific metrics (not covered by wd-otel yet) ───────────────
# TODO: move to a wd-otel-langgraph helper when that package exists.
graph_build_time = meter.create_histogram(
    "langgraph.build.duration",
    unit="s",
    description="Time to construct and compile the execution graph",
)
step_total = meter.create_counter(
    "langgraph.step.total",
    unit="1",
    description="Total graph node executions by node and status",
)
execution_duration = meter.create_histogram(
    "langgraph.execution.duration",
    unit="s",
    description="Total duration of a full graph run",
)
step_retries = meter.create_counter(
    "langgraph.step.retries",
    unit="1",
    description="Total step retry attempts per node",
)

# ── 3. Imports that rely on OTel being live ──────────────────────────────────
from fastmcp import Context, FastMCP
from langgraph.graph import END, StateGraph
from wd_otel_mcp import traced_tool

# ── 4. LangGraph: safe expression evaluator ──────────────────────────────────
ALLOWED_OPS = {
    ast.Add: op_module.add,
    ast.Sub: op_module.sub,
    ast.Mult: op_module.mul,
    ast.Div: op_module.truediv,
    ast.Pow: op_module.pow,
    ast.USub: op_module.neg,
    ast.UAdd: op_module.pos,
}


def _eval_node(node: ast.AST) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.BinOp) and type(node.op) in ALLOWED_OPS:
        return ALLOWED_OPS[type(node.op)](_eval_node(node.left), _eval_node(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in ALLOWED_OPS:
        return ALLOWED_OPS[type(node.op)](_eval_node(node.operand))
    raise ValueError(f"Unsupported expression: {ast.dump(node)}")


def _safe_eval(expr: str) -> float:
    tree = ast.parse(expr.strip(), mode="eval")
    return _eval_node(tree.body)


# ── 5. LangGraph state + nodes ───────────────────────────────────────────────
class MathState(TypedDict):
    expression: str
    tokens: list
    result: float
    steps: list
    error: str


def parse_node(state: MathState) -> dict:
    with tracer.start_as_current_span("langgraph_parse_node") as span:
        expr = state["expression"]
        try:
            tokens = re.findall(r"\d+\.?\d*|[+\-*/^()]", expr)
            span.set_attribute("expression", expr)
            span.set_attribute("token_count", len(tokens))
            step_total.add(1, {"node": "parse_node", "status": "success"})
            return {"tokens": tokens, "steps": [f"[Parse]    '{expr}'  ->  tokens: {tokens}"]}
        except Exception as e:
            step_total.add(1, {"node": "parse_node", "status": "failure"})
            span.record_exception(e)
            raise


def evaluate_node(state: MathState) -> dict:
    with tracer.start_as_current_span("langgraph_evaluate_node") as span:
        expr = state["expression"]
        steps = state["steps"]
        span.set_attribute("expression", expr)
        try:
            result = _safe_eval(expr)
            span.set_attribute("result", result)
            step_total.add(1, {"node": "evaluate_node", "status": "success"})
            return {"result": result, "error": "", "steps": steps + [f"[Evaluate] '{expr}'  =  {result}"]}
        except Exception as exc:
            span.set_attribute("error", str(exc))
            span.record_exception(exc)
            step_total.add(1, {"node": "evaluate_node", "status": "failure"})
            return {"result": 0.0, "error": str(exc), "steps": steps + [f"[Evaluate] ERROR: {exc}"]}


def format_node(state: MathState) -> dict:
    with tracer.start_as_current_span("langgraph_format_node") as span:
        steps = state["steps"]
        try:
            if state["error"]:
                summary = f"Could not solve '{state['expression']}': {state['error']}"
                step_total.add(1, {"node": "format_node", "status": "failure"})
            else:
                result = state["result"]
                result_str = str(int(result)) if result == int(result) else str(result)
                summary = f"[Format]   Result = {result_str}"
                step_total.add(1, {"node": "format_node", "status": "success"})
            span.set_attribute("expression", state["expression"])
            return {"steps": steps + [summary]}
        except Exception as e:
            step_total.add(1, {"node": "format_node", "status": "failure"})
            span.record_exception(e)
            raise


# Compile the graph once at import — record build duration
_build_start = _t.perf_counter()
_solver_graph = (
    StateGraph(MathState)
    .add_node("parse", parse_node)
    .add_node("evaluate", evaluate_node)
    .add_node("format", format_node)
    .set_entry_point("parse")
    .add_edge("parse", "evaluate")
    .add_edge("evaluate", "format")
    .add_edge("format", END)
    .compile()
)
graph_build_time.record(_t.perf_counter() - _build_start, {"worker_type": "solver"})


# ── 6. Server 1: Addition & Subtraction  (port 8081) ─────────────────────────
add_sub_mcp = FastMCP(name="add_sub_server")


@add_sub_mcp.tool()
@traced_tool("add", server="add_sub_server")
def add(a: float, b: float, ctx: Context) -> float:
    """Add two numbers together."""
    result = a + b
    logger.info(f"add({a}, {b}) = {result}")
    return result


@add_sub_mcp.tool()
@traced_tool("subtract", server="add_sub_server")
def subtract(a: float, b: float, ctx: Context) -> float:
    """Subtract b from a."""
    result = a - b
    logger.info(f"subtract({a}, {b}) = {result}")
    return result


# ── 7. Server 2: Multi-step solver with LangGraph  (port 8082) ───────────────
mul_div_mcp = FastMCP(name="mul_div_server")


@mul_div_mcp.tool()
@traced_tool("solve_steps", server="mul_div_server", timeout_s=30.0)
def solve_steps(expression: str, ctx: Context) -> str:
    """Solve a multi-step arithmetic expression with a 3-node LangGraph pipeline."""
    exec_start = _t.perf_counter()
    initial_state: MathState = {
        "expression": expression,
        "tokens": [],
        "result": 0.0,
        "steps": [],
        "error": "",
    }
    try:
        final_state = _solver_graph.invoke(initial_state)
        result_str = "\n".join(final_state["steps"])
        execution_duration.record(_t.perf_counter() - exec_start, {"worker_type": "solver"})
        logger.info(f"solve_steps('{expression}') -> ok")
        return result_str
    except Exception as exc:
        execution_duration.record(_t.perf_counter() - exec_start, {"worker_type": "solver"})
        logger.error(f"solve_steps('{expression}') -> {exc}")
        raise


# ── 8. Entry point ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    try:
        if _MODE == "add_sub":
            logger.info("Starting add_sub MCP server on http://localhost:8081 (metrics :8001)")
            add_sub_mcp.run(transport="http", host="0.0.0.0", port=8081)
        elif _MODE == "mul_div":
            logger.info("Starting mul_div MCP server on http://localhost:8082 (metrics :8002)")
            mul_div_mcp.run(transport="http", host="0.0.0.0", port=8082)
    finally:
        wd_otel.shutdown()
```

- [ ] **Step 2.2: Smoke-verify the add_sub server boots**

Open two terminals. Terminal 1:

```bash
python otel_agent_v2/mcp_server.py add_sub
```

Expected: `[wd-otel] SDK initialised — service=otel-agent-v2-mcp-add-sub env=local` in the log, followed by FastMCP banner.

Terminal 2:

```bash
curl -s http://localhost:8001/metrics | head -50
```

Expected: Prometheus text output including lines with `# HELP wd_otel_tool_invocations_total` and `# HELP langgraph_build_duration_seconds`. No invocations recorded yet (metric value 0 or absent until first call).

Stop the server with Ctrl+C.

- [ ] **Step 2.3: Smoke-verify the mul_div server boots**

Terminal 1:

```bash
python otel_agent_v2/mcp_server.py mul_div
```

Expected: `service=otel-agent-v2-mcp-mul-div` in the banner.

Terminal 2:

```bash
curl -s http://localhost:8002/metrics | grep langgraph_build_duration
```

Expected: a `langgraph_build_duration_seconds_count` line with value `1.0` (graph was compiled once at import).

Stop the server.

- [ ] **Step 2.4: Commit**

```bash
git add otel_agent_v2/mcp_server.py
git commit -m "feat(otel_agent_v2): MCP server with @traced_tool + LangGraph metrics"
```

---

## Task 3: `orchestrator.py` — pure multi-agent logic via `TracedOrchestrator`

**Files:**
- Create: `otel_agent_v2/orchestrator.py`

**What this demonstrates:** `TracedOrchestrator` eliminates all manual lifecycle/transition/sync_failure bookkeeping (compare line count against `agent_auto_multiple.py` lines 253–354). The subclass only defines agents + `sync_status` hook.

**Contract:** This module assumes the caller has **already** run `wd_otel.init()` and `OpenAIAgentsInstrumentor().instrument()`. It does not do either itself. Both `api.py` and `cli.py` must honour this (Tasks 4, 5).

- [ ] **Step 3.1: Write `otel_agent_v2/orchestrator.py`**

```python
"""
Multi-Agent Calculator — orchestrator logic only (no transport, no OTel bootstrap).

Preconditions (enforced by the caller, not this file):
    1. `wd_otel.init("otel_agent_v2/wd-otel-orchestrator.yaml")` has been called.
    2. `OpenAIAgentsInstrumentor().instrument()` has been called.

Both api.py and cli.py set these up before importing this module.

Exports:
    orchestrator — a singleton CalculatorOrchestrator instance.
                   Call `await orchestrator.execute(question)` to run one session.
"""
from __future__ import annotations

import logging
import os

from agents import Agent, AsyncOpenAI, OpenAIChatCompletionsModel, handoff
from agents.mcp import MCPServerStreamableHttp

from wd_otel_orchestrator import TracedOrchestrator
from wd_otel_orchestrator.base import HandoffReason

logger = logging.getLogger(__name__)

# ── 1. LLM client ────────────────────────────────────────────────────────────
# Swap base_url/api_key to point at any OpenAI-compatible endpoint
# (Groq here; a Bedrock proxy, Ollama, or vLLM would work identically).
_client = AsyncOpenAI(
    api_key=os.environ["API_KEY"],
    base_url=os.environ.get("LLM_BASE_URL", "https://api.groq.com/openai/v1/"),
)
_model = OpenAIChatCompletionsModel(
    model=os.environ.get("LLM_MODEL", "openai/gpt-oss-120b"),
    openai_client=_client,
)

# ── 2. MCP server handles ────────────────────────────────────────────────────
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

# ── 3. Specialist agents ─────────────────────────────────────────────────────
add_sub_agent = Agent(
    name="AddSubAgent",
    instructions=(
        "You only handle addition and subtraction. "
        "Always use the add or subtract tool — never calculate mentally. "
        "Return just the numeric result."
    ),
    model=_model,
    mcp_servers=[add_sub_server],
)

solver_agent = Agent(
    name="SolverAgent",
    instructions=(
        "You handle complex arithmetic expressions with multiple operations. "
        "Always use the solve_steps tool — never calculate mentally. "
        "Return the full step-by-step breakdown."
    ),
    model=_model,
    mcp_servers=[mul_div_server],
)

# ── 4. Orchestrator agent (the entry_agent) ──────────────────────────────────
# handoff(input_type=HandoffReason) is required for Groq-compatible JSON schema.
# TracedOrchestrator.execute() also wires in on_handoff callbacks that record
# idle→running transitions automatically via TransitionTracker.
_orchestrator_agent = Agent(
    name="OrchestratorAgent",
    instructions=(
        "You are a routing orchestrator for a calculator system. "
        "Given a math question, hand off to the correct specialist:\n"
        "  - AddSubAgent  -> simple addition or subtraction only\n"
        "  - SolverAgent  -> complex expressions with *, /, ** or parentheses\n"
        "Always include a brief reason when handing off. "
        "Never calculate yourself — always hand off."
    ),
    model=_model,
    handoffs=[
        handoff(add_sub_agent, input_type=HandoffReason),
        handoff(solver_agent, input_type=HandoffReason),
    ],
)


# ── 5. CalculatorOrchestrator(TracedOrchestrator) ────────────────────────────
class CalculatorOrchestrator(TracedOrchestrator):
    """Concrete orchestrator. The base class handles all lifecycle metrics."""

    name = "multi-agent-calculator"
    agents = {"AddSubAgent": add_sub_agent, "SolverAgent": solver_agent}
    entry_agent = _orchestrator_agent

    async def sync_status(self, worker_name: str, status: str, output: str) -> None:
        """Simulate syncing worker status to an external system.

        Any exception raised here is recorded as a sync_failure by the base
        class automatically (see TracedOrchestrator.execute).
        """
        logger.info(f"[Sync] {worker_name} status='{status}' (output len={len(output)}) synced")


# ── 6. Rebuild handoffs with on_handoff callbacks wired by TracedOrchestrator ─
# The base class's _build_handoffs() generates callbacks that record the
# idle→running transition via TransitionTracker. We overwrite the plain
# handoffs defined above so metrics fire. This pattern is required because
# the Agent object needs the handoff callback bound at construction time,
# but the callback needs a reference to the orchestrator's tracker.
orchestrator = CalculatorOrchestrator()
_orchestrator_agent.handoffs = orchestrator._build_handoffs()
```

**Note on the handoff-rebinding dance at the bottom:** the `Agent` instance
is constructed at module load with plain `handoff(...)` calls (no callback).
We then instantiate `CalculatorOrchestrator`, which creates a
`TransitionTracker`, and ask the base class to rebuild the handoffs with
instrumented callbacks. Those get assigned back onto the entry agent in
place. This is the cleanest way to get callback wiring without making agent
construction dependent on orchestrator construction.

- [ ] **Step 3.2: Smoke-verify the module imports without calling `init()` first**

The module should import cleanly as long as `API_KEY` is set — it must not raise because OTel isn't initialised (agents SDK is lazy). From repo root:

```bash
API_KEY=test-key python -c "
import wd_otel
wd_otel.init('otel_agent_v2/wd-otel-orchestrator.yaml')
from otel_agent_v2.orchestrator import orchestrator
print('name =', orchestrator.name)
print('entry =', orchestrator.entry_agent.name)
print('agents =', list(orchestrator.agents.keys()))
"
```

Expected output:
```
name = multi-agent-calculator
entry = OrchestratorAgent
agents = ['AddSubAgent', 'SolverAgent']
```

- [ ] **Step 3.3: Commit**

```bash
git add otel_agent_v2/orchestrator.py
git commit -m "feat(otel_agent_v2): orchestrator module using TracedOrchestrator"
```

---

## Task 4: `cli.py` — asyncio smoke runner

**Files:**
- Create: `otel_agent_v2/cli.py`

**What this demonstrates:** The orchestrator module is transport-agnostic. The CLI is thin — bootstrap, import, run, shut down.

- [ ] **Step 4.1: Write `otel_agent_v2/cli.py`**

```python
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
        wd_otel.shutdown()
```

- [ ] **Step 4.2: Smoke-verify — requires both MCP servers running**

In three separate terminals:

Terminal 1:
```bash
python otel_agent_v2/mcp_server.py add_sub
```

Terminal 2:
```bash
python otel_agent_v2/mcp_server.py mul_div
```

Terminal 3 (with `API_KEY` set in `.env` or environment):
```bash
python otel_agent_v2/cli.py "What is 100 - 37?"
```

Expected: final line is `=== ANSWER ===` followed by the model's response (typically `63.0` or a short sentence containing `63`).

- [ ] **Step 4.3: Commit**

```bash
git add otel_agent_v2/cli.py
git commit -m "feat(otel_agent_v2): CLI smoke runner"
```

---

## Task 5: `api.py` — FastAPI transport over the orchestrator

**Files:**
- Create: `otel_agent_v2/api.py`

**What this demonstrates:** FastAPI layer has no OTel code and no agent definitions. It imports the orchestrator module and exposes one endpoint.

- [ ] **Step 5.1: Write `otel_agent_v2/api.py`**

```python
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


@app.post("/run", response_model=AnswerResponse)
async def run(request: QuestionRequest) -> AnswerResponse:
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="question cannot be empty")
    answer = await orchestrator.execute(request.question)
    return AnswerResponse(answer=answer)
```

- [ ] **Step 5.2: Smoke-verify — end-to-end through FastAPI**

Terminals 1 and 2 running MCP servers as in Task 4.2.

Terminal 3:
```bash
uvicorn otel_agent_v2.api:app --host 0.0.0.0 --port 8080
```

Expected startup log includes `[wd-otel] SDK initialised — service=otel-agent-v2-orchestrator env=local` and `MCP servers connected and tool lists cached`.

Terminal 4:
```bash
curl -s http://localhost:8080/health
```

Expected: `{"status":"ok","metrics":"http://localhost:8000/metrics"}`

```bash
curl -s -X POST http://localhost:8080/run \
  -H "Content-Type: application/json" \
  -d '{"question":"What is 100 - 37?"}'
```

Expected: `{"answer":"63"}` or similar short response containing `63`.

```bash
curl -s http://localhost:8000/metrics | grep -E "wd_otel_(session|state|workers|tool)" | head
```

Expected: non-zero counters for `wd_otel_session_count_total`, `wd_otel_state_transitions_total`, and `wd_otel_tool_invocations_total`.

Stop uvicorn with Ctrl+C.

- [ ] **Step 5.3: Commit**

```bash
git add otel_agent_v2/api.py
git commit -m "feat(otel_agent_v2): FastAPI transport layer"
```

---

## Task 6: Update `kpi_proxy.py` queries to match new metric names

**Files:**
- Modify: `otel_agent_v2/kpi_proxy.py`

**Context:** The 7 auto-emitted metrics changed names between `otel_agent/` and `otel_agent_v2/`:

| KPI key | Old Prom name | New Prom name |
|---|---|---|
| orchestrator.active_workers | `orchestrator_active_workers` | `wd_otel_workers_active` |
| orchestrator.state_transitions_rate | `orchestrator_state_transitions_total` | `wd_otel_state_transitions_total` |
| orchestrator.errors_total | `orchestrator_errors_total` | `wd_otel_orchestration_errors_total` |
| orchestrator.sync_failures_1h | `orchestrator_sync_failures_total` | `wd_otel_sync_failures_total` |
| mcp.invocations_rate | `mcp_tool_invocations_total` | `wd_otel_tool_invocations_total` |
| mcp.duration_p95 | `mcp_tool_duration_bucket` | `wd_otel_tool_duration_bucket` |
| mcp.timeouts_rate | `mcp_tool_timeouts_total` | `wd_otel_tool_timeouts_total` |

The 4 LangGraph metric names are **unchanged** (`langgraph_*`) because we kept them custom with the same names.

Also: the new metrics use `worker` / `tool` / `server` labels (what the wd-otel helpers emit), not the old `worker_type` / `tool_server`. Queries must reflect this.

- [ ] **Step 6.1: Edit the `QUERIES` dict in `otel_agent_v2/kpi_proxy.py`**

Replace the whole `QUERIES` dict (lines 63–131 in the copied file) with this:

```python
QUERIES: dict[str, dict[str, str]] = {
    # ── DW Orchestrator (4) ──────────────────────────────────────────────
    "orchestrator.active_workers": {
        "area": "orchestrator",
        "title": "Concurrent active workers",
        "query": "sum by (worker) (wd_otel_workers_active)",
    },
    "orchestrator.state_transitions_rate": {
        "area": "orchestrator",
        "title": "State transitions /min by worker→to",
        "query": "sum by (worker, from, to) "
                 "(rate(wd_otel_state_transitions_total[5m])) * 60",
    },
    "orchestrator.errors_total": {
        "area": "orchestrator",
        "title": "Orchestration errors (cumulative)",
        "query": "sum by (worker_type, error_type) "
                 "(wd_otel_orchestration_errors_total)",
    },
    "orchestrator.sync_failures_1h": {
        "area": "orchestrator",
        "title": "Status sync failures (last 1h)",
        "query": "sum by (worker_type, failure_type) "
                 "(increase(wd_otel_sync_failures_total[1h]))",
    },

    # ── Worker Runner / LangGraph (4) — UNCHANGED from otel_agent/ ───────
    "langgraph.build_duration_avg": {
        "area": "langgraph",
        "title": "Graph build duration (avg)",
        "query": "sum(langgraph_build_duration_seconds_sum) "
                 "/ clamp_min(sum(langgraph_build_duration_seconds_count), 1)",
    },
    "langgraph.step_rate": {
        "area": "langgraph",
        "title": "Step success/failure rate by node",
        "query": "sum by (node, status) (rate(langgraph_step_total[5m]))",
    },
    "langgraph.execution_duration_p95": {
        "area": "langgraph",
        "title": "Full graph execution p95",
        "query": "histogram_quantile(0.95, sum by (le) "
                 "(rate(langgraph_execution_duration_seconds_bucket[5m])))",
    },
    "langgraph.step_retries_rate": {
        "area": "langgraph",
        "title": "Node retries /min",
        "query": "sum by (node) (rate(langgraph_step_retries_total[5m])) * 60",
    },

    # ── MCP Tool Server (3) ──────────────────────────────────────────────
    "mcp.invocations_rate": {
        "area": "mcp",
        "title": "Tool invocation rate by status",
        "query": "sum by (tool, server, status) "
                 "(rate(wd_otel_tool_invocations_total[5m]))",
    },
    "mcp.duration_p95": {
        "area": "mcp",
        "title": "Tool latency p95",
        "query": "histogram_quantile(0.95, sum by (le, tool, server) "
                 "(rate(wd_otel_tool_duration_seconds_bucket[5m])))",
    },
    "mcp.timeouts_rate": {
        "area": "mcp",
        "title": "Tool timeouts /min",
        "query": "sum by (tool, server) "
                 "(rate(wd_otel_tool_timeouts_total[5m])) * 60",
    },
}
```

**Note on label names:**
- `wd_otel_workers_active` → label is `worker` (from `helpers._record_transition_internal`)
- `wd_otel_state_transitions_total` → labels `worker`, `from`, `to`
- `wd_otel_orchestration_errors_total` / `wd_otel_sync_failures_total` → labels `worker_type`, `error_type` / `failure_type` (emitted by `TransitionTracker`)
- `wd_otel_tool_*` → labels `tool`, `server`, `status` (from `tool_span` / `@traced_tool`)

If labels don't match at smoke-test time, inspect raw metrics with `curl http://localhost:8000/metrics | grep wd_otel` and adjust `sum by (...)` accordingly.

- [ ] **Step 6.2: Smoke-verify the updated proxy queries resolve**

Need Prometheus running (see `Grafana_stackv1/` in the repo, or any existing dev stack). With the 3 otel_agent_v2 processes and Prometheus up, issue one `POST /run` (from Task 5.2), wait ~15s for scrape, then:

```bash
python otel_agent_v2/kpi_proxy.py &
sleep 2
curl -s http://localhost:8900/kpi/all | python -m json.tool | head -50
```

Expected: JSON with keys `orchestrator.active_workers`, `mcp.invocations_rate`, etc. None of them should have an `error` field. `result` arrays may be empty until traffic flows but should not error.

Kill the proxy: `kill %1`.

- [ ] **Step 6.3: Commit**

```bash
git add otel_agent_v2/kpi_proxy.py
git commit -m "feat(otel_agent_v2): update kpi_proxy queries for wd_otel metric names"
```

---

## Task 7: `README.md` — runbook + concept map

**Files:**
- Create: `otel_agent_v2/README.md`

- [ ] **Step 7.1: Write `otel_agent_v2/README.md`**

````markdown
# otel_agent_v2

Working rewrite of `otel_agent/` using the `wd-otel-core`, `wd-otel-mcp`,
and `wd-otel-orchestrator` packages. Not a Python package — just working
code to study and modify.

See `docs/superpowers/specs/2026-04-19-otel-agent-v2-design.md` for the
full rationale.

## File map

| File | Role | Notable pattern |
|---|---|---|
| `mcp_server.py` | MCP tool servers (add_sub \| mul_div) | `@traced_tool(...)` replaces manual span/thread plumbing |
| `orchestrator.py` | Agent definitions + `CalculatorOrchestrator(TracedOrchestrator)` | Subclass a base, override `sync_status`, done |
| `api.py` | FastAPI transport | No OTel, no agent defs — just imports `orchestrator` |
| `cli.py` | CLI smoke runner | Same orchestrator, different entry point |
| `kpi_proxy.py` | Prometheus → REST proxy for the 11 KPIs | Queries updated for `wd_otel_*` metric names |
| `wd-otel-*.yaml` | One config per process (distinct Prom ports) | `wd_otel.init("<yaml>")` reads this |

## Prerequisites

- Python 3.10+
- `API_KEY` env var (Groq key, or swap `LLM_BASE_URL` to your Bedrock/etc. proxy)
- `pip install -e wd-otel-core wd-otel-mcp wd-otel-orchestrator`
- `pip install -r otel_agent_v2/requirements.txt`
- Optional: Tempo on `localhost:4317`, Loki on `localhost:3100`, Prometheus
  scraping ports 8000/8001/8002. See `Grafana_stackv1/` for a ready stack.

## Run

Four terminals from the repo root.

```bash
# Terminal 1 — add/subtract MCP server
python otel_agent_v2/mcp_server.py add_sub

# Terminal 2 — multi-step solver MCP server
python otel_agent_v2/mcp_server.py mul_div

# Terminal 3 — FastAPI
uvicorn otel_agent_v2.api:app --host 0.0.0.0 --port 8080

# Terminal 4 — fire a request
curl -X POST http://localhost:8080/run \
  -H "Content-Type: application/json" \
  -d '{"question":"What is (3+5)*2 - 4/2?"}'
```

CLI smoke test (no FastAPI):
```bash
python otel_agent_v2/cli.py "What is 100 - 37?"
```

KPI proxy (after traffic has flowed):
```bash
python otel_agent_v2/kpi_proxy.py
curl http://localhost:8900/kpi/all
```

## Port map

| Port | Purpose |
|---|---|
| 8000 | Prometheus scrape — orchestrator API |
| 8001 | Prometheus scrape — add_sub MCP server |
| 8002 | Prometheus scrape — mul_div MCP server |
| 8080 | FastAPI |
| 8081 | add_sub MCP HTTP |
| 8082 | mul_div MCP HTTP |
| 8900 | KPI proxy |
| 4317 | OTLP gRPC → Tempo |
| 3100 | Loki HTTP |

## Provider notes

The orchestrator talks to any OpenAI-compatible endpoint. Default is Groq:

```python
# orchestrator.py
_client = AsyncOpenAI(
    api_key=os.environ["API_KEY"],
    base_url=os.environ.get("LLM_BASE_URL", "https://api.groq.com/openai/v1/"),
)
```

To route to an AWS Bedrock proxy that mimics the Chat Completions API, set:

```
LLM_BASE_URL=https://your-bedrock-proxy.example.com/v1
LLM_MODEL=anthropic.claude-3-5-sonnet-20241022-v2:0
```

No OTel changes needed — spans and metrics are provider-agnostic.

## 11 KPIs — where they come from now

| KPI | Source in new code |
|---|---|
| `orchestrator.active_workers` | `TransitionTracker` (auto) |
| `orchestrator.state_transitions_rate` | `TransitionTracker` (auto on handoff / completion / error) |
| `orchestrator.errors_total` | `TracedOrchestrator.execute` exception path (auto) |
| `orchestrator.sync_failures_1h` | `TracedOrchestrator.execute` sync phase (auto when `sync_status` raises) |
| `mcp.invocations_rate` | `@traced_tool` finally block (auto) |
| `mcp.duration_p95` | `@traced_tool` finally block (auto) |
| `mcp.timeouts_rate` | `@traced_tool` on thread-join timeout (auto) |
| `langgraph.*` (×4) | `mcp_server.py` — **still custom**, candidate for future helper |
````

- [ ] **Step 7.2: Commit**

```bash
git add otel_agent_v2/README.md
git commit -m "docs(otel_agent_v2): README runbook and concept map"
```

---

## Task 8: End-to-end verification + label-name correction

**Files:**
- Possibly modify: `otel_agent_v2/kpi_proxy.py` (if label names in Task 6 don't match reality)

**Why this task exists:** The exact label names emitted by `TransitionTracker` (`worker_type` vs. `worker`) depend on which helper is called. Task 6 made an educated guess based on reading the source; this task verifies against real Prometheus output and corrects any mismatch.

- [ ] **Step 8.1: Bring up the full stack**

Four terminals as in the README Run section. Then:

```bash
# Send a simple addition (triggers AddSubAgent path)
curl -X POST http://localhost:8080/run \
  -H "Content-Type: application/json" \
  -d '{"question":"What is 100 - 37?"}'

# Send a complex expression (triggers SolverAgent + LangGraph path)
curl -X POST http://localhost:8080/run \
  -H "Content-Type: application/json" \
  -d '{"question":"What is (3+5)*2 - 4/2?"}'
```

Both should return a non-error JSON response.

- [ ] **Step 8.2: Inspect actual metric names and labels**

```bash
curl -s http://localhost:8000/metrics | grep -E "^wd_otel_(workers|state|orchestration|sync)" | head -20
curl -s http://localhost:8001/metrics | grep -E "^wd_otel_tool" | head -20
curl -s http://localhost:8002/metrics | grep -E "^(wd_otel_tool|langgraph)" | head -20
```

Note the exact label names each metric uses. Examples of what to check:

- Does `wd_otel_state_transitions_total` use labels `worker`, `from`, `to`, or `worker_type`, `from_state`, `to_state`?
- Does `wd_otel_orchestration_errors_total` use `worker_type` or `worker`?

- [ ] **Step 8.3: Correct `QUERIES` in `kpi_proxy.py` if label names differ**

If the metrics output shows `worker_type` where Task 6 wrote `worker` (or vice versa), edit `otel_agent_v2/kpi_proxy.py` to match. The target is that every query's `sum by (...)` clause uses label names that actually exist on the metric.

- [ ] **Step 8.4: Verify each of the 11 KPIs returns data**

```bash
python otel_agent_v2/kpi_proxy.py &
sleep 2
for kpi in \
  orchestrator.active_workers \
  orchestrator.state_transitions_rate \
  orchestrator.errors_total \
  orchestrator.sync_failures_1h \
  langgraph.build_duration_avg \
  langgraph.step_rate \
  langgraph.execution_duration_p95 \
  langgraph.step_retries_rate \
  mcp.invocations_rate \
  mcp.duration_p95 \
  mcp.timeouts_rate; do
  echo "--- $kpi ---"
  curl -s "http://localhost:8900/kpi/${kpi}" | python -m json.tool | head -20
done
kill %1
```

Expected: every KPI responds with a `result` array. Some may be empty (e.g. `mcp.timeouts_rate` should be empty — no timeouts occurred), but none should return an `error` field or a Prometheus `execution error`.

- [ ] **Step 8.5: Commit any kpi_proxy corrections**

```bash
git add otel_agent_v2/kpi_proxy.py
git commit -m "fix(otel_agent_v2): align kpi_proxy labels with real metric output"
```

If no corrections were needed, skip the commit.

---

## Summary of what the plan produces

After all 8 tasks:

1. `otel_agent_v2/` sibling directory, 5 Python files + 3 YAMLs + 1 requirements.txt + 1 README.
2. All 11 KPIs flowing end-to-end through `kpi_proxy.py`.
3. ~500 lines of custom OTel bootstrap / decorator / metric-recording code from `otel_agent/` replaced by 3-package library calls.
4. A concrete reference for how to compose the 3 wd-otel packages in a real multi-agent + MCP flow.
5. Seven discrete commits, one per task (Task 8's commit is conditional).

What's explicitly NOT in this plan (per spec non-goals):
- No test suite.
- No helper for the 4 LangGraph KPIs (left custom inside `mcp_server.py`).
- No changes to `otel_agent/`.
- No LLM-provider changes.
