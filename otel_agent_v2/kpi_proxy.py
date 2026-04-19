"""KPI proxy — thin FastAPI layer over the Prometheus HTTP API.

Exposes the 11 predefined KPIs (4 DW Orchestrator + 4 LangGraph worker runner
+ 3 MCP tool server) as clean JSON endpoints, plus a Grafana-style passthrough
for arbitrary PromQL.

Run
---
    uvicorn kpi_proxy:app --reload --port 8900

Env
---
    PROM_URL   base URL of Prometheus (default: http://localhost:9090)

Predefined KPI endpoints
------------------------
    GET /kpi                          list all 11 KPIs with metadata
    GET /kpi?area=orchestrator        filter by area (orchestrator|langgraph|mcp)
    GET /kpi/all                      fetch every KPI in parallel (one round-trip)
    GET /kpi/all?area=langgraph       batch fetch a single area
    GET /kpi/{name}                   instant value for one KPI
    GET /kpi/{name}/range?minutes=60&step=30s   time series for one KPI

KPI names are namespaced: `orchestrator.*`, `langgraph.*`, `mcp.*`.

Grafana-style passthrough (arbitrary PromQL)
--------------------------------------------
    GET /query?q=<PromQL>                       instant query
    GET /query_range?q=<PromQL>&minutes=60&step=30s   range query

Examples
--------
    # Instant query
    curl -G http://localhost:8900/query \\
      --data-urlencode 'q=sum(wd_otel_workers_active)'

    # Range query (time series)
    curl -G http://localhost:8900/query_range \\
      --data-urlencode 'q=rate(wd_otel_tool_invocations_total[5m])' \\
      -d minutes=60 -d step=30s

    # Batch all predefined KPIs (dashboard poll)
    curl http://localhost:8900/kpi/all

Security
--------
`/query` and `/query_range` are open passthroughs — anyone who can reach them
can run arbitrary PromQL and read every metric in Prometheus. Safe for local
or internal networks; put auth in front of it before exposing publicly.
"""
from __future__ import annotations

import os
import time
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

PROM_URL = os.getenv("PROM_URL", "http://localhost:9090").rstrip("/")

QUERIES: dict[str, dict[str, str]] = {
    # ── DW Orchestrator (4) ──────────────────────────────────────────────
    "orchestrator.active_workers": {
        "area": "orchestrator",
        "title": "Concurrent active workers",
        "query": "sum by (worker_type) (wd_otel_workers_active)",
    },
    "orchestrator.state_transitions_rate": {
        "area": "orchestrator",
        "title": "State transitions /min by worker→to",
        "query": "sum by (worker_type, from_state, to_state) "
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

app = FastAPI(title="DW Orchestrator KPI Proxy", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

_client = httpx.AsyncClient(timeout=10.0)


async def _prom_instant(promql: str) -> list[dict[str, Any]]:
    r = await _client.get(
        f"{PROM_URL}/api/v1/query", params={"query": promql}
    )
    if r.status_code != 200:
        raise HTTPException(502, f"prometheus {r.status_code}: {r.text}")
    body = r.json()
    if body.get("status") != "success":
        raise HTTPException(502, f"prometheus error: {body}")
    return body["data"]["result"]


async def _prom_range(
    promql: str, start: float, end: float, step: str
) -> list[dict[str, Any]]:
    r = await _client.get(
        f"{PROM_URL}/api/v1/query_range",
        params={"query": promql, "start": start, "end": end, "step": step},
    )
    if r.status_code != 200:
        raise HTTPException(502, f"prometheus {r.status_code}: {r.text}")
    body = r.json()
    if body.get("status") != "success":
        raise HTTPException(502, f"prometheus error: {body}")
    return body["data"]["result"]


import asyncio


@app.get("/kpi")
async def list_kpis(area: str | None = None) -> dict[str, Any]:
    if area:
        return {k: v for k, v in QUERIES.items() if v["area"] == area}
    return QUERIES


@app.get("/kpi/all")
async def get_all(area: str | None = None) -> dict[str, Any]:
    names = [k for k, v in QUERIES.items() if not area or v["area"] == area]
    results = await asyncio.gather(
        *(_prom_instant(QUERIES[n]["query"]) for n in names),
        return_exceptions=True,
    )
    out: dict[str, Any] = {}
    for n, r in zip(names, results):
        meta = QUERIES[n]
        if isinstance(r, Exception):
            out[n] = {**meta, "error": str(r)}
        else:
            out[n] = {**meta, "result": r}
    return out


@app.get("/kpi/{name}")
async def get_kpi(name: str) -> dict[str, Any]:
    if name not in QUERIES:
        raise HTTPException(404, f"unknown kpi '{name}'")
    meta = QUERIES[name]
    result = await _prom_instant(meta["query"])
    return {"name": name, **meta, "result": result}


@app.get("/kpi/{name}/range")
async def get_kpi_range(
    name: str,
    minutes: int = Query(60, ge=1, le=1440),
    step: str = Query("30s"),
) -> dict[str, Any]:
    if name not in QUERIES:
        raise HTTPException(404, f"unknown kpi '{name}'")
    meta = QUERIES[name]
    end = time.time()
    start = end - minutes * 60
    result = await _prom_range(meta["query"], start, end, step)
    return {
        "name": name,
        **meta,
        "start": start,
        "end": end,
        "step": step,
        "result": result,
    }


@app.get("/query")
async def query(q: str = Query(..., description="PromQL expression")) -> dict[str, Any]:
    """Instant query — Grafana-style passthrough."""
    return {"query": q, "result": await _prom_instant(q)}


@app.get("/query_range")
async def query_range(
    q: str = Query(..., description="PromQL expression"),
    minutes: int = Query(60, ge=1, le=1440),
    step: str = Query("30s"),
) -> dict[str, Any]:
    """Range query — Grafana-style passthrough."""
    end = time.time()
    start = end - minutes * 60
    return {
        "query": q,
        "start": start,
        "end": end,
        "step": step,
        "result": await _prom_range(q, start, end, step),
    }


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    try:
        r = await _client.get(f"{PROM_URL}/-/ready")
        return {"status": "ok" if r.status_code == 200 else "degraded"}
    except Exception as e:
        return {"status": "down", "error": str(e)}


# ──  Entry point ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "kpi_proxy:app",
        host=os.getenv("KPI_HOST", "127.0.0.1"),
        port=int(os.getenv("KPI_PORT", "8900")),
        reload=False,
    )
