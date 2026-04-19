# How to View All 11 KPIs

## Step 1 — Start All Services

**Terminal 1** — MCP add/subtract server:
```bash
cd otel_agent
"D:/Code/ENVS/ai/Scripts/python.exe" mcp_tool_instrumented.py add_sub
```

**Terminal 2** — MCP solver server:
```bash
cd otel_agent
"D:/Code/ENVS/ai/Scripts/python.exe" mcp_tool_instrumented.py mul_div
```

**Terminal 3** — FastAPI agent:
```bash
cd otel_agent
"D:/Code/ENVS/ai/Scripts/python.exe" agent_api.py
```
Input : 
```
    questions = [
         "What is 42 + 58?",                      # → AddSubAgent → add tool
        "What is 100 - 37?",                      # → AddSubAgent → subtract tool
         "Solve step by step: (3 + 5) * 2 - 4 / 2",  # → SolverAgent → solve_steps tool
    ]
```

**Terminal 4** — Grafana stack (if not already running):
```bash
cd grafana_stack
docker compose up -d
```

---

## Step 2 — Generate Data for All KPIs

Send one of each type to hit both agents:

```bash
# Hits AddSubAgent (add_sub_server port 8001)
curl -s -X POST http://localhost:8080/run -H "Content-Type: application/json" -d "{\"question\": \"What is 100 - 37?\"}"

# Hits SolverAgent (mul_div_server port 8002) + LangGraph
curl -s -X POST http://localhost:8080/run -H "Content-Type: application/json" -d "{\"question\": \"Solve step by step: (3 + 5) * 2 - 4 / 2\"}"
```

---

## Step 3 — Confirm Prometheus is Scraping All 3 Targets

Open `http://localhost:9090/targets` — all three must show **UP**:

| Job | Target | Metrics |
|---|---|---|
| `calculator-agent` | `host.docker.internal:8000` | Orchestrator KPIs |
| `mcp-add-sub-server` | `host.docker.internal:8001` | add/subtract tool KPIs |
| `mcp-mul-div-server` | `host.docker.internal:8002` | LangGraph + solve_steps KPIs |

---

## Step 4 — View KPIs in Grafana

Open `http://localhost:3000` → **Explore** → select **Prometheus** datasource.

### DW Orchestrator (4 KPIs)

```promql
orchestrator_state_transitions_total
```
```promql
orchestrator_active_workers
```
```promql
orchestrator_errors_total
```
```promql
orchestrator_sync_failures_total
```

### Worker Runner — LangGraph (4 KPIs)

```promql
langgraph_build_duration_sum / langgraph_build_duration_count
```
```promql
rate(langgraph_step_total[5m])
```
```promql
histogram_quantile(0.95, rate(langgraph_execution_duration_bucket[5m]))
```
```promql
rate(langgraph_step_retries_total[5m])
```

### MCP Tool Servers (3 KPIs)

```promql
rate(mcp_tool_invocations_total[5m])
```
```promql
histogram_quantile(0.95, rate(mcp_tool_duration_bucket[5m]))
```
```promql
rate(mcp_tool_timeouts_total[5m])
```

---

## Step 5 — Quick Verify via curl

Confirm all metrics are present on each endpoint before querying Grafana:

```bash
# DW Orchestrator metrics
curl -s http://localhost:8000/metrics | grep -E "^orchestrator"

# MCP add/subtract tool metrics
curl -s http://localhost:8001/metrics | grep -E "^mcp_tool"

# MCP solver + LangGraph metrics
curl -s http://localhost:8002/metrics | grep -E "^(mcp_tool|langgraph)"
```

---

## Ports Reference

| Service | Port | Purpose |
|---|---|---|
| FastAPI agent | 8080 | Send questions via POST /run |
| Prometheus metrics (agent) | 8000 | Orchestrator KPIs |
| Prometheus metrics (add_sub) | 8001 | add/subtract tool KPIs |
| Prometheus metrics (mul_div) | 8002 | LangGraph + solve_steps KPIs |
| Prometheus | 9090 | Query metrics, check targets |
| Grafana | 3000 | Dashboards and Explore |
| Tempo | 3200 | Distributed traces |
