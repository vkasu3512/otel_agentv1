"""WD-OTel SDK — public API.

Usage::

    import wd_otel

    wd_otel.init()                          # or init(config_path="./wd-otel.yaml")
    tracer = wd_otel.tracer("my_service")
    meter  = wd_otel.meter("my_service")
    ...
    wd_otel.shutdown()
"""
from __future__ import annotations

import logging

from opentelemetry import metrics, trace

from wd_otel import helpers
from wd_otel.config import load_config
from wd_otel.errors import WdOtelConfigError
from wd_otel.setup import setup_logging, setup_metrics, setup_tracing

__all__ = [
    "init",
    "tracer",
    "meter",
    "shutdown",
    "WdOtelConfigError",
]

logger = logging.getLogger("wd_otel")

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_initialized: bool = False
_trace_provider = None
_metrics_provider = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def init(config_path: str | None = None) -> None:
    """Initialize the WD-OTel SDK.

    Loads configuration, sets up tracing, metrics, and logging, and initialises
    the helpers module's metric instruments.

    Args:
        config_path: Path to wd-otel.yaml. Defaults to ./wd-otel.yaml.
    """
    global _initialized, _trace_provider, _metrics_provider

    cfg = load_config(config_path)

    _trace_provider = setup_tracing(cfg)
    _metrics_provider = setup_metrics(cfg)
    setup_logging(cfg)

    # Initialise helper instrument references
    meter_instance = _metrics_provider.get_meter("wd_otel")
    helpers.init_instruments(meter_instance)
    helpers._tracer = trace.get_tracer("wd_otel")

    _initialized = True
    logger.info("[wd-otel] SDK initialised — service=%s env=%s", cfg.service_name, cfg.env)


def _require_init() -> None:
    """Raise WdOtelConfigError if init() has not been called."""
    if not _initialized:
        raise WdOtelConfigError(
            "wd_otel.init() must be called before using tracer() or meter()",
            hint="Call wd_otel.init() at application startup.",
        )


def tracer(name: str) -> trace.Tracer:
    """Return an OpenTelemetry Tracer for the given instrumentation scope.

    Args:
        name: Instrumentation scope name (typically the module or component name).

    Returns:
        opentelemetry.trace.Tracer

    Raises:
        WdOtelConfigError: If init() has not been called.
    """
    _require_init()
    return trace.get_tracer(name)


def meter(name: str) -> metrics.Meter:
    """Return an OpenTelemetry Meter for the given instrumentation scope.

    Args:
        name: Instrumentation scope name.

    Returns:
        opentelemetry.metrics.Meter

    Raises:
        WdOtelConfigError: If init() has not been called.
    """
    _require_init()
    return metrics.get_meter(name)


def shutdown() -> None:
    """Flush and shut down the trace and metrics providers.

    Safe to call even if init() was never called.
    """
    global _initialized

    if _trace_provider is not None:
        try:
            _trace_provider.force_flush()
        except Exception:
            logger.exception("[wd-otel] Error flushing trace provider during shutdown")

    if _metrics_provider is not None:
        try:
            _metrics_provider.shutdown()
        except Exception:
            logger.exception("[wd-otel] Error shutting down metrics provider during shutdown")

    _initialized = False
    logger.info("[wd-otel] SDK shut down")
