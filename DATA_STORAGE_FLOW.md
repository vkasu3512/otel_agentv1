# Data Storage Flow Guide

Complete guide explaining how traces, logs, and metrics are collected, transmitted, and stored in the observability stack.

---

## Overview

The observability stack uses three specialized backends for different telemetry data types:

| Data Type | Backend | Port | Storage Format | Retention | Query Time |
|-----------|---------|------|----------------|-----------|-----------|
| **Traces** | Tempo | 3200 | OTLP JSON | 15 days | Milliseconds |
| **Logs** | Loki | 3100 | Time-indexed streams | 7 days | Seconds |
| **Metrics** | Prometheus | 9090 | Time-series TSDB | 15 days | Milliseconds |

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│            Application Layer (Instrumentation)              │
│  otel_agent_v2 (8080) → MCP Servers (8081, 8082)           │
└─────────────────────────────────────────────────────────────┘
        ↓ OTLP gRPC          ↓ /metrics              ↓ Logs
        (4317)             (endpoints)            (HTTP)
        │                     │                      │
        ↓                     ↓                      ↓
┌────────────────────────────────────────────────────────────┐
│              Collection Layer (Alloy/Scraper)              │
│  Grafana Alloy (4317) | Prometheus Scraper | Log Pusher   │
└────────────────────────────────────────────────────────────┘
        │                     │                      │
        ↓                     ↓                      ↓
    ┌─────────┐          ┌──────────┐          ┌──────────┐
    │  TEMPO  │          │PROMETHEUS│          │   LOKI   │
    │ (3200)  │          │  (9090)  │          │ (3100)   │
    │ Traces  │          │ Metrics  │          │  Logs    │
    └─────────┘          └──────────┘          └──────────┘
        │                     │                      │
        ↓                     ↓                      ↓
┌────────────────────────────────────────────────────────────┐
│           Dashboard (Next.js on Port 3001)                  │
│  /api/traces → /api/kpi → /api/logs Unified View          │
└────────────────────────────────────────────────────────────┘
```

---

## 1. TRACES - Tempo (Port 3200)

### Collection Flow

```
Application (otel_agent_v2)
    ↓ OpenTelemetry Instrumentation
    ├─ Creates root span on request arrival
    ├─ Generates unique traceID
    ├─ Records startTime, attributes
    └─ Creates child spans during execution
    
    ↓ Span Execution
    ├─ Child operations create nested spans
    ├─ Records startTime, endTime for each
    ├─ Captures attributes (HTTP method, status, etc.)
    └─ Records span status (success/error)
    
    ↓ OTLP Serialization
    └─ Converts spans to OpenTelemetry Protocol format
    
    ↓ gRPC Transmission
    └─ Sends to localhost:4317 (Alloy receiver)
    
Grafana Alloy (Port 4317)
    ├─ Receives OTLP gRPC data
    ├─ Batches multiple traces
    ├─ Applies processing rules
    └─ Routes to Tempo
    
Tempo (Port 3200)
    ├─ Receives batched traces
    ├─ Stores in OTLP JSON format
    ├─ Indexes by traceID
    ├─ Creates span-level indexes
    └─ Retains for 15 days
```

### Storage Structure

**Format**: OpenTelemetry Protocol (OTLP) JSON

**Organization**:
- **Top-level**: By traceID (unique trace identifier)
- **Second-level**: Batches of spans with scopes
- **Third-level**: Individual spans with parent-child relationships

**Key Fields per Trace**:
```json
{
  "traceID": "abc123def456",
  "startTimeUnixNano": "1713699840000000000",
  "durationMs": 245,
  "rootServiceName": "otel-agent-api",
  "rootTraceName": "POST /run",
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

### Query Endpoints

#### List All Traces
```
GET http://localhost:3200/api/search
```

**Response**:
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

#### Get Specific Trace Details
```
GET http://localhost:3200/api/traces/{traceID}
```

**Example**:
```
GET http://localhost:3200/api/traces/abc123def456
```

### PowerShell Examples

**List traces**:
```powershell
$traces = (Invoke-WebRequest -Uri "http://localhost:3200/api/search").Content | ConvertFrom-Json
$traces.traces | Select-Object traceID, durationMs | Format-Table
```

**Get trace details**:
```powershell
$traceID = "abc123def456"
$trace = (Invoke-WebRequest -Uri "http://localhost:3200/api/traces/$traceID").Content | ConvertFrom-Json
$trace.batches[0].scopeSpans[0].spans | Format-List name, startTimeUnixNano, endTimeUnixNano
```

---

## 2. METRICS - Prometheus (Port 9090)

### Collection Flow

```
Application Endpoints
    ├─ localhost:8000/metrics (agent-api)
    ├─ localhost:8001/metrics (mcp-add-sub)
    ├─ localhost:8002/metrics (mcp-mul-div)
    └─ localhost:8080/metrics (orchestrator)
    
    ↓ Prometheus Scraper (every 15 seconds)
    ├─ Polls /metrics endpoints
    ├─ Parses Prometheus text format
    ├─ Extracts metric name, labels, value
    └─ Applies timestamp
    
    ↓ Time-series Processing
    ├─ Groups by metric name + label combination
    ├─ Compresses into time-series format
    ├─ Calculates statistics (min, max, avg)
    └─ Stores with timestamp
    
Prometheus (Port 9090)
    ├─ Receives scraped data every 15 seconds
    ├─ Stores in TSDB (time-series database)
    ├─ Indexes by metric name and labels
    ├─ Retains for 15 days
    └─ Compresses old data
```

### Metric Types

**Counter** (monotonic increasing):
```
mcp_tool_invocations_total: 42
wd_otel_errors_total: 5
```

**Gauge** (can go up or down):
```
wd_otel_workers_active: 2
```

**Histogram** (distribution):
```
langgraph_execution_duration_seconds_bucket{le="0.1"}: 10
langgraph_execution_duration_seconds_bucket{le="0.5"}: 25
langgraph_execution_duration_seconds_bucket{le="1.0"}: 40
```

### Query Endpoints

#### Instant Query
```
GET http://localhost:9090/api/v1/query?query={metric_name}
```

**Example**:
```
GET http://localhost:9090/api/v1/query?query=wd_otel_workers_active
```

#### Range Query
```
GET http://localhost:9090/api/v1/query_range?query={metric}&start={t1}&end={t2}&step=60s
```

**Example**:
```
GET http://localhost:9090/api/v1/query_range?query=wd_otel_errors_total&start=1713699840&end=1713786240&step=60s
```

#### Targets Status
```
GET http://localhost:9090/targets
```

#### Available Metrics
```
GET http://localhost:9090/api/v1/label/__name__/values
```

### Available Metrics

| Metric Name | Type | Source | Purpose |
|-------------|------|--------|---------|
| `wd_otel_workers_active` | Gauge | Orchestrator | Active worker threads |
| `wd_otel_state_transitions_total` | Counter | Orchestrator | Total state transitions |
| `wd_otel_errors_total` | Counter | Orchestrator | Total errors |
| `wd_otel_sync_failures_total` | Counter | Orchestrator | Sync failures |
| `mcp_tool_invocations_total` | Counter | MCP Servers | Tool invocation count |
| `mcp_tool_errors_total` | Counter | MCP Servers | Tool error count |
| `mcp_tool_duration_seconds` | Histogram | MCP Servers | Tool execution duration |
| `langgraph_execution_duration_seconds_bucket` | Histogram | Agent | Agent execution latency |
| `agent_api_request_duration_seconds` | Histogram | Agent API | Request duration |
| `agent_api_requests_total` | Counter | Agent API | Total requests |
| `agent_api_errors_total` | Counter | Agent API | Total errors |

### PowerShell Examples

**Query active workers**:
```powershell
$result = (Invoke-WebRequest -Uri "http://localhost:9090/api/v1/query?query=wd_otel_workers_active").Content | ConvertFrom-Json
$result.data.result[0].value[1]  # Returns value
```

**Query time range**:
```powershell
$start = [int](Get-Date).AddHours(-1).ToUniversalTime().Subtract((Get-Date -Date "1970-01-01")).TotalSeconds
$end = [int](Get-Date).ToUniversalTime().Subtract((Get-Date -Date "1970-01-01")).TotalSeconds
$url = "http://localhost:9090/api/v1/query_range?query=wd_otel_errors_total&start=$start&end=$end&step=60s"
$data = (Invoke-WebRequest -Uri $url).Content | ConvertFrom-Json
```

**Calculate P95 latency**:
```powershell
$query = "histogram_quantile(0.95, sum(rate(langgraph_execution_duration_seconds_bucket[5m])))"
$result = (Invoke-WebRequest -Uri "http://localhost:9090/api/v1/query?query=$query").Content | ConvertFrom-Json
$p95 = $result.data.result[0].value[1]
Write-Host "P95 Latency: ${p95}s"
```

---

## 3. LOGS - Loki (Port 3100)

### Collection Flow

```
Application Logging
    ├─ Application generates log message
    ├─ OTel logging SDK captures:
    │   ├─ Log message text
    │   ├─ Severity level (debug, info, warn, error)
    │   ├─ Timestamp
    │   └─ Context (logger name, etc.)
    └─ Applies labels:
        ├─ job: Source service
        ├─ instance: Server instance
        ├─ level: Severity
        └─ service: Service name
    
    ↓ Log Batching
    ├─ Collects multiple log entries
    ├─ Groups by label combination
    └─ Creates batch payload
    
    ↓ HTTP Push
    └─ Sends to Loki /loki/api/v1/push
    
Loki (Port 3100)
    ├─ Receives log batch
    ├─ Parses labels
    ├─ Stores in log streams
    ├─ Indexes by label combination
    ├─ Compresses storage
    └─ Retains for 7 days
```

### Storage Structure

**Format**: Time-indexed log entries grouped by labels

**Organization**:
- **Primary key**: Label combination (job + level + service + etc.)
- **Secondary key**: Timestamp
- **Value**: Log message text

**Available Labels**:
```
job: "otel-agent-api" | "orchestrator" | "mcp-server"
instance: Server identifier
level: "debug" | "info" | "warn" | "error"
service: Service name
```

### Query Endpoints

#### Instant Query
```
GET http://localhost:3100/loki/api/v1/query?query={labels}
```

**Examples**:
```
http://localhost:3100/loki/api/v1/query?query={job="otel-agent-api"}
http://localhost:3100/loki/api/v1/query?query={level="error"}
http://localhost:3100/loki/api/v1/query?query={job=~".*"}
http://localhost:3100/loki/api/v1/query?query={level="error"}&limit=50
```

#### Range Query
```
GET http://localhost:3100/loki/api/v1/query_range?query={labels}&start={t1}&end={t2}&step=60s
```

**Parameters**:
- `query`: LogQL query (required)
- `start`: Start timestamp (Unix seconds)
- `end`: End timestamp (Unix seconds)
- `limit`: Max results per stream (default: 1000)
- `step`: Query resolution step

### PowerShell Examples

**Query error logs**:
```powershell
$logs = (Invoke-WebRequest -Uri 'http://localhost:3100/loki/api/v1/query?query={level="error"}').Content | ConvertFrom-Json
$logs.data.result | ForEach-Object { $_.values }
```

**Query time range**:
```powershell
$start = [int](Get-Date).AddHours(-1).ToUniversalTime().Subtract((Get-Date -Date "1970-01-01")).TotalSeconds
$end = [int](Get-Date).ToUniversalTime().Subtract((Get-Date -Date "1970-01-01")).TotalSeconds
$url = "http://localhost:3100/loki/api/v1/query_range?query={job=`"otel-agent-api`"}&start=$start&end=$end"
$logs = (Invoke-WebRequest -Uri $url).Content | ConvertFrom-Json
```

---

## Complete Request Flow Example

### Scenario: Single `POST /run` Request

```
STEP 1: REQUEST ARRIVES (Port 8080)
├─ HTTP POST /run
└─ OpenTelemetry auto-instrumentation activates

STEP 2: TRACE DATA GENERATED
├─ traceID created: "abc123def456"
├─ Root span created:
│  ├─ spanID: "root-001"
│  ├─ name: "POST /run"
│  ├─ startTime: 1713699840000000000 (nanoseconds)
│  └─ attributes: {http.method: POST, http.target: /run}
└─ Span queued for export

STEP 3: CODE EXECUTION
├─ Handler processes request
├─ Calls MCP tool (e.g., add(a, b))
├─ Child span created:
│  ├─ parentSpanID: "root-001"
│  ├─ spanID: "child-001"
│  ├─ name: "mcp.tool.add"
│  └─ startTime: recorded
└─ Tool completes

STEP 4: OPERATION COMPLETES
├─ Child span ends:
│  ├─ endTime: 1713699840050000000
│  ├─ duration: 50000000 ns
│  └─ status: OK
├─ Root span ends:
│  ├─ endTime: 1713699840245000000
│  ├─ duration: 245000000 ns
│  └─ http.status_code: 200
└─ Span batch marked complete

STEP 5: SERIALIZE & SEND
├─ Spans converted to OTLP JSON
├─ Batched with other spans from batch
└─ Sent via gRPC to localhost:4317

STEP 6: ALLOY PROCESSES
├─ Receives OTLP data
├─ Validates schema
├─ Batches with other traces
└─ Routes to Tempo

STEP 7: TEMPO STORES TRACE
├─ Receives batched spans
├─ Parses OTLP JSON
├─ Stores with index:
│  └─ traceID: "abc123def456"
├─ Creates reverse indexes:
│  ├─ By service name
│  ├─ By span name
│  └─ By time window
└─ Compressed storage

STEP 8: METRICS EMITTED
├─ Execution duration recorded:
│  ├─ Histogram bucket: [0.1s] += 1
│  ├─ Histogram bucket: [0.5s] += 1
│  ├─ Total count += 1
│  └─ Sum += 0.245s
├─ Request count += 1
├─ Success count += 1
└─ Metrics in /metrics endpoint

STEP 9: PROMETHEUS SCRAPES
├─ Polls /metrics every 15 seconds
├─ Extracts metrics:
│  ├─ langgraph_execution_duration_seconds_bucket
│  ├─ langgraph_execution_duration_seconds_sum
│  ├─ langgraph_execution_duration_seconds_count
│  └─ Other metrics
├─ Stores time-series:
│  └─ Metric name + labels → [timestamp, value]
└─ Compresses into TSDB

STEP 10: LOGS GENERATED
├─ Application logs operation:
│  ├─ Message: "Executed tool add with args [5, 3]"
│  ├─ Level: INFO
│  ├─ Timestamp: 1713699840123456789
│  └─ Labels: {job: "otel-agent-api", level: info}
├─ Batched with other logs
└─ Pushed to Loki HTTP endpoint

STEP 11: LOKI RECEIVES & STORES
├─ Receives log batch
├─ Groups by labels
├─ Stores in log stream:
│  └─ Stream key: {job="otel-agent-api", level="info"}
├─ Indexes by:
│  ├─ Label combination
│  ├─ Timestamp
│  └─ Message text (inverted index)
└─ Retains for 7 days

STEP 12: DASHBOARD QUERIES
├─ User opens http://localhost:3001
├─ Dashboard calls /api/traces
│  ├─ Queries Tempo for latest traces
│  ├─ Returns trace metadata
│  └─ Renders in Traces tab
├─ Dashboard calls /api/kpi
│  ├─ Queries Prometheus for metrics
│  ├─ Calculates aggregations (p95, error rate)
│  └─ Renders in KPI panel
└─ Dashboard renders unified view

STEP 13: USER VIEWS DATA
├─ Traces Tab:
│  ├─ Shows traceID: "abc123def456"
│  ├─ Duration: 245ms
│  ├─ Service: otel-agent-api
│  └─ Spans: Shows hierarchy
├─ KPI Tab:
│  ├─ Execution Duration P95: 0.245s
│  ├─ Error Rate: 0%
│  ├─ Active Workers: 2
│  └─ Other metrics
└─ Data retained:
   ├─ Traces: 15 days
   ├─ Metrics: 15 days
   └─ Logs: 7 days
```

---

## Data Retention Policy

| Backend | Data Type | Retention | Scrape Interval | Query Speed |
|---------|-----------|-----------|-----------------|-------------|
| **Tempo** | Traces | 15 days | Continuous push | ~100ms |
| **Prometheus** | Metrics | 15 days | Every 15 seconds | ~50ms |
| **Loki** | Logs | 7 days | Continuous push | ~1s |

---

## Quick Reference: Query Commands

### Tempo (Traces)
```powershell
# List all traces
Invoke-WebRequest -Uri "http://localhost:3200/api/search" | ConvertFrom-Json

# Get specific trace
Invoke-WebRequest -Uri "http://localhost:3200/api/traces/TRACE_ID" | ConvertFrom-Json
```

### Prometheus (Metrics)
```powershell
# Query active workers
Invoke-WebRequest -Uri "http://localhost:9090/api/v1/query?query=wd_otel_workers_active"

# Query errors
Invoke-WebRequest -Uri "http://localhost:9090/api/v1/query?query=wd_otel_errors_total"

# Calculate P95 latency
Invoke-WebRequest -Uri "http://localhost:9090/api/v1/query?query=histogram_quantile(0.95,sum(rate(langgraph_execution_duration_seconds_bucket[5m])))"
```

### Loki (Logs)
```powershell
# Query error logs
Invoke-WebRequest -Uri "http://localhost:3100/loki/api/v1/query?query={level=%22error%22}"

# Query by job
Invoke-WebRequest -Uri "http://localhost:3100/loki/api/v1/query?query={job=%22otel-agent-api%22}"

# Query time range
Invoke-WebRequest -Uri "http://localhost:3100/loki/api/v1/query_range?query={job=%22otel-agent-api%22}&start=START_TIME&end=END_TIME"
```

### Dashboard
```powershell
# Get traces via dashboard
Invoke-WebRequest -Uri "http://localhost:3001/api/traces"

# Get KPIs via dashboard
Invoke-WebRequest -Uri "http://localhost:3001/api/kpi"

# Check alert status
Invoke-WebRequest -Uri "http://localhost:3001/api/alerts/check"
```

---

## Storage Locations Summary

| Data | Backend | Port | Format | Retention | Access |
|------|---------|------|--------|-----------|--------|
| Traces | Tempo | 3200 | OTLP JSON | 15 days | `/api/search`, `/api/traces/{id}` |
| Metrics | Prometheus | 9090 | Time-series | 15 days | `/api/v1/query`, `/api/v1/query_range` |
| Logs | Loki | 3100 | Log streams | 7 days | `/loki/api/v1/query`, `/loki/api/v1/query_range` |
| Gateway | Dashboard | 3001 | REST APIs | Real-time | `/api/traces`, `/api/kpi`, `/api/alerts/check` |

---

## Performance Characteristics

**Query Performance**:
- **Traces**: Fast (100-200ms) - indexed by traceID
- **Metrics**: Very fast (50-100ms) - time-indexed
- **Logs**: Moderate (500ms-2s) - label-indexed with full-text search

**Storage Efficiency**:
- **Traces**: ~1-5 KB per trace (depends on span count)
- **Metrics**: ~100 bytes per data point
- **Logs**: ~500 bytes per log entry

**Network Overhead**:
- **Traces**: Batched gRPC (efficient binary protocol)
- **Metrics**: HTTP GET (minimal bandwidth)
- **Logs**: Batched HTTP push (minimal overhead)

---

## Troubleshooting

### Traces Not Appearing
1. Check Alloy on port 4317: `Test-NetConnection -ComputerName localhost -Port 4317`
2. Verify Tempo on port 3200: `Invoke-WebRequest -Uri http://localhost:3200/api/search`
3. Check OTLP export configuration in application

### Metrics Missing
1. Verify /metrics endpoint: `Invoke-WebRequest -Uri http://localhost:8080/metrics`
2. Check Prometheus targets: `http://localhost:9090/targets`
3. Wait 15 seconds for scrape interval

### Logs Not Appearing
1. Check application logging is enabled
2. Verify Loki on port 3100: `Invoke-WebRequest -Uri http://localhost:3100/api/prom/query?query={job="any"}`
3. Verify log push configuration

---

## References

- [Tempo Documentation](https://grafana.com/docs/tempo/)
- [Prometheus Documentation](https://prometheus.io/docs/)
- [Loki Documentation](https://grafana.com/docs/loki/)
- [OpenTelemetry](https://opentelemetry.io/)
- [OTLP Specification](https://opentelemetry.io/docs/specs/otel/protocol/)
