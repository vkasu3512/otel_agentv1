# WD-OTel SDK Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a three-package Python SDK (`wd-otel-core`, `wd-otel-mcp`, `wd-otel-orchestrator`) that abstracts OpenTelemetry instrumentation behind decorators, base classes, and helpers — so teams write business logic, not tracing code.

**Architecture:** Monorepo layout with three pip-installable packages under the project root. `wd-otel-core` provides config loading, OTel setup, and escape-hatch helpers. `wd-otel-mcp` provides the `@traced_tool` decorator for MCP servers. `wd-otel-orchestrator` provides the `TracedOrchestrator` base class for agent orchestrators. Packages depend on each other: `mcp` → `core`, `orchestrator` → `core`.

**Tech Stack:** Python 3.10+, OpenTelemetry SDK/API, PyYAML, FastMCP, OpenAI Agents SDK, pytest

**Spec:** `docs/superpowers/specs/2026-04-17-wd-otel-sdk-design.md`

---

## File Structure

```
wd-otel-core/
  pyproject.toml                    # Package metadata, deps: opentelemetry-*, pyyaml, logging-loki, prometheus-client
  wd_otel/
    __init__.py                     # Public API: init(), tracer(), meter(), shutdown()
    errors.py                       # WdOtelConfigError exception
    config.py                       # YAML loader, validation, env detection fallback
    setup.py                        # FilteringSpanExporter, TracerProvider, MeterProvider, Loki
    helpers.py                      # tool_span, lifecycle_span, child_span, record_transition
  tests/
    __init__.py
    conftest.py                     # Shared fixtures: tmp yaml files, OTel test setup
    test_errors.py
    test_config.py
    test_setup.py
    test_helpers.py
    test_init.py

wd-otel-mcp/
  pyproject.toml                    # Package metadata, deps: wd-otel-core, fastmcp
  wd_otel_mcp/
    __init__.py                     # Re-exports: traced_tool, current_span
    context.py                      # extract_parent_context(ctx: Context)
    decorator.py                    # @traced_tool decorator
  tests/
    __init__.py
    conftest.py
    test_context.py
    test_decorator.py

wd-otel-orchestrator/
  pyproject.toml                    # Package metadata, deps: wd-otel-core, openai-agents
  wd_otel_orchestrator/
    __init__.py                     # Re-exports: TracedOrchestrator
    transitions.py                  # TransitionTracker: state transitions + active worker metrics
    base.py                         # TracedOrchestrator base class with execute()
  tests/
    __init__.py
    conftest.py
    test_transitions.py
    test_base.py
```

---

## Task 1: `wd-otel-core` — Errors module

**Files:**
- Create: `wd-otel-core/wd_otel/errors.py`
- Create: `wd-otel-core/wd_otel/__init__.py` (empty placeholder)
- Create: `wd-otel-core/tests/__init__.py`
- Create: `wd-otel-core/tests/test_errors.py`
- Create: `wd-otel-core/pyproject.toml`

- [ ] **Step 1: Create package scaffolding**

```
mkdir -p wd-otel-core/wd_otel wd-otel-core/tests
```

- [ ] **Step 2: Write `pyproject.toml`**

Create `wd-otel-core/pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=68.0"]
build-backend = "setuptools.build_meta"

[project]
name = "wd-otel-core"
version = "0.1.0"
description = "WD OpenTelemetry SDK — core config, setup, and helpers"
requires-python = ">=3.10"
dependencies = [
    "opentelemetry-api>=1.24.0",
    "opentelemetry-sdk>=1.24.0",
    "opentelemetry-exporter-otlp-proto-grpc>=1.24.0",
    "opentelemetry-exporter-prometheus>=0.45b0",
    "opentelemetry-instrumentation-logging>=0.45b0",
    "prometheus-client>=0.20.0",
    "logging-loki>=0.3.1",
    "pyyaml>=6.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.0"]
```

- [ ] **Step 3: Write the failing test**

Create `wd-otel-core/tests/__init__.py` (empty file).

Create `wd-otel-core/tests/test_errors.py`:

```python
from wd_otel.errors import WdOtelConfigError


def test_wd_otel_config_error_is_exception():
    err = WdOtelConfigError("test message")
    assert isinstance(err, Exception)
    assert str(err) == "test message"


def test_wd_otel_config_error_with_hint():
    err = WdOtelConfigError("missing config", hint="Create wd-otel.yaml")
    assert "missing config" in str(err)
    assert err.hint == "Create wd-otel.yaml"


def test_wd_otel_config_error_hint_defaults_to_none():
    err = WdOtelConfigError("basic error")
    assert err.hint is None
```

- [ ] **Step 4: Run test to verify it fails**

Run: `cd wd-otel-core && pip install -e ".[dev]" && pytest tests/test_errors.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'wd_otel'`

- [ ] **Step 5: Write `errors.py`**

Create `wd-otel-core/wd_otel/__init__.py` (empty file for now).

Create `wd-otel-core/wd_otel/errors.py`:

```python
class WdOtelConfigError(Exception):
    """Raised when WD-OTel SDK configuration is invalid or missing.

    In local/dev environments, this halts the service at startup.
    In staging/production, the SDK logs a warning and degrades gracefully instead.
    """

    def __init__(self, message: str, hint: str | None = None):
        super().__init__(message)
        self.hint = hint
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd wd-otel-core && pytest tests/test_errors.py -v`
Expected: 3 passed

- [ ] **Step 7: Commit**

```bash
git add wd-otel-core/
git commit -m "feat(wd-otel-core): add errors module with WdOtelConfigError"
```

---

## Task 2: `wd-otel-core` — Config module

**Files:**
- Create: `wd-otel-core/wd_otel/config.py`
- Create: `wd-otel-core/tests/conftest.py`
- Create: `wd-otel-core/tests/test_config.py`

- [ ] **Step 1: Write the failing tests**

Create `wd-otel-core/tests/conftest.py`:

```python
import os
import pytest
import yaml


@pytest.fixture
def tmp_config(tmp_path):
    """Write a wd-otel.yaml to a temp dir and return its path."""
    def _make(data: dict) -> str:
        path = tmp_path / "wd-otel.yaml"
        path.write_text(yaml.dump(data))
        return str(path)
    return _make


@pytest.fixture
def minimal_config_data():
    return {
        "service": {"name": "test-service", "env": "local"},
    }


@pytest.fixture(autouse=True)
def clean_env():
    """Remove WD_OTEL_ENV from env before each test."""
    old = os.environ.pop("WD_OTEL_ENV", None)
    yield
    if old is not None:
        os.environ["WD_OTEL_ENV"] = old
    else:
        os.environ.pop("WD_OTEL_ENV", None)
```

Create `wd-otel-core/tests/test_config.py`:

```python
import os
import pytest
from wd_otel.config import load_config, WdOtelConfig
from wd_otel.errors import WdOtelConfigError


class TestLoadConfig:
    """Tests for YAML loading and validation."""

    def test_loads_valid_config(self, tmp_config, minimal_config_data):
        path = tmp_config(minimal_config_data)
        cfg = load_config(path)
        assert isinstance(cfg, WdOtelConfig)
        assert cfg.service_name == "test-service"
        assert cfg.env == "local"

    def test_applies_defaults_for_optional_fields(self, tmp_config, minimal_config_data):
        path = tmp_config(minimal_config_data)
        cfg = load_config(path)
        assert cfg.service_version == "0.0.0"
        assert cfg.traces_endpoint == "localhost:4317"
        assert cfg.traces_protocol == "grpc"
        assert cfg.filter_libraries == []
        assert cfg.prometheus_port == 8000
        assert cfg.loki_url is None

    def test_overrides_defaults_with_yaml_values(self, tmp_config):
        data = {
            "service": {"name": "my-svc", "version": "2.0.0", "env": "dev"},
            "traces": {"endpoint": "tempo:4317", "filter_libraries": ["fastmcp"]},
            "metrics": {"prometheus_port": 9001},
            "logs": {"loki_url": "http://loki:3100/loki/api/v1/push"},
        }
        cfg = load_config(tmp_config(data))
        assert cfg.service_version == "2.0.0"
        assert cfg.traces_endpoint == "tempo:4317"
        assert cfg.filter_libraries == ["fastmcp"]
        assert cfg.prometheus_port == 9001
        assert cfg.loki_url == "http://loki:3100/loki/api/v1/push"


class TestValidationStrictEnv:
    """In local/dev, config errors raise WdOtelConfigError."""

    def test_missing_file_raises_in_dev(self):
        os.environ["WD_OTEL_ENV"] = "dev"
        with pytest.raises(WdOtelConfigError, match="not found"):
            load_config("/nonexistent/wd-otel.yaml")

    def test_missing_service_name_raises_in_local(self, tmp_config):
        path = tmp_config({"service": {"env": "local"}})
        with pytest.raises(WdOtelConfigError, match="service.name"):
            load_config(path)

    def test_missing_service_env_raises_in_local(self, tmp_config):
        os.environ["WD_OTEL_ENV"] = "local"
        path = tmp_config({"service": {"name": "svc"}})
        with pytest.raises(WdOtelConfigError, match="service.env"):
            load_config(path)

    def test_invalid_env_value_raises_in_dev(self, tmp_config):
        os.environ["WD_OTEL_ENV"] = "dev"
        path = tmp_config({"service": {"name": "svc", "env": "invalid"}})
        with pytest.raises(WdOtelConfigError, match="service.env"):
            load_config(path)


class TestValidationLenientEnv:
    """In staging/production, config errors log warnings and use defaults."""

    def test_missing_file_returns_defaults_in_production(self):
        os.environ["WD_OTEL_ENV"] = "production"
        cfg = load_config("/nonexistent/wd-otel.yaml")
        assert cfg.service_name == "unknown-service"
        assert cfg.env == "production"

    def test_missing_service_name_defaults_in_staging(self, tmp_config):
        os.environ["WD_OTEL_ENV"] = "staging"
        path = tmp_config({"service": {"env": "staging"}})
        cfg = load_config(path)
        assert cfg.service_name == "unknown-service"


class TestEnvDetectionFallback:
    """Environment detection: YAML → WD_OTEL_ENV → defaults to production."""

    def test_yaml_env_takes_precedence(self, tmp_config):
        os.environ["WD_OTEL_ENV"] = "production"
        path = tmp_config({"service": {"name": "svc", "env": "local"}})
        cfg = load_config(path)
        assert cfg.env == "local"

    def test_falls_back_to_wd_otel_env(self):
        os.environ["WD_OTEL_ENV"] = "production"
        cfg = load_config("/nonexistent/wd-otel.yaml")
        assert cfg.env == "production"

    def test_defaults_to_production_when_nothing_set(self):
        cfg = load_config("/nonexistent/wd-otel.yaml")
        assert cfg.env == "production"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd wd-otel-core && pytest tests/test_config.py -v`
Expected: FAIL with `ImportError: cannot import name 'load_config'`

- [ ] **Step 3: Write `config.py`**

Create `wd-otel-core/wd_otel/config.py`:

```python
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from wd_otel.errors import WdOtelConfigError

logger = logging.getLogger("wd_otel.config")

_VALID_ENVS = {"local", "dev", "staging", "production"}


@dataclass(frozen=True)
class WdOtelConfig:
    """Validated, immutable configuration for the WD-OTel SDK."""

    service_name: str
    service_version: str = "0.0.0"
    env: str = "production"

    traces_endpoint: str = "localhost:4317"
    traces_protocol: str = "grpc"
    filter_libraries: list[str] = field(default_factory=list)

    prometheus_port: int = 8000

    loki_url: str | None = None

    @property
    def is_strict(self) -> bool:
        """True in local/dev — config errors raise exceptions."""
        return self.env in ("local", "dev")


def _detect_env() -> str:
    """Detect environment from WD_OTEL_ENV env var, default to production."""
    return os.environ.get("WD_OTEL_ENV", "production")


def _fail_or_warn(message: str, env: str, hint: str | None = None) -> None:
    """Raise in strict envs, warn in lenient envs."""
    if env in ("local", "dev"):
        raise WdOtelConfigError(message, hint=hint)
    logger.warning(f"[wd-otel] {message}")


def load_config(path: str | None = None) -> WdOtelConfig:
    """Load and validate wd-otel.yaml. Returns WdOtelConfig.

    Args:
        path: Explicit path to config file. If None, looks for
              wd-otel.yaml in the current working directory.

    Raises:
        WdOtelConfigError: In local/dev if config is invalid or missing.
    """
    if path is None:
        path = str(Path.cwd() / "wd-otel.yaml")

    detected_env = _detect_env()

    # Load YAML file
    config_path = Path(path)
    if not config_path.exists():
        _fail_or_warn(
            f"wd-otel.yaml not found at {config_path}",
            detected_env,
            hint=f"Create {config_path} with:\n  service:\n    name: \"my-service\"\n    env: \"local\"",
        )
        return WdOtelConfig(service_name="unknown-service", env=detected_env)

    with open(config_path) as f:
        raw = yaml.safe_load(f) or {}

    # Extract sections
    service = raw.get("service", {})
    traces = raw.get("traces", {})
    metrics_section = raw.get("metrics", {})
    logs = raw.get("logs", {})

    # Resolve env: YAML takes precedence, then detected_env
    env = service.get("env") or detected_env

    # Validate env value
    if env not in _VALID_ENVS:
        _fail_or_warn(
            f"service.env must be one of {_VALID_ENVS}, got '{env}'",
            detected_env,
        )
        env = "production"

    # Validate required: service.name
    service_name = service.get("name")
    if not service_name:
        _fail_or_warn("service.name is required in wd-otel.yaml", env)
        service_name = "unknown-service"

    return WdOtelConfig(
        service_name=service_name,
        service_version=service.get("version", "0.0.0"),
        env=env,
        traces_endpoint=traces.get("endpoint", "localhost:4317"),
        traces_protocol=traces.get("protocol", "grpc"),
        filter_libraries=traces.get("filter_libraries", []),
        prometheus_port=metrics_section.get("prometheus_port", 8000),
        loki_url=logs.get("loki_url"),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd wd-otel-core && pytest tests/test_config.py -v`
Expected: All passed

- [ ] **Step 5: Commit**

```bash
git add wd-otel-core/wd_otel/config.py wd-otel-core/tests/conftest.py wd-otel-core/tests/test_config.py
git commit -m "feat(wd-otel-core): add config module with YAML loading and env-aware validation"
```

---

## Task 3: `wd-otel-core` — Setup module

**Files:**
- Create: `wd-otel-core/wd_otel/setup.py`
- Create: `wd-otel-core/tests/test_setup.py`

- [ ] **Step 1: Write the failing tests**

Create `wd-otel-core/tests/test_setup.py`:

```python
import pytest
from unittest.mock import patch, MagicMock
from wd_otel.config import WdOtelConfig
from wd_otel.setup import setup_tracing, setup_metrics, FilteringSpanExporter


class TestFilteringSpanExporter:
    """FilteringSpanExporter drops CLIENT spans and filtered libraries."""

    def test_drops_client_kind_spans(self):
        from opentelemetry.trace import SpanKind
        mock_wrapped = MagicMock()
        exporter = FilteringSpanExporter(mock_wrapped)

        client_span = MagicMock()
        client_span.kind = SpanKind.CLIENT

        server_span = MagicMock()
        server_span.kind = SpanKind.SERVER
        server_span.instrumentation_scope = MagicMock()
        server_span.instrumentation_scope.name = "my_app"

        exporter.export([client_span, server_span])
        mock_wrapped.export.assert_called_once()
        exported = mock_wrapped.export.call_args[0][0]
        assert len(exported) == 1
        assert exported[0] is server_span

    def test_drops_filtered_library_spans(self):
        from opentelemetry.trace import SpanKind
        mock_wrapped = MagicMock()
        exporter = FilteringSpanExporter(mock_wrapped, filter_libraries=["fastmcp"])

        fastmcp_span = MagicMock()
        fastmcp_span.kind = SpanKind.SERVER
        fastmcp_span.instrumentation_scope = MagicMock()
        fastmcp_span.instrumentation_scope.name = "fastmcp"

        app_span = MagicMock()
        app_span.kind = SpanKind.SERVER
        app_span.instrumentation_scope = MagicMock()
        app_span.instrumentation_scope.name = "my_app"

        exporter.export([fastmcp_span, app_span])
        exported = mock_wrapped.export.call_args[0][0]
        assert len(exported) == 1
        assert exported[0] is app_span

    def test_delegates_shutdown(self):
        mock_wrapped = MagicMock()
        exporter = FilteringSpanExporter(mock_wrapped)
        exporter.shutdown()
        mock_wrapped.shutdown.assert_called_once()

    def test_delegates_force_flush(self):
        mock_wrapped = MagicMock()
        exporter = FilteringSpanExporter(mock_wrapped)
        exporter.force_flush(5000)
        mock_wrapped.force_flush.assert_called_once_with(5000)


class TestSetupTracing:
    """setup_tracing returns a configured TracerProvider."""

    @patch("wd_otel.setup.OTLPSpanExporter")
    @patch("wd_otel.setup.BatchSpanProcessor")
    def test_returns_tracer_provider(self, mock_bsp, mock_exporter):
        cfg = WdOtelConfig(service_name="test-svc", env="local")
        tp = setup_tracing(cfg)
        from opentelemetry.sdk.trace import TracerProvider
        assert isinstance(tp, TracerProvider)

    @patch("wd_otel.setup.OTLPSpanExporter")
    @patch("wd_otel.setup.BatchSpanProcessor")
    def test_uses_config_endpoint(self, mock_bsp, mock_exporter):
        cfg = WdOtelConfig(service_name="test-svc", env="local", traces_endpoint="tempo:4317")
        setup_tracing(cfg)
        mock_exporter.assert_called_once_with(endpoint="tempo:4317", insecure=True)


class TestSetupMetrics:
    """setup_metrics returns a configured MeterProvider."""

    @patch("wd_otel.setup.start_http_server")
    def test_returns_meter_provider(self, mock_http):
        cfg = WdOtelConfig(service_name="test-svc", env="local", prometheus_port=19090)
        mp = setup_metrics(cfg)
        from opentelemetry.sdk.metrics import MeterProvider
        assert isinstance(mp, MeterProvider)

    @patch("wd_otel.setup.start_http_server")
    def test_starts_prometheus_on_configured_port(self, mock_http):
        cfg = WdOtelConfig(service_name="test-svc", env="local", prometheus_port=19090)
        setup_metrics(cfg)
        mock_http.assert_called_once_with(19090, addr="0.0.0.0")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd wd-otel-core && pytest tests/test_setup.py -v`
Expected: FAIL with `ImportError: cannot import name 'setup_tracing'`

- [ ] **Step 3: Write `setup.py`**

Create `wd-otel-core/wd_otel/setup.py`:

```python
from __future__ import annotations

import logging
from typing import Sequence

from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider, ReadableSpan
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SpanExporter,
    SpanExportResult,
)
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.trace import SpanKind
from prometheus_client import start_http_server

from wd_otel.config import WdOtelConfig
from wd_otel.errors import WdOtelConfigError

logger = logging.getLogger("wd_otel.setup")


class FilteringSpanExporter(SpanExporter):
    """Wraps another exporter and drops CLIENT spans and filtered library spans."""

    def __init__(
        self, wrapped: SpanExporter, filter_libraries: list[str] | None = None
    ):
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
            lib = (
                span.instrumentation_scope.name
                if span.instrumentation_scope
                else ""
            )
            if lib in self._filter_libraries:
                return True
        return False

    def shutdown(self) -> None:
        self._wrapped.shutdown()

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        return self._wrapped.force_flush(timeout_millis)


def _build_resource(cfg: WdOtelConfig) -> Resource:
    return Resource.create(
        {
            "service.name": cfg.service_name,
            "service.version": cfg.service_version,
        }
    )


def setup_tracing(cfg: WdOtelConfig) -> TracerProvider:
    """Create and configure a TracerProvider with OTLP gRPC export + span filtering."""
    resource = _build_resource(cfg)
    raw_exporter = OTLPSpanExporter(endpoint=cfg.traces_endpoint, insecure=True)
    exporter = FilteringSpanExporter(raw_exporter, cfg.filter_libraries)
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    return provider


def setup_metrics(cfg: WdOtelConfig) -> MeterProvider:
    """Create and configure a MeterProvider with Prometheus exporter."""
    resource = _build_resource(cfg)
    try:
        start_http_server(cfg.prometheus_port, addr="0.0.0.0")
    except OSError as e:
        if cfg.is_strict:
            raise WdOtelConfigError(
                f"metrics.prometheus_port {cfg.prometheus_port} already in use: {e}"
            ) from e
        logger.warning(f"[wd-otel] Prometheus port {cfg.prometheus_port} in use, metrics disabled: {e}")
    reader = PrometheusMetricReader()
    provider = MeterProvider(resource=resource, metric_readers=[reader])
    metrics.set_meter_provider(provider)
    return provider


def setup_logging(cfg: WdOtelConfig) -> None:
    """Configure logging with OTel trace/span ID injection and optional Loki push."""
    logging.basicConfig(level=logging.INFO)
    LoggingInstrumentor().instrument(set_logging_format=True)

    if cfg.loki_url:
        try:
            import logging_loki

            handler = logging_loki.LokiHandler(
                url=cfg.loki_url,
                tags={"service": cfg.service_name, "env": cfg.env},
                version="1",
            )
            handler.setLevel(logging.INFO)
            logging.getLogger().addHandler(handler)
        except ImportError:
            logger.warning("[wd-otel] logging-loki not installed, Loki push disabled")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd wd-otel-core && pytest tests/test_setup.py -v`
Expected: All passed

- [ ] **Step 5: Commit**

```bash
git add wd-otel-core/wd_otel/setup.py wd-otel-core/tests/test_setup.py
git commit -m "feat(wd-otel-core): add setup module with FilteringSpanExporter, tracing, metrics, logging"
```

---

## Task 4: `wd-otel-core` — Helpers module

**Files:**
- Create: `wd-otel-core/wd_otel/helpers.py`
- Create: `wd-otel-core/tests/test_helpers.py`

- [ ] **Step 1: Write the failing tests**

Create `wd-otel-core/tests/test_helpers.py`:

```python
import pytest
from unittest.mock import patch, MagicMock
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory import InMemorySpanExporter
from opentelemetry import trace

from wd_otel import helpers


@pytest.fixture(autouse=True)
def setup_test_tracer():
    """Set up an in-memory tracer for capturing spans in tests."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    # Patch the helpers module to use a meter that won't fail
    helpers._tracer = provider.get_tracer("test")
    helpers._meter = MagicMock()
    helpers._tool_invocations = MagicMock()
    helpers._tool_duration = MagicMock()
    helpers._tool_timeouts = MagicMock()
    helpers._session_counter = MagicMock()
    helpers._session_duration = MagicMock()
    helpers._state_transitions = MagicMock()
    helpers._active_workers = MagicMock()
    yield exporter
    exporter.clear()


class TestChildSpan:
    def test_creates_child_span(self, setup_test_tracer):
        exporter = setup_test_tracer
        with helpers.child_span("my_step", attributes={"key": "val"}):
            pass
        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].name == "my_step"
        assert spans[0].attributes.get("key") == "val"

    def test_child_span_yields_span_object(self, setup_test_tracer):
        with helpers.child_span("step") as span:
            span.set_attribute("dynamic", 42)
        spans = setup_test_tracer.get_finished_spans()
        assert spans[0].attributes.get("dynamic") == 42


class TestToolSpan:
    def test_records_invocation_metric_on_success(self, setup_test_tracer):
        mock_ctx = MagicMock()
        mock_ctx.request_context.request.headers = {}

        with helpers.tool_span(mock_ctx, "add", server="s1", inputs={"a": 1}) as ts:
            ts.set_output(2)

        helpers._tool_invocations.add.assert_called_once()
        call_args = helpers._tool_invocations.add.call_args
        assert call_args[0][0] == 1
        assert call_args[0][1]["status"] == "success"

    def test_records_duration_metric(self, setup_test_tracer):
        mock_ctx = MagicMock()
        mock_ctx.request_context.request.headers = {}

        with helpers.tool_span(mock_ctx, "add", server="s1"):
            pass

        helpers._tool_duration.record.assert_called_once()

    def test_records_error_status_on_exception(self, setup_test_tracer):
        mock_ctx = MagicMock()
        mock_ctx.request_context.request.headers = {}

        with pytest.raises(ValueError):
            with helpers.tool_span(mock_ctx, "add", server="s1"):
                raise ValueError("boom")

        call_args = helpers._tool_invocations.add.call_args
        assert call_args[0][1]["status"] == "error"


class TestLifecycleSpan:
    def test_complete_sets_status(self, setup_test_tracer):
        exporter = setup_test_tracer
        with helpers.lifecycle_span("wf", input="hello") as lc:
            lc.complete(agent="A", output="world")

        helpers._session_counter.add.assert_called_once()
        helpers._session_duration.record.assert_called_once()

    def test_error_records_exception(self, setup_test_tracer):
        with pytest.raises(RuntimeError):
            with helpers.lifecycle_span("wf", input="hello") as lc:
                lc.error(agent="A", exception=RuntimeError("fail"))
                raise RuntimeError("fail")

        helpers._session_counter.add.assert_called_once()


class TestRecordTransition:
    def test_records_transition_metric(self, setup_test_tracer):
        exporter = setup_test_tracer
        helpers.record_transition(
            worker="Agent1", from_state="idle", to_state="running", reason="test"
        )
        helpers._state_transitions.add.assert_called_once()
        spans = exporter.get_finished_spans()
        assert any(s.name == "orchestrator.transition" for s in spans)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd wd-otel-core && pytest tests/test_helpers.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Write `helpers.py`**

Create `wd-otel-core/wd_otel/helpers.py`:

```python
"""Escape-hatch helpers: tool_span, lifecycle_span, child_span, record_transition.

These are composable building blocks used internally by wd-otel-mcp and
wd-otel-orchestrator, and available to teams for custom scenarios.
"""
from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Any

from opentelemetry import trace, metrics
from opentelemetry.propagate import extract as otel_extract

logger = logging.getLogger("wd_otel.helpers")

# Module-level instruments — initialized by wd_otel.init() or overridden in tests
_tracer: trace.Tracer | None = None
_meter: metrics.Meter | None = None

# MCP tool metrics
_tool_invocations = None
_tool_duration = None
_tool_timeouts = None

# Orchestrator metrics
_session_counter = None
_session_duration = None
_state_transitions = None
_active_workers = None
_orchestration_errors = None
_sync_failures = None


def _get_tracer() -> trace.Tracer:
    if _tracer is not None:
        return _tracer
    return trace.get_tracer("wd_otel")


def init_instruments(meter: metrics.Meter) -> None:
    """Create all metric instruments. Called once by wd_otel.init()."""
    global _tool_invocations, _tool_duration, _tool_timeouts
    global _session_counter, _session_duration
    global _state_transitions, _active_workers
    global _orchestration_errors, _sync_failures

    _tool_invocations = meter.create_counter(
        "mcp.tool.invocations", unit="1",
        description="Total MCP tool invocations by tool, server, and status",
    )
    _tool_duration = meter.create_histogram(
        "mcp.tool.duration", unit="s",
        description="MCP tool response latency by tool and server",
    )
    _tool_timeouts = meter.create_counter(
        "mcp.tool.timeouts", unit="1",
        description="MCP tool calls that exceeded timeout",
    )
    _session_counter = meter.create_counter(
        "multi_agent.sessions.total", unit="1",
        description="Total multi-agent sessions run",
    )
    _session_duration = meter.create_histogram(
        "multi_agent.session.duration", unit="s",
        description="Wall-clock duration of each multi-agent session",
    )
    _state_transitions = meter.create_counter(
        "orchestrator.state.transitions", unit="1",
        description="Worker state transitions",
    )
    _active_workers = meter.create_up_down_counter(
        "orchestrator.active.workers", unit="1",
        description="Currently active workers (sub-agents)",
    )
    _orchestration_errors = meter.create_counter(
        "orchestrator.errors", unit="1",
        description="Total orchestration errors",
    )
    _sync_failures = meter.create_counter(
        "orchestrator.sync.failures", unit="1",
        description="Status sync failures between orchestrator and API",
    )


def extract_parent_context(ctx: Any) -> Any:
    """Extract W3C trace context from a FastMCP Context's request headers."""
    try:
        headers = dict(ctx.request_context.request.headers)
        tp = headers.get("traceparent")
        if not tp:
            logger.warning("[wd-otel] traceparent header missing — span will be a root")
            return None
        parent_ctx = otel_extract(headers)
        logger.debug(f"[wd-otel] traceparent={tp} -> linked")
        return parent_ctx
    except Exception as exc:
        logger.warning(f"[wd-otel] Failed to extract parent context: {exc}")
        return None


# ── tool_span ────────────────────────────────────────────────────────────────

class ToolSpanContext:
    """Wrapper yielded by tool_span, provides set_output()."""

    def __init__(self, span: trace.Span):
        self._span = span

    def set_output(self, result: Any) -> None:
        self._span.set_attribute("result", str(result))

    def set_attribute(self, key: str, value: Any) -> None:
        self._span.set_attribute(key, value)


@contextmanager
def tool_span(
    ctx: Any,
    tool_name: str,
    server: str,
    inputs: dict[str, Any] | None = None,
    timeout_s: float = 10.0,
):
    """Context manager for MCP tool instrumentation with guaranteed metrics.

    Creates a span, records invocation/duration/timeout metrics on exit.
    """
    tracer = _get_tracer()
    parent_ctx = extract_parent_context(ctx)
    start = time.perf_counter()
    status = "success"

    with tracer.start_as_current_span(
        f"{tool_name}_operation", context=parent_ctx
    ) as span:
        if inputs:
            for k, v in inputs.items():
                span.set_attribute(f"input.{k}", str(v))

        try:
            yield ToolSpanContext(span)
        except TimeoutError:
            status = "timeout"
            _tool_timeouts.add(1, {"tool": tool_name, "tool_server": server})
            span.record_exception(TimeoutError(f"{tool_name} timed out"))
            raise
        except Exception as e:
            status = "error"
            span.record_exception(e)
            raise
        finally:
            elapsed = time.perf_counter() - start
            _tool_invocations.add(
                1, {"tool": tool_name, "tool_server": server, "status": status}
            )
            _tool_duration.record(
                elapsed, {"tool": tool_name, "tool_server": server}
            )
            logger.info(f"[wd-otel] {tool_name} {status} in {elapsed:.3f}s")


# ── lifecycle_span ───────────────────────────────────────────────────────────

class LifecycleSpanContext:
    """Wrapper yielded by lifecycle_span, provides complete() and error()."""

    def __init__(self, span: trace.Span, workflow_name: str):
        self._span = span
        self._workflow_name = workflow_name
        self._status = "unknown"

    def complete(self, agent: str, output: str | Any = "") -> None:
        self._status = "completed"
        self._span.set_attribute("lifecycle.status", "completed")
        self._span.set_attribute("lifecycle.final_agent", agent)
        self._span.set_attribute("agent.output", str(output))

    def error(self, agent: str, exception: Exception) -> None:
        self._status = "error"
        self._span.set_attribute("lifecycle.status", "error")
        self._span.set_attribute("lifecycle.error", str(exception))
        self._span.record_exception(exception)

    def transition(self, worker: str, from_state: str, to_state: str) -> None:
        record_transition(worker=worker, from_state=from_state, to_state=to_state)


@contextmanager
def lifecycle_span(workflow_name: str, input: str = ""):
    """Context manager for orchestrator lifecycle with guaranteed session metrics."""
    tracer = _get_tracer()
    start = time.perf_counter()

    with tracer.start_as_current_span(
        "orchestrator.worker.lifecycle",
        attributes={"workflow.name": workflow_name, "agent.input": input},
    ) as span:
        lc = LifecycleSpanContext(span, workflow_name)
        try:
            yield lc
        finally:
            elapsed = time.perf_counter() - start
            span.set_attribute("lifecycle.duration_s", round(elapsed, 3))
            _session_counter.add(1, {"workflow": workflow_name})
            _session_duration.record(elapsed, {"workflow": workflow_name})


# ── child_span ───────────────────────────────────────────────────────────────

@contextmanager
def child_span(name: str, attributes: dict[str, Any] | None = None):
    """Create a child span of the current active span."""
    tracer = _get_tracer()
    with tracer.start_as_current_span(name, attributes=attributes or {}) as span:
        yield span


# ── record_transition ────────────────────────────────────────────────────────

def record_transition(
    worker: str,
    from_state: str,
    to_state: str,
    reason: str = "",
) -> None:
    """Record a state transition with span + metrics."""
    tracer = _get_tracer()
    with tracer.start_as_current_span(
        "orchestrator.transition",
        attributes={
            "worker.type": worker,
            "worker.from_state": from_state,
            "worker.to_state": to_state,
        },
    ) as span:
        if reason:
            span.set_attribute("handoff.reason", reason)
        _state_transitions.add(
            1,
            {"worker_type": worker, "from_state": from_state, "to_state": to_state},
        )
        if to_state == "running":
            _active_workers.add(1, {"worker_type": worker})
        elif to_state in ("completed", "error"):
            _active_workers.add(-1, {"worker_type": worker})
        span.add_event(
            "state_changed", {"previous": from_state, "current": to_state}
        )
        logger.info(f"[wd-otel] {worker}: {from_state}->{to_state}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd wd-otel-core && pytest tests/test_helpers.py -v`
Expected: All passed

- [ ] **Step 5: Commit**

```bash
git add wd-otel-core/wd_otel/helpers.py wd-otel-core/tests/test_helpers.py
git commit -m "feat(wd-otel-core): add helpers module with tool_span, lifecycle_span, child_span, record_transition"
```

---

## Task 5: `wd-otel-core` — Public `__init__.py` API

**Files:**
- Modify: `wd-otel-core/wd_otel/__init__.py`
- Create: `wd-otel-core/tests/test_init.py`

- [ ] **Step 1: Write the failing tests**

Create `wd-otel-core/tests/test_init.py`:

```python
import os
import pytest
from unittest.mock import patch, MagicMock
import wd_otel
from wd_otel.errors import WdOtelConfigError


class TestInit:
    """Tests for wd_otel.init() public API."""

    @patch("wd_otel.setup_logging")
    @patch("wd_otel.setup_metrics")
    @patch("wd_otel.setup_tracing")
    @patch("wd_otel.load_config")
    def test_init_sets_initialized_flag(self, mock_load, mock_trace, mock_metrics, mock_logs):
        from wd_otel.config import WdOtelConfig
        mock_load.return_value = WdOtelConfig(service_name="test", env="local")
        mock_trace.return_value = MagicMock()
        mock_metrics.return_value = MagicMock()

        wd_otel._initialized = False
        wd_otel.init("/fake/path.yaml")
        assert wd_otel._initialized is True

    def test_tracer_before_init_raises(self):
        wd_otel._initialized = False
        with pytest.raises(WdOtelConfigError, match="wd_otel.init()"):
            wd_otel.tracer("test")

    def test_meter_before_init_raises(self):
        wd_otel._initialized = False
        with pytest.raises(WdOtelConfigError, match="wd_otel.init()"):
            wd_otel.meter("test")

    @patch("wd_otel.setup_logging")
    @patch("wd_otel.setup_metrics")
    @patch("wd_otel.setup_tracing")
    @patch("wd_otel.load_config")
    def test_tracer_after_init_returns_tracer(self, mock_load, mock_trace, mock_metrics, mock_logs):
        from wd_otel.config import WdOtelConfig
        mock_load.return_value = WdOtelConfig(service_name="test", env="local")
        mock_trace.return_value = MagicMock()
        mock_metrics.return_value = MagicMock()

        wd_otel._initialized = False
        wd_otel.init("/fake/path.yaml")
        t = wd_otel.tracer("my_module")
        assert t is not None

    @patch("wd_otel.setup_logging")
    @patch("wd_otel.setup_metrics")
    @patch("wd_otel.setup_tracing")
    @patch("wd_otel.load_config")
    def test_shutdown_flushes_providers(self, mock_load, mock_trace, mock_metrics, mock_logs):
        from wd_otel.config import WdOtelConfig
        mock_load.return_value = WdOtelConfig(service_name="test", env="local")
        mock_tp = MagicMock()
        mock_mp = MagicMock()
        mock_trace.return_value = mock_tp
        mock_metrics.return_value = mock_mp

        wd_otel._initialized = False
        wd_otel.init("/fake/path.yaml")
        wd_otel.shutdown()
        mock_tp.force_flush.assert_called_once()
        mock_mp.shutdown.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd wd-otel-core && pytest tests/test_init.py -v`
Expected: FAIL

- [ ] **Step 3: Write `__init__.py`**

Overwrite `wd-otel-core/wd_otel/__init__.py`:

```python
"""WD-OTel SDK — core config, setup, and helpers.

Usage:
    import wd_otel
    wd_otel.init()                    # reads wd-otel.yaml from cwd
    tracer = wd_otel.tracer("my_module")
    meter = wd_otel.meter("my_module")
"""
from __future__ import annotations

from opentelemetry import trace, metrics

from wd_otel.config import load_config
from wd_otel.errors import WdOtelConfigError
from wd_otel.setup import setup_tracing, setup_metrics, setup_logging
from wd_otel import helpers

_initialized: bool = False
_trace_provider = None
_metrics_provider = None


def init(config_path: str | None = None) -> None:
    """Initialize the WD-OTel SDK. Must be called before tracer()/meter().

    Args:
        config_path: Path to wd-otel.yaml. If None, looks in cwd.
    """
    global _initialized, _trace_provider, _metrics_provider

    cfg = load_config(config_path)
    _trace_provider = setup_tracing(cfg)
    _metrics_provider = setup_metrics(cfg)
    setup_logging(cfg)

    # Initialize metric instruments in the helpers module
    m = metrics.get_meter("wd_otel")
    helpers._tracer = trace.get_tracer("wd_otel")
    helpers._meter = m
    helpers.init_instruments(m)

    _initialized = True

    print(f"[wd-otel] Service: {cfg.service_name} v{cfg.service_version} ({cfg.env}) ready")
    print(f"[wd-otel] Traces  -> grpc://{cfg.traces_endpoint}")
    print(f"[wd-otel] Metrics -> http://localhost:{cfg.prometheus_port}/metrics")
    if cfg.loki_url:
        print(f"[wd-otel] Logs    -> {cfg.loki_url}")


def _require_init() -> None:
    if not _initialized:
        raise WdOtelConfigError(
            "wd_otel.init() must be called before using tracer() or meter()",
            hint="Add 'import wd_otel; wd_otel.init()' at the top of your module",
        )


def tracer(name: str) -> trace.Tracer:
    """Return a tracer scoped to the given module name."""
    _require_init()
    return trace.get_tracer(name)


def meter(name: str) -> metrics.Meter:
    """Return a meter scoped to the given module name."""
    _require_init()
    return metrics.get_meter(name)


def shutdown() -> None:
    """Flush traces and shut down metrics. Call before process exit."""
    if _trace_provider:
        _trace_provider.force_flush()
    if _metrics_provider:
        _metrics_provider.shutdown()
```

- [ ] **Step 4: Run all core tests to verify they pass**

Run: `cd wd-otel-core && pytest tests/ -v`
Expected: All passed

- [ ] **Step 5: Commit**

```bash
git add wd-otel-core/wd_otel/__init__.py wd-otel-core/tests/test_init.py
git commit -m "feat(wd-otel-core): add public API — init(), tracer(), meter(), shutdown()"
```

---

## Task 6: `wd-otel-mcp` — Context extraction module

**Files:**
- Create: `wd-otel-mcp/pyproject.toml`
- Create: `wd-otel-mcp/wd_otel_mcp/__init__.py` (empty placeholder)
- Create: `wd-otel-mcp/wd_otel_mcp/context.py`
- Create: `wd-otel-mcp/tests/__init__.py`
- Create: `wd-otel-mcp/tests/test_context.py`

- [ ] **Step 1: Create package scaffolding**

```bash
mkdir -p wd-otel-mcp/wd_otel_mcp wd-otel-mcp/tests
```

- [ ] **Step 2: Write `pyproject.toml`**

Create `wd-otel-mcp/pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=68.0"]
build-backend = "setuptools.build_meta"

[project]
name = "wd-otel-mcp"
version = "0.1.0"
description = "WD OpenTelemetry SDK — MCP tool decorator"
requires-python = ">=3.10"
dependencies = [
    "wd-otel-core>=0.1.0",
    "fastmcp>=2.0.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.0"]
```

- [ ] **Step 3: Write the failing test**

Create `wd-otel-mcp/tests/__init__.py` (empty).

Create `wd-otel-mcp/tests/test_context.py`:

```python
from unittest.mock import MagicMock
from wd_otel_mcp.context import extract_parent_context


class TestExtractParentContext:
    def test_returns_none_when_no_traceparent(self):
        ctx = MagicMock()
        ctx.request_context.request.headers = {}
        result = extract_parent_context(ctx)
        assert result is None

    def test_returns_context_when_traceparent_present(self):
        ctx = MagicMock()
        ctx.request_context.request.headers = {
            "traceparent": "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"
        }
        result = extract_parent_context(ctx)
        assert result is not None

    def test_returns_none_on_exception(self):
        ctx = MagicMock()
        ctx.request_context.request.headers = property(lambda s: (_ for _ in ()).throw(RuntimeError("boom")))
        # Accessing .headers will raise — context.py should catch and return None
        ctx.request_context.request = MagicMock(side_effect=RuntimeError("boom"))
        ctx.request_context.request.headers = MagicMock(side_effect=RuntimeError)
        result = extract_parent_context(ctx)
        assert result is None
```

- [ ] **Step 4: Run test to verify it fails**

Run: `cd wd-otel-mcp && pip install -e "../wd-otel-core[dev]" && pip install -e ".[dev]" && pytest tests/test_context.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 5: Write `context.py`**

Create `wd-otel-mcp/wd_otel_mcp/__init__.py` (empty).

Create `wd-otel-mcp/wd_otel_mcp/context.py`:

```python
"""Extract W3C trace context from FastMCP request headers."""
from __future__ import annotations

import logging
from typing import Any

from opentelemetry.propagate import extract as otel_extract

logger = logging.getLogger("wd_otel_mcp.context")


def extract_parent_context(ctx: Any) -> Any:
    """Extract W3C trace context from a FastMCP Context's request headers.

    Returns an OTel context if traceparent is present, None otherwise.
    """
    try:
        headers = dict(ctx.request_context.request.headers)
        tp = headers.get("traceparent")
        if not tp:
            logger.warning("[wd-otel] traceparent header missing — span will be a root")
            return None
        parent_ctx = otel_extract(headers)
        logger.debug(f"[wd-otel] traceparent={tp} -> linked")
        return parent_ctx
    except Exception as exc:
        logger.warning(f"[wd-otel] Failed to extract parent context: {exc}")
        return None
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd wd-otel-mcp && pytest tests/test_context.py -v`
Expected: All passed

- [ ] **Step 7: Commit**

```bash
git add wd-otel-mcp/
git commit -m "feat(wd-otel-mcp): add context module for parent trace extraction"
```

---

## Task 7: `wd-otel-mcp` — `@traced_tool` decorator

**Files:**
- Create: `wd-otel-mcp/wd_otel_mcp/decorator.py`
- Create: `wd-otel-mcp/tests/conftest.py`
- Create: `wd-otel-mcp/tests/test_decorator.py`

- [ ] **Step 1: Write the failing tests**

Create `wd-otel-mcp/tests/conftest.py`:

```python
import pytest
from unittest.mock import MagicMock
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory import InMemorySpanExporter
from opentelemetry import trace

from wd_otel import helpers


@pytest.fixture(autouse=True)
def setup_test_otel():
    """Set up in-memory tracer and mock metrics for all tests."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    helpers._tracer = provider.get_tracer("test")
    helpers._meter = MagicMock()
    helpers._tool_invocations = MagicMock()
    helpers._tool_duration = MagicMock()
    helpers._tool_timeouts = MagicMock()
    # Mark wd_otel as initialized so decorator doesn't raise
    import wd_otel
    wd_otel._initialized = True
    yield exporter
    exporter.clear()
    wd_otel._initialized = False
```

Create `wd-otel-mcp/tests/test_decorator.py`:

```python
import inspect
import pytest
from unittest.mock import MagicMock
from fastmcp import Context

from wd_otel import helpers
from wd_otel_mcp.decorator import traced_tool, current_span


def _make_ctx():
    ctx = MagicMock(spec=Context)
    ctx.request_context.request.headers = {}
    return ctx


class TestTracedToolBasic:
    def test_wraps_function_and_returns_result(self, setup_test_otel):
        @traced_tool("add", server="s1")
        def add(a: float, b: float, ctx: Context) -> float:
            return a + b

        result = add(1.0, 2.0, _make_ctx())
        assert result == 3.0

    def test_creates_span_with_operation_name(self, setup_test_otel):
        exporter = setup_test_otel

        @traced_tool("add", server="s1")
        def add(a: float, b: float, ctx: Context) -> float:
            return a + b

        add(1.0, 2.0, _make_ctx())
        spans = exporter.get_finished_spans()
        assert any(s.name == "add_operation" for s in spans)

    def test_records_input_attributes(self, setup_test_otel):
        exporter = setup_test_otel

        @traced_tool("add", server="s1")
        def add(a: float, b: float, ctx: Context) -> float:
            return a + b

        add(3.0, 4.0, _make_ctx())
        span = next(s for s in exporter.get_finished_spans() if s.name == "add_operation")
        assert span.attributes.get("input.a") == "3.0"
        assert span.attributes.get("input.b") == "4.0"

    def test_records_result_attribute(self, setup_test_otel):
        exporter = setup_test_otel

        @traced_tool("add", server="s1")
        def add(a: float, b: float, ctx: Context) -> float:
            return a + b

        add(3.0, 4.0, _make_ctx())
        span = next(s for s in exporter.get_finished_spans() if s.name == "add_operation")
        assert span.attributes.get("result") == "7.0"

    def test_records_invocation_counter(self, setup_test_otel):
        @traced_tool("add", server="s1")
        def add(a: float, b: float, ctx: Context) -> float:
            return a + b

        add(1.0, 2.0, _make_ctx())
        helpers._tool_invocations.add.assert_called_once()
        args = helpers._tool_invocations.add.call_args[0]
        assert args[1]["status"] == "success"

    def test_records_duration_histogram(self, setup_test_otel):
        @traced_tool("add", server="s1")
        def add(a: float, b: float, ctx: Context) -> float:
            return a + b

        add(1.0, 2.0, _make_ctx())
        helpers._tool_duration.record.assert_called_once()


class TestTracedToolErrors:
    def test_records_error_status_on_exception(self, setup_test_otel):
        @traced_tool("div", server="s1")
        def divide(a: float, b: float, ctx: Context) -> float:
            raise ValueError("division by zero")

        with pytest.raises(ValueError):
            divide(1.0, 0.0, _make_ctx())

        args = helpers._tool_invocations.add.call_args[0]
        assert args[1]["status"] == "error"


class TestTracedToolOptions:
    def test_capture_args_filters_inputs(self, setup_test_otel):
        exporter = setup_test_otel

        @traced_tool("solve", server="s1", capture_args=["expression"])
        def solve(expression: str, verbose: bool, ctx: Context) -> str:
            return "ok"

        solve("1+2", True, _make_ctx())
        span = next(s for s in exporter.get_finished_spans() if s.name == "solve_operation")
        assert span.attributes.get("input.expression") == "1+2"
        assert "input.verbose" not in span.attributes

    def test_extra_attributes_added_to_span(self, setup_test_otel):
        exporter = setup_test_otel

        @traced_tool("add", server="s1", extra_attributes={"tool.category": "math"})
        def add(a: float, b: float, ctx: Context) -> float:
            return a + b

        add(1.0, 2.0, _make_ctx())
        span = next(s for s in exporter.get_finished_spans() if s.name == "add_operation")
        assert span.attributes.get("tool.category") == "math"


class TestTracedToolCtxDetection:
    def test_raises_if_no_context_param(self):
        with pytest.raises(Exception, match="Context"):
            @traced_tool("bad", server="s1")
            def bad_func(a: float, b: float) -> float:
                return a + b


class TestCurrentSpan:
    def test_current_span_returns_active_span(self, setup_test_otel):
        captured_span = None

        @traced_tool("add", server="s1")
        def add(a: float, b: float, ctx: Context) -> float:
            nonlocal captured_span
            captured_span = current_span()
            return a + b

        add(1.0, 2.0, _make_ctx())
        assert captured_span is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd wd-otel-mcp && pytest tests/test_decorator.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Write `decorator.py`**

Create `wd-otel-mcp/wd_otel_mcp/decorator.py`:

```python
"""@traced_tool decorator — primary API for instrumenting MCP tool functions."""
from __future__ import annotations

import functools
import inspect
import logging
import time
import threading
import contextvars
from typing import Any

from opentelemetry import trace

from wd_otel.errors import WdOtelConfigError
from wd_otel import helpers
from wd_otel_mcp.context import extract_parent_context

logger = logging.getLogger("wd_otel_mcp.decorator")


def current_span() -> trace.Span:
    """Return the currently active OTel span. Use inside a @traced_tool function."""
    return trace.get_current_span()


def _find_ctx_param(fn) -> str | None:
    """Find a parameter annotated with fastmcp.Context in the function signature."""
    sig = inspect.signature(fn)
    for name, param in sig.parameters.items():
        ann = param.annotation
        if ann is inspect.Parameter.empty:
            continue
        # Check by class name to avoid hard import of fastmcp at module level
        if hasattr(ann, "__name__") and ann.__name__ == "Context":
            return name
        if hasattr(ann, "__qualname__") and "Context" in ann.__qualname__:
            return name
    return None


def traced_tool(
    tool_name: str,
    server: str,
    timeout_s: float = 10.0,
    capture_args: list[str] | None = None,
    extra_attributes: dict[str, Any] | None = None,
):
    """Decorator that instruments an MCP tool function with OTel spans and metrics.

    Args:
        tool_name: Name for the tool (used in span name and metric labels).
        server: Server name (used in metric labels).
        timeout_s: Timeout in seconds. If exceeded, records timeout metric.
        capture_args: If set, only capture these arg names as span attributes.
                      If None, captures all args except ctx.
        extra_attributes: Static attributes to add to every span.
    """

    def decorator(fn):
        # Validate that the function has a Context parameter
        ctx_param = _find_ctx_param(fn)
        if ctx_param is None:
            raise WdOtelConfigError(
                f"@traced_tool('{tool_name}'): function '{fn.__name__}' has no "
                f"parameter with type annotation fastmcp.Context. "
                f"Add 'ctx: Context' to the function signature.",
            )

        sig = inspect.signature(fn)
        param_names = [
            p for p in sig.parameters if p != ctx_param
        ]

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            tracer = helpers._get_tracer()
            start = time.perf_counter()
            status = "success"

            # Bind args to param names for attribute extraction
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()
            ctx_value = bound.arguments.get(ctx_param)

            parent_ctx = extract_parent_context(ctx_value)

            with tracer.start_as_current_span(
                f"{tool_name}_operation", context=parent_ctx
            ) as span:
                # Set extra static attributes
                if extra_attributes:
                    for k, v in extra_attributes.items():
                        span.set_attribute(k, v)

                # Set input attributes
                args_to_capture = capture_args if capture_args is not None else param_names
                for name in args_to_capture:
                    if name in bound.arguments:
                        span.set_attribute(f"input.{name}", str(bound.arguments[name]))

                try:
                    # Run with timeout using thread (matches existing pattern)
                    cv_ctx = contextvars.copy_context()
                    result_holder = [None]
                    exc_holder = [None]

                    def target():
                        try:
                            result_holder[0] = cv_ctx.run(fn, *args, **kwargs)
                        except Exception as e:
                            exc_holder[0] = e

                    t = threading.Thread(target=target, daemon=True)
                    t.start()
                    t.join(timeout=timeout_s)

                    if t.is_alive():
                        helpers._tool_timeouts.add(
                            1, {"tool": tool_name, "tool_server": server}
                        )
                        status = "timeout"
                        raise TimeoutError(
                            f"{tool_name} exceeded {timeout_s}s timeout"
                        )

                    if exc_holder[0] is not None:
                        raise exc_holder[0]

                    result = result_holder[0]
                    span.set_attribute("result", str(result))
                    return result

                except TimeoutError:
                    status = "timeout"
                    span.record_exception(
                        TimeoutError(f"{tool_name} timed out")
                    )
                    raise
                except Exception as e:
                    status = "error"
                    span.record_exception(e)
                    raise
                finally:
                    elapsed = time.perf_counter() - start
                    helpers._tool_invocations.add(
                        1,
                        {
                            "tool": tool_name,
                            "tool_server": server,
                            "status": status,
                        },
                    )
                    helpers._tool_duration.record(
                        elapsed, {"tool": tool_name, "tool_server": server}
                    )
                    logger.info(
                        f"[wd-otel] {tool_name} {status} in {elapsed:.3f}s"
                    )

        return wrapper

    return decorator
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd wd-otel-mcp && pytest tests/test_decorator.py -v`
Expected: All passed

- [ ] **Step 5: Wire up `__init__.py` re-exports**

Overwrite `wd-otel-mcp/wd_otel_mcp/__init__.py`:

```python
"""WD-OTel SDK — MCP tool instrumentation.

Usage:
    from wd_otel_mcp import traced_tool, current_span

    @mcp.tool()
    @traced_tool("my_tool", server="my_server")
    def my_tool(x: int, ctx: Context) -> int:
        return x * 2
"""
from wd_otel_mcp.decorator import traced_tool, current_span

__all__ = ["traced_tool", "current_span"]
```

- [ ] **Step 6: Run all MCP tests**

Run: `cd wd-otel-mcp && pytest tests/ -v`
Expected: All passed

- [ ] **Step 7: Commit**

```bash
git add wd-otel-mcp/
git commit -m "feat(wd-otel-mcp): add @traced_tool decorator with auto span/metrics/context"
```

---

## Task 8: `wd-otel-orchestrator` — Transitions module

**Files:**
- Create: `wd-otel-orchestrator/pyproject.toml`
- Create: `wd-otel-orchestrator/wd_otel_orchestrator/__init__.py` (empty)
- Create: `wd-otel-orchestrator/wd_otel_orchestrator/transitions.py`
- Create: `wd-otel-orchestrator/tests/__init__.py`
- Create: `wd-otel-orchestrator/tests/conftest.py`
- Create: `wd-otel-orchestrator/tests/test_transitions.py`

- [ ] **Step 1: Create package scaffolding**

```bash
mkdir -p wd-otel-orchestrator/wd_otel_orchestrator wd-otel-orchestrator/tests
```

- [ ] **Step 2: Write `pyproject.toml`**

Create `wd-otel-orchestrator/pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=68.0"]
build-backend = "setuptools.build_meta"

[project]
name = "wd-otel-orchestrator"
version = "0.1.0"
description = "WD OpenTelemetry SDK — orchestrator base class"
requires-python = ">=3.10"
dependencies = [
    "wd-otel-core>=0.1.0",
    "openai-agents>=0.0.15",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-asyncio>=0.23.0"]
```

- [ ] **Step 3: Write the failing tests**

Create `wd-otel-orchestrator/tests/__init__.py` (empty).

Create `wd-otel-orchestrator/tests/conftest.py`:

```python
import pytest
from unittest.mock import MagicMock
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory import InMemorySpanExporter
from opentelemetry import trace

from wd_otel import helpers


@pytest.fixture(autouse=True)
def setup_test_otel():
    """Set up in-memory tracer and mock metrics for all tests."""
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
```

Create `wd-otel-orchestrator/tests/test_transitions.py`:

```python
import pytest
from wd_otel import helpers
from wd_otel_orchestrator.transitions import TransitionTracker


class TestTransitionTracker:
    def test_record_handoff_creates_span_and_metrics(self, setup_test_otel):
        exporter = setup_test_otel
        tracker = TransitionTracker()

        tracker.record_handoff("AddSubAgent", reason="simple addition")

        helpers._state_transitions.add.assert_called_once()
        call_labels = helpers._state_transitions.add.call_args[0][1]
        assert call_labels["from_state"] == "idle"
        assert call_labels["to_state"] == "running"

        helpers._active_workers.add.assert_called_once_with(
            1, {"worker_type": "AddSubAgent"}
        )

        spans = exporter.get_finished_spans()
        assert any(s.name == "orchestrator.transition" for s in spans)

    def test_record_completion_decrements_active_workers(self, setup_test_otel):
        tracker = TransitionTracker()
        tracker.record_completion("AddSubAgent")

        helpers._active_workers.add.assert_called_once_with(
            -1, {"worker_type": "AddSubAgent"}
        )

    def test_record_error_decrements_active_workers_and_counts_error(self, setup_test_otel):
        tracker = TransitionTracker()
        err = RuntimeError("boom")
        tracker.record_error("AddSubAgent", err)

        helpers._active_workers.add.assert_called_once_with(
            -1, {"worker_type": "AddSubAgent"}
        )
        helpers._orchestration_errors.add.assert_called_once()

    def test_record_sync_failure(self, setup_test_otel):
        tracker = TransitionTracker()
        tracker.record_sync_failure("AddSubAgent", RuntimeError("sync fail"))

        helpers._sync_failures.add.assert_called_once()
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `cd wd-otel-orchestrator && pip install -e "../wd-otel-core[dev]" && pip install -e ".[dev]" && pytest tests/test_transitions.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 5: Write `transitions.py`**

Create `wd-otel-orchestrator/wd_otel_orchestrator/__init__.py` (empty).

Create `wd-otel-orchestrator/wd_otel_orchestrator/transitions.py`:

```python
"""TransitionTracker — records state transitions and active worker metrics."""
from __future__ import annotations

import logging

from wd_otel import helpers

logger = logging.getLogger("wd_otel_orchestrator.transitions")


class TransitionTracker:
    """Encapsulates all orchestrator state-transition metric recording.

    Used internally by TracedOrchestrator. Can also be used standalone.
    """

    def record_handoff(self, worker_name: str, reason: str = "") -> None:
        """Record idle → running transition (on agent handoff)."""
        tracer = helpers._get_tracer()
        with tracer.start_as_current_span(
            "orchestrator.transition",
            attributes={
                "worker.type": worker_name,
                "worker.from_state": "idle",
                "worker.to_state": "running",
                "handoff.reason": reason,
            },
        ) as span:
            helpers._state_transitions.add(
                1,
                {
                    "worker_type": worker_name,
                    "from_state": "idle",
                    "to_state": "running",
                },
            )
            helpers._active_workers.add(1, {"worker_type": worker_name})
            span.add_event(
                "state_changed", {"previous": "idle", "current": "running"}
            )
            logger.info(f"[wd-otel] {worker_name}: idle->running, reason='{reason}'")

    def record_completion(self, worker_name: str) -> None:
        """Record running → completed transition."""
        tracer = helpers._get_tracer()
        with tracer.start_as_current_span(
            "orchestrator.transition",
            attributes={
                "worker.type": worker_name,
                "worker.from_state": "running",
                "worker.to_state": "completed",
            },
        ) as span:
            helpers._state_transitions.add(
                1,
                {
                    "worker_type": worker_name,
                    "from_state": "running",
                    "to_state": "completed",
                },
            )
            helpers._active_workers.add(-1, {"worker_type": worker_name})
            span.add_event(
                "state_changed", {"previous": "running", "current": "completed"}
            )
            logger.info(f"[wd-otel] {worker_name}: running->completed")

    def record_error(self, worker_name: str, error: Exception) -> None:
        """Record running → error transition."""
        tracer = helpers._get_tracer()
        with tracer.start_as_current_span(
            "orchestrator.transition",
            attributes={
                "worker.type": worker_name,
                "worker.from_state": "running",
                "worker.to_state": "error",
            },
        ) as span:
            helpers._state_transitions.add(
                1,
                {
                    "worker_type": worker_name,
                    "from_state": "running",
                    "to_state": "error",
                },
            )
            helpers._active_workers.add(-1, {"worker_type": worker_name})
            helpers._orchestration_errors.add(
                1,
                {"error_type": type(error).__name__, "worker_type": worker_name},
            )
            span.record_exception(error)
            span.add_event(
                "state_changed", {"previous": "running", "current": "error"}
            )
            logger.error(f"[wd-otel] {worker_name}: running->error: {error}")

    def record_sync_failure(self, worker_name: str, error: Exception) -> None:
        """Record a sync failure metric."""
        helpers._sync_failures.add(
            1,
            {"failure_type": type(error).__name__, "worker_type": worker_name},
        )
        logger.error(f"[wd-otel] sync failure for {worker_name}: {error}")
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd wd-otel-orchestrator && pytest tests/test_transitions.py -v`
Expected: All passed

- [ ] **Step 7: Commit**

```bash
git add wd-otel-orchestrator/
git commit -m "feat(wd-otel-orchestrator): add TransitionTracker for state transition metrics"
```

---

## Task 9: `wd-otel-orchestrator` — `TracedOrchestrator` base class

**Files:**
- Create: `wd-otel-orchestrator/wd_otel_orchestrator/base.py`
- Create: `wd-otel-orchestrator/tests/test_base.py`
- Modify: `wd-otel-orchestrator/wd_otel_orchestrator/__init__.py`

- [ ] **Step 1: Write the failing tests**

Create `wd-otel-orchestrator/tests/test_base.py`:

```python
import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from wd_otel import helpers
from wd_otel.errors import WdOtelConfigError
from wd_otel_orchestrator.base import TracedOrchestrator


class TestTracedOrchestratorValidation:
    def test_missing_name_raises(self):
        with pytest.raises(WdOtelConfigError, match="name"):
            class Bad(TracedOrchestrator):
                agents = {}
                entry_agent = MagicMock()

            Bad()

    def test_missing_entry_agent_raises(self):
        with pytest.raises(WdOtelConfigError, match="entry_agent"):
            class Bad(TracedOrchestrator):
                name = "test"
                agents = {}

            Bad()


class TestTracedOrchestratorExecute:
    @pytest.mark.asyncio
    async def test_execute_returns_result(self, setup_test_otel):
        mock_result = MagicMock()
        mock_result.final_output = "42"
        mock_result.last_agent = MagicMock()
        mock_result.last_agent.name = "AddSubAgent"

        with patch("wd_otel_orchestrator.base.Runner") as MockRunner:
            MockRunner.run = AsyncMock(return_value=mock_result)

            class TestOrch(TracedOrchestrator):
                name = "test-workflow"
                agents = {"AddSubAgent": MagicMock()}
                entry_agent = MagicMock()

            orch = TestOrch()
            result = await orch.execute("What is 1+1?")
            assert result == "42"

    @pytest.mark.asyncio
    async def test_execute_records_session_metrics(self, setup_test_otel):
        mock_result = MagicMock()
        mock_result.final_output = "42"
        mock_result.last_agent = MagicMock()
        mock_result.last_agent.name = "AgentA"

        with patch("wd_otel_orchestrator.base.Runner") as MockRunner:
            MockRunner.run = AsyncMock(return_value=mock_result)

            class TestOrch(TracedOrchestrator):
                name = "test-workflow"
                agents = {"AgentA": MagicMock()}
                entry_agent = MagicMock()

            orch = TestOrch()
            await orch.execute("test")

        helpers._session_counter.add.assert_called()
        helpers._session_duration.record.assert_called()

    @pytest.mark.asyncio
    async def test_execute_records_completion_transition(self, setup_test_otel):
        mock_result = MagicMock()
        mock_result.final_output = "ok"
        mock_result.last_agent = MagicMock()
        mock_result.last_agent.name = "AgentA"

        with patch("wd_otel_orchestrator.base.Runner") as MockRunner:
            MockRunner.run = AsyncMock(return_value=mock_result)

            class TestOrch(TracedOrchestrator):
                name = "test-workflow"
                agents = {"AgentA": MagicMock()}
                entry_agent = MagicMock()

            orch = TestOrch()
            await orch.execute("test")

        # active_workers should be decremented (completion)
        helpers._active_workers.add.assert_called()

    @pytest.mark.asyncio
    async def test_execute_records_error_on_exception(self, setup_test_otel):
        with patch("wd_otel_orchestrator.base.Runner") as MockRunner:
            MockRunner.run = AsyncMock(side_effect=RuntimeError("LLM error"))

            class TestOrch(TracedOrchestrator):
                name = "test-workflow"
                agents = {"AgentA": MagicMock()}
                entry_agent = MagicMock()

            orch = TestOrch()
            result = await orch.execute("test")
            assert "Error:" in result

        helpers._orchestration_errors.add.assert_called()

    @pytest.mark.asyncio
    async def test_execute_calls_hooks(self, setup_test_otel):
        mock_result = MagicMock()
        mock_result.final_output = "42"
        mock_result.last_agent = MagicMock()
        mock_result.last_agent.name = "A"

        with patch("wd_otel_orchestrator.base.Runner") as MockRunner:
            MockRunner.run = AsyncMock(return_value=mock_result)

            class TestOrch(TracedOrchestrator):
                name = "test-workflow"
                agents = {"A": MagicMock()}
                entry_agent = MagicMock()

                on_before_run = AsyncMock()
                on_after_run = AsyncMock()
                sync_status = AsyncMock()

            orch = TestOrch()
            await orch.execute("test")

            orch.on_before_run.assert_called_once()
            orch.on_after_run.assert_called_once()
            orch.sync_status.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_calls_on_error_hook(self, setup_test_otel):
        with patch("wd_otel_orchestrator.base.Runner") as MockRunner:
            MockRunner.run = AsyncMock(side_effect=RuntimeError("fail"))

            class TestOrch(TracedOrchestrator):
                name = "test-workflow"
                agents = {"A": MagicMock()}
                entry_agent = MagicMock()

                on_error = AsyncMock()
                sync_status = AsyncMock()

            orch = TestOrch()
            await orch.execute("test")

            orch.on_error.assert_called_once()
            orch.sync_status.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd wd-otel-orchestrator && pytest tests/test_base.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Write `base.py`**

Create `wd-otel-orchestrator/wd_otel_orchestrator/base.py`:

```python
"""TracedOrchestrator — base class that guarantees all orchestrator metrics fire."""
from __future__ import annotations

import logging
import time
from typing import Any

import httpx
from opentelemetry import context as otel_context
from opentelemetry.propagate import inject as otel_inject
from pydantic import BaseModel
from agents import Runner, handoff
from agents import trace as agents_trace

from wd_otel import helpers
from wd_otel.errors import WdOtelConfigError
from wd_otel_orchestrator.transitions import TransitionTracker

logger = logging.getLogger("wd_otel_orchestrator.base")

# Module-level trace context for httpx monkey-patch
_mcp_trace_context = None
_httpx_patched = False


def _ensure_httpx_patch():
    """Monkey-patch httpx.AsyncClient.send to inject traceparent headers."""
    global _httpx_patched
    if _httpx_patched:
        return

    _original_send = httpx.AsyncClient.send

    async def _send_with_trace(self, request, **kwargs):
        carrier = {}
        otel_inject(carrier, context=_mcp_trace_context)
        for k, v in carrier.items():
            request.headers[k] = v
        return await _original_send(self, request, **kwargs)

    httpx.AsyncClient.send = _send_with_trace
    _httpx_patched = True


class HandoffReason(BaseModel):
    """Reason the orchestrator is handing off to a specialist."""
    reason: str


class TracedOrchestrator:
    """Base class for agent orchestrators with guaranteed OTel instrumentation.

    Subclasses must define:
        name: str           — workflow name (used in spans and metrics)
        agents: dict        — mapping of agent_name -> Agent instance
        entry_agent: Agent  — the routing/entry agent

    Optional overrides:
        on_before_run(input)           — called before Runner.run
        on_after_run(result, elapsed)  — called after success
        on_error(error, elapsed)       — called after error (metrics already recorded)
        sync_status(worker, status, output) — called after every run for API sync
    """

    name: str = ""
    agents: dict[str, Any] = {}
    entry_agent: Any = None

    def __init__(self):
        if not self.name:
            raise WdOtelConfigError(
                f"{self.__class__.__name__} must define 'name' class attribute"
            )
        if self.entry_agent is None:
            raise WdOtelConfigError(
                f"{self.__class__.__name__} must define 'entry_agent' class attribute"
            )
        self._tracker = TransitionTracker()
        _ensure_httpx_patch()

    def _make_on_handoff(self, worker_name: str):
        """Create a handoff callback that records the idle->running transition."""
        tracker = self._tracker

        def on_handoff(ctx, input: HandoffReason) -> None:
            tracker.record_handoff(worker_name, reason=input.reason)

        return on_handoff

    def _build_handoffs(self) -> list:
        """Build handoff objects with instrumented callbacks for all agents."""
        return [
            handoff(
                agent,
                on_handoff=self._make_on_handoff(agent_name),
                input_type=HandoffReason,
            )
            for agent_name, agent in self.agents.items()
        ]

    async def on_before_run(self, input: str) -> None:
        """Hook: called before Runner.run. Override for custom logic."""
        pass

    async def on_after_run(self, result: Any, elapsed: float) -> None:
        """Hook: called after successful run. Override for custom logic."""
        pass

    async def on_error(self, error: Exception, elapsed: float) -> None:
        """Hook: called on error. Metrics already recorded. Override for alerts, etc."""
        pass

    async def sync_status(self, worker_name: str, status: str, output: str) -> None:
        """Hook: called after every run for status sync. Override for API sync."""
        pass

    async def execute(self, input: str) -> str:
        """Run the orchestrator with full lifecycle tracing. All metrics guaranteed.

        Returns the final output string from the agent chain.
        """
        global _mcp_trace_context
        tracer = helpers._get_tracer()
        start = time.perf_counter()

        with tracer.start_as_current_span(
            "orchestrator.worker.lifecycle",
            attributes={
                "workflow.name": self.name,
                "agent.input": input,
                "orchestrator": self.entry_agent.name if hasattr(self.entry_agent, "name") else self.name,
            },
        ) as lifecycle_span:

            with tracer.start_as_current_span(
                "multi-agent-run",
                attributes={"workflow.name": self.name, "agent.input": input},
            ) as run_span:
                _mcp_trace_context = otel_context.get_current()

                logger.info(f"[wd-otel] {self.name} starting: {input}")

                final_agent_name = self.name
                lifecycle_status = "unknown"
                final_output = ""

                try:
                    await self.on_before_run(input)

                    with tracer.start_as_current_span(
                        "runner.run",
                        attributes={"entry.agent": self.name},
                    ):
                        with agents_trace(workflow_name=self.name):
                            result = await Runner.run(
                                self.entry_agent, input=input
                            )

                    elapsed = time.perf_counter() - start
                    final_output = result.final_output
                    final_agent_name = (
                        result.last_agent.name
                        if result.last_agent
                        else self.name
                    )

                    # Record running → completed
                    self._tracker.record_completion(final_agent_name)

                    run_span.set_attribute("agent.output", final_output)
                    run_span.set_attribute("duration_seconds", round(elapsed, 3))

                    lifecycle_status = "completed"
                    lifecycle_span.set_attribute("lifecycle.status", "completed")
                    lifecycle_span.set_attribute("lifecycle.final_agent", final_agent_name)
                    lifecycle_span.set_attribute("lifecycle.duration_s", round(elapsed, 3))

                    await self.on_after_run(result, elapsed)
                    logger.info(f"[wd-otel] {self.name} done ({elapsed:.3f}s): {final_output}")

                except Exception as e:
                    elapsed = time.perf_counter() - start

                    # Record running → error
                    self._tracker.record_error(final_agent_name, e)

                    run_span.record_exception(e)
                    lifecycle_status = "error"
                    lifecycle_span.set_attribute("lifecycle.status", "error")
                    lifecycle_span.set_attribute("lifecycle.error", str(e))

                    await self.on_error(e, elapsed)
                    logger.error(f"[wd-otel] {self.name} error ({elapsed:.3f}s): {e}")

                    final_output = f"Error: {e}"

                finally:
                    # Session metrics — ALWAYS fire
                    elapsed = time.perf_counter() - start
                    helpers._session_counter.add(1, {"workflow": self.name})
                    helpers._session_duration.record(elapsed, {"workflow": self.name})

            # Sync status (outside run span, inside lifecycle span)
            with tracer.start_as_current_span(
                "orchestrator.sync",
                attributes={
                    "worker.type": final_agent_name,
                    "sync.status": lifecycle_status,
                },
            ) as sync_span:
                try:
                    await self.sync_status(final_agent_name, lifecycle_status, final_output)
                    sync_span.set_attribute("sync.success", True)
                except Exception as e:
                    self._tracker.record_sync_failure(final_agent_name, e)
                    sync_span.record_exception(e)
                    sync_span.set_attribute("sync.success", False)
                    logger.error(f"[wd-otel] sync failed: {e}")

        return final_output
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd wd-otel-orchestrator && pytest tests/test_base.py -v`
Expected: All passed

- [ ] **Step 5: Wire up `__init__.py` re-exports**

Overwrite `wd-otel-orchestrator/wd_otel_orchestrator/__init__.py`:

```python
"""WD-OTel SDK — orchestrator base class.

Usage:
    from wd_otel_orchestrator import TracedOrchestrator

    class MyOrchestrator(TracedOrchestrator):
        name = "my-workflow"
        agents = {"AgentA": agent_a}
        entry_agent = router_agent
"""
from wd_otel_orchestrator.base import TracedOrchestrator

__all__ = ["TracedOrchestrator"]
```

- [ ] **Step 6: Run all orchestrator tests**

Run: `cd wd-otel-orchestrator && pytest tests/ -v`
Expected: All passed

- [ ] **Step 7: Commit**

```bash
git add wd-otel-orchestrator/
git commit -m "feat(wd-otel-orchestrator): add TracedOrchestrator base class with guaranteed metrics"
```

---

## Task 10: Sample `wd-otel.yaml` configs

**Files:**
- Create: `wd-otel-core/examples/wd-otel.yaml`
- Create: `wd-otel-core/examples/wd-otel.production.yaml`

- [ ] **Step 1: Create local dev config**

Create `wd-otel-core/examples/wd-otel.yaml`:

```yaml
# WD-OTel SDK config — local development
service:
  name: "my-mcp-server"
  version: "1.0.0"
  env: "local"

traces:
  endpoint: "localhost:4317"
  protocol: "grpc"
  filter_libraries:
    - "fastmcp"

metrics:
  prometheus_port: 8001

logs:
  loki_url: "http://localhost:3100/loki/api/v1/push"
```

- [ ] **Step 2: Create production config**

Create `wd-otel-core/examples/wd-otel.production.yaml`:

```yaml
# WD-OTel SDK config — production
service:
  name: "my-mcp-server"
  version: "1.0.0"
  env: "production"

traces:
  endpoint: "alloy.monitoring.svc.cluster.local:4317"
  protocol: "grpc"
  filter_libraries:
    - "fastmcp"

metrics:
  prometheus_port: 8001

logs:
  loki_url: "http://loki.monitoring.svc.cluster.local:3100/loki/api/v1/push"
```

- [ ] **Step 3: Commit**

```bash
git add wd-otel-core/examples/
git commit -m "docs(wd-otel-core): add example YAML configs for local and production"
```

---

## Task 11: Run full test suite across all packages

**Files:** None (verification only)

- [ ] **Step 1: Install all packages in dev mode**

```bash
cd wd-otel-core && pip install -e ".[dev]"
cd ../wd-otel-mcp && pip install -e ".[dev]"
cd ../wd-otel-orchestrator && pip install -e ".[dev]"
```

- [ ] **Step 2: Run all tests**

```bash
cd wd-otel-core && pytest tests/ -v
cd ../wd-otel-mcp && pytest tests/ -v
cd ../wd-otel-orchestrator && pytest tests/ -v
```

Expected: All tests pass across all 3 packages.

- [ ] **Step 3: Verify imports work end-to-end**

```bash
python -c "
import wd_otel
from wd_otel.errors import WdOtelConfigError
from wd_otel.config import load_config, WdOtelConfig
from wd_otel import helpers
from wd_otel_mcp import traced_tool, current_span
from wd_otel_orchestrator import TracedOrchestrator
print('All imports successful')
"
```

Expected: `All imports successful`

- [ ] **Step 4: Final commit on feature branch**

```bash
git log --oneline feature/wd-otel-sdk
```

Verify the commit history looks clean with one commit per task.
