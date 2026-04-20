# Task 8 — End-to-End Smoke Test

Run this after the automated implementation (Tasks 1–7) to verify all 11 KPIs flow end-to-end. You need 4 terminals, your `API_KEY`, and a running observability stack (Tempo / Loki / Prometheus).

## 1. Install dependencies (one-time)

From repo root:

```bash
pip install -e wd-otel-core wd-otel-mcp wd-otel-orchestrator
pip install -r otel_agent_v2/requirements.txt
```

## 2. Bring up the observability stack

Ensure these services are reachable:

| Service | Address | Purpose |
|---|---|---|
| Tempo | `localhost:4317` (OTLP gRPC) | Traces sink |
| Loki | `localhost:3100` (HTTP) | Logs sink |
| Prometheus | scraping `:8000`, `:8001`, `:8002` | Metrics storage |

The `Grafana_stackv1/` directory in this repo has a `docker compose` that serves this stack. If you're running it locally already, skip this step.

## 3. Start the three services (3 terminals)

All commands run from the **repo root** (not from inside `otel_agent_v2/`).

**Terminal 1 — add/subtract MCP server:**
```bash
python otel_agent_v2/mcp_server.py add_sub
```
Expect `[wd-otel] SDK initialised — service=otel-agent-v2-mcp-add-sub env=local` plus the FastMCP banner on port 8081. Prometheus metrics on `:8001`.

**Terminal 2 — multi-step solver MCP server:**
```bash
python otel_agent_v2/mcp_server.py mul_div
```
Expect service `otel-agent-v2-mcp-mul-div`, FastMCP on port 8082, metrics on `:8002`.

**Terminal 3 — FastAPI:**
```bash
API_KEY=<your-key> uvicorn otel_agent_v2.api:app --host 0.0.0.0 --port 8080
```
Expect `service=otel-agent-v2-orchestrator` + `MCP servers connected and tool lists cached`. Metrics on `:8000`.

> If you're using a Bedrock-proxy instead of Groq, also set `LLM_BASE_URL` and `LLM_MODEL` — see `README.md` § Provider notes.

## 4. Fire both agent paths (Terminal 4)

```bash
# Simple path → AddSubAgent → add_sub_server
curl -X POST http://localhost:8080/run \
  -H 'Content-Type: application/json' \
  -d '{"question":"What is 100 - 37?"}'

# Complex path → SolverAgent → mul_div_server → LangGraph
curl -X POST http://localhost:8080/run \
  -H 'Content-Type: application/json' \
  -d '{"question":"What is (3+5)*2 - 4/2?"}'
```

Both should return `{"answer": "..."}` (no HTTP error). The second exercises the full LangGraph pipeline and records `langgraph_*` metrics.

## 5. Verify metric labels match the kpi_proxy queries

This is the one real unknown — Prometheus exports whatever label names `wd-otel` actually emits, which must match the `sum by (...)` clauses in `kpi_proxy.py`.

```bash
curl -s http://localhost:8000/metrics | grep -E '^wd_otel_(workers|state|orchestration|sync)'
curl -s http://localhost:8001/metrics | grep -E '^wd_otel_tool'
curl -s http://localhost:8002/metrics | grep -E '^(wd_otel_tool|langgraph)'
```

**Expected labels** (what `kpi_proxy.py` queries):

| Metric | Expected labels |
|---|---|
| `wd_otel_workers_active` | `worker_type` |
| `wd_otel_state_transitions_total` | `worker_type`, `from_state`, `to_state` |
| `wd_otel_orchestration_errors_total` | `worker_type`, `error_type` |
| `wd_otel_sync_failures_total` | `worker_type`, `failure_type` |
| `wd_otel_tool_invocations_total` | `tool`, `server`, `status` |
| `wd_otel_tool_duration_seconds_bucket` | `le`, `tool`, `server` |
| `wd_otel_tool_timeouts_total` | `tool`, `server` |
| `langgraph_step_total` | `node`, `status` |
| `langgraph_step_retries_total` | `node` (always 0 — see note in mcp_server.py) |
| `langgraph_build_duration_seconds_*` | `worker_type` |
| `langgraph_execution_duration_seconds_bucket` | `le`, `worker_type` |

**If any metric uses different label keys** (e.g. `worker` instead of `worker_type`), edit `otel_agent_v2/kpi_proxy.py` `QUERIES` dict to match the real labels, then:

```bash
git add otel_agent_v2/kpi_proxy.py
git commit -m "fix(otel_agent_v2): align kpi_proxy labels with real metric output"
```

## 6. Verify all 11 KPIs return data (Terminal 4)

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

**Pass criteria:** every KPI returns an HTTP 200 with a `result` array and no `error` field.

**Empty arrays are OK** for:
- `mcp.timeouts_rate` — no tool timed out (tools are fast)
- `langgraph.step_retries_rate` — retry logic was dropped for clarity in this demo; metric is declared but never incremented (see `mcp_server.py:60` note)

All other KPIs should return non-empty `result` arrays after you've fired at least one request through each agent path in step 4.

## 7. Spot-check a trace in Tempo

Open Grafana → Explore → Tempo, find a recent trace, and confirm the span tree has this shape:

```
orchestrator.worker.lifecycle
└── multi-agent-run
    ├── runner.run
    │   └── OrchestratorAgent                    ← auto by OpenAIAgentsInstrumentor
    │       ├── generation
    │       ├── orchestrator.transition          ← KPI: idle→running
    │       ├── handoff → AddSubAgent | SolverAgent
    │       │   └── AddSubAgent | SolverAgent
    │       │       ├── generation
    │       │       └── add_operation | solve_steps_operation    ← MCP tool call
    │       │           └── (same trace_id in MCP server) ✅
    │       │               ├── langgraph_parse_node
    │       │               ├── langgraph_evaluate_node
    │       │               └── langgraph_format_node
    ├── orchestrator.transition                  ← KPI: running→completed
    └── orchestrator.sync                        ← KPI: status sync
```

If the MCP-server spans are detached from the parent trace (different `trace_id`), the traceparent header isn't propagating — check that `wd-otel-orchestrator` httpx monkey-patch is running and that your stack's OTLP endpoint is reachable.

## 8. Known caveats to expect during the test

- **Concurrent requests** will cross-contaminate `traceparent` headers due to the `_mcp_trace_context` module-variable race (see `README.md` § Known limitations and `wd-otel-orchestrator/wd_otel_orchestrator/base.py`). Fire requests sequentially to avoid confusion.
- **`langgraph.step_retries_rate` is always zero** — retry logic was removed for clarity; the metric is declared to keep the 4-metric LangGraph contract.
- **Loki warnings in logs are benign** if you don't have Loki running — `wd_otel.init()` logs a warning and continues.
- **Prometheus port bind failures on startup** happen if another process is holding `:8000`/`:8001`/`:8002`. In `env: "local"` the init raises; switch to `WD_OTEL_ENV=production` to warn-and-continue instead, or free the port.

## Reporting back

If something unexpected shows up (different labels, missing KPI, trace detached, etc.), capture:
- Which step failed (1–7)
- Exact command + output
- Which metric/KPI is affected

The most likely adjustment is step 5's label alignment — `kpi_proxy.py` is a thin config file, easy to edit and re-commit.
