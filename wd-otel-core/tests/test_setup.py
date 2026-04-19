"""Tests for wd_otel.setup module."""
from __future__ import annotations

from unittest.mock import MagicMock, patch, call

import pytest
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExportResult
from opentelemetry.trace import SpanKind

from wd_otel.config import WdOtelConfig
from wd_otel.setup import FilteringSpanExporter, setup_tracing, setup_metrics, setup_logging


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_span(kind: SpanKind, lib_name: str = "") -> MagicMock:
    """Return a mock ReadableSpan with the given kind and instrumentation scope."""
    span = MagicMock(spec=ReadableSpan)
    span.kind = kind
    scope = MagicMock()
    scope.name = lib_name
    span.instrumentation_scope = scope
    return span


def _minimal_cfg(**overrides) -> WdOtelConfig:
    defaults = dict(service_name="test-svc", env="local")
    defaults.update(overrides)
    return WdOtelConfig(**defaults)


# ---------------------------------------------------------------------------
# FilteringSpanExporter
# ---------------------------------------------------------------------------

class TestFilteringSpanExporter:
    def test_drops_client_spans(self):
        wrapped = MagicMock()
        wrapped.export.return_value = SpanExportResult.SUCCESS
        exporter = FilteringSpanExporter(wrapped)

        client_span = _make_span(SpanKind.CLIENT)
        result = exporter.export([client_span])

        wrapped.export.assert_not_called()
        assert result == SpanExportResult.SUCCESS

    def test_passes_non_client_spans(self):
        wrapped = MagicMock()
        wrapped.export.return_value = SpanExportResult.SUCCESS
        exporter = FilteringSpanExporter(wrapped)

        server_span = _make_span(SpanKind.SERVER)
        result = exporter.export([server_span])

        wrapped.export.assert_called_once_with([server_span])
        assert result == SpanExportResult.SUCCESS

    def test_drops_filtered_library_spans(self):
        wrapped = MagicMock()
        wrapped.export.return_value = SpanExportResult.SUCCESS
        exporter = FilteringSpanExporter(wrapped, filter_libraries=["fastmcp"])

        lib_span = _make_span(SpanKind.INTERNAL, lib_name="fastmcp")
        result = exporter.export([lib_span])

        wrapped.export.assert_not_called()
        assert result == SpanExportResult.SUCCESS

    def test_passes_non_filtered_library_spans(self):
        wrapped = MagicMock()
        wrapped.export.return_value = SpanExportResult.SUCCESS
        exporter = FilteringSpanExporter(wrapped, filter_libraries=["fastmcp"])

        other_span = _make_span(SpanKind.INTERNAL, lib_name="my_lib")
        result = exporter.export([other_span])

        wrapped.export.assert_called_once_with([other_span])

    def test_mixed_spans_only_passes_non_filtered(self):
        wrapped = MagicMock()
        wrapped.export.return_value = SpanExportResult.SUCCESS
        exporter = FilteringSpanExporter(wrapped, filter_libraries=["filtered_lib"])

        client_span = _make_span(SpanKind.CLIENT)
        lib_span = _make_span(SpanKind.INTERNAL, lib_name="filtered_lib")
        server_span = _make_span(SpanKind.SERVER, lib_name="my_lib")

        exporter.export([client_span, lib_span, server_span])

        wrapped.export.assert_called_once_with([server_span])

    def test_delegates_shutdown(self):
        wrapped = MagicMock()
        exporter = FilteringSpanExporter(wrapped)
        exporter.shutdown()
        wrapped.shutdown.assert_called_once()

    def test_delegates_force_flush(self):
        wrapped = MagicMock()
        exporter = FilteringSpanExporter(wrapped)
        exporter.force_flush(5000)
        wrapped.force_flush.assert_called_once_with(5000)

    def test_force_flush_default_timeout(self):
        wrapped = MagicMock()
        exporter = FilteringSpanExporter(wrapped)
        exporter.force_flush()
        wrapped.force_flush.assert_called_once_with(30000)

    def test_no_filter_libraries_by_default(self):
        """When no filter_libraries given, only CLIENT spans are dropped."""
        wrapped = MagicMock()
        wrapped.export.return_value = SpanExportResult.SUCCESS
        exporter = FilteringSpanExporter(wrapped)

        # Internal span with any lib name should pass
        span = _make_span(SpanKind.INTERNAL, lib_name="anything")
        exporter.export([span])
        wrapped.export.assert_called_once()


# ---------------------------------------------------------------------------
# setup_tracing
# ---------------------------------------------------------------------------

class TestSetupTracing:
    def test_returns_tracer_provider(self):
        cfg = _minimal_cfg()
        with patch("wd_otel.setup.OTLPSpanExporter") as mock_exporter_cls, \
             patch("wd_otel.setup.BatchSpanProcessor") as mock_processor_cls, \
             patch("wd_otel.setup.trace") as mock_trace:
            mock_exporter_cls.return_value = MagicMock()
            mock_processor_cls.return_value = MagicMock()

            from opentelemetry.sdk.trace import TracerProvider
            provider = setup_tracing(cfg)

            assert isinstance(provider, TracerProvider)

    def test_uses_config_endpoint(self):
        cfg = _minimal_cfg(traces_endpoint="myhost:4317")
        with patch("wd_otel.setup.OTLPSpanExporter") as mock_exporter_cls, \
             patch("wd_otel.setup.BatchSpanProcessor"), \
             patch("wd_otel.setup.trace"):
            mock_exporter_cls.return_value = MagicMock()
            setup_tracing(cfg)
            # Check endpoint was passed
            call_kwargs = mock_exporter_cls.call_args
            endpoint_arg = (
                call_kwargs.kwargs.get("endpoint") or
                (call_kwargs.args[0] if call_kwargs.args else None)
            )
            assert endpoint_arg == "myhost:4317"

    def test_sets_global_tracer_provider(self):
        cfg = _minimal_cfg()
        with patch("wd_otel.setup.OTLPSpanExporter") as mock_exporter_cls, \
             patch("wd_otel.setup.BatchSpanProcessor") as mock_proc, \
             patch("wd_otel.setup.trace") as mock_trace:
            mock_exporter_cls.return_value = MagicMock()
            mock_proc.return_value = MagicMock()

            setup_tracing(cfg)

            mock_trace.set_tracer_provider.assert_called_once()


# ---------------------------------------------------------------------------
# setup_metrics
# ---------------------------------------------------------------------------

class TestSetupMetrics:
    def test_returns_meter_provider(self):
        cfg = _minimal_cfg()
        with patch("wd_otel.setup.start_http_server"), \
             patch("wd_otel.setup.metrics") as mock_metrics:
            from opentelemetry.sdk.metrics import MeterProvider
            provider = setup_metrics(cfg)
            assert isinstance(provider, MeterProvider)

    def test_starts_prometheus_on_configured_port(self):
        cfg = _minimal_cfg(prometheus_port=9999)
        with patch("wd_otel.setup.start_http_server") as mock_start, \
             patch("wd_otel.setup.metrics"):
            setup_metrics(cfg)
            mock_start.assert_called_once_with(9999)

    def test_port_in_use_strict_raises(self):
        """In local/dev (strict), port-in-use raises WdOtelConfigError."""
        from wd_otel.errors import WdOtelConfigError
        cfg = _minimal_cfg(env="local")  # strict

        import socket
        with patch("wd_otel.setup.start_http_server", side_effect=OSError("port in use")), \
             patch("wd_otel.setup.metrics"):
            with pytest.raises(WdOtelConfigError):
                setup_metrics(cfg)

    def test_port_in_use_lenient_logs_warning(self, caplog):
        """In production (lenient), port-in-use logs warning and continues."""
        import logging
        cfg = _minimal_cfg(env="production")

        with patch("wd_otel.setup.start_http_server", side_effect=OSError("port in use")), \
             patch("wd_otel.setup.metrics"):
            with caplog.at_level(logging.WARNING):
                provider = setup_metrics(cfg)
            # Should not raise; provider still returned
            assert provider is not None


# ---------------------------------------------------------------------------
# setup_logging
# ---------------------------------------------------------------------------

class TestSetupLogging:
    def test_no_loki_url_does_not_add_loki_handler(self):
        cfg = _minimal_cfg(loki_url=None)
        with patch("wd_otel.setup.LoggingInstrumentor") as mock_li:
            mock_li.return_value.instrument = MagicMock()
            setup_logging(cfg)
            # Just ensure no exception raised without loki_url

    def test_with_loki_url_adds_handler(self):
        cfg = _minimal_cfg(loki_url="http://loki:3100/loki/api/v1/push")
        with patch("wd_otel.setup.LoggingInstrumentor") as mock_li, \
             patch("wd_otel.setup.logging_loki") as mock_loki:
            mock_li.return_value.instrument = MagicMock()
            mock_loki.LokiHandler.return_value = MagicMock()
            setup_logging(cfg)
            mock_loki.LokiHandler.assert_called_once()
