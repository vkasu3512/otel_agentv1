# Layer 3: Execution Engine — Revised Implementation Plan

> **Aligned to:** `otel_setup.py`, `TRACING_GUIDE.md`, existing codebase conventions
> **Language:** Python
> **Stack:** `init_otel()` → Tempo (OTLP gRPC) · PrometheusMetricReader · structlog → Loki via Alloy · Alertmanager · Grafana
> **Note:** All metrics use `get_meter()` from `otel_setup.py` → exported via `PrometheusMetricReader` → Prometheus scrapes the `/metrics` endpoint. OTel meter names are auto-prefixed with `otel_` by the Prometheus exporter (e.g. `meter.create_counter("runner.dispatch.failures")` becomes `otel_runner_dispatch_failures_total` in PromQL).

---

## 1. Shared Foundation (Already Exists — Reuse As-Is)

Your existing `otel_setup.py` provides everything needed. No changes required.

```python
# Every Layer 3 service starts the same way — BEFORE any other imports
from otel_setup import init_otel, get_tracer, get_meter

trace_provider, metrics_provider = init_otel(
    "runner-service",          # unique per service
    prometheus_port=8003,      # unique per service, avoid collision with MCP 8001/8002
)
tracer = get_tracer(__name__)
meter  = get_meter(__name__)
```

### Structured Logging (Loki)

`LoggingInstrumentor` in `init_otel()` already injects `otelTraceID` and `otelSpanID` into every Python log record. Alloy picks up container stdout and ships to Loki. For richer structured fields, add `structlog`:

```python
import structlog

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer(),
    ]
)
logger = structlog.get_logger(service="runner-service")
```

---

## 2. Runner Service

**Service name:** `runner-service`
**Prometheus port:** `8003`

### 2.1 Metrics via `get_meter()`

```python
meter = get_meter("runner.service")

dispatch_latency = meter.create_histogram(
    "runner.dispatch.latency",
    unit="s",
    description="Time from job received to dispatched",
)

queue_depth = meter.create_up_down_counter(
    "runner.queue.depth",
    unit="1",
    description="Current jobs waiting in queue",
)

dispatch_failures = meter.create_counter(
    "runner.dispatch.failures",
    unit="1",
    description="Total failed job dispatches",
)

job_timeouts = meter.create_counter(
    "runner.job.timeouts",
    unit="1",
    description="Total jobs that exceeded timeout",
)
```

**PromQL names after export:**

| Meter name | PromQL name |
|---|---|
| `runner.dispatch.latency` | `otel_runner_dispatch_latency_*` (histogram buckets) |
| `runner.queue.depth` | `otel_runner_queue_depth` |
| `runner.dispatch.failures` | `otel_runner_dispatch_failures_total` |
| `runner.job.timeouts` | `otel_runner_job_timeouts_total` |

### 2.2 Tracing — Span Hierarchy

```
runner.job                          ← parent span (full lifecycle)
  ├── runner.job.receive            ← job picked up from queue
  ├── runner.job.dispatch           ← routing to worker
  └── runner.job.complete           ← final status
```

```python
import time

async def process_job(job):
    start = time.perf_counter()

    with tracer.start_as_current_span("runner.job", attributes={
        "job.id": job.id,
        "job.type": job.type,
    }) as root:

        with tracer.start_as_current_span("runner.job.receive"):
            queue_depth.add(-1, {"job_type": job.type})

        with tracer.start_as_current_span("runner.job.dispatch") as dispatch_span:
            try:
                result = await dispatch_to_worker(job)
                dispatch_span.set_attribute("job.dispatch.target", result.worker_id)
            except Exception as e:
                dispatch_failures.add(1, {"job_type": job.type, "error_type": type(e).__name__})
                dispatch_span.record_exception(e)
                raise

        elapsed = time.perf_counter() - start
        dispatch_latency.record(elapsed, {"job_type": job.type})

        root.set_attribute("job.status", "completed")
        root.set_attribute("job.duration_s", round(elapsed, 3))

        logger.info("job_lifecycle_complete",
            job_id=job.id,
            job_type=job.type,
            status="completed",
            duration_s=round(elapsed, 3),
        )
```

### 2.3 Timeout Tracking

```python
async def execute_with_timeout(job, timeout_s: int = 300):
    try:
        return await asyncio.wait_for(process_job(job), timeout=timeout_s)
    except asyncio.TimeoutError:
        job_timeouts.add(1, {"job_type": job.type})
        logger.error("job_timeout",
            job_id=job.id,
            job_type=job.type,
            timeout_s=timeout_s,
        )
        raise
```

---

## 3. DW Orchestrator

**Service name:** `dw-orchestrator`
**Prometheus port:** `8004`

### 3.1 Metrics via `get_meter()`

```python
meter = get_meter("dw.orchestrator")

active_workers = meter.create_up_down_counter(
    "orchestrator.active.workers",
    unit="1",
    description="Currently active workers",
)

state_transitions = meter.create_counter(
    "orchestrator.state.transitions",
    unit="1",
    description="Worker state transitions",
)

orchestration_errors = meter.create_counter(
    "orchestrator.errors",
    unit="1",
    description="Total orchestration errors",
)

sync_failures = meter.create_counter(
    "orchestrator.sync.failures",
    unit="1",
    description="Status sync failures between orchestrator and API",
)
```

**PromQL names after export:**

| Meter name | PromQL name |
|---|---|
| `orchestrator.active.workers` | `otel_orchestrator_active_workers` |
| `orchestrator.state.transitions` | `otel_orchestrator_state_transitions_total` |
| `orchestrator.errors` | `otel_orchestrator_errors_total` |
| `orchestrator.sync.failures` | `otel_orchestrator_sync_failures_total` |

### 3.2 Tracing — Span Hierarchy

```
orchestrator.worker.lifecycle       ← parent span (full worker lifecycle)
  ├── orchestrator.transition       ← each state change
  ├── orchestrator.transition       ← ...
  └── orchestrator.sync             ← status sync to API
```

```python
async def transition_worker(worker, new_state: str):
    with tracer.start_as_current_span("orchestrator.transition", attributes={
        "worker.id": worker.id,
        "worker.type": worker.type,
        "worker.from_state": worker.state,
        "worker.to_state": new_state,
    }) as span:
        prev = worker.state

        try:
            await worker.apply_transition(new_state)

            state_transitions.add(1, {
                "worker_type": worker.type,
                "from_state": prev,
                "to_state": new_state,
            })

            if new_state == "running":
                active_workers.add(1, {"worker_type": worker.type})
            elif new_state in ("completed", "error"):
                active_workers.add(-1, {"worker_type": worker.type})

            span.add_event("state_changed", {"previous": prev, "current": new_state})

        except Exception as e:
            orchestration_errors.add(1, {
                "error_type": type(e).__name__,
                "worker_type": worker.type,
            })
            span.record_exception(e)
            raise

        logger.info("worker_state_transition",
            worker_id=worker.id,
            worker_type=worker.type,
            from_state=prev,
            to_state=new_state,
        )
```

### 3.3 Sync Failure Tracking

```python
async def sync_status_to_api(worker):
    with tracer.start_as_current_span("orchestrator.sync", attributes={
        "worker.id": worker.id,
    }) as span:
        try:
            await api_client.push_status(worker)
        except Exception as e:
            sync_failures.add(1, {"failure_type": "websocket_desync"})
            span.record_exception(e)
            logger.error("status_sync_failure",
                worker_id=worker.id,
                failure_type="websocket_desync",
            )
            raise
```

---

## 4. Worker Runner (LangGraph)

**Service name:** `worker-runner`
**Prometheus port:** `8005`

This follows the same pattern as your `mcp_tool_instrumented.py` LangGraph nodes — each node gets its own child span.

### 4.1 Metrics via `get_meter()`

```python
meter = get_meter("worker.runner")

graph_build_time = meter.create_histogram(
    "langgraph.build.duration",
    unit="s",
    description="Time to construct execution graph",
)

step_total = meter.create_counter(
    "langgraph.step.total",
    unit="1",
    description="Total graph node executions",
)

execution_duration = meter.create_histogram(
    "langgraph.execution.duration",
    unit="s",
    description="Total duration of full graph run",
)

step_retries = meter.create_counter(
    "langgraph.step.retries",
    unit="1",
    description="Total step retry attempts",
)
```

**PromQL names after export:**

| Meter name | PromQL name |
|---|---|
| `langgraph.build.duration` | `otel_langgraph_build_duration_*` (histogram) |
| `langgraph.step.total` | `otel_langgraph_step_total` |
| `langgraph.execution.duration` | `otel_langgraph_execution_duration_*` (histogram) |
| `langgraph.step.retries` | `otel_langgraph_step_retries_total` |

### 4.2 Tracing — Span Hierarchy

Mirrors your existing `mcp_tool_instrumented.py` pattern exactly:

```
worker.runner.execution             ← parent span (full graph run)
  ├── worker.runner.build           ← graph construction
  ├── langgraph_node.<name>         ← per-node (same pattern as your parse/evaluate/format nodes)
  ├── langgraph_node.<name>
  └── langgraph_node.<name>
```

```python
import time

async def run_worker_graph(worker, graph):
    start = time.perf_counter()

    with tracer.start_as_current_span("worker.runner.execution", attributes={
        "worker.id": worker.id,
        "worker.type": worker.type,
        "graph.node_count": len(graph.nodes),
    }) as root:

        # Graph build phase
        with tracer.start_as_current_span("worker.runner.build") as build_span:
            build_start = time.perf_counter()
            compiled_graph = graph.compile()
            build_elapsed = time.perf_counter() - build_start
            graph_build_time.record(build_elapsed, {"worker_type": worker.type})
            build_span.set_attribute("build.duration_s", round(build_elapsed, 3))

        # Execute — node-level spans created inside each LangGraph node
        # (same pattern as your parse_node / evaluate_node / format_node)
        result = compiled_graph.invoke(initial_state)

        elapsed = time.perf_counter() - start
        execution_duration.record(elapsed, {"worker_type": worker.type})

        root.set_attribute("execution.duration_s", round(elapsed, 3))
        root.set_attribute("execution.status", "completed" if not result.get("error") else "failed")

        logger.info("graph_execution_complete",
            worker_id=worker.id,
            worker_type=worker.type,
            duration_s=round(elapsed, 3),
            node_count=len(graph.nodes),
        )

    return result
```

### 4.3 Node-Level Instrumentation (Your Existing Pattern)

Each LangGraph node follows the same pattern as your `parse_node`, `evaluate_node`, `format_node`:

```python
def my_node(state: WorkerState) -> dict:
    with tracer.start_as_current_span("langgraph_node.my_node") as span:
        span.set_attribute("input", str(state["input"]))

        try:
            result = do_work(state)
            step_total.add(1, {"node": "my_node", "status": "success"})
            span.set_attribute("status", "success")
            return result
        except Exception as e:
            step_total.add(1, {"node": "my_node", "status": "failure"})
            span.record_exception(e)
            span.set_attribute("status", "failure")
            raise
```

### 4.4 Retry Wrapper

```python
import asyncio

async def run_node_with_retry(node_fn, state, max_retries=3):
    node_name = node_fn.__name__
    for attempt in range(max_retries + 1):
        try:
            return node_fn(state)
        except Exception as e:
            if attempt < max_retries:
                step_retries.add(1, {"node": node_name})
                logger.warning("node_retry",
                    node=node_name,
                    attempt=attempt + 1,
                    max_retries=max_retries,
                    error=str(e),
                )
                await asyncio.sleep(2 ** attempt)  # exponential backoff
            else:
                raise
```

---

## 5. Alertmanager Rules

All PromQL uses `otel_` prefixed names from PrometheusMetricReader.

**File:** `layer3_alerts.yml`

```yaml
groups:
  - name: layer3_runner_service
    rules:
      # P1: No jobs dispatching at all
      - alert: RunnerAllJobsFailing
        expr: >
          rate(otel_runner_dispatch_failures_total[5m]) > 0
          AND rate(otel_runner_dispatch_latency_count[5m]) == 0
        for: 2m
        labels:
          severity: p1
        annotations:
          summary: "Runner Service — no jobs dispatching, all failing"

      # P2: >5% dispatch failure rate
      - alert: RunnerHighFailureRate
        expr: >
          rate(otel_runner_dispatch_failures_total[5m])
          / rate(otel_runner_dispatch_latency_count[5m])
          > 0.05
        for: 5m
        labels:
          severity: p2
        annotations:
          summary: "Runner Service — dispatch failure rate >5%"

      # P2: Queue depth spike
      - alert: RunnerQueueBacklog
        expr: otel_runner_queue_depth > 100
        for: 5m
        labels:
          severity: p2
        annotations:
          summary: "Runner Service — job queue depth exceeds threshold"

      # P3: Elevated timeout rate
      - alert: RunnerJobTimeouts
        expr: rate(otel_runner_job_timeouts_total[10m]) > 0.02
        for: 10m
        labels:
          severity: p3
        annotations:
          summary: "Runner Service — elevated job timeout rate"

  - name: layer3_orchestrator
    rules:
      # P1: Orchestrator error spike
      - alert: OrchestratorErrorSpike
        expr: rate(otel_orchestrator_errors_total[5m]) > 0.1
        for: 2m
        labels:
          severity: p1
        annotations:
          summary: "DW Orchestrator — error rate spiking"

      # P2: Sync failures
      - alert: OrchestratorSyncFailures
        expr: rate(otel_orchestrator_sync_failures_total[5m]) > 0
        for: 5m
        labels:
          severity: p2
        annotations:
          summary: "DW Orchestrator — status sync failures detected"

      # P3: Workers stuck in intermediate state
      - alert: OrchestratorStuckWorkers
        expr: >
          otel_orchestrator_active_workers > 0
          AND rate(otel_orchestrator_state_transitions_total[15m]) == 0
        for: 15m
        labels:
          severity: p3
        annotations:
          summary: "DW Orchestrator — workers stuck in intermediate state"

  - name: layer3_langgraph
    rules:
      # P2: High node failure rate
      - alert: LangGraphNodeFailureSpike
        expr: >
          rate(otel_langgraph_step_total{status="failure"}[5m])
          / rate(otel_langgraph_step_total[5m])
          > 0.05
        for: 5m
        labels:
          severity: p2
        annotations:
          summary: "Worker Runner — node failure rate >5% for {{ $labels.node }}"

      # P3: Elevated retry count
      - alert: LangGraphHighRetries
        expr: rate(otel_langgraph_step_retries_total[10m]) > 0.1
        for: 10m
        labels:
          severity: p3
        annotations:
          summary: "Worker Runner — elevated retry rate on {{ $labels.node }}"

      # P3: Slow execution (p95 > 2 min)
      - alert: LangGraphSlowExecution
        expr: >
          histogram_quantile(0.95,
            rate(otel_langgraph_execution_duration_bucket[10m])
          ) > 120
        for: 10m
        labels:
          severity: p3
        annotations:
          summary: "Worker Runner — p95 execution duration >2min"
```

### Alertmanager Routing

```yaml
# alertmanager.yml
route:
  receiver: default
  group_by: [alertname, severity]
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h
  routes:
    - match:
        severity: p1
      receiver: ops-immediate
      repeat_interval: 15m
    - match:
        severity: p2
      receiver: ops-15min
      repeat_interval: 1h
    - match:
        severity: p3
      receiver: ops-1hour
      repeat_interval: 4h
    - match:
        severity: p4
      receiver: ops-weekly-digest

receivers:
  - name: default
  - name: ops-immediate
    # PagerDuty / Teams webhook → Ops → Dev Lead → Platform Owner
  - name: ops-15min
    # Teams webhook / email → Ops → Dev On-Call
  - name: ops-1hour
    # email → Ops → Dev (next business day if non-critical)
  - name: ops-weekly-digest
    # email digest → Ops → Dev (sprint backlog)
```

---

## 6. Grafana Dashboard

### 6.1 Panel Layout

Single dashboard: **"Layer 3 — Execution Engine"**

```
Row 1: Runner Service
  ├── Dispatch Latency p50/p95/p99    (Prometheus histogram)
  ├── Queue Depth                     (Prometheus up-down counter)
  ├── Dispatch Failure Rate           (Prometheus counter rate)
  └── Job Timeouts                    (Prometheus counter rate)

Row 2: DW Orchestrator
  ├── Active Workers                  (Prometheus up-down counter)
  ├── State Transitions/min           (Prometheus counter rate, stacked)
  ├── Orchestration Error Rate        (Prometheus counter rate)
  └── Sync Failures                   (Prometheus counter rate)

Row 3: Worker Runner (LangGraph)
  ├── Graph Build Time p50/p95        (Prometheus histogram)
  ├── Node Success/Failure Rate       (Prometheus counter rate, stacked)
  ├── Execution Duration p50/p95/p99  (Prometheus histogram)
  └── Retry Rate by Node              (Prometheus counter rate)
```

### 6.2 Provisioning JSON

**File:** `layer3-execution-engine.json`

```json
{
  "dashboard": {
    "title": "Layer 3 — Execution Engine",
    "uid": "layer3-execution-engine",
    "tags": ["dw-hq", "layer3", "execution-engine"],
    "timezone": "browser",
    "refresh": "30s",
    "templating": {
      "list": [
        {
          "name": "job_type",
          "type": "query",
          "datasource": "Prometheus",
          "query": "label_values(otel_runner_dispatch_latency_bucket, job_type)"
        },
        {
          "name": "worker_type",
          "type": "query",
          "datasource": "Prometheus",
          "query": "label_values(otel_orchestrator_active_workers, worker_type)"
        },
        {
          "name": "node",
          "type": "query",
          "datasource": "Prometheus",
          "query": "label_values(otel_langgraph_step_total, node)"
        }
      ]
    },
    "panels": [
      {
        "title": "— Runner Service —",
        "type": "row",
        "gridPos": { "h": 1, "w": 24, "x": 0, "y": 0 }
      },
      {
        "title": "Dispatch Latency",
        "type": "timeseries",
        "datasource": "Prometheus",
        "gridPos": { "h": 8, "w": 6, "x": 0, "y": 1 },
        "fieldConfig": {
          "defaults": { "unit": "s" }
        },
        "targets": [
          { "expr": "histogram_quantile(0.50, rate(otel_runner_dispatch_latency_bucket{job_type=~\"$job_type\"}[5m]))", "legendFormat": "p50" },
          { "expr": "histogram_quantile(0.95, rate(otel_runner_dispatch_latency_bucket{job_type=~\"$job_type\"}[5m]))", "legendFormat": "p95" },
          { "expr": "histogram_quantile(0.99, rate(otel_runner_dispatch_latency_bucket{job_type=~\"$job_type\"}[5m]))", "legendFormat": "p99" }
        ]
      },
      {
        "title": "Queue Depth",
        "type": "timeseries",
        "datasource": "Prometheus",
        "gridPos": { "h": 8, "w": 6, "x": 6, "y": 1 },
        "targets": [
          { "expr": "otel_runner_queue_depth{job_type=~\"$job_type\"}", "legendFormat": "{{ job_type }}" }
        ]
      },
      {
        "title": "Dispatch Failure Rate",
        "type": "timeseries",
        "datasource": "Prometheus",
        "gridPos": { "h": 8, "w": 6, "x": 12, "y": 1 },
        "fieldConfig": {
          "defaults": { "unit": "ops" }
        },
        "targets": [
          { "expr": "rate(otel_runner_dispatch_failures_total{job_type=~\"$job_type\"}[5m])", "legendFormat": "{{ job_type }} — {{ error_type }}" }
        ]
      },
      {
        "title": "Job Timeouts",
        "type": "timeseries",
        "datasource": "Prometheus",
        "gridPos": { "h": 8, "w": 6, "x": 18, "y": 1 },
        "fieldConfig": {
          "defaults": { "unit": "ops" }
        },
        "targets": [
          { "expr": "rate(otel_runner_job_timeouts_total{job_type=~\"$job_type\"}[5m])", "legendFormat": "{{ job_type }}" }
        ]
      },
      {
        "title": "— DW Orchestrator —",
        "type": "row",
        "gridPos": { "h": 1, "w": 24, "x": 0, "y": 9 }
      },
      {
        "title": "Active Workers",
        "type": "timeseries",
        "datasource": "Prometheus",
        "gridPos": { "h": 8, "w": 6, "x": 0, "y": 10 },
        "targets": [
          { "expr": "otel_orchestrator_active_workers{worker_type=~\"$worker_type\"}", "legendFormat": "{{ worker_type }}" }
        ]
      },
      {
        "title": "State Transitions / min",
        "type": "timeseries",
        "datasource": "Prometheus",
        "gridPos": { "h": 8, "w": 6, "x": 6, "y": 10 },
        "targets": [
          { "expr": "rate(otel_orchestrator_state_transitions_total{worker_type=~\"$worker_type\"}[5m]) * 60", "legendFormat": "{{ from_state }}→{{ to_state }}" }
        ]
      },
      {
        "title": "Orchestration Error Rate",
        "type": "timeseries",
        "datasource": "Prometheus",
        "gridPos": { "h": 8, "w": 6, "x": 12, "y": 10 },
        "fieldConfig": {
          "defaults": { "unit": "ops" }
        },
        "targets": [
          { "expr": "rate(otel_orchestrator_errors_total{worker_type=~\"$worker_type\"}[5m])", "legendFormat": "{{ error_type }}" }
        ]
      },
      {
        "title": "Sync Failures",
        "type": "timeseries",
        "datasource": "Prometheus",
        "gridPos": { "h": 8, "w": 6, "x": 18, "y": 10 },
        "fieldConfig": {
          "defaults": { "unit": "ops" }
        },
        "targets": [
          { "expr": "rate(otel_orchestrator_sync_failures_total[5m])", "legendFormat": "{{ failure_type }}" }
        ]
      },
      {
        "title": "— Worker Runner (LangGraph) —",
        "type": "row",
        "gridPos": { "h": 1, "w": 24, "x": 0, "y": 18 }
      },
      {
        "title": "Graph Build Time",
        "type": "timeseries",
        "datasource": "Prometheus",
        "gridPos": { "h": 8, "w": 6, "x": 0, "y": 19 },
        "fieldConfig": {
          "defaults": { "unit": "s" }
        },
        "targets": [
          { "expr": "histogram_quantile(0.50, rate(otel_langgraph_build_duration_bucket{worker_type=~\"$worker_type\"}[5m]))", "legendFormat": "p50" },
          { "expr": "histogram_quantile(0.95, rate(otel_langgraph_build_duration_bucket{worker_type=~\"$worker_type\"}[5m]))", "legendFormat": "p95" }
        ]
      },
      {
        "title": "Node Success / Failure Rate",
        "type": "timeseries",
        "datasource": "Prometheus",
        "gridPos": { "h": 8, "w": 6, "x": 6, "y": 19 },
        "fieldConfig": {
          "defaults": { "unit": "ops" }
        },
        "targets": [
          { "expr": "rate(otel_langgraph_step_total{node=~\"$node\", status=\"success\"}[5m])", "legendFormat": "{{ node }} ✓" },
          { "expr": "rate(otel_langgraph_step_total{node=~\"$node\", status=\"failure\"}[5m])", "legendFormat": "{{ node }} ✗" }
        ]
      },
      {
        "title": "Execution Duration",
        "type": "timeseries",
        "datasource": "Prometheus",
        "gridPos": { "h": 8, "w": 6, "x": 12, "y": 19 },
        "fieldConfig": {
          "defaults": { "unit": "s" }
        },
        "targets": [
          { "expr": "histogram_quantile(0.50, rate(otel_langgraph_execution_duration_bucket{worker_type=~\"$worker_type\"}[5m]))", "legendFormat": "p50" },
          { "expr": "histogram_quantile(0.95, rate(otel_langgraph_execution_duration_bucket{worker_type=~\"$worker_type\"}[5m]))", "legendFormat": "p95" },
          { "expr": "histogram_quantile(0.99, rate(otel_langgraph_execution_duration_bucket{worker_type=~\"$worker_type\"}[5m]))", "legendFormat": "p99" }
        ]
      },
      {
        "title": "Retry Rate by Node",
        "type": "timeseries",
        "datasource": "Prometheus",
        "gridPos": { "h": 8, "w": 6, "x": 18, "y": 19 },
        "fieldConfig": {
          "defaults": { "unit": "ops" }
        },
        "targets": [
          { "expr": "rate(otel_langgraph_step_retries_total{node=~\"$node\"}[5m])", "legendFormat": "{{ node }}" }
        ]
      }
    ]
  }
}
```

### 6.3 Datasource Cross-Linking

Same as your existing Grafana stack config — ensures metric→trace→log navigation:

```yaml
# datasources/prometheus.yml
apiVersion: 1
datasources:
  - name: Prometheus
    type: prometheus
    url: http://prometheus:9090
    jsonData:
      exemplarTraceIdDestinations:
        - name: traceID
          datasourceUid: tempo

# datasources/loki.yml
  - name: Loki
    type: loki
    url: http://loki:3100
    jsonData:
      derivedFields:
        - datasourceUid: tempo
          matcherRegex: "trace_id=(\\w+)"
          name: TraceID
          url: "$${__value.raw}"

# datasources/tempo.yml
  - name: Tempo
    type: tempo
    uid: tempo
    url: http://tempo:3200
    jsonData:
      tracesToLogsV2:
        datasourceUid: loki
        filterByTraceID: true
      tracesToMetrics:
        datasourceUid: prometheus
```

---

## 7. Implementation Order

| Phase | Scope | Effort | Dependencies |
|---|---|---|---|
| **Phase 1** | Add `structlog` to existing `requirements.txt`; assign prometheus ports per service (8003/8004/8005) | 0.5 day | — |
| **Phase 2** | Runner Service — `init_otel("runner-service")`, metrics, spans, structured logs | 2 days | Phase 1 |
| **Phase 3** | DW Orchestrator — `init_otel("dw-orchestrator")`, metrics, spans, structured logs | 2 days | Phase 1 |
| **Phase 4** | Worker Runner — `init_otel("worker-runner")`, metrics, spans (reuse existing LangGraph node pattern) | 2 days | Phase 1 |
| **Phase 5** | Alertmanager rules (`layer3_alerts.yml`) + routing config | 1 day | Phases 2–4 |
| **Phase 6** | Grafana dashboard provisioning JSON + verify cross-linking | 1 day | Phase 5 |
| **Phase 7** | End-to-end validation — trigger jobs, verify metric→trace→log in Grafana | 1 day | Phase 6 |

**Total estimate: ~9–10 days**

---

## 8. Key Differences from Previous Plan

| Item | Previous Plan | Revised Plan |
|---|---|---|
| Metrics library | `prometheus_client` directly | `get_meter()` via `PrometheusMetricReader` from `otel_setup.py` |
| PromQL metric names | `runner_dispatch_failures_total` | `otel_runner_dispatch_failures_total` (auto `otel_` prefix) |
| Tracer init | Generic `TracerProvider` setup | Reuses `init_otel()` with `FilteringSpanExporter` |
| Span naming | Generic | Follows `service.operation` convention from your codebase |
| LangGraph nodes | New pattern | Mirrors existing `parse_node`/`evaluate_node`/`format_node` pattern |
| Logging | New `structlog` setup | `LoggingInstrumentor` already active via `init_otel()`, `structlog` adds structured fields |
| Prometheus ports | Not specified | Unique per service: 8003/8004/8005 (avoids collision with MCP 8001/8002) |
| Effort | 10–16 days | 9–10 days (foundation already exists) |
