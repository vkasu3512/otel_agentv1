# How to Check Loki Logs

## Quick Reference

**Available Services:**
- `otel-agent-v2-orchestrator` (FastAPI, port 8000)
- `otel-agent-v2-mcp-add-sub` (MCP add/sub, port 8001)
- `otel-agent-v2-mcp-mul-div` (MCP mul/div, port 8002)

---

## Method 1: Grafana UI (Recommended) ✅

### Access Loki in Grafana
1. Open **http://localhost:3000**
2. Click **Explore** (left sidebar)
3. Select **Loki** from the dropdown (top left)
4. Use the **LogQL** query builder

### Example Queries

#### View all logs from orchestrator (last 1 hour)
```logql
{service_name="otel-agent-v2-orchestrator"}
```

#### View logs from all otel services
```logql
{service_name=~"otel-agent.*"}
```

#### View only ERROR/WARNING level logs
```logql
{service_name="otel-agent-v2-orchestrator"} | level="ERROR" or level="WARNING"
```

#### Find logs containing "Handoff" (agent decisions)
```logql
{service_name="otel-agent-v2-orchestrator"} | "Handoff"
```

#### Find logs containing "Done" (completed requests)
```logql
{service_name="otel-agent-v2-orchestrator"} | "Done"
```

#### View MCP tool calls
```logql
{service_name="otel-agent-v2-mcp-add-sub"} | "subtract" or "add"
```

#### View LangGraph execution (mul_div server)
```logql
{service_name="otel-agent-v2-mcp-mul-div"} | "solve_steps"
```

#### Correlate logs with trace ID
```logql
{service_name=~"otel-agent.*"} | json | trace_id="dfc2a2097e709935bdae69133c1bf4e7"
```

---

## Method 2: Loki API (Direct HTTP)

### Get all services with logs
```bash
curl http://localhost:3100/loki/api/v1/label/service_name/values
```

### Get all logger names
```bash
curl http://localhost:3100/loki/api/v1/label/logger/values
```

### Query logs (LogQL)
```bash
curl -G -d 'query={service_name="otel-agent-v2-orchestrator"}' \
     -d 'limit=50' \
     http://localhost:3100/loki/api/v1/query_range
```

### Query with time range (Unix seconds)
```bash
START=$(date -d '10 minutes ago' +%s)
END=$(date +%s)

curl -G \
  -d "query={service_name=\"otel-agent-v2-orchestrator\"}" \
  -d "start=${START}s" \
  -d "end=${END}s" \
  -d "limit=100" \
  http://localhost:3100/loki/api/v1/query_range
```

---

## Method 3: Grafana Dashboards

### Pre-built Log Panels
1. Go to **Dashboards** in Grafana
2. Create a new dashboard
3. Add a **Logs** panel
4. Configure:
   - **Data Source**: Loki
   - **Query**: `{service_name=~"otel-agent.*"}`
   - **Options**: Set refresh rate, line limit

### Link Traces to Logs
1. In **Tempo** trace view, click a span
2. Click **"Logs"** tab
3. Grafana automatically shows correlated logs (if trace_id is in logs)

---

## Common LogQL Patterns

### Filter by log level
```logql
{service_name="otel-agent-v2-orchestrator"} | level="INFO"
```

### Filter by JSON field
```logql
{service_name="otel-agent-v2-orchestrator"} | json | status="completed"
```

### Count logs per service (in range)
```logql
count_over_time({service_name=~"otel-agent.*"}[5m])
```

### Parse structured logs
```logql
{service_name="otel-agent-v2-orchestrator"} 
| json 
| status="running"
```

### Show logs with context (5 min window around timestamp)
```logql
{service_name="otel-agent-v2-orchestrator"} | "Orchestrator" | "Done"
```

---

## Live Monitoring

### Stream live logs
```bash
# Using curl (tail mode)
curl -N "http://localhost:3100/loki/api/v1/tail?query={service_name=~\"otel-agent.*\"}"
```

### In Grafana
1. Go to **Explore** → **Loki**
2. Write your query
3. Click the **"Tail"** option (upper right)
4. Logs will stream live as they arrive

---

## Troubleshooting

### No logs appearing?
1. Check Loki is running: `curl http://localhost:3100/ready`
2. Check services are pushing logs: Look at orchestrator output
3. Verify Loki configuration in `Grafana_stackv1/loki-values.yaml`

### Logs not persisting?
- By default, Loki keeps logs for 24 hours
- Configure retention in `loki-values.yaml`:
  ```yaml
  retention:
    enabled: true
    period: 720h  # 30 days
  ```

### Missing service labels?
- Ensure `otel_setup.py` initialized with correct service name
- Check `wd-otel-orchestrator.yaml` service configuration

---

## Example: Complete Log Investigation

**Scenario:** Investigate why the complex calculation took longer

1. **Open Grafana Explore** (Loki)
2. **Query orchestrator logs:**
   ```logql
   {service_name="otel-agent-v2-orchestrator"} | "Done"
   ```
3. **Find the trace:**
   - Copy the trace ID from the span
4. **Switch to Tempo** datasource
5. **Paste trace ID** to view full waterfall
6. **Cross-reference logs** by service:
   ```logql
   {service_name="otel-agent-v2-mcp-mul-div"} | trace_id="<copied-id>"
   ```

---

## Labels Available

Every log stream in Loki has these labels:

| Label | Examples | Use |
|-------|----------|-----|
| `service_name` | otel-agent-v2-orchestrator | Filter by service |
| `logger` | wd_otel, __main__, httpx | Filter by component |
| `level` | INFO, WARNING, ERROR, DEBUG | Filter by severity |
| `pod` | otel-agent-v2-orchestrator-xxx | K8s pod identification |
| `stream` | stdout, stderr | Log stream type |

