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
        assert add(1.0, 2.0, _make_ctx()) == 3.0

    def test_creates_span_with_operation_name(self, setup_test_otel):
        exporter = setup_test_otel
        @traced_tool("add", server="s1")
        def add(a: float, b: float, ctx: Context) -> float:
            return a + b
        add(1.0, 2.0, _make_ctx())
        assert any(s.name == "add_operation" for s in exporter.get_finished_spans())

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
        assert helpers._tool_invocations.add.call_args[0][1]["status"] == "success"

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
        assert helpers._tool_invocations.add.call_args[0][1]["status"] == "error"

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
        captured = None
        @traced_tool("add", server="s1")
        def add(a: float, b: float, ctx: Context) -> float:
            nonlocal captured
            captured = current_span()
            return a + b
        add(1.0, 2.0, _make_ctx())
        assert captured is not None
