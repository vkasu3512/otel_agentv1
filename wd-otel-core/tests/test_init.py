"""Tests for wd_otel public API (__init__.py)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch, call
import pytest

import wd_otel
from wd_otel.errors import WdOtelConfigError


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_wd_otel():
    """Reset wd_otel module state between tests."""
    # Save original state
    orig_initialized = wd_otel._initialized
    orig_trace_provider = wd_otel._trace_provider
    orig_metrics_provider = wd_otel._metrics_provider

    yield

    # Restore original state
    wd_otel._initialized = orig_initialized
    wd_otel._trace_provider = orig_trace_provider
    wd_otel._metrics_provider = orig_metrics_provider


def _make_mock_config(env="staging"):
    cfg = MagicMock()
    cfg.service_name = "test-svc"
    cfg.service_version = "1.0.0"
    cfg.env = env
    cfg.prometheus_port = 8000
    cfg.loki_url = None
    return cfg


def _setup_init_mocks():
    """Return a context manager stack that patches all init dependencies."""
    import contextlib

    @contextlib.contextmanager
    def _ctx():
        mock_cfg = _make_mock_config()
        mock_trace_provider = MagicMock()
        mock_metrics_provider = MagicMock()
        mock_meter = MagicMock()
        mock_metrics_provider.get_meter.return_value = mock_meter

        with patch("wd_otel.load_config", return_value=mock_cfg) as p_cfg, \
             patch("wd_otel.setup_tracing", return_value=mock_trace_provider) as p_tracing, \
             patch("wd_otel.setup_metrics", return_value=mock_metrics_provider) as p_metrics, \
             patch("wd_otel.setup_logging") as p_logging, \
             patch("wd_otel.helpers") as p_helpers:
            yield {
                "cfg": mock_cfg,
                "trace_provider": mock_trace_provider,
                "metrics_provider": mock_metrics_provider,
                "meter": mock_meter,
                "p_cfg": p_cfg,
                "p_tracing": p_tracing,
                "p_metrics": p_metrics,
                "p_logging": p_logging,
                "p_helpers": p_helpers,
            }

    return _ctx()


# ---------------------------------------------------------------------------
# init()
# ---------------------------------------------------------------------------

class TestInit:
    def test_sets_initialized_flag(self):
        assert wd_otel._initialized is False
        with _setup_init_mocks():
            wd_otel.init()
            assert wd_otel._initialized is True

    def test_calls_load_config_with_path(self):
        with _setup_init_mocks() as mocks:
            wd_otel.init(config_path="/some/path.yaml")
            mocks["p_cfg"].assert_called_once_with("/some/path.yaml")

    def test_calls_load_config_with_none_by_default(self):
        with _setup_init_mocks() as mocks:
            wd_otel.init()
            mocks["p_cfg"].assert_called_once_with(None)

    def test_calls_setup_tracing(self):
        with _setup_init_mocks() as mocks:
            wd_otel.init()
            mocks["p_tracing"].assert_called_once_with(mocks["cfg"])

    def test_calls_setup_metrics(self):
        with _setup_init_mocks() as mocks:
            wd_otel.init()
            mocks["p_metrics"].assert_called_once_with(mocks["cfg"])

    def test_calls_setup_logging(self):
        with _setup_init_mocks() as mocks:
            wd_otel.init()
            mocks["p_logging"].assert_called_once_with(mocks["cfg"])

    def test_initializes_helpers_instruments(self):
        with _setup_init_mocks() as mocks:
            wd_otel.init()
            mocks["p_helpers"].init_instruments.assert_called_once()

    def test_stores_trace_provider(self):
        with _setup_init_mocks() as mocks:
            wd_otel.init()
            assert wd_otel._trace_provider is mocks["trace_provider"]

    def test_stores_metrics_provider(self):
        with _setup_init_mocks() as mocks:
            wd_otel.init()
            assert wd_otel._metrics_provider is mocks["metrics_provider"]


# ---------------------------------------------------------------------------
# _require_init / tracer() / meter()
# ---------------------------------------------------------------------------

class TestRequireInit:
    def test_tracer_before_init_raises(self):
        wd_otel._initialized = False
        with pytest.raises(WdOtelConfigError, match="init()"):
            wd_otel.tracer("my-tracer")

    def test_meter_before_init_raises(self):
        wd_otel._initialized = False
        with pytest.raises(WdOtelConfigError, match="init()"):
            wd_otel.meter("my-meter")

    def test_tracer_after_init_returns_tracer(self):
        wd_otel._initialized = True
        with patch("wd_otel.trace") as mock_trace:
            mock_trace.get_tracer.return_value = MagicMock()
            result = wd_otel.tracer("my-tracer")
            mock_trace.get_tracer.assert_called_once_with("my-tracer")
            assert result is mock_trace.get_tracer.return_value

    def test_meter_after_init_returns_meter(self):
        wd_otel._initialized = True
        with patch("wd_otel.metrics") as mock_metrics:
            mock_metrics.get_meter.return_value = MagicMock()
            result = wd_otel.meter("my-meter")
            mock_metrics.get_meter.assert_called_once_with("my-meter")
            assert result is mock_metrics.get_meter.return_value


# ---------------------------------------------------------------------------
# shutdown()
# ---------------------------------------------------------------------------

class TestShutdown:
    def test_shutdown_force_flushes_trace_provider(self):
        mock_tp = MagicMock()
        mock_mp = MagicMock()
        wd_otel._trace_provider = mock_tp
        wd_otel._metrics_provider = mock_mp
        wd_otel._initialized = True

        wd_otel.shutdown()

        mock_tp.force_flush.assert_called_once()

    def test_shutdown_shuts_down_metrics_provider(self):
        mock_tp = MagicMock()
        mock_mp = MagicMock()
        wd_otel._trace_provider = mock_tp
        wd_otel._metrics_provider = mock_mp
        wd_otel._initialized = True

        wd_otel.shutdown()

        mock_mp.shutdown.assert_called_once()

    def test_shutdown_resets_initialized(self):
        wd_otel._trace_provider = MagicMock()
        wd_otel._metrics_provider = MagicMock()
        wd_otel._initialized = True

        wd_otel.shutdown()

        assert wd_otel._initialized is False

    def test_shutdown_when_not_initialized_is_safe(self):
        """Calling shutdown before init should not raise."""
        wd_otel._initialized = False
        wd_otel._trace_provider = None
        wd_otel._metrics_provider = None

        # Should not raise
        wd_otel.shutdown()
