# Storage and Endpoints Reference

Complete guide to traces, logs, and metrics storage with all available endpoints.

---

## Overview

The Observability Stack uses three specialized backends for different telemetry data types:

| Data Type | Backend | Port | Storage Type | Retention |
|-----------|---------|------|--------------|-----------|
| **Traces** | Tempo | 3200 | OTLP JSON | 15 days |
| **Logs** | Loki | 3100 | Time-indexed streams | 7 days |
| **Metrics** | Prometheus | 9090 | Time-series | 15 days |

---

## Traces - Tempo (Port 3200)

### Collection Flow
```
otel_agent_v2 (port 8080)
  ↓ (OTLP gRPC)
Alloy (port 4317)
  ↓
Tempo (port 3200)
```

### Storage Structure
- **Format**: OpenTelemetry Protocol (OTLP) JSON
- **Organization**: Batches of spans grouped by trace ID
- **Key Fields**:
  - `traceID`: Unique trace identifier
  - `startTimeUnixNano`: Trace start time (nanoseconds)
  - `durationMs`: Total trace duration in milliseconds
  - `rootServiceName`: Source service name
  - `rootTraceName`: Trace operation name
  - `batches`: Array of span batches with scopes

### Detailed Collection and Storage Flow

#### Step 1: Trace Generation (Application Layer)
```
otel_agent_v2 (Port 8080)
  ├─ POST /run request arrives
  ├─ OpenTelemetry instrumentation activates
  └─ Generates trace data:
      • traceID (unique identifier)
      • spanID (operation identifier)
      • startTimeUnixNano & endTimeUnixNano
      • attributes (HTTP method, status code, etc.)
      • parent-child span relationships
```

#### Step 2: Trace Transmission (Collection Layer)
```
OTLP gRPC Sender
  ├─ Serializes trace to OTLP format
  ├─ Sends to localhost:4317 (Alloy receiver)
  └─ Protocol: gRPC (efficient binary)
       ↓
Grafana Alloy (Port 4317)
  ├─ Receives OTLP gRPC data
  ├─ Batches multiple traces
  ├─ Applies processing rules
  └─ Routes to Tempo
```

#### Step 3: Storage (Backend)
```
Tempo (Port 3200)
  ├─ Receives batched traces
  ├─ Stores in OTLP JSON format
  ├─ Organizes by traceID
  ├─ Indexes spans for lookup
  ├─ Retention: 15 days
  └─ Time-indexed distributed trace DB
```

#### Step 4: Data Retrieval (Query Layer)
```
Dashboard (Port 3001)
  ├─ Calls /api/traces endpoint
  ├─ Proxies to Tempo /api/search
  ├─ Receives trace metadata
  └─ Renders in browser UI
```

### Execution Example

**When you call `POST /run` on the orchestrator:**

1. **Request arrives** → OpenTelemetry creates root span
   - `traceID`: "xyz789" (newly generated)
   - `spanID`: "root-001"
   - `name`: "POST /run"
   - `startTime`: now

2. **Code executes** → Child spans created for each operation
   - `spanID`: "child-001"
   - `parentSpanID`: "root-001"
   - `name`: "mcp.tool.add"

3. **Operation completes** → Span ends
   - `endTime`: recorded
   - `duration`: endTime - startTime
   - `status`: success/error

4. **Trace serialized** → OTLP JSON format

5. **Sent to Alloy** → localhost:4317 (OTLP gRPC)

6. **Alloy batches** → Collects multiple traces

7. **Forwarded to Tempo** → localhost:3200

8. **Tempo stores** → Indexed and queryable

9. **Dashboard queries** → /api/search (lists all traces)

10. **Full trace retrieved** → /api/traces/{traceID}

11. **Browser renders** → Trace visualization with timeline

### Key Retention Points

- **Stored for**: 15 days (configurable in Tempo)
- **Indexed by**: traceID (primary key)
- **Query speed**: Milliseconds (indexed lookups)
- **Total storage**: Depends on trace volume and complexity

### Endpoints

#### 1. Search All Traces
```
GET http://localhost:3200/api/search
```

**Response Example**:
```json
{
  "traces": [
    {
      "traceID": "abc123def456",
      "rootServiceName": "otel-agent-api",
      "rootTraceName": "POST /run",
      "startTimeUnixNano": "1713699840000000000",
      "durationMs": 245
    }
  ]
}
```

#### 2. Get Specific Trace by ID
```
GET http://localhost:3200/api/traces/{traceID}
```

**Example**:
```
GET http://localhost:3200/api/traces/abc123def456
```

**Response Example**:
```json
{
  "traceID": "abc123def456",
  "startTimeUnixNano": "1713699840000000000",
  "durationMs": 245,
  "batches": [
    {
      "scopeSpans": [
        {
          "spans": [
            {
              "traceID": "abc123def456",
              "spanID": "span001",
              "parentSpanID": "",
              "name": "POST /run",
              "startTimeUnixNano": "1713699840000000000",
              "endTimeUnixNano": "1713699840245000000",
              "attributes": {
                "http.method": "POST",
                "http.target": "/run",
                "http.status_code": 200
              }
            }
          ]
        }
      ]
    }
  ]
}
```

### PowerShell Examples

**List all traces**:
```powershell
$traces = (Invoke-WebRequest -Uri "http://localhost:3200/api/search").Content | ConvertFrom-Json
$traces.traces | Select-Object traceID, rootServiceName, durationMs | Format-Table
```

**Get specific trace details**:
```powershell
$traceID = "abc123def456"
$trace = (Invoke-WebRequest -Uri "http://localhost:3200/api/traces/$traceID").Content | ConvertFrom-Json
$trace.batches[0].scopeSpans[0].spans | Select-Object name, startTimeUnixNano | Format-Table
```

---

## Logs - Loki (Port 3100)

### Collection Flow
```
otel_agent_v2.otel_setup (logging)
  ↓ (HTTP push)
Loki (port 3100)
```

### Storage Structure
- **Format**: Time-indexed log streams with labels
- **Organization**: Logs grouped by labels (job, level, service, etc.)
- **Retention**: 7 days (configurable)

### Labels
- `job`: Source application (e.g., `otel-agent-api`)
- `instance`: Server instance identifier
- `level`: Log severity (`debug`, `info`, `warn`, `error`)
- `service`: Service name

### Endpoints

#### 1. Query Logs (Instant)
```
GET http://localhost:3100/loki/api/v1/query
```

**Parameters**:
- `query`: LogQL query (required)
- `limit`: Max number of results (default: 1000)

**Examples**:
```
http://localhost:3100/loki/api/v1/query?query={job="otel-agent-api"}
http://localhost:3100/loki/api/v1/query?query={level="error"}&limit=50
http://localhost:3100/loki/api/v1/query?query={job=~".*"}&limit=100
```

#### 2. Query Logs (Range)
```
GET http://localhost:3100/loki/api/v1/query_range
```

**Parameters**:
- `query`: LogQL query (required)
- `start`: Start timestamp (Unix seconds)
- `end`: End timestamp (Unix seconds)
- `limit`: Max results per stream (default: 1000)
- `step`: Query resolution step

**Example**:
```
GET http://localhost:3100/loki/api/v1/query_range?query={job="otel-agent-api"}&start=1713699840&end=1713786240&step=60s
```

### PowerShell Examples

**Query error logs**:
```powershell
$logs = (Invoke-WebRequest -Uri 'http://localhost:3100/loki/api/v1/query?query={level="error"}').Content | ConvertFrom-Json
$logs.data.result | ForEach-Object { $_.values }
```

**Query logs with time range**:
```powershell
$start = [int][double]::Parse((Get-Date).AddHours(-1).ToString("yyyyMMddHHmmss"))
$end = [int][double]::Parse((Get-Date).ToString("yyyyMMddHHmmss"))
$url = "http://localhost:3100/loki/api/v1/query_range?query={job=`"otel-agent-api`"}&start=$start&end=$end"
$logs = (Invoke-WebRequest -Uri $url).Content | ConvertFrom-Json
```

---

## Metrics - Prometheus (Port 9090)

### Collection Flow
```
otel_agent_v2 (port 8000, 8001, 8002, 8080)
  ↓ (/metrics endpoint)
Prometheus (port 9090)
  ↓ (scrape, every 15 seconds)
Time-series storage
```

### Scrape Targets
- `localhost:8000/metrics` → otel-agent-api
- `localhost:8001/metrics` → mcp-add-sub-server
- `localhost:8002/metrics` → mcp-mul-div-server
- `localhost:8080/metrics` → orchestrator

### Storage Structure
- **Format**: Prometheus time-series format
- **Retention**: 15 days (default)
- **Scrape Interval**: 15 seconds (default)

### Metric Types
- **Counter**: Monotonic increasing value (never decreases)
  - Example: `mcp_tool_invocations_total`
- **Gauge**: Instantaneous value that can go up or down
  - Example: `wd_otel_workers_active`
- **Histogram**: Bucketed distribution of values
  - Example: `langgraph_execution_duration_seconds_bucket`
- **Summary**: Percentile data
  - Example: `request_duration_seconds`

### Endpoints

#### 1. Query Metrics (Instant)
```
GET http://localhost:9090/api/v1/query
```

**Parameters**:
- `query`: PromQL expression (required)
- `time`: Unix timestamp (default: current time)

**Examples**:
```
http://localhost:9090/api/v1/query?query=up
http://localhost:9090/api/v1/query?query=langgraph_execution_duration_seconds_bucket
http://localhost:9090/api/v1/query?query=sum(mcp_tool_invocations_total)
```

#### 2. Query Metrics (Range)
```
GET http://localhost:9090/api/v1/query_range
```

**Parameters**:
- `query`: PromQL expression (required)
- `start`: Start timestamp (Unix seconds)
- `end`: End timestamp (Unix seconds)
- `step`: Query resolution step (e.g., `60s`, `5m`)

**Example**:
```
GET http://localhost:9090/api/v1/query_range?query=up&start=1713699840&end=1713786240&step=60s
```

#### 3. Scrape Targets Status
```
GET http://localhost:9090/targets
```

Returns status of all scrape targets (UP/DOWN).

#### 4. Available Metrics List
```
GET http://localhost:9090/api/v1/label/__name__/values
```

Returns all available metric names.

### Common Metrics

**Langgraph/Agent Metrics**:
- `langgraph_execution_duration_seconds_bucket`: Execution time distribution
- `langgraph_execution_duration_seconds_count`: Total execution count
- `langgraph_execution_duration_seconds_sum`: Total execution time

**MCP Tool Metrics**:
- `mcp_tool_invocations_total`: Total tool invocations (counter)
- `mcp_tool_errors_total`: Total tool errors (counter)
- `mcp_tool_duration_seconds`: Tool execution duration

**Orchestrator Metrics**:
- `wd_otel_workers_active`: Active worker threads (gauge)
- `wd_otel_state_transitions_total`: Total state transitions (counter)
- `wd_otel_errors_total`: Total errors (counter)
- `wd_otel_sync_failures_total`: Sync failures (counter)

**Agent API Metrics**:
- `agent_api_request_duration_seconds`: Request duration
- `agent_api_requests_total`: Total requests
- `agent_api_errors_total`: Total errors

### PowerShell Examples

**Get all metrics from target**:
```powershell
$metrics = (Invoke-WebRequest -Uri "http://localhost:9090/api/v1/query?query=up").Content | ConvertFrom-Json
$metrics.data.result | Select-Object -Property @{N='Job';E={$_.metric.job}}, @{N='Instance';E={$_.metric.instance}}, @{N='Value';E={$_.value[1]}} | Format-Table
```

**Query specific metric with time range**:
```powershell
$start = [int](Get-Date).AddHours(-1).ToUniversalTime().Subtract((Get-Date -Date "1970-01-01")).TotalSeconds
$end = [int](Get-Date).ToUniversalTime().Subtract((Get-Date -Date "1970-01-01")).TotalSeconds
$url = "http://localhost:9090/api/v1/query_range?query=langgraph_execution_duration_seconds_bucket&start=$start&end=$end&step=60s"
$data = (Invoke-WebRequest -Uri $url).Content | ConvertFrom-Json
$data.data.result | ForEach-Object { $_.metric | ConvertTo-Json }
```

**Calculate P95 latency**:
```powershell
$query = "histogram_quantile(0.95, sum(rate(langgraph_execution_duration_seconds_bucket[5m])))"
$result = (Invoke-WebRequest -Uri "http://localhost:9090/api/v1/query?query=$query").Content | ConvertFrom-Json
$result.data.result[0].value[1]
```

---

## Dashboard Endpoints (Port 3001)

### Architecture
```
Dashboard (http://localhost:3001)
    ├─ /api/traces        → Proxies to Tempo (3200)
    ├─ /api/kpi           → Proxies to KPI Proxy (8900)
    └─ React Context (TelemetryContext)
```

### Data Flow
1. User opens http://localhost:3001
2. TelemetryProvider (store.tsx) fetches `/api/traces` on component mount
3. `buildKpiFromTraces()` processes traces into KPI metrics
4. McpPanel displays MCP tool statistics
5. Charts render time-series data

### Endpoints

#### 1. Get Traces (Proxied)
```
GET http://localhost:3001/api/traces
```

Returns traces from Tempo, formatted for the dashboard.

#### 2. Get KPI Data (Proxied)
```
GET http://localhost:3001/api/kpi
```

Returns KPI metrics from KPI Proxy service (port 8900).

---

## Data Collection Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Application Layer                         │
│  (otel_agent_v2, mcp_server, orchestrator)                  │
└─────────────────────────────────────────────────────────────┘
        ↓ (Instrumentation)          ↓ (Metrics)              ↓ (Logs)
        │                             │                         │
    OTLP gRPC                    Prometheus                  HTTP Push
    (port 4317)              (/metrics endpoint)          (port 3100)
        │                             │                         │
        ↓                             ↓                         ↓
┌──────────────────────────────────────────────────────────────┐
│                  Collection Layer                            │
│  (Grafana Alloy, Prometheus scraper)                         │
└──────────────────────────────────────────────────────────────┘
        │                             │                         │
        ↓                             ↓                         ↓
┌──────────────┐           ┌──────────────┐          ┌─────────────┐
│    Tempo     │           │ Prometheus   │          │    Loki     │
│   (3200)     │           │   (9090)     │          │  (3100)     │
│  (Traces)    │           │ (Metrics)    │          │  (Logs)     │
└──────────────┘           └──────────────┘          └─────────────┘
        ↓                             ↓                         ↓
┌─────────────────────────────────────────────────────────────┐
│                   Dashboard Layer                           │
│  (Next.js Frontend on port 3001)                           │
│  ├─ Traces Tab (fetches from Tempo)                        │
│  ├─ Logs Tab (fetches from Loki)                          │
│  ├─ Metrics Tab (fetches from Prometheus)                 │
│  └─ MCP Panel (aggregated from all sources)               │
└─────────────────────────────────────────────────────────────┘
```

---

## Testing Connectivity

### All Services Status
```powershell
Write-Host "Service Status:"; 
try { Invoke-WebRequest -Uri "http://localhost:3200/api/search" -TimeoutSec 1 | Out-Null; Write-Host "✓ Tempo (3200)" } catch { Write-Host "✗ Tempo (3200)" };
try { Invoke-WebRequest -Uri "http://localhost:9090/api/v1/query?query=up" -TimeoutSec 1 | Out-Null; Write-Host "✓ Prometheus (9090)" } catch { Write-Host "✗ Prometheus (9090)" };
try { Invoke-WebRequest -Uri "http://localhost:3100/loki/api/v1/query" -TimeoutSec 1 | Out-Null; Write-Host "✓ Loki (3100)" } catch { Write-Host "✗ Loki (3100)" };
try { Invoke-WebRequest -Uri "http://localhost:3001" -TimeoutSec 1 | Out-Null; Write-Host "✓ Dashboard (3001)" } catch { Write-Host "✗ Dashboard (3001)" };
```

### Sample Data Queries
```powershell
# Get sample trace
$trace = (Invoke-WebRequest -Uri "http://localhost:3200/api/search").Content | ConvertFrom-Json
$traceId = $trace.traces[0].traceID
Write-Host "Sample Trace ID: $traceId"

# Get sample metrics
$metrics = (Invoke-WebRequest -Uri "http://localhost:9090/api/v1/query?query=up").Content | ConvertFrom-Json
Write-Host "Scrape targets: $($metrics.data.result.Count)"

# Get sample logs
$logs = (Invoke-WebRequest -Uri "http://localhost:3100/loki/api/v1/query?query={job=%22otel-agent-api%22}").Content | ConvertFrom-Json
Write-Host "Log streams: $($logs.data.result.Count)"
```

---

## Reference

- **Tempo Documentation**: https://grafana.com/docs/tempo/
- **Prometheus Documentation**: https://prometheus.io/docs/
- **Loki Documentation**: https://grafana.com/docs/loki/
- **OpenTelemetry**: https://opentelemetry.io/

