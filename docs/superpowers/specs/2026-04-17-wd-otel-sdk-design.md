# WD-OTel SDK — Design Spec

> Date: 2026-04-17
> Status: Approved
> Author: Charikshith + Claude

---

## Problem

The current codebase requires every MCP tool and agent orchestrator to manually write OpenTelemetry instrumentation — span creation, context propagation, metric recording, error handling, and logging. This is:

- **Error-prone:** Missing a single `span.set_attribute()`, forgetting `active_workers.add(-1)` in an error branch, or mishandling `traceparent` extraction causes silent telemetry gaps that are hard to debug.
- **Repetitive:** Each MCP tool repeats ~25 lines of identical boilerplate. The orchestrator lifecycle is ~120 lines of copy-pasted span nesting and metric recording across files.
- **Hard to teach:** Dozens of teams building their own agents and MCP servers need to learn OTel internals. One mistake = unrecorded spans that go unnoticed until an incident.

## Solution

A Python SDK split into three packages that abstracts OTel instrumentation behind decorators, base classes, and helpers — so teams write business logic, not tracing code.

### Design Principles

1. **Never miss a metric** — the SDK guarantees every metric fires by construction, not by developer discipline.
2. **Fail loud in dev, degrade gracefully in prod** — config errors crash the service locally, warn in production.
3. **Decorator for tools, base class for orchestrators, helpers for everything else** — each pattern gets the right abstraction level.
4. **Teams own business logic, SDK owns instrumentation** — agent definitions, MCP server setup, and LLM clients stay in team code.

---

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Scale | Start as internal library, grow to SDK for dozens of teams | Lean start, graduates to framework as adoption grows |
| MCP tools | Decorator (primary) + helpers (escape hatch) | One line to opt in, drop to manual when needed |
| Orchestrators | Base class — metrics fire by construction | Never miss a metric, even at cost of flexibility |
| Init | YAML config file (`wd-otel.yaml`) | Visible, reviewable, team-owned config |
| Packaging | Split: `wd-otel-core`, `wd-otel-mcp`, `wd-otel-orchestrator` | Teams install only what they need |
| Config format | YAML | Consistent with existing Helm/K8s stack |
| Error handling | Strict in dev, lenient in prod | Catch mistakes early without crashing production |

---

## Package Structure

```
wd-otel-core/                     # Foundation — every team installs this
  wd_otel/
    __init__.py                   # wd_otel.init(), wd_otel.tracer(), wd_otel.meter()
    config.py                     # YAML loader + validation
    setup.py                      # TracerProvider, MeterProvider, Loki setup
    helpers.py                    # Escape-hatch context managers
    errors.py                     # WdOtelConfigError, validation logic

wd-otel-mcp/                     # For teams building MCP tool servers
  wd_otel_mcp/
    __init__.py                   # Re-exports traced_tool, current_span
    decorator.py                  # @traced_tool decorator
    context.py                    # Parent context extraction from FastMCP

wd-otel-orchestrator/             # For teams building agent orchestrators
  wd_otel_orchestrator/
    __init__.py                   # Re-exports TracedOrchestrator
    base.py                       # TracedOrchestrator base class
    transitions.py                # State transition + active worker metric logic
```

---

## Section 1: Config (`wd-otel.yaml`)

### Format

```yaml
service:
  name: "my-mcp-server"          # REQUIRED — non-empty string
  version: "1.0.0"               # optional, default "0.0.0"
  env: "local"                   # REQUIRED — local | dev | staging | production

traces:
  endpoint: "localhost:4317"     # optional, default "localhost:4317"
  protocol: "grpc"               # optional, default "grpc"
  filter_libraries:              # optional, default []
    - "fastmcp"

metrics:
  prometheus_port: 8001          # optional, default 8000

logs:
  loki_url: "http://localhost:3100/loki/api/v1/push"  # optional
```

### Initialization

```python
import wd_otel

# Reads wd-otel.yaml from cwd:
wd_otel.init()

# Or pass explicit path:
wd_otel.init("path/to/wd-otel.yaml")

# Then use:
tracer = wd_otel.tracer("my_module")
meter = wd_otel.meter("my_module")
```

### Environment detection fallback

The SDK determines the environment in this order:
1. `service.env` in `wd-otel.yaml` (primary)
2. `WD_OTEL_ENV` environment variable (fallback when YAML is missing)
3. Defaults to `"production"` if neither is set (lenient mode — safest for unknown environments)

This solves the chicken-and-egg problem: if the YAML is missing, the SDK checks `WD_OTEL_ENV` to decide whether to crash or warn.

### Error behavior by environment

| Scenario | `local` / `dev` | `staging` / `production` |
|---|---|---|
| `wd-otel.yaml` not found | `WdOtelConfigError` — service won't start | WARNING log, init with defaults |
| `service.name` missing | `WdOtelConfigError` | WARNING log, uses `"unknown-service"` |
| `service.env` invalid value | `WdOtelConfigError` | WARNING log, assumes `"production"` |
| `traces.endpoint` unreachable | `WdOtelConfigError` | WARNING log, spans silently dropped |
| `metrics.prometheus_port` already in use | `WdOtelConfigError` | WARNING log, metrics disabled |
| `@traced_tool` used without `wd_otel.init()` | `WdOtelConfigError` — always, any env | Same |
| `TracedOrchestrator` missing `name` | `WdOtelConfigError` — always, any env | Same |
| `TracedOrchestrator` missing `entry_agent` | `WdOtelConfigError` — always, any env | Same |

**Principle:** Config issues are strict in dev, lenient in prod. Code issues (missing init, incomplete base class) are strict everywhere.

---

## Section 2: MCP Tool Decorator (`wd-otel-mcp`)

### Primary API — `@traced_tool`

```python
from wd_otel_mcp import traced_tool

@mcp.tool()
@traced_tool("add", server="add_sub_server")
def add(a: float, b: float, ctx: Context) -> float:
    """Add two numbers."""
    return a + b
```

### How `@traced_tool` detects the `ctx` parameter

The decorator inspects the wrapped function's signature for a parameter with type annotation `fastmcp.Context`. It does NOT match by name — a parameter called `ctx` without the type annotation will not be detected. If no `Context` parameter is found, the decorator raises `WdOtelConfigError` (this is a code bug — strict in all environments).

### What `@traced_tool` does automatically

1. Extracts parent trace context from `ctx` (W3C `traceparent` header)
2. Creates a span named `{tool_name}_operation` (e.g., `add_operation`) linked to parent
3. Sets input attributes from function arguments
4. Sets `result` attribute from return value
5. Records `mcp.tool.invocations` counter (labels: `tool`, `server`, `status`)
6. Records `mcp.tool.duration` histogram (labels: `tool`, `server`)
7. On timeout: records `mcp.tool.timeouts` counter
8. On exception: sets `status=error`, calls `span.record_exception(e)`
9. Logs the call via Python logging (correlated with trace ID)

### Customization options

```python
@mcp.tool()
@traced_tool(
    "solve_steps",
    server="mul_div_server",
    timeout_s=30.0,                              # override default 10s
    capture_args=["expression"],                  # only capture these as attributes
    extra_attributes={"tool.category": "math"},   # static attributes on every span
)
def solve_steps(expression: str, ctx: Context) -> str:
    ...
```

### Enriching the auto-created span

`current_span()` is a thin wrapper over `opentelemetry.trace.get_current_span()` — re-exported from the SDK for convenience so teams don't need to import OTel directly.

```python
from wd_otel_mcp import traced_tool, current_span

@mcp.tool()
@traced_tool("divide", server="mul_div_server")
def divide(a: float, b: float, ctx: Context) -> float:
    """Divide a by b."""
    span = current_span()
    if b == 0:
        span.set_attribute("error.reason", "division_by_zero")
        raise ValueError("Cannot divide by zero")
    return a / b
```

### Before/After comparison

**Before (current — ~25 lines per tool):**

```python
@add_sub_mcp.tool()
@instrumented_tool("add", "add_sub_server")
def add(a: float, b: float, ctx: Context) -> float:
    parent_ctx = _get_parent_ctx(ctx)
    with tracer.start_as_current_span("add_operation", context=parent_ctx) as span:
        span.set_attribute("operand_a", a)
        span.set_attribute("operand_b", b)
        result = a + b
        span.set_attribute("result", result)
        logger.info(f"add({a}, {b}) = {result}")
        return result
```

**After (with SDK — 4 lines per tool):**

```python
@add_sub_mcp.tool()
@traced_tool("add", server="add_sub_server")
def add(a: float, b: float, ctx: Context) -> float:
    """Add two numbers."""
    return a + b
```

---

## Section 3: Orchestrator Base Class (`wd-otel-orchestrator`)

### Primary API — `TracedOrchestrator`

```python
from wd_otel_orchestrator import TracedOrchestrator

class CalculatorOrchestrator(TracedOrchestrator):
    name = "multi-agent-calculator"

    agents = {
        "AddSubAgent": add_sub_agent,
        "SolverAgent": solver_agent,
    }
    entry_agent = orchestrator

    async def sync_status(self, worker_name: str, status: str, output: str):
        """Called automatically after every run. Override for custom sync logic."""
        logger.info(f"[Sync] {worker_name} status='{status}' synced to API")

# Usage:
result = await CalculatorOrchestrator().execute("What is 42 + 58?")
```

### Lifecycle guaranteed by the base class

Every call to `execute()` runs this — teams never touch this code:

```
execute("What is 42 + 58?")
|
+- span: orchestrator.worker.lifecycle
|   +- attributes: workflow.name, agent.input, orchestrator
|   |
|   +- span: multi-agent-run
|   |   +- _mcp_trace_context captured
|   |   |
|   |   +- span: runner.run
|   |   |   +- Runner.run(entry_agent, input=...)
|   |   |
|   |   +- on success:
|   |   |   +- span: orchestrator.transition (running -> completed)
|   |   |   +- state_transitions.add(1)
|   |   |   +- active_workers.add(-1)
|   |   |   +- session_counter.add(1)
|   |   |   +- session_duration.record(elapsed)
|   |   |
|   |   +- on error:
|   |       +- span: orchestrator.transition (running -> error)
|   |       +- state_transitions.add(1)
|   |       +- active_workers.add(-1)
|   |       +- orchestration_errors.add(1)
|   |       +- span.record_exception(e)
|   |
|   +- lifecycle_span attributes: status, final_agent, duration_s
|   |
|   +- sync_status(worker_name, status, output)
|       +- span: orchestrator.sync
|       +- on failure: sync_failures.add(1)
|
+- return result
```

### Metrics guaranteed by construction

| Metric | When | Can be missed? |
|---|---|---|
| `orchestrator.active.workers` +1 | On handoff | No — wired into handoff registration |
| `orchestrator.active.workers` -1 | On success OR error | No — both branches in base class |
| `orchestrator.state.transitions` (idle->running) | On handoff | No — wired into handoff registration |
| `orchestrator.state.transitions` (running->completed/error) | On success OR error | No — both branches in base class |
| `orchestrator.errors` | On exception | No — in except block of base class |
| `orchestrator.sync.failures` | On sync exception | No — in sync wrapper of base class |
| `multi_agent.sessions.total` | On every execute | No — fires in finally block |
| `multi_agent.session.duration` | On every execute | No — fires in finally block |

### Framework coupling

`TracedOrchestrator` is coupled to the OpenAI Agents SDK (`Runner.run()`, `handoff()`, `Agent`). Teams using a different agent framework (LangChain, CrewAI, AutoGen) should use `helpers.lifecycle_span` + `helpers.record_transition` instead, or a new base class can be built for that framework.

### Hooks for customization

```python
class CalculatorOrchestrator(TracedOrchestrator):
    name = "multi-agent-calculator"
    agents = {...}
    entry_agent = orchestrator

    async def on_before_run(self, input: str):
        """Called before Runner.run."""
        pass

    async def on_after_run(self, result, elapsed: float):
        """Called after successful run."""
        pass

    async def on_error(self, error: Exception, elapsed: float):
        """Called on error. Metrics already recorded."""
        pass

    async def sync_status(self, worker_name: str, status: str, output: str):
        """Called after every run for status sync."""
        pass
```

### Before/After comparison

**Before (current — ~120 lines):**

```python
# 20 lines of metric declarations
active_workers = meter.create_up_down_counter(...)
state_transitions = meter.create_counter(...)
orchestration_errors = meter.create_counter(...)
sync_failures = meter.create_counter(...)
session_counter = meter.create_counter(...)
session_duration = meter.create_histogram(...)

# 15 lines for make_on_handoff
def make_on_handoff(worker_name):
    ...

# 80 lines for run_multi_agent
async def run_multi_agent(user_message):
    ...
```

**After (with SDK — ~15 lines):**

```python
from wd_otel_orchestrator import TracedOrchestrator

class CalculatorOrchestrator(TracedOrchestrator):
    name = "multi-agent-calculator"
    agents = {
        "AddSubAgent": add_sub_agent,
        "SolverAgent": solver_agent,
    }
    entry_agent = orchestrator

    async def sync_status(self, worker_name, status, output):
        logger.info(f"[Sync] {worker_name} status='{status}' synced")

result = await CalculatorOrchestrator().execute("What is 42 + 58?")
```

---

## Section 4: Helpers / Escape Hatch (`wd-otel-core`)

Composable building blocks used internally by the decorator and base class, available to teams for custom scenarios.

### `helpers.tool_span` — MCP tools with custom inner structure

```python
from wd_otel import helpers

@mcp.tool()
def solve_steps(expression: str, ctx: Context) -> str:
    with helpers.tool_span(ctx, "solve_steps", server="mul_div_server",
                           inputs={"expression": expression}) as span:
        with helpers.child_span("parse", attributes={"token_count": 5}):
            tokens = parse(expression)

        with helpers.child_span("evaluate"):
            result = evaluate(tokens)

        span.set_output(result)
        return result
```

Guarantees: invocation counter, duration histogram, timeout counter, exception recording.
Team controls: inner span structure, custom attributes, output timing.

### `helpers.lifecycle_span` — custom orchestrators

```python
from wd_otel import helpers

async def my_custom_orchestrator(input: str) -> str:
    with helpers.lifecycle_span("my-workflow", input=input) as lifecycle:
        try:
            result = await some_custom_runner(input)
            lifecycle.complete(agent="MyAgent", output=result)
            return result
        except Exception as e:
            lifecycle.error(agent="MyAgent", exception=e)
            raise
```

Guarantees: session counter, session duration histogram, lifecycle span.
Team responsibility: state transitions, active worker tracking.

### `helpers.child_span` — simple nested spans

```python
with helpers.child_span("my_step", attributes={"key": "value"}) as span:
    result = do_work()
    span.set_attribute("result", result)
```

### `helpers.record_transition` — standalone state transition

```python
helpers.record_transition(
    worker="AddSubAgent",
    from_state="idle",
    to_state="running",
    reason="simple addition request"
)
```

### When to use what

| Scenario | Use this | Safety level |
|---|---|---|
| Standard MCP tool | `@traced_tool` decorator | Full |
| MCP tool with sub-spans | `helpers.tool_span` context manager | High |
| Standard orchestrator | `TracedOrchestrator` base class | Full |
| Custom orchestrator | `helpers.lifecycle_span` + `helpers.record_transition` | Medium |
| Nested work inside a span | `helpers.child_span` | N/A |

---

## Section 5: Out of Scope

| Area | Reason |
|---|---|
| Dashboard / frontend (`otel-monitor/`) | Separate concern — SDK produces signals, dashboards consume |
| Grafana/K8s deployment (`Grafana_stackv1/`) | Infrastructure config stays separate |
| LLM client setup | Not an observability concern |
| Agent definition (instructions, handoffs) | Business logic — SDK only wraps execution |
| Prometheus alert rules | Teams define own SLO thresholds |
| LangGraph graph construction | SDK traces nodes via `child_span`, doesn't own graph building |
| MCP server creation | Teams create own `FastMCP(name=...)` — SDK decorates tools |

### What stays in team code

MCP server file:

```python
from fastmcp import FastMCP
import wd_otel
from wd_otel_mcp import traced_tool

wd_otel.init()
mcp = FastMCP(name="my_server")

@mcp.tool()
@traced_tool("my_tool", server="my_server")
def my_tool(x: int, ctx: Context) -> int:
    return x * 2

if __name__ == "__main__":
    mcp.run(transport="http", port=8081)
```

Orchestrator file:

```python
import wd_otel
from wd_otel_orchestrator import TracedOrchestrator

wd_otel.init()

class MyOrchestrator(TracedOrchestrator):
    name = "my-workflow"
    agents = {"AgentA": agent_a}
    entry_agent = router_agent
```
