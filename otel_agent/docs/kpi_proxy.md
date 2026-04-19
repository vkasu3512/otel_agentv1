# KPI Proxy

A thin FastAPI layer that sits in front of Prometheus and exposes the 11
predefined agent KPIs (plus an arbitrary PromQL passthrough) as clean JSON
endpoints a custom frontend can consume directly.

Implemented in: `otel_agent/kpi_proxy.py`

## Why it exists

Grafana is excellent for exploration, but when you want to build a **custom
UI** (status page, internal dashboard, embedded widget), you don't want the
frontend to:

- speak raw PromQL and parse Prometheus's nested result format
- worry about CORS against Prometheus
- hard-code metric names that may change

The proxy solves all three:

1. Predefined KPI endpoints return stable, named JSON contracts
   (`orchestrator.active_workers`, `langgraph.step_rate`, etc.)
2. CORS is enabled for browser clients.
3. A Grafana-style passthrough (`/query`, `/query_range`) is available for
   ad-hoc queries when the predefined set isn't enough.

## Architecture

```
┌─────────────┐        ┌─────────────┐        ┌──────────────┐
│  Custom UI  │  HTTP  │  kpi_proxy  │  HTTP  │  Prometheus  │
│  (browser)  │ ─────► │  FastAPI    │ ─────► │  HTTP API    │
└─────────────┘  JSON  │  :8900      │ PromQL │  :9090       │
                       └─────────────┘        └──────────────┘
```

No state, no database. One `httpx.AsyncClient` is held open for connection
reuse. Requests to `/kpi/all` fan out in parallel via `asyncio.gather` so a
full dashboard poll is a single round-trip from the frontend's perspective.

## Configuration

| Env var      | Default                  | Purpose                       |
|--------------|--------------------------|-------------------------------|
| `PROM_URL`   | `http://localhost:9090`  | Base URL of Prometheus        |
| `KPI_HOST`   | `127.0.0.1`              | Bind host (used by `__main__`)|
| `KPI_PORT`   | `8900`                   | Bind port (used by `__main__`)|

## Running

```bash
# Option 1 — run the module directly
python kpi_proxy.py

# Option 2 — run with uvicorn (adds --reload for dev)
uvicorn kpi_proxy:app --reload --port 8900
```

If Prometheus is in Kubernetes, port-forward it first:

```bash
kubectl -n monitoring port-forward svc/kube-prom-stack-kube-prome-prometheus 9090:9090
```

## The 11 KPIs

KPI names are namespaced by area: `orchestrator.*`, `langgraph.*`, `mcp.*`.
Each entry in the `QUERIES` dict carries `area`, `title`, and the PromQL
expression — the proxy returns all three along with the result so the
frontend can render tiles without hard-coding labels.

### DW Orchestrator (4)

| Name | Title | PromQL |
|---|---|---|
| `orchestrator.active_workers` | Concurrent active workers | `sum by (worker_type) (orchestrator_active_workers)` |
| `orchestrator.state_transitions_rate` | State transitions /min by from→to | `sum by (worker_type, from_state, to_state) (rate(orchestrator_state_transitions_total[5m])) * 60` |
| `orchestrator.errors_total` | Orchestration errors (cumulative) | `sum by (worker_type, error_type) (orchestrator_errors_total)` |
| `orchestrator.sync_failures_1h` | Status sync failures (last 1h) | `sum by (worker_type, failure_type) (increase(orchestrator_sync_failures_total[1h]))` |

### Worker Runner / LangGraph (4)

| Name | Title | PromQL |
|---|---|---|
| `langgraph.build_duration_avg` | Graph build duration (avg) | `sum(langgraph_build_duration_sum) / clamp_min(sum(langgraph_build_duration_count), 1)` |
| `langgraph.step_rate` | Step success/failure rate by node | `sum by (node, status) (rate(langgraph_step_total[5m]))` |
| `langgraph.execution_duration_p95` | Full graph execution p95 | `histogram_quantile(0.95, sum by (le) (rate(langgraph_execution_duration_bucket[5m])))` |
| `langgraph.step_retries_rate` | Node retries /min | `sum by (node) (rate(langgraph_step_retries_total[5m])) * 60` |

### MCP Tool Server (3)

| Name | Title | PromQL |
|---|---|---|
| `mcp.invocations_rate` | Tool invocation rate by status | `sum by (tool, tool_server, status) (rate(mcp_tool_invocations_total[5m]))` |
| `mcp.duration_p95` | Tool latency p95 | `histogram_quantile(0.95, sum by (le, tool, tool_server) (rate(mcp_tool_duration_bucket[5m])))` |
| `mcp.timeouts_rate` | Tool timeouts /min | `sum by (tool, tool_server) (rate(mcp_tool_timeouts_total[5m])) * 60` |

## Endpoints

### Predefined KPI endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/kpi` | List all 11 KPIs with metadata |
| `GET` | `/kpi?area=orchestrator` | Filter list by area (`orchestrator` \| `langgraph` \| `mcp`) |
| `GET` | `/kpi/all` | Fetch every KPI in parallel — **use for dashboard polls** |
| `GET` | `/kpi/all?area=langgraph` | Batch fetch a single area |
| `GET` | `/kpi/{name}` | Instant value for one KPI |
| `GET` | `/kpi/{name}/range?minutes=60&step=30s` | Time series for one KPI |

`/kpi/all` fans out with `asyncio.gather` and returns per-KPI errors inline
(as `{"error": "..."}`) instead of failing the whole batch.

### Grafana-style passthrough

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/query?q=<PromQL>` | Instant query — any PromQL expression |
| `GET` | `/query_range?q=<PromQL>&minutes=60&step=30s` | Range query — any PromQL expression |

Same contract as Grafana's Prometheus data source: the frontend sends raw
PromQL, the proxy forwards it and returns the Prometheus result verbatim.
Use this as the escape hatch when a view needs a query not in the
predefined set.

### Operational

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/healthz` | Probes Prometheus `/-/ready`; returns `ok`, `degraded`, or `down` |

## Example responses

### `GET /kpi/orchestrator.active_workers`

```json
{
  "name": "orchestrator.active_workers",
  "area": "orchestrator",
  "title": "Concurrent active workers",
  "query": "sum by (worker_type) (orchestrator_active_workers)",
  "result": [
    {
      "metric": {"worker_type": "AddSubAgent"},
      "value": [1776222801.515, "0"]
    }
  ]
}
```

### `GET /query?q=up`

```json
{
  "query": "up",
  "result": [
    {
      "metric": {"__name__": "up", "job": "otel-agent-api", ...},
      "value": [1776222801.515, "1"]
    }
  ]
}
```

## Example usage

```bash
# Health
curl http://127.0.0.1:8900/healthz

# List all KPIs (metadata only, no values)
curl http://127.0.0.1:8900/kpi

# Single instant KPI
curl http://127.0.0.1:8900/kpi/orchestrator.active_workers

# Time series for one KPI — last hour at 30s resolution
curl "http://127.0.0.1:8900/kpi/mcp.invocations_rate/range?minutes=60&step=30s"

# Dashboard poll — every KPI in one shot
curl http://127.0.0.1:8900/kpi/all

# Ad-hoc PromQL — how many orchestrator sessions in the last 2 days
curl -G http://127.0.0.1:8900/query \
  --data-urlencode 'q=count_over_time(orchestrator_state_transitions_total[2d])'
```

## Frontend integration notes

- **CORS is wide open** (`allow_origins=["*"]`) so browsers can call the
  proxy directly. Tighten this in production.
- **Result shape mirrors Prometheus** — `result[].metric` is the label set,
  `result[].value = [timestamp, "stringified_number"]`. Range queries use
  `result[].values = [[ts, "val"], ...]`. Parse `value[1]` with
  `parseFloat` in JS.
- **Empty `result: []`** means "no series matched" — typically no data yet
  for that metric, not an error. OpenTelemetry counters in particular only
  appear after their first increment.
- **Per-KPI failures in `/kpi/all`** surface as `{"error": "..."}` inside
  that KPI's entry; the rest of the batch still succeeds.

## Security

`/query` and `/query_range` are **unauthenticated passthroughs**. Anyone
who can reach the proxy can run arbitrary PromQL and read every metric in
Prometheus. This is fine for:

- local development
- trusted internal networks
- behind an existing auth proxy (oauth2-proxy, ingress auth)

Do **not** expose the proxy to the public internet without auth. Options
if you need to:

- Put it behind an ingress with basic auth / OIDC
- Drop `/query` and `/query_range` entirely and rely only on the
  predefined `/kpi/*` endpoints
- Add a FastAPI dependency that validates an API key header

## Relationship to the rest of the stack

```
agent_api.py / mcp servers  ──► OTel metrics ──► Prometheus
                                                     │
                                                     ├──► Grafana (exploration)
                                                     └──► kpi_proxy ──► Custom UI
```

The proxy is a **sibling** to Grafana, not a replacement. Both read from
the same Prometheus. Use Grafana for free-form investigation and alert
authoring; use the proxy when you want tight, stable JSON contracts for a
purpose-built frontend.
