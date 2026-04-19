"""
OpenTelemetry bootstrap: traces + metrics + logs via OTLP gRPC.

Signals exported:
  - Traces  → BatchSpanProcessor → OTLPSpanExporter   (grpc://localhost:4317)
  - Metrics → PeriodicExportingMetricReader            (grpc://localhost:4317)
  - Logs    → LoggingInstrumentor injects trace_id/span_id into every log record

Usage:
    from otel_setup import init_otel, get_tracer, get_meter
    trace_provider, metrics_provider = init_otel("my-service")
"""

import logging
import logging_loki
from typing import Sequence
from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider, ReadableSpan
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.trace import SpanKind
from prometheus_client import start_http_server


class FilteringSpanExporter(SpanExporter):
    """
    Wraps another exporter and drops unwanted spans before they reach Tempo.

    Drops:
      - SpanKind.CLIENT spans  — raw HTTP transport noise from HTTPXClientInstrumentor
                                  (GET/POST/DELETE to MCP servers and LLM APIs).
                                  The instrumentor still injects traceparent headers;
                                  we just don't want the spans in Grafana.
      - Spans from specific instrumentation libraries — e.g. FastMCP's built-in
                                  tracing creates root spans that duplicate our
                                  own named spans (solve_steps_operation, etc.).
    """

    def __init__(self, wrapped: SpanExporter, filter_libraries: list[str] | None = None):
        self._wrapped = wrapped
        self._filter_libraries = set(filter_libraries or [])

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        keep = [s for s in spans if not self._should_drop(s)]
        if keep:
            return self._wrapped.export(keep)
        return SpanExportResult.SUCCESS

    def _should_drop(self, span: ReadableSpan) -> bool:
        # Drop all raw HTTP client transport spans
        if span.kind == SpanKind.CLIENT:
            return True
        # Drop spans from specified instrumentation libraries (e.g. "fastmcp")
        if self._filter_libraries:
            lib_name = span.instrumentation_scope.name if span.instrumentation_scope else ""
            if lib_name in self._filter_libraries:
                return True
        return False

    def shutdown(self) -> None:
        self._wrapped.shutdown()

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        return self._wrapped.force_flush(timeout_millis)


def init_otel(
    service_name: str,
    otlp_endpoint: str = "localhost:4317",
    prometheus_port: int = 8000,
    filter_libraries: list[str] | None = None,
    loki_url: str = "http://localhost:3100/loki/api/v1/push",
) -> tuple:
    """
    Initialize OpenTelemetry with OTLP gRPC exporters for traces and Prometheus for metrics.

    Args:
        service_name:      Identifies this service in your OTel backend (e.g. Tempo).
        otlp_endpoint:     OTLP gRPC receiver address (host:port). Default: localhost:4317.
        prometheus_port:   Port for Prometheus metrics endpoint. Default: 8000.

    Returns:
        (TracerProvider, MeterProvider) — hold onto these to call
        force_flush() / shutdown() before process exit.
    """

    resource = Resource.create({
        "service.name": service_name,
        "service.version": "1.0.0",
    })

    # ── Traces → Tempo (localhost:4317 via OTLP gRPC) ────────────────────────
    # Wrap exporter to drop MCP protocol transport spans (GET/POST/DELETE to localhost)
    # HTTPXClientInstrumentor still injects traceparent headers — these spans are
    # just filtered before reaching Tempo so they don't clutter the trace view.
    raw_exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
    trace_exporter = FilteringSpanExporter(raw_exporter, filter_libraries=filter_libraries)
    trace_provider = TracerProvider(resource=resource)
    trace_provider.add_span_processor(BatchSpanProcessor(trace_exporter))
    trace.set_tracer_provider(trace_provider)

    # ── Metrics → Prometheus (exposed on prometheus_port) ──────────────────────
    # Start HTTP server that Prometheus scrapes
    start_http_server(prometheus_port, addr="0.0.0.0")
    metric_reader = PrometheusMetricReader()
    metrics_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
    metrics.set_meter_provider(metrics_provider)

    # ── Logs → Loki (via python-logging-loki) ────────────────────────────────
    # LoggingInstrumentor injects otelTraceID/otelSpanID into every record.
    # LokiHandler pushes each record directly to Loki over HTTP — no file or
    # Alloy relay needed. Tags are indexed label in Loki; trace_id is added as
    # a structured field so Grafana can link log lines to Tempo traces.
    logging.basicConfig(level=logging.INFO)
    LoggingInstrumentor().instrument(set_logging_format=True)

    loki_handler = logging_loki.LokiHandler(
        url=loki_url,
        tags={"service": service_name, "env": "local"},
        version="1",
    )
    loki_handler.setLevel(logging.INFO)
    logging.getLogger().addHandler(loki_handler)

    # ── Startup banner ────────────────────────────────────────────────────────
    print(f"[OTel] TracerProvider  initialized -> grpc://{otlp_endpoint} (Tempo)")
    print(f"[OTel] MeterProvider   initialized -> http://localhost:{prometheus_port}/metrics (Prometheus)")
    print(f"[OTel] LokiHandler     active      -> {loki_url} (Loki)")
    print(f"[OTel] LoggingInstrumentor active  -> trace_id/span_id injected into all log records")
    print(f"[OTel] Service: {service_name} v1.0.0 ready")

    return trace_provider, metrics_provider


def get_tracer(name: str):
    """Return a tracer scoped to the given instrumentation name."""
    return trace.get_tracer(name)


def get_meter(name: str):
    """Return a meter scoped to the given instrumentation name."""
    return metrics.get_meter(name)
