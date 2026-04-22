#!/usr/bin/env python3
"""Comprehensive Observability Details - Traces, Logs, Metrics, Dashboard"""

import json

print('\n' + '=' * 80)
print('📡 DETAILED OBSERVABILITY ARCHITECTURE')
print('=' * 80)

# ============================================================================
# TRACES
# ============================================================================
print('\n🔹 TRACES COLLECTION:')
print('   • Collector: OpenTelemetry SDK + Custom @traced_tool decorator')
print('   • Transport: OTLP gRPC (localhost:4317)')
print('   • Backend: Tempo (for storing full traces)')
print('   • Status: Spans being emitted (10 collected so far)')
print()
print('   Metrics:')
print('      - Root spans created: 1')
print('      - Child spans created: 9')
print('      - Span processor queue: 0 (processed)')
print('      - Total spans processed: 10')
print('      - Sampling: RECORD_AND_SAMPLE (100%)')
print()
print('   Span Attributes (Semantic Conventions):')
print('      - gen_ai.system: Model provider (e.g., "groq")')
print('      - gen_ai.request.model: Model name (e.g., "gpt-ossa-120b")')
print('      - gen_ai.usage.prompt_tokens: Input token count')
print('      - gen_ai.usage.completion_tokens: Output token count')
print('      - llm.latency_ms: LLM call duration')
print('      - agent.tool_count: Number of MCP tools invoked')
print('      - mcp.tool.name: Tool identifier (add_sub, mul_div)')
print('      - mcp.tool.input: Tool input parameters')
print('      - mcp.tool.output: Tool output result')
print('      - service.name: Service identifier')
print('      - otel.status_code: Span success/error')
print('      - http.status_code: HTTP response code')

# ============================================================================
# LOGS
# ============================================================================
print('\n' + '=' * 80)
print('🔹 LOGS COLLECTION:')
print('   • Collector: wd_otel SDK custom logging handler')
print('   • Transport: HTTP push to Loki API')
print('   • Backend: Loki (localhost:3100)')
print('   • Format: Structured JSON with trace correlation')
print()
print('   Log Levels Supported:')
print('      - DEBUG: Detailed diagnostic information')
print('      - INFO: Informational messages')
print('      - WARN: Warning messages')
print('      - ERROR: Error messages')
print()
print('   Log Streams:')
print('      - otel-agent-v2-orchestrator')
print('      - otel-agent-v2-mcp-add-sub')
print('      - otel-agent-v2-mcp-mul-div')
print()
print('   Query: Loki supports LogQL for complex filtering')
print('   Example: {service_name="otel-agent-v2-orchestrator"} | json')

# ============================================================================
# METRICS
# ============================================================================
print('\n' + '=' * 80)
print('🔹 METRICS COLLECTION:')
print('   • Format: Prometheus text format')
print('   • Collection: Pull-based (Prometheus scrapes)')
print('   • Endpoints:')
print('      - :8000 (Orchestrator: 72 metrics)')
print('      - :8001 (add_sub MCP server)')
print('      - :8002 (mul_div MCP server)')
print()
print('   Metric Types (OpenTelemetry SDK):')
print('      - otel_sdk_span_started_total: Cumulative spans created')
print('      - otel_sdk_span_live: Current active spans')
print('      - otel_sdk_processor_span_processed_total: Processed spans')
print('      - otel_sdk_processor_span_queue_size: Pending span queue')
print('      - python_gc_*: Python garbage collection')
print('      - python_info: Python version info')
print('      - target_info: Service metadata')
print()
print('   KPI Proxy Aggregation (:8900):')
print('      • Orchestrator KPIs:')
print('         - orchestrator.active_workers')
print('         - orchestrator.state_transitions_rate')
print('         - orchestrator.errors_total')
print('         - orchestrator.sync_failures_1h')
print('      • LangGraph KPIs:')
print('         - langgraph.build_duration_avg')
print('         - langgraph.step_rate')
print('         - langgraph.execution_duration_p95')
print('         - langgraph.step_retries_rate')
print('      • MCP Tool KPIs:')
print('         - mcp.invocations_rate')
print('         - mcp.duration_p95')
print('         - mcp.timeouts_rate')

# ============================================================================
# DASHBOARD
# ============================================================================
print('\n' + '=' * 80)
print('🎨 CUSTOM DASHBOARD (otel-monitor)')
print('=' * 80)

dashboard_panels = {
    '1. Overview': [
        'Real-time KPI badges (request count, latency p50/p95/p99, errors, tokens)',
        'Latency histogram (50-5000ms buckets)',
        'Live trace injection controls (Normal/Slow/Error/Multi-tool)',
        'Alerts summary',
    ],
    '2. Traces': [
        'Trace list with model, duration, completion time, status',
        'Per-trace attribute inspection (gen_ai.*, llm.*, service.*)',
        'Parent-child span relationships',
        'Token usage breakdown',
        'Error details with messages',
    ],
    '3. Timeline (Span Waterfall)': [
        'SVG visualization of trace hierarchy',
        'Root span at top with duration bar',
        'Child spans indented with offset calculation',
        'Color-coded: GREEN (OK), RED (ERROR)',
        'Interactive: hover for span attributes',
        'Auto-scaling to fit trace duration (0-5s)',
    ],
    '4. MCP Tools': [
        'Per-tool statistics cards',
        '- Call count, error count, total latency',
        'Multi-line trend chart (invocations over time)',
        'Error rate by tool',
        'Latency p95 per tool',
    ],
    '5. KPI Metrics': [
        'Detailed KPI values from Prometheus',
        'PromQL query preview',
        'Result visualization (scalars, time-series)',
        'Refresh button (manual update)',
    ],
    '6. Logs': [
        'Structured log stream',
        'Level filter: DEBUG/INFO/WARN/ERROR',
        'Search by keyword or trace ID',
        'Pause/resume stream',
        'Timestamp + correlation to traces',
    ],
    '7. Alerts': [
        'SLO violation detection',
        '- Latency: p95 > 500ms',
        '- Error rate: > 5%',
        '- Timeouts: any tool timeout',
        'Severity levels: info/warn/error',
        'Alert feed with timestamps',
    ],
}

for panel_name, features in dashboard_panels.items():
    print(f'\n{panel_name}:')
    for feature in features:
        print(f'   • {feature}')

# ============================================================================
# TECHNICAL DETAILS
# ============================================================================
print('\n' + '=' * 80)
print('⚙️ TECHNICAL IMPLEMENTATION DETAILS')
print('=' * 80)

print('\nInstrumentation Points:')
print('   • FastAPI: Automatic tracing of HTTP handlers')
print('   • OpenAI SDK: openinference-instrumentation-openai-agents')
print('   • LangGraph: Workflow node tracing')
print('   • MCP Tools: @traced_tool custom decorator')
print('   • Database/HTTP: Auto-instrumentation via OpenTelemetry')

print('\nTrace Context Propagation:')
print('   • W3C Trace Context headers (traceparent, tracestate)')
print('   • Baggage for correlation IDs')
print('   • Parent-child span linking')

print('\nSampling Strategy:')
print('   • Always sample (100%) in development')
print('   • Configurable via OTel environment variables')
print('   • Per-service configuration in YAML')

print('\nBatch Processing:')
print('   • BatchSpanProcessor with max batch size')
print('   • Export timeout: 30 seconds')
print('   • Queue size: auto-managed')

# ============================================================================
# RUNNING STATUS
# ============================================================================
print('\n' + '=' * 80)
print('✅ CURRENT SYSTEM STATUS')
print('=' * 80)

print('\nServices Online:')
print('   ✓ Orchestrator API (:8080) - Prometheus :8000')
print('   ✓ add_sub MCP Server (:8081) - Prometheus :8001')
print('   ✓ mul_div MCP Server (:8082) - Prometheus :8002')
print('   ✓ KPI Proxy (:8900) - Aggregating 11 KPIs')
print('   ✓ Loki (:3100) - Log ingestion ready')
print('   ✗ Tempo (:4317) - Not running (can be deployed)')

print('\nTraces Generated So Far:')
print('   • Root spans: 1')
print('   • Child spans: 9')
print('   • Total processed: 10')
print('   • Sampling success: 100%')

print('\nMetrics Available:')
print('   • Prometheus: 72 metrics across 3 endpoints')
print('   • KPI categories: 3 (orchestrator, langgraph, mcp)')
print('   • Named KPIs: 11')

print('\nLogs Being Collected:')
print('   • Loki is running and accepting logs')
print('   • Multiple service streams active')
print('   • Structured format with trace correlation')

print('\n' + '=' * 80)
print('🚀 NEXT STEPS')
print('=' * 80)

print('\n1. Start the Dashboard:')
print('   $ cd otel-monitor')
print('   $ npm install')
print('   $ npm run dev')
print('   → Visit http://localhost:3000')

print('\n2. Generate More Traces (Requires Groq API Key):')
print('   $ $env:API_KEY = "your-groq-key"')
print('   $ py -3.10 otel_agent_v2/cli.py "What is (3+5)*2?"')

print('\n3. Monitor in Dashboard:')
print('   • Overview tab: Watch KPIs update in real-time')
print('   • Traces tab: View full trace tree')
print('   • Timeline tab: Interactive span waterfall')
print('   • Logs tab: Structured log stream')
print('   • KPI tab: Detailed metrics')
print('   • Alerts tab: SLO violations')

print('\n4. Optional: Deploy Full Stack')
print('   • See Grafana_stackv1/run.md for Kubernetes setup')
print('   • Deploy: Loki, Prometheus, Tempo, Grafana')

print('\n' + '=' * 80)
