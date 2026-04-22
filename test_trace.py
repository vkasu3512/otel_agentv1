import sys
sys.path.insert(0, 'wd-otel-core')

import wd_otel
from opentelemetry import trace
wd_otel.init('otel_agent_v2/wd-otel-orchestrator.yaml')

tracer = wd_otel.tracer('test_trace')

with tracer.start_as_current_span('test_operation') as span:
    span.set_attribute('test.key', 'test_value')
    ctx = span.get_span_context()
    print(f"Created test span: trace_id={ctx.trace_id}")

# Force flush
trace_provider = trace.get_tracer_provider()
trace_provider.force_flush(timeout_millis=5000)
print("Flushed traces")

# Shutdown  
wd_otel.shutdown()
print("Shutdown complete")
