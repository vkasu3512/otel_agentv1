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

    # Validate required: service.env must be explicitly set in YAML
    if not service.get("env"):
        _fail_or_warn("service.env is required in wd-otel.yaml", env)

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
