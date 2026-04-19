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
    """Environment detection: YAML -> WD_OTEL_ENV -> defaults to production."""

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
