# otel_agent_v2 — design

**Date:** 2026-04-19
**Status:** Approved (pending user spec review)
**Owner:** Charikshith

## Context

`otel_agent/` instruments an OpenAI-Agents-SDK multi-agent calculator and its
MCP tool servers with OpenTelemetry traces and Prometheus metrics, emitting the
11 KPIs consumed by `kpi_proxy.py`. It was written before the WD-OTel SDK
packages existed and carries a lot of boilerplate:

- Custom `otel_setup.py` bootstrap (~60 lines duplicated in every entry point)
- A 40-line `@instrumented_tool` decorator reimplementing thread-based timeouts,
  context propagation, and metric recording
- Manual `active_workers` / `state_transitions` / `orchestration_errors` /
  `sync_failures` counter bookkeeping sprinkled through `agent_api.py` and
  `agent_auto_multiple.py`
- Handoff callbacks that duplicate state-transition logic

Three packages now cover the same ground:

- **`wd-otel-core`** — `wd_otel.init()` bootstrap, pre-registered instruments
  for all tool/session/state/error KPIs, span helpers
- **`wd-otel-mcp`** — `@traced_tool` decorator (auto W3C extraction, timeout
  handling, metrics)
- **`wd-otel-orchestrator`** — `TracedOrchestrator` base class (lifecycle
  spans, handoff wiring, session metrics, sync-failure tracking, httpx
  traceparent injection)

## Goal

Produce a working, runnable rewrite of the `otel_agent/` flow that uses the
three packages. The artefact is **working code Charikshith will upgrade** — not
an installable package. Its primary purpose is to serve as a reference for how
the packages compose in a real multi-agent + MCP flow.

## Non-goals

- Not a pip-installable package (no `pyproject.toml`, no `__init__.py` module
  structure)
- Not a test suite. Manual smoke tests only.
- Not touching `otel_agent/`. The rewrite lives in a sibling directory so both
  can be diffed side-by-side.
- Not adding helpers for the 4 LangGraph KPIs (`langgraph.build.duration`,
  `langgraph.step.total`, `langgraph.execution.duration`,
  `langgraph.step.retries`). Those remain custom inside `mcp_server.py`. A
  future `wd-otel-langgraph` or `wd-otel-worker` package is the right home.
- Not changing the LLM provider. `agent_auto_multiple.py` uses
  `openai-agents` + `AsyncOpenAI` routed to Groq; that setup is preserved
  verbatim. The same code works with any OpenAI-compatible proxy (e.g. AWS
  Bedrock) by changing only the `AsyncOpenAI(base_url=..., api_key=...)` line
  — the OTel instrumentation is provider-agnostic.

## File layout — `otel_agentv1/otel_agent_v2/`

```
otel_agent_v2/
├── README.md                     # how to run + file→concept mapping
├── requirements.txt
│
├── wd-otel-orchestrator.yaml     # service=orchestrator,  prometheus_port=8000
├── wd-otel-mcp-addsub.yaml       # service=mcp-add-sub,   prometheus_port=8001
├── wd-otel-mcp-muldiv.yaml       # service=mcp-mul-div,   prometheus_port=8002
│
├── mcp_server.py                 # MCP tools decorated with @traced_tool
├── orchestrator.py               # CalculatorOrchestrator(TracedOrchestrator) — PURE LOGIC
├── api.py                        # FastAPI app — POST /run → orchestrator.execute()
├── cli.py                        # asyncio smoke-test entry, no HTTP
└── kpi_proxy.py                  # copied unchanged from otel_agent/
```

**Separate YAMLs** are required because `wd_otel.init()` reads
`prometheus_port` from the YAML and binds an HTTP server on it. Each of the
three processes (API + 2 MCP servers) needs its own port, therefore its own
config file.

## What each file demonstrates

| File | `otel_agent/` equivalent | Changes |
|---|---|---|
| `mcp_server.py` | `mcp_tool_instrumented.py` (400 LOC) | Replace `@instrumented_tool` + `_get_parent_ctx` + thread plumbing with `@traced_tool(tool_name, server=...)`. LangGraph metrics kept verbatim with `# TODO: move to wd-otel helper` comments. |
| `orchestrator.py` | `agent_auto_multiple.py` orchestration chunk | Subclass `TracedOrchestrator`; set `name`, `agents`, `entry_agent`; override `sync_status` hook. Drop all manual `active_workers` / `state_transitions` / `orchestration_errors` / `sync_failures` counter code. |
| `api.py` | `agent_api.py` | Pure FastAPI wrapper: `from orchestrator import orchestrator` + one `POST /run` route. No OTel code, no agent definitions. |
| `cli.py` | CLI block at bottom of `agent_auto_multiple.py` | 15-line `asyncio.run(orchestrator.execute(q))` runner for smoke-testing without HTTP. |
| `kpi_proxy.py` | same | Byte-for-byte copy. Lives here so `otel_agent_v2/` is self-contained. |

## Startup contract

Every process entry point (`api.py`, `cli.py`, `mcp_server.py`) does exactly
two things before importing anything else that touches OTel:

1. `wd_otel.init("<its-yaml>")`
2. Import the orchestrator / tools module

Rules:

- `orchestrator.py` builds the agents and instantiates the orchestrator at
  module-import time. It **never** calls `wd_otel.init()` — that's the entry
  point's responsibility.
- `api.py` contains **zero** OTel imports or instrumentation code.
- `mcp_server.py` calls `wd_otel.init()` with the YAML selected by CLI arg
  (`python mcp_server.py add_sub` → `wd-otel-mcp-addsub.yaml`).

## End-to-end flow (unchanged from `otel_agent/`)

1. `POST /run` → `api.py` → `orchestrator.execute(question)`
2. `TracedOrchestrator.execute()` creates `orchestrator.worker.lifecycle` +
   `multi-agent-run` + `runner.run` spans and captures current OTel context
   into the module-level variable the httpx patch reads
3. OrchestratorAgent hands off → `TransitionTracker.record_handoff()` →
   `state_transitions++`, `active_workers++`, `orchestrator.transition` span
4. Specialist agent calls an MCP tool; httpx send is monkey-patched to inject
   `traceparent`
5. MCP server: `@traced_tool` extracts parent context from `ctx`, creates the
   tool span in the parent trace, runs the function in a context-copied thread
   with the configured timeout, emits `wd_otel.tool.{invocations,duration}`
   and `wd_otel.tool.timeouts` on timeout
6. On Runner completion: `record_completion()` fires
   (`state_transitions++`, `active_workers--`); `sync_status` hook runs inside
   `orchestrator.sync` span; on exception, `sync_failures++` automatically
7. Prometheus scrapes ports 8000/8001/8002; `kpi_proxy.py` on 8900 fronts
   them with the 11-KPI REST API

## KPI coverage after rewrite

| KPI family | Before (manual) | After |
|---|---|---|
| `orchestrator.active_workers` | `agent_auto_multiple.py:114` | `wd_otel.workers.active` (auto via `TransitionTracker`) |
| `orchestrator.state_transitions_rate` | `agent_auto_multiple.py:119` | `wd_otel.state.transitions` (auto) |
| `orchestrator.errors_total` | `agent_auto_multiple.py:124` | `wd_otel.orchestration.errors` (auto on handoff error) |
| `orchestrator.sync_failures_1h` | `agent_auto_multiple.py:129` | `wd_otel.sync.failures` (auto on `sync_status` exception) |
| `langgraph.build_duration_avg` | `mcp_tool_instrumented.py:46` | **kept custom** in `mcp_server.py` |
| `langgraph.step_rate` | `mcp_tool_instrumented.py:51` | **kept custom** |
| `langgraph.execution_duration_p95` | `mcp_tool_instrumented.py:56` | **kept custom** |
| `langgraph.step_retries_rate` | `mcp_tool_instrumented.py:61` | **kept custom** |
| `mcp.invocations_rate` | `mcp_tool_instrumented.py:68` | `wd_otel.tool.invocations` (auto via `@traced_tool`) |
| `mcp.duration_p95` | `mcp_tool_instrumented.py:73` | `wd_otel.tool.duration` (auto) |
| `mcp.timeouts_rate` | `mcp_tool_instrumented.py:78` | `wd_otel.tool.timeouts` (auto on `TimeoutError`) |

Metric names change from `orchestrator.*` / `mcp.tool.*` in the old code to
`wd_otel.*` in the new code. **`kpi_proxy.py` queries will need their
`QUERIES` dict updated** to match the new Prometheus metric names. This is
called out in the plan.

## Risks / open items to handle during implementation

1. **Metric-name migration for `kpi_proxy.py`** — after the rewrite, the 7
   auto-emitted metrics have `wd_otel_*` names instead of `orchestrator_*` /
   `mcp_tool_*`. `kpi_proxy.py` queries must be updated. Plan will include a
   diff.
2. **`langgraph.step.total` counter double-suffix** — the underlying OTel
   Prometheus exporter may append `_total` to a counter whose name already
   ends in `total`, yielding `langgraph_step_total_total` in Prometheus.
   Applies to existing code; unchanged by this rewrite but worth verifying
   during smoke test.
3. **OpenInference instrumentor** — `OpenAIAgentsInstrumentor().instrument()`
   is what produces the `generation` spans around LLM calls. It must be
   called after `wd_otel.init()` and before agent invocation. Goes in
   `orchestrator.py` at module top, after the import block.

## Out-of-scope follow-ups

- A future `wd-otel-langgraph` package covering the 4 LangGraph KPIs with
  `@traced_node` and `langgraph_build_span()` helpers.
- Env-var override for `prometheus_port` in `wd-otel-core` so a single YAML
  could serve multiple processes.
- `kpi_proxy.py` query migration script, if the rewrite ships before the
  existing Grafana dashboards are updated.
