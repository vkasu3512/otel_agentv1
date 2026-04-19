"""WD-OTel SDK — tracing, metrics, and logging setup."""
from __future__ import annotations

import logging
from typing import Sequence

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.trace import SpanKind
from prometheus_client import start_http_server

try:
    import logging_loki
except ImportError:  # pragma: no cover
    logging_loki = None  # type: ignore[assignment]

from wd_otel.config import WdOtelConfig
from wd_otel.errors import WdOtelConfigError

logger = logging.getLogger("wd_otel.setup")


# ---------------------------------------------------------------------------
# FilteringSpanExporter
# ---------------------------------------------------------------------------

class FilteringSpanExporter(SpanExporter):
    """Wraps another SpanExporter, dropping CLIENT spans and filtered library spans."""

    def __init__(self, wrapped: SpanExporter, filter_libraries: list[str] | None = None):
        self._wrapped = wrapped
        self._filter_libraries = set(filter_libraries or [])

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        keep = [s for s in spans if not self._should_drop(s)]
        if keep:
            return self._wrapped.export(keep)
        return SpanExportResult.SUCCESS

    def _should_drop(self, span: ReadableSpan) -> bool:
        if span.kind == SpanKind.CLIENT:
            return True
        if self._filter_libraries:
            lib = span.instrumentation_scope.name if span.instrumentation_scope else ""
            if lib in self._filter_libraries:
                return True
        return False

    def shutdown(self):
        self._wrapped.shutdown()

    def force_flush(self, timeout_millis: int = 30000):
        return self._wrapped.force_flush(timeout_millis)


# ---------------------------------------------------------------------------
# setup_tracing
# ---------------------------------------------------------------------------

def setup_tracing(cfg: WdOtelConfig) -> TracerProvider:
    """Create TracerProvider with OTLP gRPC + FilteringSpanExporter, set global provider.

    Args:
        cfg: Validated WdOtelConfig instance.

    Returns:
        Configured TracerProvider.
    """
    resource = Resource.create(
        {
            "service.name": cfg.service_name,
            "service.version": cfg.service_version,
            "deployment.environment": cfg.env,
        }
    )

    otlp_exporter = OTLPSpanExporter(endpoint=cfg.traces_endpoint)
    filtering_exporter = FilteringSpanExporter(
        otlp_exporter,
        filter_libraries=cfg.filter_libraries,
    )

    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(filtering_exporter))

    trace.set_tracer_provider(provider)
    logger.info(
        "[wd-otel] Tracing configured — endpoint=%s env=%s",
        cfg.traces_endpoint,
        cfg.env,
    )
    return provider


# ---------------------------------------------------------------------------
# setup_metrics
# ---------------------------------------------------------------------------

def setup_metrics(cfg: WdOtelConfig) -> MeterProvider:
    """Start Prometheus HTTP server and create MeterProvider, set global provider.

    Args:
        cfg: Validated WdOtelConfig instance.

    Returns:
        Configured MeterProvider.

    Raises:
        WdOtelConfigError: In strict (local/dev) envs if the Prometheus port is in use.
    """
    try:
        start_http_server(cfg.prometheus_port)
    except OSError as exc:
        msg = f"Could not start Prometheus server on port {cfg.prometheus_port}: {exc}"
        if cfg.is_strict:
            raise WdOtelConfigError(msg, hint="Choose a different prometheus_port in wd-otel.yaml") from exc
        logger.warning("[wd-otel] %s — metrics endpoint unavailable", msg)

    reader = PrometheusMetricReader()
    resource = Resource.create(
        {
            "service.name": cfg.service_name,
            "service.version": cfg.service_version,
            "deployment.environment": cfg.env,
        }
    )
    provider = MeterProvider(metric_readers=[reader], resource=resource)
    metrics.set_meter_provider(provider)
    logger.info("[wd-otel] Metrics configured — prometheus_port=%d", cfg.prometheus_port)
    return provider


# ---------------------------------------------------------------------------
# setup_logging
# ---------------------------------------------------------------------------

def setup_logging(cfg: WdOtelConfig) -> None:
    """Configure standard logging with OTel trace context injection and optional Loki.

    Args:
        cfg: Validated WdOtelConfig instance.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    LoggingInstrumentor().instrument(set_logging_format=True)

    if cfg.loki_url:
        if logging_loki is None:
            logger.warning("[wd-otel] python-logging-loki not installed; Loki handler skipped.")
            return

        handler = logging_loki.LokiHandler(
            url=cfg.loki_url,
            tags={"service": cfg.service_name, "env": cfg.env},
            version="1",
        )
        logging.getLogger().addHandler(handler)
        logger.info("[wd-otel] Loki handler added — url=%s", cfg.loki_url)
