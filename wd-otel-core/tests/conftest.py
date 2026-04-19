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
