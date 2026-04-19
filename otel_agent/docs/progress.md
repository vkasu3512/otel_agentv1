# KPI Implementation Progress

## Overview

| Area | KPIs | Status | File | Metrics Port |
|---|---|---|---|---|
| DW Orchestrator | 4 | Done | `agent_auto_multiple.py`, `agent_api.py` | 8000 |
| Worker Runner (LangGraph) | 4 | Done | `mcp_tool_instrumented.py` | 8002 |
| MCP Tool Servers | 3 | Done | `mcp_tool_instrumented.py` | 8001, 8002 |
| **Total** | **11** | **Done** | | |

---

## DW Orchestrator KPIs

Implemented in: `agent_auto_multiple.py`, `agent_api.py`
Metrics served on: port 8000

### Metrics

| KPI | Metric | Type | Labels |
|---|---|---|---|
| Concurrent active workers | `orchestrator_active_workers` | UpDownCounter | `worker_type` |
| Worker state transitions | `orchestrator_state_transitions_total` | Counter | `worker_type`, `from_state`, `to_state` |
| Orchestration error rate | `orchestrator_errors_total` | Counter | `error_type`, `worker_type` |
| Status sync failures | `orchestrator_sync_failures_total` | Counter | `failure_type`, `worker_type` |

### Tracing Spans

| Span | Where | Purpose |
|---|---|---|
| `orchestrator.worker.lifecycle` | Wraps entire `run_multi_agent` | Full worker lifecycle (parent) |
| `orchestrator.transition` (idle->running) | `on_handoff` callback | Tracks handoff start |
| `orchestrator.transition` (running->completed/error) | After `Runner.run` completes/fails | Tracks completion |
| `orchestrator.sync` | `_sync_status_to_api()` | Status sync to external API |

### Flow

1. Handoff fires -> `on_handoff` records `idle->running` transition, increments `active_workers`
2. Run succeeds -> records `running->completed`, decrements `active_workers`
3. Run fails -> records `running->error`, decrements `active_workers`, increments `orchestration_errors`
4. Sync -> `_sync_status_to_api` reports final status, tracks failures

### Grafana Queries

```promql
# KPI 1 - State transitions by from/to state
orchestrator_state_transitions_total

# KPI 2 - Currently active workers
orchestrator_active_workers

# KPI 3 - Transitions rate per minute
rate(orchestrator_state_transitions_total[5m]) * 60

# KPI 4 - Error rate (0 until an error occurs)
orchestrator_errors_total
```

> **Note — KPI 3 shows zero when idle**
>
> `rate()` measures the per-second rate of change over the 5-minute window, scaled to per-minute.
> It returns `0` when no transitions occurred in the last 5 minutes — this is correct behavior.
>
> | Time | Value |
> |------|-------|
> | Just after running the agent | `~0.4/min` (2 transitions / 300s × 60) |
> | 5 minutes later with no new runs | `0` — transitions have aged out of the window |
> | Running repeatedly every minute | `~2.0/min` (2 transitions × 1 run/min) |
>
> To always see a non-zero value regardless of activity, use the raw counter:
> ```promql
> orchestrator_state_transitions_total        -- total ever, never resets
> rate(orchestrator_state_transitions_total[1h]) * 60  -- wider window
> ```

### Expected Values After One Successful Request

For a single request (e.g. `"What is 100 - 37?"`) hitting AddSubAgent:

**KPI 1 — `orchestrator_state_transitions_total`**

Two label combinations, each with value `1`:
```
{worker_type="AddSubAgent", from_state="idle",    to_state="running"}   = 1
{worker_type="AddSubAgent", from_state="running", to_state="completed"} = 1
```
One `idle->running` fires in `on_handoff`, one `running->completed` fires after `Runner.run()` returns.

**KPI 2 — `orchestrator_active_workers`**

```
{worker_type="AddSubAgent"} = 0
```
+1 on handoff, -1 on completion — net zero by the time Prometheus scrapes. Would show `1` only if queried during the ~1 second the agent is running.

**KPI 3 — `rate(orchestrator_state_transitions_total[5m]) * 60`**

```
~0.4 transitions/min
```
2 transitions in a 5-minute window: `2 / 300s * 60 = 0.4/min`. Run 3 times to see ~1.2/min.

**KPI 4 — `orchestrator_errors_total`**

```
no data
```
OTel counters only appear after their first increment. No errors occurred so the series was never created. This is correct — not a bug. To trigger it, stop an MCP server and send a request.

---

## Worker Runner (LangGraph) KPIs

Implemented in: `mcp_tool_instrumented.py`
Metrics served on: port 8002 (mul_div_server)

### Metrics

| KPI | Metric | Type | Labels |
|---|---|---|---|
| Execution graph build time | `langgraph_build_duration` | Histogram | `worker_type` |
| Step success/failure rate per node | `langgraph_step_total` | Counter | `node`, `status` |
| Total execution duration | `langgraph_execution_duration` | Histogram | `worker_type` |
| Step retry count | `langgraph_step_retries_total` | Counter | `node` |

### Tracing Spans

| Span | Where | Purpose |
|---|---|---|
| `worker.runner.execution` | Wraps `_solver_graph.invoke()` in `solve_steps` | Full graph run lifecycle |
| `worker.runner.build` | Entry point of `solve_steps` | Marks graph execution entry |
| `langgraph_parse_node` | `parse_node` function | Tokenization step |
| `langgraph_evaluate_node` | `evaluate_node` function | Expression evaluation step |
| `langgraph_format_node` | `format_node` function | Result formatting step |

### Implementation Details

- `graph_build_time` recorded once at module load when `StateGraph(...).compile()` runs
- Each node (`parse_node`, `evaluate_node`, `format_node`) increments `langgraph_step_total` with `{node, status}` labels inside its try/except
- `execution_duration` recorded in `solve_steps` wrapping the full `_solver_graph.invoke()` call
- `run_node_with_retry(node_fn, state, max_retries=2)` wrapper available for retry tracking — increments `langgraph_step_retries_total` on each failed attempt with exponential backoff

### Grafana Queries

```promql
# Build time (fires once at server startup)
langgraph_build_duration_sum / langgraph_build_duration_count

# Node success/failure rate
rate(langgraph_step_total{status="success"}[5m])
rate(langgraph_step_total{status="failure"}[5m])

# Execution duration p95
histogram_quantile(0.95, rate(langgraph_execution_duration_bucket[5m]))

# Retry rate per node
rate(langgraph_step_retries_total[5m])
```

### Expected Values After One Successful Request

For a single request that triggers `solve_steps` (e.g., "Solve step by step: (3 + 5) * 2 - 4 / 2"):

**KPI 1 — `langgraph_build_duration`**

```
~0.002s (2 milliseconds)
```
This fires once at module load when the StateGraph is compiled, not per request. Shows in Prometheus only once when the server starts.

**KPI 2 — `langgraph_step_total`**

```
{node="parse_node", status="success"} = 1
{node="evaluate_node", status="success"} = 1
{node="format_node", status="success"} = 1
```
All three nodes execute in order (parse → evaluate → format) and succeed. Each increments its own counter.

**KPI 3 — `langgraph_execution_duration`**

```
~0.005s (5 milliseconds)
```
Total time for the full graph run (all 3 nodes). Typically very fast for simple math expressions.

**KPI 4 — `langgraph_step_retries_total`**

```
no data
```
No retries occurred — all nodes succeeded on first attempt. This metric only appears if a node fails and is retried via `run_node_with_retry()`.

---

## MCP Tool Server KPIs

Implemented in: `mcp_tool_instrumented.py`
Metrics served on: port 8001 (add_sub_server), port 8002 (mul_div_server)

### Metrics

| KPI | Metric | Type | Labels |
|---|---|---|---|
| Tool invocation success/failure rate | `mcp_tool_invocations_total` | Counter | `tool`, `tool_server`, `status` |
| Response latency per tool | `mcp_tool_duration` | Histogram | `tool`, `tool_server` |
| Tool timeout count | `mcp_tool_timeouts_total` | Counter | `tool`, `tool_server` |

### Status Label Values

| Value | When set |
|---|---|
| `success` | Tool returned a result normally |
| `error` | Tool raised an exception (not timeout) |
| `timeout` | Thread did not complete within `timeout_s` |

### Implementation Details

- `@instrumented_tool(tool_name, server_name, timeout_s=10.0)` decorator applied to `add`, `subtract`, `solve_steps`
- Decorator runs the tool in a daemon thread and joins with `timeout_s`; if the thread is still alive, increments `mcp_tool_timeouts_total` and raises `TimeoutError`
- `mcp_tool_invocations_total` always fires in the `finally` block regardless of outcome
- `mcp_tool_duration` records wall-clock elapsed time in the `finally` block regardless of outcome

### Grafana Queries

```promql
# Invocation rate by tool and status
rate(mcp_tool_invocations_total[5m])

# Success vs error rate
rate(mcp_tool_invocations_total{status="success"}[5m])
rate(mcp_tool_invocations_total{status="error"}[5m])

# Latency p50/p95 per tool
histogram_quantile(0.50, rate(mcp_tool_duration_bucket[5m]))
histogram_quantile(0.95, rate(mcp_tool_duration_bucket[5m]))

# Timeout rate
rate(mcp_tool_timeouts_total[5m])
```

### Expected Values After One Successful Request

For a single request that hits both servers (e.g., "What is 100 - 33?"):

**KPI 1 — `mcp_tool_invocations_total`**

```
{tool="subtract", tool_server="add_sub_server", status="success"} = 1
```
One invocation of the `subtract` tool, which succeeded. If the request used `solve_steps` instead, you'd see:
```
{tool="solve_steps", tool_server="mul_div_server", status="success"} = 1
```

**KPI 2 — `mcp_tool_duration`**

```
~0.001s to 0.005s (1-5 milliseconds)
```
Latency histogram for the tool call, measured wall-clock time inside the `@instrumented_tool` decorator (includes thread spawn overhead and the actual computation). Run multiple times to populate histogram buckets.

**KPI 3 — `mcp_tool_timeouts_total`**

```
no data
```
No timeouts occurred — all tools completed within the 10-second timeout window. This metric only appears after an increment (i.e., when a tool call times out).

---

## Logs in Loki

All application logs are automatically shipped to Loki with trace/span context injected.

### What Gets Logged

**From `agent_auto_multiple.py`:**
```
[Handoff] AddSubAgent: idle->running, reason='...'
[Transition] AddSubAgent: running->completed
[Sync] Status synced to API
```

**From `mcp_tool_instrumented.py`:**
```
add(a, b) = result
solve_steps('...') completed in 0.123s
[LangGraph] Parse: '...' -> N tokens
[LangGraph] Evaluate: '...' = result
[TraceCtx] traceparent=... -> linked
```

### How to View Logs in Grafana

1. Go to **Explore** (left sidebar)
2. Select **Loki** from the data source dropdown
3. Use LogQL queries:

```logql
# All logs from the agent service
{service="multi-agent-calculator"}

# Logs from a specific trace (copy Trace ID from Tempo)
{service="multi-agent-calculator"} | json trace_id="6b819b37a6c15cbc..."

# Only errors
{service="multi-agent-calculator"} | level="error"

# Handoff events
{service="multi-agent-calculator"} | "Handoff"
```

### Linking Logs to Traces

Every log record includes `otelTraceID` and `otelSpanID` injected by `LoggingInstrumentor`.
When you click a log line in Loki, the details panel shows the trace ID — click it to jump directly to that trace in Tempo.
Logs and traces are linked by both trace ID and span ID for full observability.

---

## Prometheus Scrape Config

```yaml
- job_name: calculator-agent
  static_configs:
    - targets: ["host.docker.internal:8000"]   # orchestrator metrics

- job_name: mcp-add-sub-server
  static_configs:
    - targets: ["host.docker.internal:8001"]   # add/subtract tool metrics

- job_name: mcp-mul-div-server
  static_configs:
    - targets: ["host.docker.internal:8002"]   # solve_steps + LangGraph metrics
```
