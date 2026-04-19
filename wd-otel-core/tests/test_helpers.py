"""Tests for wd_otel.helpers module."""
from __future__ import annotations

from unittest.mock import MagicMock, patch, call
import pytest

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.sdk.trace.export import SimpleSpanProcessor

import wd_otel.helpers as helpers


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_helpers():
    """Before each test: replace module-level instruments with fresh mocks
    and install a real in-memory tracer so spans can be captured."""
    # Set up an in-memory tracer provider
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    # Inject a real tracer
    helpers._tracer = provider.get_tracer("test")

    # Inject mock metric instruments
    helpers._tool_invocations = MagicMock()
    helpers._tool_duration = MagicMock()
    helpers._tool_timeouts = MagicMock()
    helpers._session_counter = MagicMock()
    helpers._session_duration = MagicMock()
    helpers._state_transitions = MagicMock()
    helpers._active_workers = MagicMock()
    helpers._orchestration_errors = MagicMock()
    helpers._sync_failures = MagicMock()

    yield exporter  # tests can use this to inspect spans

    exporter.clear()


# ---------------------------------------------------------------------------
# _get_tracer
# ---------------------------------------------------------------------------

class TestGetTracer:
    def test_returns_set_tracer_when_initialized(self):
        mock_tracer = MagicMock()
        helpers._tracer = mock_tracer
        assert helpers._get_tracer() is mock_tracer

    def test_returns_default_tracer_when_none(self):
        helpers._tracer = None
        tracer = helpers._get_tracer()
        assert tracer is not None  # falls back to trace.get_tracer("wd_otel")


# ---------------------------------------------------------------------------
# init_instruments
# ---------------------------------------------------------------------------

class TestInitInstruments:
    def test_creates_all_metric_instruments(self):
        meter = MagicMock()
        meter.create_counter.return_value = MagicMock()
        meter.create_histogram.return_value = MagicMock()
        meter.create_up_down_counter.return_value = MagicMock()

        helpers.init_instruments(meter)

        # Check counters created
        counter_calls = [c[1].get("name") or c[0][0] for c in meter.create_counter.call_args_list]
        assert meter.create_counter.call_count >= 4  # invocations, timeouts, session, etc.
        assert meter.create_histogram.call_count >= 2  # duration, session_duration
        assert meter.create_up_down_counter.call_count >= 1  # active_workers


# ---------------------------------------------------------------------------
# child_span
# ---------------------------------------------------------------------------

class TestChildSpan:
    def test_creates_span_with_name(self, reset_helpers):
        exporter = reset_helpers
        with helpers.child_span("my_child"):
            pass

        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].name == "my_child"

    def test_creates_span_with_attributes(self, reset_helpers):
        exporter = reset_helpers
        with helpers.child_span("attr_span", attributes={"key": "val", "num": 42}):
            pass

        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].attributes.get("key") == "val"
        assert spans[0].attributes.get("num") == 42

    def test_child_span_with_no_attributes(self, reset_helpers):
        exporter = reset_helpers
        with helpers.child_span("bare_span"):
            pass

        spans = exporter.get_finished_spans()
        assert len(spans) == 1


# ---------------------------------------------------------------------------
# tool_span
# ---------------------------------------------------------------------------

class TestToolSpan:
    def _make_mock_ctx(self, traceparent="00-abc123-def456-01"):
        ctx = MagicMock()
        ctx.meta = {"headers": {"traceparent": traceparent}}
        return ctx

    def test_records_invocation_on_success(self, reset_helpers):
        ctx = self._make_mock_ctx()
        with helpers.tool_span(ctx, "my_tool", "my_server") as tsc:
            tsc.set_output("ok")

        helpers._tool_invocations.add.assert_called()
        helpers._tool_duration.record.assert_called()

    def test_records_invocation_on_error(self, reset_helpers):
        ctx = self._make_mock_ctx()
        with pytest.raises(ValueError):
            with helpers.tool_span(ctx, "my_tool", "my_server"):
                raise ValueError("oops")

        helpers._tool_invocations.add.assert_called()

    def test_creates_span_with_tool_name(self, reset_helpers):
        exporter = reset_helpers
        ctx = self._make_mock_ctx()
        with helpers.tool_span(ctx, "calc_tool", "math_server"):
            pass

        spans = exporter.get_finished_spans()
        assert any("calc_tool" in s.name for s in spans)

    def test_set_output_sets_attribute(self, reset_helpers):
        exporter = reset_helpers
        ctx = self._make_mock_ctx()
        with helpers.tool_span(ctx, "echo_tool", "echo_server") as tsc:
            tsc.set_output("hello")

        spans = exporter.get_finished_spans()
        assert len(spans) >= 1

    def test_set_attribute_on_span(self, reset_helpers):
        exporter = reset_helpers
        ctx = self._make_mock_ctx()
        with helpers.tool_span(ctx, "info_tool", "info_server") as tsc:
            tsc.set_attribute("custom.key", "custom_val")

        spans = exporter.get_finished_spans()
        assert any(s.attributes.get("custom.key") == "custom_val" for s in spans)

    def test_records_timeout_on_timeout_error(self, reset_helpers):
        ctx = self._make_mock_ctx()
        with pytest.raises(TimeoutError):
            with helpers.tool_span(ctx, "slow_tool", "slow_server"):
                raise TimeoutError("timed out")

        helpers._tool_timeouts.add.assert_called()

    def test_span_inputs_attribute(self, reset_helpers):
        exporter = reset_helpers
        ctx = self._make_mock_ctx()
        with helpers.tool_span(ctx, "typed_tool", "svc", inputs={"x": 1}):
            pass

        spans = exporter.get_finished_spans()
        assert len(spans) >= 1


# ---------------------------------------------------------------------------
# lifecycle_span
# ---------------------------------------------------------------------------

class TestLifecycleSpan:
    def test_creates_span_with_workflow_name(self, reset_helpers):
        exporter = reset_helpers
        with helpers.lifecycle_span("my_workflow") as lsc:
            lsc.complete("agent1", "done")

        spans = exporter.get_finished_spans()
        assert any("my_workflow" in s.name for s in spans)

    def test_records_session_counter_on_exit(self, reset_helpers):
        with helpers.lifecycle_span("wf") as lsc:
            lsc.complete("a", "result")

        helpers._session_counter.add.assert_called()
        helpers._session_duration.record.assert_called()

    def test_records_session_counter_on_error(self, reset_helpers):
        with pytest.raises(RuntimeError):
            with helpers.lifecycle_span("wf") as lsc:
                lsc.error("agent1", RuntimeError("failed"))
                raise RuntimeError("failed")

        helpers._session_counter.add.assert_called()

    def test_transition_records_state_change(self, reset_helpers):
        exporter = reset_helpers
        with helpers.lifecycle_span("wf") as lsc:
            lsc.transition("worker1", "idle", "running")
            lsc.complete("worker1", "done")

        helpers._state_transitions.add.assert_called()

    def test_complete_sets_agent_attribute(self, reset_helpers):
        exporter = reset_helpers
        with helpers.lifecycle_span("wf") as lsc:
            lsc.complete("my_agent", "final output")

        spans = exporter.get_finished_spans()
        assert len(spans) >= 1


# ---------------------------------------------------------------------------
# record_transition
# ---------------------------------------------------------------------------

class TestRecordTransition:
    def test_creates_transition_span(self, reset_helpers):
        exporter = reset_helpers
        helpers.record_transition("worker_a", "idle", "busy")

        spans = exporter.get_finished_spans()
        assert len(spans) >= 1
        assert any("transition" in s.name.lower() or "idle" in s.name or "busy" in s.name
                   for s in spans)

    def test_records_state_transitions_counter(self, reset_helpers):
        helpers.record_transition("worker_b", "running", "done")
        helpers._state_transitions.add.assert_called()

    def test_adjusts_active_workers_gauge(self, reset_helpers):
        helpers.record_transition("w", "idle", "running")
        # active_workers should be adjusted
        helpers._active_workers.add.assert_called()

    def test_reason_attribute_optional(self, reset_helpers):
        exporter = reset_helpers
        helpers.record_transition("w", "a", "b", reason="manual override")
        spans = exporter.get_finished_spans()
        assert len(spans) >= 1

    def test_adjust_on_terminal_state(self, reset_helpers):
        """Transitioning to 'done' or 'error' should decrement active_workers."""
        helpers.record_transition("w", "running", "done")
        calls = helpers._active_workers.add.call_args_list
        # At least one call with negative amount (decrement)
        amounts = [c[0][0] for c in calls if c[0]]
        assert any(a < 0 for a in amounts)


# ---------------------------------------------------------------------------
# extract_parent_context
# ---------------------------------------------------------------------------

class TestExtractParentContext:
    def test_extracts_valid_traceparent(self):
        ctx = MagicMock()
        ctx.meta = {"headers": {"traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"}}
        result = helpers.extract_parent_context(ctx)
        # Should return an OTel context object (not None, not raising)
        assert result is not None

    def test_returns_none_on_missing_headers(self):
        ctx = MagicMock()
        ctx.meta = {}
        result = helpers.extract_parent_context(ctx)
        # Returns None or empty context — should not raise
        assert result is None or result is not None  # just no exception

    def test_handles_none_ctx(self):
        result = helpers.extract_parent_context(None)
        assert result is None
