# Layer 4: Data & AI — Implementation Plan

> **Aligned to:** `otel_setup.py`, `TRACING_GUIDE.md`, existing codebase conventions
> **Language:** Python
> **Stack:** `init_otel()` → Tempo (OTLP gRPC) · PrometheusMetricReader · structlog → Loki via Alloy · Alertmanager · Grafana
> **Components:** MS SQL Server · AWS Bedrock / AI Assistant · Novi Chatbot / Orchestrator
> **Note:** All metrics use `get_meter()` → `PrometheusMetricReader` → auto `otel_` prefix in PromQL.

---

## 1. MS SQL Server

**Service name:** `mssql-monitor`
**Prometheus port:** `8006`

MS SQL is external infrastructure — you don't instrument its internals. Instead, instrument the Python DB access layer and use `sql_exporter` for DMV-level metrics.

### 1.1 Metrics via `get_meter()`

These cover the Python application's view of the database:

```python
from otel_setup import init_otel, get_tracer, get_meter

trace_provider, metrics_provider = init_otel("mssql-monitor", prometheus_port=8006)
tracer = get_tracer(__name__)
meter  = get_meter("mssql.monitor")

query_duration = meter.create_histogram(
    "mssql.query.duration",
    unit="s",
    description="Query execution time as seen by the application",
)

connection_pool_usage = meter.create_up_down_counter(
    "mssql.connection.pool.active",
    unit="1",
    description="Currently active connections from the pool",
)

connection_pool_size = meter.create_up_down_counter(
    "mssql.connection.pool.size",
    unit="1",
    description="Total pool size (active + idle)",
)

deadlock_count = meter.create_counter(
    "mssql.deadlocks",
    unit="1",
    description="Deadlocks encountered by the application",
)

slow_queries = meter.create_counter(
    "mssql.slow.queries",
    unit="1",
    description="Queries exceeding SLA budget",
)
```

**PromQL names after export:**

| Meter name | PromQL name |
|---|---|
| `mssql.query.duration` | `otel_mssql_query_duration_*` (histogram) |
| `mssql.connection.pool.active` | `otel_mssql_connection_pool_active` |
| `mssql.connection.pool.size` | `otel_mssql_connection_pool_size` |
| `mssql.deadlocks` | `otel_mssql_deadlocks_total` |
| `mssql.slow.queries` | `otel_mssql_slow_queries_total` |

### 1.2 External Metrics via `sql_exporter`

For DMV-level metrics that the Python app can't see (index fragmentation, table growth, internal waits), use [`sql_exporter`](https://github.com/burningalchemist/sql_exporter) as a sidecar. It runs its own `/metrics` endpoint that Prometheus scrapes directly.

```yaml
# sql_exporter config snippet — these metrics appear WITHOUT otel_ prefix
# since they bypass PrometheusMetricReader
collector_name: mssql
metrics:
  - metric_name: mssql_index_fragmentation_percent
    type: gauge
    help: "Average fragmentation percentage per index"
    values: [fragmentation]
    query: |
      SELECT
        OBJECT_NAME(ips.object_id) AS table_name,
        i.name AS index_name,
        ips.avg_fragmentation_in_percent AS fragmentation
      FROM sys.dm_db_index_physical_stats(DB_ID(), NULL, NULL, NULL, 'LIMITED') ips
      JOIN sys.indexes i ON ips.object_id = i.object_id AND ips.index_id = i.index_id
      WHERE ips.avg_fragmentation_in_percent > 10

  - metric_name: mssql_table_row_count
    type: gauge
    help: "Approximate row count per table"
    values: [row_count]
    query: |
      SELECT
        OBJECT_NAME(object_id) AS table_name,
        SUM(rows) AS row_count
      FROM sys.partitions
      WHERE index_id IN (0, 1)
      GROUP BY object_id
```

### 1.3 Tracing — Span Hierarchy

```
mssql.query                         ← parent span per DB call
  └── (query execution)             ← attributes capture query metadata
```

```python
import time

SLOW_QUERY_THRESHOLD_S = 1.0  # 1 second SLA budget

async def execute_query(pool, query: str, params: dict = None, operation: str = "query"):
    start = time.perf_counter()

    with tracer.start_as_current_span("mssql.query", attributes={
        "db.system": "mssql",
        "db.operation": operation,
        "db.statement.summary": query[:100],  # truncated — never log full query with params
    }) as span:
        conn = None
        try:
            conn = await pool.acquire()
            connection_pool_usage.add(1)

            result = await conn.execute(query, params)
            elapsed = time.perf_counter() - start

            query_duration.record(elapsed, {"operation": operation})
            span.set_attribute("db.duration_s", round(elapsed, 3))
            span.set_attribute("db.row_count", result.rowcount if result.rowcount else 0)

            if elapsed > SLOW_QUERY_THRESHOLD_S:
                slow_queries.add(1, {"operation": operation})
                span.add_event("slow_query", {"threshold_s": SLOW_QUERY_THRESHOLD_S})
                logger.warning("slow_query_detected",
                    operation=operation,
                    duration_s=round(elapsed, 3),
                    threshold_s=SLOW_QUERY_THRESHOLD_S,
                )

            return result

        except Exception as e:
            elapsed = time.perf_counter() - start
            query_duration.record(elapsed, {"operation": operation})
            span.record_exception(e)

            if "deadlock" in str(e).lower():
                deadlock_count.add(1, {"operation": operation})
                logger.error("deadlock_detected", operation=operation)

            raise
        finally:
            if conn:
                await pool.release(conn)
                connection_pool_usage.add(-1)
```

### 1.4 Structured Logging

```python
logger.info("query_executed",
    operation=operation,
    duration_s=round(elapsed, 3),
    row_count=result.rowcount,
)
```

---

## 2. AWS Bedrock / AI Assistant

**Service name:** `bedrock-ai`
**Prometheus port:** `8007`

This extends your existing Bedrock tracing pattern from `agent_auto_multiple.py`. The key addition is token cost tracking and retry/throttle metrics.

### 2.1 Metrics via `get_meter()`

```python
from otel_setup import init_otel, get_tracer, get_meter

trace_provider, metrics_provider = init_otel("bedrock-ai", prometheus_port=8007)
tracer = get_tracer(__name__)
meter  = get_meter("bedrock.ai")

bedrock_call_duration = meter.create_histogram(
    "bedrock.call.duration",
    unit="s",
    description="Bedrock API call latency",
)

bedrock_tokens_input = meter.create_counter(
    "bedrock.tokens.input",
    unit="1",
    description="Total input tokens consumed",
)

bedrock_tokens_output = meter.create_counter(
    "bedrock.tokens.output",
    unit="1",
    description="Total output tokens consumed",
)

bedrock_errors = meter.create_counter(
    "bedrock.errors",
    unit="1",
    description="Bedrock API errors (throttling, timeouts, failures)",
)

bedrock_calls = meter.create_counter(
    "bedrock.calls",
    unit="1",
    description="Total Bedrock API calls",
)

lambda_proxy_duration = meter.create_histogram(
    "bedrock.lambda.proxy.duration",
    unit="s",
    description="Lambda proxy response time (if using Lambda intermediary)",
)
```

**PromQL names after export:**

| Meter name | PromQL name |
|---|---|
| `bedrock.call.duration` | `otel_bedrock_call_duration_*` (histogram) |
| `bedrock.tokens.input` | `otel_bedrock_tokens_input_total` |
| `bedrock.tokens.output` | `otel_bedrock_tokens_output_total` |
| `bedrock.errors` | `otel_bedrock_errors_total` |
| `bedrock.calls` | `otel_bedrock_calls_total` |
| `bedrock.lambda.proxy.duration` | `otel_bedrock_lambda_proxy_duration_*` (histogram) |

### 2.2 Tracing — Span Hierarchy

Extends your existing pattern from `agent_auto_multiple.py`:

```
bedrock.invoke                      ← parent span per LLM call
  └── bedrock.retry (if retried)    ← child span per retry attempt
```

```python
import time
import asyncio

async def invoke_bedrock(model_id: str, prompt: str, max_retries: int = 3):
    start = time.perf_counter()

    with tracer.start_as_current_span("bedrock.invoke", attributes={
        "llm.model": model_id,
        "llm.prompt.length": len(prompt),
    }) as span:
        last_error = None

        for attempt in range(max_retries + 1):
            try:
                if attempt > 0:
                    with tracer.start_as_current_span("bedrock.retry", attributes={
                        "retry.attempt": attempt,
                    }):
                        await asyncio.sleep(2 ** attempt)

                response = await bedrock_client.invoke_model(
                    modelId=model_id,
                    body=build_request_body(prompt),
                )

                elapsed = time.perf_counter() - start
                usage = response.get("usage", {})
                input_tokens = usage.get("input_tokens", 0)
                output_tokens = usage.get("output_tokens", 0)

                # Span attributes — mirrors your existing pattern
                span.set_attribute("llm.tokens.input", input_tokens)
                span.set_attribute("llm.tokens.output", output_tokens)
                span.set_attribute("llm.status", "success")
                span.set_attribute("llm.duration_s", round(elapsed, 3))

                # Metrics
                bedrock_call_duration.record(elapsed, {"model": model_id})
                bedrock_tokens_input.add(input_tokens, {"model": model_id, "service": "bedrock"})
                bedrock_tokens_output.add(output_tokens, {"model": model_id, "service": "bedrock"})
                bedrock_calls.add(1, {"model": model_id, "status": "success"})

                logger.info("bedrock_call_success",
                    model=model_id,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    duration_s=round(elapsed, 3),
                )

                return response

            except Exception as e:
                last_error = e
                error_type = _classify_bedrock_error(e)

                bedrock_errors.add(1, {"model": model_id, "error_type": error_type})
                span.add_event("error", {
                    "attempt": attempt,
                    "error_type": error_type,
                    "error_message": str(e),
                })

                if error_type != "throttling" or attempt == max_retries:
                    span.set_attribute("llm.status", "failure")
                    span.record_exception(e)

                    bedrock_calls.add(1, {"model": model_id, "status": "failure"})
                    logger.error("bedrock_call_failed",
                        model=model_id,
                        error_type=error_type,
                        attempt=attempt,
                    )
                    raise

        raise last_error


def _classify_bedrock_error(e: Exception) -> str:
    """Classify Bedrock errors for metric labels."""
    error_str = str(e).lower()
    if "throttl" in error_str or "rate" in error_str:
        return "throttling"
    elif "timeout" in error_str:
        return "timeout"
    elif "validation" in error_str:
        return "validation"
    else:
        return "unknown"
```

### 2.3 Lambda Proxy Instrumentation (If Applicable)

If Bedrock calls go through a Lambda proxy:

```python
async def invoke_via_lambda(payload: dict):
    start = time.perf_counter()

    with tracer.start_as_current_span("bedrock.lambda.proxy", attributes={
        "lambda.function": "bedrock-proxy",
    }) as span:
        response = await lambda_client.invoke(FunctionName="bedrock-proxy", Payload=payload)
        elapsed = time.perf_counter() - start

        lambda_proxy_duration.record(elapsed)
        span.set_attribute("lambda.duration_s", round(elapsed, 3))
        span.set_attribute("lambda.status", response["StatusCode"])

        if response["StatusCode"] != 200:
            span.add_event("lambda_cold_start_suspected" if elapsed > 5 else "lambda_error")

        return response
```

---

## 3. Novi Chatbot / Orchestrator

**Service name:** `novi-chatbot`
**Prometheus port:** `8008`

Novi is a multi-turn conversational agent. The tracing pattern extends your multi-agent setup from `agent_auto_multiple.py`, with the addition of session-level tracking and skill matching.

### 3.1 Metrics via `get_meter()`

```python
from otel_setup import init_otel, get_tracer, get_meter

trace_provider, metrics_provider = init_otel("novi-chatbot", prometheus_port=8008)
tracer = get_tracer(__name__)
meter  = get_meter("novi.chatbot")

skill_match_total = meter.create_counter(
    "novi.skill.match.total",
    unit="1",
    description="Skill match attempts",
)

intent_resolution = meter.create_counter(
    "novi.intent.resolution",
    unit="1",
    description="Intent resolution outcomes",
)

session_errors = meter.create_counter(
    "novi.session.errors",
    unit="1",
    description="Chatbot session errors",
)

canvas_generation = meter.create_counter(
    "novi.canvas.generation",
    unit="1",
    description="Canvas generation attempts",
)

canvas_duration = meter.create_histogram(
    "novi.canvas.duration",
    unit="s",
    description="Canvas generation duration",
)

turn_duration = meter.create_histogram(
    "novi.turn.duration",
    unit="s",
    description="Per-turn response latency",
)

session_turns = meter.create_histogram(
    "novi.session.turns",
    unit="1",
    description="Number of turns per session",
)
```

**PromQL names after export:**

| Meter name | PromQL name |
|---|---|
| `novi.skill.match.total` | `otel_novi_skill_match_total` |
| `novi.intent.resolution` | `otel_novi_intent_resolution_total` |
| `novi.session.errors` | `otel_novi_session_errors_total` |
| `novi.canvas.generation` | `otel_novi_canvas_generation_total` |
| `novi.canvas.duration` | `otel_novi_canvas_duration_*` (histogram) |
| `novi.turn.duration` | `otel_novi_turn_duration_*` (histogram) |
| `novi.session.turns` | `otel_novi_session_turns_*` (histogram) |

### 3.2 Tracing — Span Hierarchy

```
novi.session                        ← parent span (full conversation session)
  ├── novi.turn                     ← per-turn span
  │   ├── novi.intent.resolve       ← intent classification
  │   ├── novi.skill.match          ← skill catalog lookup
  │   ├── bedrock.invoke            ← LLM call (reuses Bedrock instrumentation)
  │   └── novi.canvas.generate      ← canvas output (if applicable)
  ├── novi.turn                     ← next turn
  │   └── ...
  └── novi.turn
```

```python
import time
import uuid

async def handle_session(session_id: str, messages: list[dict]):
    with tracer.start_as_current_span("novi.session", attributes={
        "session.id": session_id,
        "session.turn_count": len(messages),
    }) as session_span:

        turn_count = 0
        for msg in messages:
            turn_count += 1
            await handle_turn(session_id, msg, turn_count)

        session_turns.record(turn_count, {"session_id": session_id})
        session_span.set_attribute("session.total_turns", turn_count)


async def handle_turn(session_id: str, message: dict, turn_number: int):
    start = time.perf_counter()

    with tracer.start_as_current_span("novi.turn", attributes={
        "session.id": session_id,
        "turn.number": turn_number,
        "turn.user_input": message.get("text", "")[:200],  # truncated
    }) as turn_span:
        try:
            # Step 1: Intent resolution
            intent = await resolve_intent(message)

            # Step 2: Skill matching
            skill = await match_skill(intent)

            # Step 3: Execute skill (includes Bedrock call)
            response = await execute_skill(skill, message)

            # Step 4: Canvas generation (if applicable)
            if skill.requires_canvas:
                await generate_canvas(response)

            elapsed = time.perf_counter() - start
            turn_duration.record(elapsed, {"skill": skill.name})
            turn_span.set_attribute("turn.duration_s", round(elapsed, 3))
            turn_span.set_attribute("turn.skill", skill.name)

        except Exception as e:
            session_errors.add(1, {"error_type": type(e).__name__, "turn": str(turn_number)})
            turn_span.record_exception(e)
            logger.error("turn_failed",
                session_id=session_id,
                turn=turn_number,
                error=str(e),
            )
            raise
```

### 3.3 Intent Resolution & Skill Matching

```python
async def resolve_intent(message: dict) -> dict:
    with tracer.start_as_current_span("novi.intent.resolve", attributes={
        "input.length": len(message.get("text", "")),
    }) as span:
        intent = await intent_classifier.classify(message["text"])

        intent_resolution.add(1, {
            "intent": intent.name,
            "status": "resolved" if intent.confidence > 0.7 else "low_confidence",
        })

        span.set_attribute("intent.name", intent.name)
        span.set_attribute("intent.confidence", intent.confidence)

        logger.info("intent_resolved",
            intent=intent.name,
            confidence=intent.confidence,
        )

        return intent


async def match_skill(intent: dict) -> object:
    with tracer.start_as_current_span("novi.skill.match", attributes={
        "intent.name": intent.name,
    }) as span:
        skill = skill_catalog.find(intent)

        if skill:
            skill_match_total.add(1, {"skill": skill.name, "status": "matched"})
            span.set_attribute("skill.name", skill.name)
            span.set_attribute("skill.status", "matched")
        else:
            skill_match_total.add(1, {"skill": "none", "status": "no_match"})
            span.set_attribute("skill.status", "no_match")
            span.add_event("no_skill_matched", {"intent": intent.name})
            logger.warning("no_skill_matched", intent=intent.name)

        return skill
```

### 3.4 Canvas Generation

```python
async def generate_canvas(response: dict):
    start = time.perf_counter()

    with tracer.start_as_current_span("novi.canvas.generate", attributes={
        "canvas.type": response.get("canvas_type", "unknown"),
    }) as span:
        try:
            canvas = await canvas_renderer.render(response)
            elapsed = time.perf_counter() - start

            canvas_generation.add(1, {"canvas_type": response["canvas_type"], "status": "success"})
            canvas_duration.record(elapsed, {"canvas_type": response["canvas_type"]})

            span.set_attribute("canvas.status", "success")
            span.set_attribute("canvas.duration_s", round(elapsed, 3))

        except Exception as e:
            canvas_generation.add(1, {"canvas_type": response.get("canvas_type", "unknown"), "status": "failure"})
            span.set_attribute("canvas.status", "failure")
            span.record_exception(e)
            logger.error("canvas_generation_failed",
                canvas_type=response.get("canvas_type"),
                error=str(e),
            )
            raise
```

---

## 4. Alertmanager Rules

**File:** `layer4_alerts.yml`

```yaml
groups:
  - name: layer4_mssql
    rules:
      # P2: Connection pool saturation >80%
      - alert: MSSQLConnectionPoolSaturation
        expr: >
          otel_mssql_connection_pool_active
          / otel_mssql_connection_pool_size
          > 0.8
        for: 5m
        labels:
          severity: p2
        annotations:
          summary: "MS SQL — connection pool usage >80%"

      # P2: Deadlock spike
      - alert: MSSQLDeadlockSpike
        expr: rate(otel_mssql_deadlocks_total[5m]) > 0.08
        for: 5m
        labels:
          severity: p2
        annotations:
          summary: "MS SQL — deadlock rate >5/min"

      # P3: Slow queries
      - alert: MSSQLSlowQueries
        expr: >
          histogram_quantile(0.95,
            rate(otel_mssql_query_duration_bucket[10m])
          ) > 1.0
        for: 10m
        labels:
          severity: p3
        annotations:
          summary: "MS SQL — p95 query duration >1s"

      # P4: Index fragmentation (from sql_exporter, no otel_ prefix)
      - alert: MSSQLHighFragmentation
        expr: mssql_index_fragmentation_percent > 30
        for: 1h
        labels:
          severity: p4
        annotations:
          summary: "MS SQL — index fragmentation >30% on {{ $labels.index_name }}"

  - name: layer4_bedrock
    rules:
      # P2: Bedrock unavailable / high error rate
      - alert: BedrockHighErrorRate
        expr: >
          rate(otel_bedrock_errors_total[5m])
          / rate(otel_bedrock_calls_total[5m])
          > 0.05
        for: 5m
        labels:
          severity: p2
        annotations:
          summary: "AWS Bedrock — error rate >5%"

      # P2: Throttling spike
      - alert: BedrockThrottling
        expr: rate(otel_bedrock_errors_total{error_type="throttling"}[5m]) > 0.1
        for: 5m
        labels:
          severity: p2
        annotations:
          summary: "AWS Bedrock — throttling rate spiking"

      # P3: High latency
      - alert: BedrockHighLatency
        expr: >
          histogram_quantile(0.95,
            rate(otel_bedrock_call_duration_bucket[10m])
          ) > 10
        for: 10m
        labels:
          severity: p3
        annotations:
          summary: "AWS Bedrock — p95 latency >10s"

      # P3: Lambda cold start
      - alert: BedrockLambdaColdStart
        expr: >
          histogram_quantile(0.95,
            rate(otel_bedrock_lambda_proxy_duration_bucket[10m])
          ) > 5
        for: 10m
        labels:
          severity: p3
        annotations:
          summary: "Bedrock Lambda proxy — p95 >5s (possible cold starts)"

      # P4: Token cost anomaly
      - alert: BedrockTokenCostAnomaly
        expr: >
          rate(otel_bedrock_tokens_input_total[1h]) + rate(otel_bedrock_tokens_output_total[1h])
          > 100000
        for: 1h
        labels:
          severity: p4
        annotations:
          summary: "AWS Bedrock — token consumption anomaly (>100k tokens/hr)"

  - name: layer4_novi
    rules:
      # P2: High session error rate
      - alert: NoviHighErrorRate
        expr: >
          rate(otel_novi_session_errors_total[5m])
          > 0.1
        for: 5m
        labels:
          severity: p2
        annotations:
          summary: "Novi Chatbot — session error rate spiking"

      # P2: High no-skill-matched rate
      - alert: NoviHighNoSkillMatch
        expr: >
          rate(otel_novi_skill_match_total{status="no_match"}[10m])
          / rate(otel_novi_skill_match_total[10m])
          > 0.2
        for: 10m
        labels:
          severity: p2
        annotations:
          summary: "Novi Chatbot — >20% of intents have no skill match"

      # P3: Canvas generation failures
      - alert: NoviCanvasFailures
        expr: >
          rate(otel_novi_canvas_generation_total{status="failure"}[10m])
          / rate(otel_novi_canvas_generation_total[10m])
          > 0.1
        for: 10m
        labels:
          severity: p3
        annotations:
          summary: "Novi Chatbot — canvas generation failure rate >10%"

      # P3: Slow turn response
      - alert: NoviSlowTurnResponse
        expr: >
          histogram_quantile(0.95,
            rate(otel_novi_turn_duration_bucket[10m])
          ) > 5
        for: 10m
        labels:
          severity: p3
        annotations:
          summary: "Novi Chatbot — p95 turn response time >5s"
```

### Alertmanager Routing

Uses the same `alertmanager.yml` routing from Layer 3 — severity labels map to the same receivers:

| Severity | Receiver | Escalation |
|---|---|---|
| `p1` | `ops-immediate` | Ops → Dev Lead → Platform Owner |
| `p2` | `ops-15min` | Ops → Dev On-Call |
| `p3` | `ops-1hour` | Ops → Dev (next business day if non-critical) |
| `p4` | `ops-weekly-digest` | Ops → Dev (sprint backlog) |

---

## 5. Grafana Dashboard

### 5.1 Panel Layout

Single dashboard: **"Layer 4 — Data & AI"**

```
Row 1: MS SQL Server
  ├── Query Duration p50/p95/p99     (Prometheus histogram)
  ├── Connection Pool Usage          (Prometheus up-down counter, ratio)
  ├── Deadlock Rate                  (Prometheus counter rate)
  └── Slow Queries / min             (Prometheus counter rate)

Row 2: AWS Bedrock
  ├── Call Latency p50/p95/p99       (Prometheus histogram)
  ├── Token Consumption (in / out)   (Prometheus counter rate, stacked)
  ├── Error Rate by Type             (Prometheus counter rate, stacked)
  └── Lambda Proxy Latency p95       (Prometheus histogram)

Row 3: Novi Chatbot
  ├── Turn Response Time p50/p95     (Prometheus histogram)
  ├── Skill Match Rate               (Prometheus counter rate, stacked by status)
  ├── Session Error Rate             (Prometheus counter rate)
  └── Canvas Generation Rate         (Prometheus counter rate, stacked by status)
```

### 5.2 Provisioning JSON

**File:** `layer4-data-ai.json`

```json
{
  "dashboard": {
    "title": "Layer 4 — Data & AI",
    "uid": "layer4-data-ai",
    "tags": ["dw-hq", "layer4", "data-ai"],
    "timezone": "browser",
    "refresh": "30s",
    "templating": {
      "list": [
        {
          "name": "model",
          "type": "query",
          "datasource": "Prometheus",
          "query": "label_values(otel_bedrock_call_duration_bucket, model)"
        },
        {
          "name": "operation",
          "type": "query",
          "datasource": "Prometheus",
          "query": "label_values(otel_mssql_query_duration_bucket, operation)"
        },
        {
          "name": "skill",
          "type": "query",
          "datasource": "Prometheus",
          "query": "label_values(otel_novi_skill_match_total, skill)"
        }
      ]
    },
    "panels": [
      {
        "title": "— MS SQL Server —",
        "type": "row",
        "gridPos": { "h": 1, "w": 24, "x": 0, "y": 0 }
      },
      {
        "title": "Query Duration",
        "type": "timeseries",
        "datasource": "Prometheus",
        "gridPos": { "h": 8, "w": 6, "x": 0, "y": 1 },
        "fieldConfig": { "defaults": { "unit": "s" } },
        "targets": [
          { "expr": "histogram_quantile(0.50, rate(otel_mssql_query_duration_bucket{operation=~\"$operation\"}[5m]))", "legendFormat": "p50" },
          { "expr": "histogram_quantile(0.95, rate(otel_mssql_query_duration_bucket{operation=~\"$operation\"}[5m]))", "legendFormat": "p95" },
          { "expr": "histogram_quantile(0.99, rate(otel_mssql_query_duration_bucket{operation=~\"$operation\"}[5m]))", "legendFormat": "p99" }
        ]
      },
      {
        "title": "Connection Pool Usage",
        "type": "gauge",
        "datasource": "Prometheus",
        "gridPos": { "h": 8, "w": 6, "x": 6, "y": 1 },
        "fieldConfig": { "defaults": { "unit": "percentunit", "min": 0, "max": 1, "thresholds": { "steps": [{ "value": 0, "color": "green" }, { "value": 0.7, "color": "yellow" }, { "value": 0.8, "color": "red" }] } } },
        "targets": [
          { "expr": "otel_mssql_connection_pool_active / otel_mssql_connection_pool_size", "legendFormat": "pool usage" }
        ]
      },
      {
        "title": "Deadlock Rate",
        "type": "timeseries",
        "datasource": "Prometheus",
        "gridPos": { "h": 8, "w": 6, "x": 12, "y": 1 },
        "fieldConfig": { "defaults": { "unit": "ops" } },
        "targets": [
          { "expr": "rate(otel_mssql_deadlocks_total[5m])", "legendFormat": "deadlocks/s" }
        ]
      },
      {
        "title": "Slow Queries / min",
        "type": "timeseries",
        "datasource": "Prometheus",
        "gridPos": { "h": 8, "w": 6, "x": 18, "y": 1 },
        "fieldConfig": { "defaults": { "unit": "ops" } },
        "targets": [
          { "expr": "rate(otel_mssql_slow_queries_total{operation=~\"$operation\"}[5m]) * 60", "legendFormat": "{{ operation }}" }
        ]
      },
      {
        "title": "— AWS Bedrock —",
        "type": "row",
        "gridPos": { "h": 1, "w": 24, "x": 0, "y": 9 }
      },
      {
        "title": "Call Latency",
        "type": "timeseries",
        "datasource": "Prometheus",
        "gridPos": { "h": 8, "w": 6, "x": 0, "y": 10 },
        "fieldConfig": { "defaults": { "unit": "s" } },
        "targets": [
          { "expr": "histogram_quantile(0.50, rate(otel_bedrock_call_duration_bucket{model=~\"$model\"}[5m]))", "legendFormat": "p50" },
          { "expr": "histogram_quantile(0.95, rate(otel_bedrock_call_duration_bucket{model=~\"$model\"}[5m]))", "legendFormat": "p95" },
          { "expr": "histogram_quantile(0.99, rate(otel_bedrock_call_duration_bucket{model=~\"$model\"}[5m]))", "legendFormat": "p99" }
        ]
      },
      {
        "title": "Token Consumption",
        "type": "timeseries",
        "datasource": "Prometheus",
        "gridPos": { "h": 8, "w": 6, "x": 6, "y": 10 },
        "fieldConfig": { "defaults": { "unit": "short" } },
        "targets": [
          { "expr": "rate(otel_bedrock_tokens_input_total{model=~\"$model\"}[5m])", "legendFormat": "input — {{ model }}" },
          { "expr": "rate(otel_bedrock_tokens_output_total{model=~\"$model\"}[5m])", "legendFormat": "output — {{ model }}" }
        ]
      },
      {
        "title": "Error Rate by Type",
        "type": "timeseries",
        "datasource": "Prometheus",
        "gridPos": { "h": 8, "w": 6, "x": 12, "y": 10 },
        "fieldConfig": { "defaults": { "unit": "ops" } },
        "targets": [
          { "expr": "rate(otel_bedrock_errors_total{model=~\"$model\"}[5m])", "legendFormat": "{{ error_type }}" }
        ]
      },
      {
        "title": "Lambda Proxy Latency",
        "type": "timeseries",
        "datasource": "Prometheus",
        "gridPos": { "h": 8, "w": 6, "x": 18, "y": 10 },
        "fieldConfig": { "defaults": { "unit": "s" } },
        "targets": [
          { "expr": "histogram_quantile(0.95, rate(otel_bedrock_lambda_proxy_duration_bucket[5m]))", "legendFormat": "p95" }
        ]
      },
      {
        "title": "— Novi Chatbot —",
        "type": "row",
        "gridPos": { "h": 1, "w": 24, "x": 0, "y": 18 }
      },
      {
        "title": "Turn Response Time",
        "type": "timeseries",
        "datasource": "Prometheus",
        "gridPos": { "h": 8, "w": 6, "x": 0, "y": 19 },
        "fieldConfig": { "defaults": { "unit": "s" } },
        "targets": [
          { "expr": "histogram_quantile(0.50, rate(otel_novi_turn_duration_bucket{skill=~\"$skill\"}[5m]))", "legendFormat": "p50" },
          { "expr": "histogram_quantile(0.95, rate(otel_novi_turn_duration_bucket{skill=~\"$skill\"}[5m]))", "legendFormat": "p95" }
        ]
      },
      {
        "title": "Skill Match Rate",
        "type": "timeseries",
        "datasource": "Prometheus",
        "gridPos": { "h": 8, "w": 6, "x": 6, "y": 19 },
        "fieldConfig": { "defaults": { "unit": "ops" } },
        "targets": [
          { "expr": "rate(otel_novi_skill_match_total{status=\"matched\"}[5m])", "legendFormat": "matched" },
          { "expr": "rate(otel_novi_skill_match_total{status=\"no_match\"}[5m])", "legendFormat": "no match" }
        ]
      },
      {
        "title": "Session Error Rate",
        "type": "timeseries",
        "datasource": "Prometheus",
        "gridPos": { "h": 8, "w": 6, "x": 12, "y": 19 },
        "fieldConfig": { "defaults": { "unit": "ops" } },
        "targets": [
          { "expr": "rate(otel_novi_session_errors_total[5m])", "legendFormat": "{{ error_type }}" }
        ]
      },
      {
        "title": "Canvas Generation",
        "type": "timeseries",
        "datasource": "Prometheus",
        "gridPos": { "h": 8, "w": 6, "x": 18, "y": 19 },
        "fieldConfig": { "defaults": { "unit": "ops" } },
        "targets": [
          { "expr": "rate(otel_novi_canvas_generation_total{status=\"success\"}[5m])", "legendFormat": "success" },
          { "expr": "rate(otel_novi_canvas_generation_total{status=\"failure\"}[5m])", "legendFormat": "failure" }
        ]
      }
    ]
  }
}
```

### 5.3 Datasource Cross-Linking

Same config as Layer 3 — already in place. No changes needed.

---

## 6. Implementation Order

| Phase | Scope | Effort | Dependencies |
|---|---|---|---|
| **Phase 1** | MS SQL — `init_otel("mssql-monitor")`, query wrapper with spans/metrics, structured logging | 2 days | `otel_setup.py` |
| **Phase 2** | MS SQL — `sql_exporter` sidecar config for DMV metrics (index fragmentation, table growth) | 1 day | Prometheus scrape config |
| **Phase 3** | AWS Bedrock — `init_otel("bedrock-ai")`, `invoke_bedrock()` wrapper with token tracking, retry spans, error classification | 2 days | `otel_setup.py` |
| **Phase 4** | Novi Chatbot — `init_otel("novi-chatbot")`, session/turn/intent/skill/canvas span hierarchy, metrics | 3 days | Phase 3 (reuses Bedrock instrumentation) |
| **Phase 5** | Alertmanager rules (`layer4_alerts.yml`) | 1 day | Phases 1–4 |
| **Phase 6** | Grafana dashboard provisioning JSON | 1 day | Phase 5 |
| **Phase 7** | End-to-end validation — trigger queries, LLM calls, chatbot sessions; verify metric→trace→log | 1 day | Phase 6 |

**Total estimate: ~11 days**

---

## 7. Prometheus Port Allocation (Running Total)

| Service | Port | Layer |
|---|---|---|
| MCP add_sub server | 8001 | 5 |
| MCP mul_div server | 8002 | 5 |
| Runner Service | 8003 | 3 |
| DW Orchestrator | 8004 | 3 |
| Worker Runner | 8005 | 3 |
| MS SQL Monitor | 8006 | 4 |
| Bedrock AI | 8007 | 4 |
| Novi Chatbot | 8008 | 4 |
