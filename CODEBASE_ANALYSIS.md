# OTel Multi-Agent Calculator — Codebase Analysis

> Generated: 2026-04-17

---

## Table of Contents

1. [Project Overview](#project-overview)
2. [Directory Structure](#directory-structure)
3. [Architecture](#architecture)
4. [Python Backend — `otel_agent/`](#python-backend--otel_agent)
5. [Next.js Dashboard — `otel-monitor/`](#nextjs-dashboard--otel-monitor)
6. [Kubernetes Stack — `Grafana_stackv1/`](#kubernetes-stack--grafana_stackv1)
7. [11 KPIs](#11-kpis)
8. [Ports & Services](#ports--services)
9. [Technology Stack](#technology-stack)
10. [Key Technical Decisions](#key-technical-decisions)
11. [Running the System](#running-the-system)

---

## Project Overview

An **OpenTelemetry-instrumented multi-agent system** that demonstrates full observability for LLM agents with MCP tool servers. The system consists of:

- A Python multi-agent orchestrator (OpenAI Agents SDK) with specialist agents for math operations
- Two MCP tool servers (add/subtract, multiply/divide) with LangGraph integration
- A Kubernetes-deployable Grafana LGTM stack (Loki, Grafana, Tempo, Mimir/Prometheus)
- A Next.js 14 observability dashboard with 6 monitoring panels
- A KPI proxy API for clean PromQL passthrough

**Total codebase:** ~2,830 lines (Python + TypeScript)

---

## Directory Structure

```
otel_agentv1/
├── otel_agent/                        # Python backend
│   ├── agent.py                       # Single agent, manual OTel spans
│   ├── agent_auto.py                  # Single agent, auto-instrumentation
│   ├── agent_auto_multiple.py         # Multi-agent orchestrator + specialists
│   ├── agent_api.py                   # FastAPI HTTP wrapper (port 8080)
│   ├── otel_setup.py                  # OTel bootstrap: traces/metrics/logs
│   ├── mcp_tool_instrumented.py       # MCP servers + LangGraph + Prometheus
│   ├── kpi_proxy.py                   # PromQL passthrough API (port 8900)
│   ├── requirements.txt               # Python dependencies
│   ├── TRACING_GUIDE.md               # 500+ line distributed tracing guide
│   └── docs/
│       ├── run.md                     # Running instructions for all 11 KPIs
│       ├── progress.md                # KPI implementation status + Grafana queries
│       ├── kpi_proxy.md               # KPI proxy API docs
│       ├── Layer3_Implementation_Plan.md
│       └── Layer4_Implementation_Plan.md
│
├── otel-monitor/                      # Next.js 14 dashboard
│   ├── app/
│   │   ├── layout.tsx                 # Root layout + TelemetryProvider
│   │   ├── page.tsx                   # Main page, 6-tab routing
│   │   ├── globals.css                # Base styles + animations
│   │   └── api/traces/route.ts        # Fetch traces from Grafana Tempo
│   ├── components/
│   │   ├── TopBar.tsx                 # Header with live KPI badges
│   │   ├── TabBar.tsx                 # Tab navigation + alert badge
│   │   ├── ui/primitives.tsx          # Reusable UI (Badge, Card, Button, etc.)
│   │   ├── charts/
│   │   │   ├── LatencyChart.tsx       # Chart.js latency histogram
│   │   │   └── McpInvocationChart.tsx # Chart.js MCP tool invocation trends
│   │   └── panels/
│   │       ├── OverviewPanel.tsx      # KPI dashboard + histogram + fault injection
│   │       ├── TracesPanel.tsx        # Trace list with drill-down
│   │       ├── TimelinePanel.tsx      # SVG waterfall timeline + span inspector
│   │       ├── McpPanel.tsx           # MCP tool stats + invocation trends
│   │       ├── LogsPanel.tsx          # Log stream with filter/search/pause
│   │       └── AlertsPanel.tsx        # SLO alerts + threshold controls
│   ├── lib/
│   │   ├── telemetry.ts              # Trace/span generation + KPI calculation
│   │   ├── tempo-mapper.ts           # OTLP JSON → dashboard types mapping
│   │   └── store.tsx                 # React Context + useReducer state
│   ├── types/
│   │   └── telemetry.ts              # TypeScript interfaces for OTel types
│   ├── package.json                   # Node.js dependencies
│   ├── tsconfig.json                  # TypeScript config
│   ├── tailwind.config.js             # Tailwind CSS theme (dark mode)
│   ├── next.config.js                 # Next.js config
│   └── postcss.config.js             # PostCSS config
│
└── Grafana_stackv1/                   # Kubernetes Helm deployment
    ├── run.md                         # Helm installation guide
    ├── prometheus-values.yaml         # Prometheus + AlertManager config
    ├── alloy-values.yaml              # Grafana Alloy OTLP receiver
    ├── grafana-values.yaml            # Grafana UI + datasources
    ├── loki-values.yaml               # Loki log aggregation
    └── tempo-values.yaml              # Tempo trace storage
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                     SIGNAL GENERATION LAYER (Python)                │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  agent_auto_multiple.py  ─── Orchestrator Agent                     │
│    ├── init_otel("multi-agent-calculator")                          │
│    ├── OpenAIAgentsInstrumentor()   (auto LLM/tool capture)        │
│    ├── httpx monkey-patch           (traceparent injection)         │
│    │                                                                │
│    ├── math_agent (specialist)  ──→  MCP Client (HTTP)              │
│    ├── triage_agent (router)                │                       │
│    └── history_agent (memory)               │                       │
│                                             │                       │
│  mcp_tool_instrumented.py ──────────────────┘                       │
│    ├── add_sub_server (port 8081)                                   │
│    │   └── add, subtract tools                                      │
│    └── mul_div_server (port 8082)                                   │
│        └── solve_steps tool + LangGraph state machine               │
│                                                                     │
│  agent_api.py ─── FastAPI wrapper (port 8080)                       │
│    └── POST /run, GET /metrics                                      │
│                                                                     │
└─────────────────┬──────────────────┬───────────────────┬────────────┘
                  │ Traces (OTLP)    │ Metrics            │ Logs
                  │ gRPC :4317       │ Prometheus scrape   │ HTTP :3100
                  ▼                  ▼                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                  SIGNAL ROUTING LAYER (Kubernetes)                   │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Grafana Alloy (:4317/:4318)                                        │
│    └── OTLP receiver → routes to Tempo / Prometheus / Loki          │
│                                                                     │
│  Prometheus (:9090) ── scrapes /metrics on ports 8000, 8001, 8002   │
│  Loki (:3100) ──────── log aggregation backend                      │
│  Tempo ─────────────── distributed trace storage                    │
│                                                                     │
└─────────────────────────────┬───────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    VISUALIZATION LAYER                               │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Grafana (:3000)                                                    │
│    └── Pre-provisioned datasources + dashboards                     │
│                                                                     │
│  otel-monitor (Next.js :3000)                                       │
│    └── 6-tab dashboard (Overview, Traces, Timeline, MCP, Logs,      │
│        Alerts) — can use real Tempo data or simulated traces        │
│                                                                     │
│  kpi_proxy.py (:8900)                                               │
│    └── /kpi, /kpi/all, /query_range — clean JSON over PromQL       │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Python Backend — `otel_agent/`

### `otel_setup.py` — OTel Bootstrap

Initializes all three signal types:

| Signal | Exporter | Destination |
|--------|----------|-------------|
| **Traces** | OTLP gRPC | Grafana Alloy (:4317) or Jaeger |
| **Metrics** | Prometheus + OTLP | `/metrics` endpoint + Alloy |
| **Logs** | Python logging + Loki | Loki (:3100) with trace correlation |

Key features:
- `FilteringSpanExporter` drops CLIENT spans and FastMCP noise
- `LoggingInstrumentor` injects `otelTraceID` / `otelSpanID` into log records
- `PrometheusMetricReader` exposes metrics for scraping

### `agent_auto_multiple.py` — Multi-Agent Orchestrator

Three specialist agents with handoff patterns:

| Agent | Role | Tools |
|-------|------|-------|
| `triage_agent` | Routes questions to specialists | Handoffs only |
| `math_agent` | Calculator operations via MCP | MCP tools (add, subtract, multiply, divide, solve_steps) |
| `history_agent` | Conversation memory | In-memory storage |

Instrumentation:
- `OpenAIAgentsInstrumentor` auto-captures all LLM calls and tool invocations
- Custom `RunHooks` track lifecycle events (agent start/end, tool start/end, handoffs)
- Orchestrator metrics: active workers, state transitions, errors, sync failures

### `mcp_tool_instrumented.py` — MCP Tool Servers

Two FastMCP servers with full observability:

**add_sub_server (port 8081):**
- `add(a, b)` — addition with OTel span
- `subtract(a, b)` — subtraction with OTel span

**mul_div_server (port 8082):**
- `multiply(a, b)` — multiplication with OTel span
- `divide(a, b)` — division with error handling (divide-by-zero)
- `solve_steps(expression)` — LangGraph state machine for multi-step evaluation

Each tool:
- Extracts `traceparent` from MCP metadata for distributed trace linking
- Records `mcp_tool_invocations_total` counter
- Records `mcp_tool_duration` histogram
- Records `mcp_tool_timeouts_total` on failures

### `mcp_tool_instrumented.py` — LangGraph Integration

The `solve_steps` tool uses a LangGraph `StateGraph`:

```
parse_node → compute_node → format_node → END
```

Each node records:
- `langgraph_step_total{status=success|failure}` counter
- `langgraph_execution_duration` histogram
- `langgraph_step_retries_total` counter
- Individual OTel spans linked to parent trace

### `agent_api.py` — FastAPI Wrapper

- `POST /run` — accepts `{"query": "..."}`, runs multi-agent orchestrator
- `GET /metrics` — Prometheus metrics endpoint
- CORS enabled for dashboard access

### `kpi_proxy.py` — KPI Proxy

Clean JSON API over Prometheus PromQL:

| Endpoint | Purpose |
|----------|---------|
| `GET /kpi?name=<metric>` | Single KPI value |
| `GET /kpi/all` | All 11 KPIs in one response |
| `GET /query_range` | Raw PromQL passthrough |

---

## Next.js Dashboard — `otel-monitor/`

### State Management (`lib/store.tsx`)

React Context + `useReducer` pattern:
- `TelemetryProvider` wraps the app
- Actions: `ADD_TRACE`, `ADD_LOG`, `ADD_ALERT`, `SET_KPI`, `TOGGLE_SIMULATION`
- Auto-generates simulated traces when no real backend connected

### Tab Panels

| Tab | Component | Features |
|-----|-----------|----------|
| **Overview** | `OverviewPanel.tsx` | 11 KPI cards, latency histogram, fault injection buttons, auto-refresh |
| **Traces** | `TracesPanel.tsx` | Trace list, status badges, attribute drill-down, search/filter |
| **Timeline** | `TimelinePanel.tsx` | SVG waterfall visualization, span inspector sidebar, zoom controls |
| **MCP** | `McpPanel.tsx` | Per-tool stat cards, invocation trend chart (Chart.js), error rates |
| **Logs** | `LogsPanel.tsx` | Real-time log stream, severity filter, text search, pause/resume |
| **Alerts** | `AlertsPanel.tsx` | SLO violation alerts, threshold editor, acknowledge/dismiss |

### Data Flow

```
Real mode:  Grafana Tempo API → /api/traces/route.ts → tempo-mapper.ts → store
Sim mode:   telemetry.ts (generators) → store → panels
```

`tempo-mapper.ts` converts OTLP JSON responses from Tempo into the dashboard's internal `Trace`/`Span` types.

### Charts

- **LatencyChart.tsx** — Chart.js bar chart showing P50/P95/P99 latency distribution
- **McpInvocationChart.tsx** — Chart.js multi-line chart showing tool invocation rates over time

---

## Kubernetes Stack — `Grafana_stackv1/`

Deployed via Helm charts on Kubernetes:

| Component | Chart | Key Config |
|-----------|-------|------------|
| **Prometheus** | `kube-prometheus-stack` | Scrapes 3 targets (8000, 8001, 8002), 15s interval, AlertManager rules |
| **Alloy** | `grafana/alloy` | OTLP gRPC/HTTP receiver, routes traces→Tempo, metrics→Prometheus, logs→Loki |
| **Grafana** | `grafana/grafana` | Pre-provisioned datasources (Prometheus, Loki, Tempo, AlertManager) |
| **Loki** | `grafana/loki` | SingleBinary mode, filesystem storage |
| **Tempo** | `grafana/tempo` | Trace storage with search enabled |

### Installation

```bash
helm repo add grafana https://grafana.github.io/helm-charts
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts

helm install prometheus prometheus-community/kube-prometheus-stack -f prometheus-values.yaml
helm install alloy grafana/alloy -f alloy-values.yaml
helm install loki grafana/loki -f loki-values.yaml
helm install tempo grafana/tempo -f tempo-values.yaml
helm install grafana grafana/grafana -f grafana-values.yaml
```

---

## 11 KPIs

### Orchestrator KPIs (4)

| # | KPI | Metric | Type |
|---|-----|--------|------|
| 1 | Active Workers | `orchestrator_active_workers` | UpDownCounter |
| 2 | State Transitions | `orchestrator_state_transitions_total` | Counter |
| 3 | Orchestrator Errors | `orchestrator_errors_total` | Counter |
| 4 | Sync Failures | `orchestrator_sync_failures_total` | Counter |

### LangGraph KPIs (4)

| # | KPI | Metric | Type |
|---|-----|--------|------|
| 5 | Build Duration | `langgraph_build_duration` | Histogram |
| 6 | Step Success/Failure | `langgraph_step_total` | Counter (labels: status, node) |
| 7 | Execution Duration | `langgraph_execution_duration` | Histogram |
| 8 | Step Retries | `langgraph_step_retries_total` | Counter |

### MCP Tool KPIs (3)

| # | KPI | Metric | Type |
|---|-----|--------|------|
| 9 | Tool Invocations | `mcp_tool_invocations_total` | Counter (labels: tool, server, status) |
| 10 | Tool Latency | `mcp_tool_duration` | Histogram (labels: tool, server) |
| 11 | Tool Timeouts | `mcp_tool_timeouts_total` | Counter (labels: tool, server) |

### Example Grafana/PromQL Queries

```promql
# Active workers
orchestrator_active_workers

# MCP tool invocation rate (per minute)
rate(mcp_tool_invocations_total[1m])

# P95 MCP tool latency
histogram_quantile(0.95, rate(mcp_tool_duration_bucket[5m]))

# LangGraph step error rate
rate(langgraph_step_total{status="failure"}[5m]) / rate(langgraph_step_total[5m])
```

---

## Ports & Services

| Port | Service | Protocol |
|------|---------|----------|
| 3000 | otel-monitor (Next.js) / Grafana | HTTP |
| 3100 | Loki | HTTP |
| 4317 | Grafana Alloy (OTLP gRPC) | gRPC |
| 4318 | Grafana Alloy (OTLP HTTP) | HTTP |
| 8000 | agent_api.py (Prometheus metrics) | HTTP |
| 8080 | agent_api.py (FastAPI) | HTTP |
| 8081 | MCP add_sub_server | HTTP (SSE) |
| 8082 | MCP mul_div_server | HTTP (SSE) |
| 8900 | kpi_proxy.py | HTTP |
| 9090 | Prometheus | HTTP |

---

## Technology Stack

### Backend
- **Python 3.10+**
- **OpenAI Agents SDK** (`openai-agents>=0.0.15`) — agent orchestration
- **OpenTelemetry** (`opentelemetry-api/sdk>=1.24.0`) — traces, metrics, logs
- **FastMCP** (`fastmcp>=2.0.0`) — MCP HTTP tool servers
- **LangGraph** — stateful computation graphs
- **FastAPI** — HTTP wrapper + Prometheus endpoint
- **openinference** — auto-instrumentation for OpenAI Agents

### Frontend
- **Next.js 14** (App Router)
- **React 18** + TypeScript
- **Tailwind CSS** (dark theme)
- **Chart.js** + react-chartjs-2

### Infrastructure
- **Kubernetes** (Helm)
- **Grafana Alloy** — OTLP receiver/router
- **Prometheus** — metrics storage + alerting
- **Loki** — log aggregation
- **Tempo** — trace storage
- **AlertManager** — alert routing

---

## Key Technical Decisions

### 1. MCP Context Propagation Fix

**Problem:** MCP client's httpx calls run in a background asyncio task created at connection time. `ContextVars` are copied at task creation, so they miss per-question OTel spans created later.

**Solution:** Module-level `_mcp_trace_context` variable + httpx `AsyncClient.send` monkey-patch that injects a fresh `traceparent` header before every MCP request.

### 2. Span Filtering

`FilteringSpanExporter` drops noisy spans:
- All `CLIENT` kind spans (httpx internal)
- FastMCP framework spans (`fastmcp.*`)
- SSE transport spans

This keeps traces clean and focused on application-level operations.

### 3. Dual-Mode Dashboard

The Next.js dashboard supports:
- **Real mode:** Fetches traces from Grafana Tempo via `/api/traces/route.ts`
- **Simulation mode:** Generates realistic synthetic traces via `lib/telemetry.ts`

This allows development/demo without a running Kubernetes cluster.

### 4. LangGraph State Machine

The `solve_steps` MCP tool uses LangGraph to evaluate multi-step math expressions:

```
parse_node → compute_node → format_node → END
```

Each node is individually instrumented with OTel spans and Prometheus metrics, giving visibility into sub-tool execution.

---

## Running the System

### Prerequisites

```bash
# Python backend
cd otel_agent
pip install -r requirements.txt

# Next.js dashboard
cd otel-monitor
npm install
```

### Start Order

```bash
# 1. MCP tool servers (two terminals)
python mcp_tool_instrumented.py add_sub    # port 8081
python mcp_tool_instrumented.py mul_div    # port 8082

# 2. Agent API
python agent_api.py                         # port 8080

# 3. KPI Proxy (optional)
uvicorn kpi_proxy:app --port 8900

# 4. Dashboard
cd otel-monitor && npm run dev              # port 3000
```

### Test a Query

```bash
curl -X POST http://localhost:8080/run \
  -H "Content-Type: application/json" \
  -d '{"query": "What is 15 + 27?"}'
```

### Kubernetes Stack (optional)

```bash
# See Grafana_stackv1/run.md for full Helm install commands
helm install prometheus prometheus-community/kube-prometheus-stack -f prometheus-values.yaml
# ... (alloy, loki, tempo, grafana)
```
