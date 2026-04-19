import pytest
from unittest.mock import MagicMock
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry import trace
from wd_otel import helpers

@pytest.fixture(autouse=True)
def setup_test_otel():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    helpers._tracer = provider.get_tracer("test")
    helpers._meter = MagicMock()
    helpers._tool_invocations = MagicMock()
    helpers._tool_duration = MagicMock()
    helpers._tool_timeouts = MagicMock()
    helpers._session_counter = MagicMock()
    helpers._session_duration = MagicMock()
    helpers._state_transitions = MagicMock()
    helpers._active_workers = MagicMock()
    helpers._orchestration_errors = MagicMock()
    helpers._sync_failures = MagicMock()
    import wd_otel
    wd_otel._initialized = True
    yield exporter
    exporter.clear()
    wd_otel._initialized = False
