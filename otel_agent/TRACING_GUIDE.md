# OTel Tracing Guide — Agent + MCP Tools

A quick reference for adding distributed tracing to a new agent and MCP tool server so everything shows up in **one unified trace** in Grafana.

---

## How it works

```
Your Agent (agent_auto.py)
    │  injects traceparent header via HTTPXClientInstrumentor
    ▼
MCP Tool Server (mcp_tool_instrumented.py)
    │  extracts traceparent from request via FastMCP Context
    ▼
Grafana / Tempo  ← single trace, all spans linked
```

---

## Prerequisites

```bash
pip install opentelemetry-api opentelemetry-sdk \
    opentelemetry-exporter-otlp-proto-grpc \
    opentelemetry-instrumentation-logging \
    opentelemetry-instrumentation-httpx \
    opentelemetry-exporter-prometheus \
    prometheus_client \
    openinference-instrumentation-openai-agents
```

Start the Grafana stack first:
```bash
cd grafana_stack && docker compose up -d
```

---

## Part 1 — Agent (`your_agent.py`)

### Step 1: Initialize OTel FIRST (before any other imports)

```python
from otel_setup import init_otel, get_tracer, get_meter

trace_provider, metrics_provider = init_otel("your-service-name")
tracer = get_tracer(__name__)
meter  = get_meter(__name__)
```

> **Why first?** The global TracerProvider must be set before any SDK or instrumentor imports. If you import agents SDK before this, auto-instrumentation won't attach correctly.

---

### Step 2: Add auto-instrumentation + httpx trace injection

```python
from openinference.instrumentation.openai_agents import OpenAIAgentsInstrumentor

OpenAIAgentsInstrumentor().instrument()   # captures LLM calls, tool calls automatically
```

Then inject `traceparent` into MCP HTTP requests. **Do NOT use `HTTPXClientInstrumentor`** — it creates root CLIENT spans with new trace_ids because the Agents SDK's async tasks don't inherit OTel context. Use the monkey-patch from Part 3 instead:

```python
import httpx
from opentelemetry import context as otel_context
from opentelemetry.propagate import inject as otel_inject

_mcp_trace_context = None   # set before each Runner.run()

_original_send = httpx.AsyncClient.send

async def _send_with_trace(self, request, **kwargs):
    carrier = {}
    otel_inject(carrier, context=_mcp_trace_context)
    for k, v in carrier.items():
        request.headers[k] = v
    return await _original_send(self, request, **kwargs)

httpx.AsyncClient.send = _send_with_trace
```

> **Why not HTTPXClientInstrumentor?** The MCP client's httpx calls run in a background asyncio task created during `async with mcp_server`. That task copies the OTel context at creation time — it never sees per-question spans. The module-level `_mcp_trace_context` variable is always read fresh.

---

### Step 3: Wrap everything in a root span

```python
async def main():
    # Wrap MCP server setup inside a span — otherwise connection calls
    # (GET/POST/DELETE) appear as separate root traces in Grafana
    with tracer.start_as_current_span("agent-session") as span:
        span.set_attribute("question.count", len(questions))

        async with your_mcp_server:
            await your_mcp_server.list_tools()   # happens inside the span ✅

            for question in questions:
                await run_agent(question)

    # Always flush before exit
    trace_provider.force_flush()
    metrics_provider.shutdown()
```

---

### Step 4: Create manual spans for your workflow

```python
async def run_agent(user_message: str) -> str:
    with tracer.start_as_current_span("agent-run") as span:
        span.set_attribute("agent.input", user_message)

        with tracer.start_as_current_span("runner.run"):
            # agents_trace links OpenAI Agents SDK auto-spans to your OTel span
            with agents_trace(workflow_name="agent-run"):
                result = await Runner.run(agent, input=user_message)

        span.set_attribute("agent.output", result.final_output)

    return result.final_output
```

---

### Step 5: Add metrics (optional)

```python
run_counter = meter.create_counter("agent.runs.total", unit="1")
run_duration = meter.create_histogram("agent.run.duration", unit="s")

# Inside your run function:
run_counter.add(1, {"agent": "MyAgent"})
run_duration.record(elapsed, {"agent": "MyAgent"})
```

---

## Part 2 — MCP Tool Server (`your_mcp_tool.py`)

### Step 1: Initialize OTel and filter FastMCP's built-in spans

```python
from otel_setup import init_otel, get_tracer
from opentelemetry.propagate import extract as otel_extract
from fastmcp import FastMCP, Context

# filter_libraries=["fastmcp"] drops FastMCP's own root spans (they are noise).
# Our custom spans below replace them with more meaningful information.
trace_provider, metrics_provider = init_otel(
    "your-mcp-service-name",
    filter_libraries=["fastmcp"],
)
tracer = get_tracer(__name__)
```

---

### Step 2: Add a helper to extract trace context from each request

```python
from opentelemetry import trace
from opentelemetry.trace import SpanContext, TraceFlags, NonRecordingSpan

def _get_parent_ctx(ctx: Context):
    """Parse W3C traceparent header and build parent context manually."""
    try:
        headers = dict(ctx.request_context.request.headers)
        tp = headers.get("traceparent")
        if not tp:
            return None

        # Format: 00-<trace_id>-<span_id>-<flags>
        parts = tp.split("-")
        span_context = SpanContext(
            trace_id=int(parts[1], 16),
            span_id=int(parts[2], 16),
            is_remote=True,
            trace_flags=TraceFlags(int(parts[3], 16)),
        )
        parent = NonRecordingSpan(span_context)
        return trace.set_span_in_context(parent)
    except Exception:
        return None
```

> **Why manual parsing instead of `otel_extract()`?** The global propagator's `extract()` can silently fail to link traces. Manual parsing is more reliable — you construct the `SpanContext` directly from the header values.

---

### Step 3: Add `ctx: Context` to every tool and use the parent context

```python
mcp = FastMCP(name="my-server")

@mcp.tool()
def my_tool(input: str, ctx: Context) -> str:
    """Your tool description."""
    parent_ctx = _get_parent_ctx(ctx)   # extract traceparent from request

    with tracer.start_as_current_span("my_tool_operation", context=parent_ctx) as span:
        span.set_attribute("input", input)

        # your logic here
        result = do_something(input)

        span.set_attribute("result", result)
        return result
```

> **Key:** `context=parent_ctx` links this span to the agent's trace. Without it, the MCP server creates a separate trace with a different `trace_id`.

---

### Step 4: Create child spans for internal steps (e.g. LangGraph nodes)

```python
def my_langgraph_node(state):
    with tracer.start_as_current_span("node_name") as span:
        span.set_attribute("input", state["expression"])

        result = do_work(state)

        span.set_attribute("result", str(result))
        return result
```

Child spans are automatically nested under the parent tool span — no extra wiring needed.

---

### Step 5: Flush on shutdown

```python
if __name__ == "__main__":
    try:
        mcp.run(transport="http", host="0.0.0.0", port=8081)
    finally:
        trace_provider.force_flush()
        metrics_provider.shutdown()
```

---

## What you get in Grafana

```
agent-session
  └─ agent-run
     └─ runner.run
        └─ CalculatorAgent          ← auto by OpenAIAgentsInstrumentor
           ├─ generation            ← LLM call
           ├─ my_tool               ← tool call
           └─ generation            ← LLM response

mcp-service  my_tool_operation      ← same trace_id as above ✅
  ├─ node_1
  ├─ node_2
  └─ node_3
```

---

---

## Part 3 — Multi-Agent Tracing

The same approach scales to multi-agent systems with handoffs. The key rules:
> 1. **Whoever starts a span owns the context. Whoever receives a call must extract it.**
> 2. **The MCP client's httpx calls run in a background task** — they don't inherit per-question OTel context automatically. You must pass it explicitly.

See `agent_auto_multiple.py` for the full working example.

---

### The async context problem

When the OpenAI Agents SDK calls an MCP server, the HTTP request happens inside a background asyncio task created during `async with mcp_server`. That task copies the OTel context **at creation time** and never sees spans you create later.

This means `HTTPXClientInstrumentor` **won't work** — it creates CLIENT spans with new trace_ids because it can't find your per-question span.

**Solution:** Replace `HTTPXClientInstrumentor` with a httpx monkey-patch that reads the trace context from a module-level variable you control.

---

### Step 1: Monkey-patch httpx to inject traceparent

```python
import httpx
from opentelemetry import context as otel_context
from opentelemetry.propagate import inject as otel_inject

_mcp_trace_context = None   # updated before each Runner.run()

_original_send = httpx.AsyncClient.send

async def _send_with_trace(self, request, **kwargs):
    carrier = {}
    otel_inject(carrier, context=_mcp_trace_context)
    for k, v in carrier.items():
        request.headers[k] = v
    return await _original_send(self, request, **kwargs)

httpx.AsyncClient.send = _send_with_trace
```

> **Why module-level instead of contextvars?** A `ContextVar` is copied when an asyncio task is created. The MCP client's background task was created before your per-question span existed, so it never sees it. A plain module-level variable is always read fresh.

---

### Step 2: Set the context before each agent run

```python
async def run_multi_agent(user_message: str) -> str:
    global _mcp_trace_context

    with tracer.start_as_current_span("multi-agent-run") as span:
        span.set_attribute("agent.input", user_message)

        # Capture this span's context for the httpx monkey-patch
        _mcp_trace_context = otel_context.get_current()

        with tracer.start_as_current_span("runner.run"):
            with agents_trace(workflow_name="multi-agent-calculator"):
                result = await Runner.run(orchestrator, input=user_message)

        span.set_attribute("agent.output", result.final_output)

    return result.final_output
```

---

### Step 3: Define agents with handoffs

Use `handoff()` with a Pydantic `input_type` — this ensures the tool schema has `properties`, which strict LLM APIs (e.g., Groq) require. The `on_handoff` callback must accept two arguments: `ctx` and `input`.

```python
from pydantic import BaseModel
from agents import Agent, Runner, handoff

class HandoffReason(BaseModel):
    reason: str

def on_handoff(ctx, input: HandoffReason) -> None:
    logger.info(f"[Handoff] reason='{input.reason}'")

add_sub_agent = Agent(
    name="AddSubAgent",
    instructions="You handle addition and subtraction only...",
    model=model,
    mcp_servers=[add_sub_server],
)

solver_agent = Agent(
    name="SolverAgent",
    instructions="You handle complex expressions...",
    model=model,
    mcp_servers=[mul_div_server],
)

orchestrator = Agent(
    name="OrchestratorAgent",
    instructions="Route to the correct specialist...",
    model=model,
    handoffs=[
        handoff(add_sub_agent, on_handoff=on_handoff, input_type=HandoffReason),
        handoff(solver_agent,  on_handoff=on_handoff, input_type=HandoffReason),
    ],
)
```

---

### Step 4: MCP server — manually parse traceparent

On the MCP server side, `otel_extract()` can silently fail to link traces. Use manual parsing instead for reliable linking:

```python
from opentelemetry import trace
from opentelemetry.trace import SpanContext, TraceFlags, NonRecordingSpan
from fastmcp import FastMCP, Context

def _get_parent_ctx(ctx: Context):
    """Parse W3C traceparent header and build parent context manually."""
    try:
        headers = dict(ctx.request_context.request.headers)
        tp = headers.get("traceparent")
        if not tp:
            return None

        # Format: 00-<trace_id>-<span_id>-<flags>
        parts = tp.split("-")
        span_context = SpanContext(
            trace_id=int(parts[1], 16),
            span_id=int(parts[2], 16),
            is_remote=True,
            trace_flags=TraceFlags(int(parts[3], 16)),
        )
        parent = NonRecordingSpan(span_context)
        return trace.set_span_in_context(parent)
    except Exception:
        return None

@mcp.tool()
def my_tool(input: str, ctx: Context) -> str:
    parent_ctx = _get_parent_ctx(ctx)
    with tracer.start_as_current_span("my_operation", context=parent_ctx) as span:
        # your logic — all child spans inherit this trace_id
        ...
```

---

### What you get in Grafana (one trace per question)

```
Trace 1: "What is 42 + 58?"
multi-agent-run
  └─ runner.run
     └─ OrchestratorAgent              ← auto (OpenAIAgentsInstrumentor)
        ├─ generation                   ← LLM decides: AddSubAgent
        ├─ handoff → AddSubAgent        ← auto
        └─ AddSubAgent
           ├─ generation                ← LLM picks add tool
           └─ add                       ← MCP tool call
              └─ add_operation          ← MCP server span (same trace_id!) ✅
                 ├─ operand_a: 42
                 ├─ operand_b: 58
                 └─ result: 100

Trace 2: "Solve step by step: (3 + 5) * 2 - 4 / 2"
multi-agent-run
  └─ runner.run
     └─ OrchestratorAgent
        ├─ generation                   ← LLM decides: SolverAgent
        ├─ handoff → SolverAgent        ← auto
        └─ SolverAgent
           ├─ generation                ← LLM picks solve_steps tool
           └─ solve_steps               ← MCP tool call
              └─ solve_steps_operation  ← MCP server span (same trace_id!) ✅
                 ├─ langgraph_parse_node
                 ├─ langgraph_evaluate_node
                 └─ langgraph_format_node
```

---

### Scenario B: HTTP agent-to-agent (separate processes/services)

Each agent is a separate service. The **calling agent** injects, the **receiving agent** extracts.

**Calling agent** — use the same httpx monkey-patch from Step 1 above.

**Receiving agent** — extract context at the entry point of its request handler:
```python
from opentelemetry.trace import SpanContext, TraceFlags, NonRecordingSpan
from fastapi import Request

@app.post("/run")
async def run_agent(request: Request):
    tp = request.headers.get("traceparent")
    parent_ctx = None
    if tp:
        parts = tp.split("-")
        sc = SpanContext(
            trace_id=int(parts[1], 16),
            span_id=int(parts[2], 16),
            is_remote=True,
            trace_flags=TraceFlags(int(parts[3], 16)),
        )
        parent_ctx = trace.set_span_in_context(NonRecordingSpan(sc))

    with tracer.start_as_current_span("sub-agent-run", context=parent_ctx) as span:
        result = await Runner.run(my_agent, input=...)
        return result
```

---

### Scenario C: Parallel agents (fan-out)

Run multiple agents concurrently — all as children of the same parent span.

```python
import asyncio
from opentelemetry.context import attach, detach, get_current

async def run_parallel_agents(questions: list[str]):
    with tracer.start_as_current_span("parallel-session") as parent:
        ctx = get_current()

        async def run_one(question: str):
            token = attach(ctx)
            try:
                with tracer.start_as_current_span("agent-run") as span:
                    span.set_attribute("agent.input", question)
                    return await Runner.run(agent, input=question)
            finally:
                detach(token)

        results = await asyncio.gather(*[run_one(q) for q in questions])
    return results
```

```
parallel-session
  ├─ agent-run (question 1)    ← same trace_id ✅
  ├─ agent-run (question 2)    ← same trace_id ✅
  └─ agent-run (question 3)    ← same trace_id ✅
```

---

### Multi-agent `init_otel` checklist

Each agent/service gets its own `init_otel()` call with a **unique service name**:

```python
# orchestrator.py
trace_provider, _ = init_otel("orchestrator-agent")

# shared_mcp_tool.py — filter FastMCP's built-in spans
trace_provider, _ = init_otel("mcp-server", filter_libraries=["fastmcp"])
```

In Grafana you'll see each service name in the **Service** column, all sharing the same `trace_id`.

---

## Common mistakes

| Mistake | Fix |
|---------|-----|
| `init_otel()` called after SDK imports | Always call it first, before any agents/MCP imports |
| Using `HTTPXClientInstrumentor` with Agents SDK | It creates root CLIENT spans with new trace_ids. Use the httpx monkey-patch + `_mcp_trace_context` instead |
| Forgot `ctx: Context` param on MCP tool | `_get_parent_ctx` has no request to read from |
| Forgot `context=parent_ctx` in `start_as_current_span` | Span starts a new root trace instead of linking |
| Forgot `_mcp_trace_context = otel_context.get_current()` | MCP calls get an empty/wrong trace context |
| Using `otel_extract()` on MCP server side | Can silently fail. Use manual traceparent parsing instead |
| Forgot `force_flush()` before exit | Last batch of spans never reaches Tempo |
| Same service name across all agents | Can't tell which agent a span came from in Grafana |
| `handoff(agent)` without `input_type` | Groq rejects empty tool schemas. Use `input_type=HandoffReason` |
| `on_handoff` with one argument | Must take two: `(ctx, input)`. SDK validates the signature |
| Spawning `asyncio.gather` tasks without `attach(ctx)` | Parallel agents create separate traces instead of siblings |
