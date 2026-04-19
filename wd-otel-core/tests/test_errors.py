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
