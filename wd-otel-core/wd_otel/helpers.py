"""WD-OTel SDK — metric instruments and span context managers for agents."""
from __future__ import annotations

import contextlib
import logging
import time
from contextlib import contextmanager
from typing import Any, Iterator

from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.propagators.textmap import DefaultGetter
from opentelemetry.propagate import extract

logger = logging.getLogger("wd_otel.helpers")

# ---------------------------------------------------------------------------
# Module-level instrument references (populated by init_instruments)
# ---------------------------------------------------------------------------

_tracer = None
_meter = None

_tool_invocations = None
_tool_duration = None
_tool_timeouts = None
_session_counter = None
_session_duration = None
_state_transitions = None
_active_workers = None
_orchestration_errors = None
_sync_failures = None

# ---------------------------------------------------------------------------
# States that mean a worker is no longer active
# ---------------------------------------------------------------------------
_TERMINAL_STATES = {"done", "error", "failed", "stopped", "complete", "completed"}


def _get_tracer() -> trace.Tracer:
    """Return the module tracer if set, otherwise fall back to global tracer."""
    if _tracer is not None:
        return _tracer
    return trace.get_tracer("wd_otel")


def init_instruments(meter) -> None:
    """Create and store all metric instruments from the supplied meter.

    Call this once after setup_metrics() returns a MeterProvider:

        helpers.init_instruments(meter_provider.get_meter("wd_otel"))
    """
    global _meter
    global _tool_invocations, _tool_duration, _tool_timeouts
    global _session_counter, _session_duration
    global _state_transitions, _active_workers
    global _orchestration_errors, _sync_failures

    _meter = meter

    _tool_invocations = meter.create_counter(
        name="wd_otel.tool.invocations",
        description="Number of tool invocations",
        unit="1",
    )
    _tool_duration = meter.create_histogram(
        name="wd_otel.tool.duration",
        description="Duration of tool invocations in seconds",
        unit="s",
    )
    _tool_timeouts = meter.create_counter(
        name="wd_otel.tool.timeouts",
        description="Number of tool timeouts",
        unit="1",
    )
    _session_counter = meter.create_counter(
        name="wd_otel.session.count",
        description="Number of lifecycle sessions",
        unit="1",
    )
    _session_duration = meter.create_histogram(
        name="wd_otel.session.duration",
        description="Duration of lifecycle sessions in seconds",
        unit="s",
    )
    _state_transitions = meter.create_counter(
        name="wd_otel.state.transitions",
        description="Number of worker state transitions",
        unit="1",
    )
    _active_workers = meter.create_up_down_counter(
        name="wd_otel.workers.active",
        description="Number of currently active workers",
        unit="1",
    )
    _orchestration_errors = meter.create_counter(
        name="wd_otel.orchestration.errors",
        description="Number of orchestration errors",
        unit="1",
    )
    _sync_failures = meter.create_counter(
        name="wd_otel.sync.failures",
        description="Number of sync failures",
        unit="1",
    )


# ---------------------------------------------------------------------------
# Context extraction
# ---------------------------------------------------------------------------

def extract_parent_context(ctx) -> otel_context.Context | None:
    """Extract W3C traceparent from a FastMCP Context's headers.

    Args:
        ctx: FastMCP Context object (or any object with .meta["headers"]).

    Returns:
        OTel Context with propagated span, or None if unavailable.
    """
    if ctx is None:
        return None
    try:
        headers = ctx.meta.get("headers", {}) if ctx.meta else {}
        if not headers:
            return None
        carrier = dict(headers)
        return extract(carrier)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# ToolSpanContext — returned from tool_span
# ---------------------------------------------------------------------------

class ToolSpanContext:
    """Handle returned by the tool_span context manager."""

    def __init__(self, span: trace.Span):
        self._span = span

    def set_output(self, result: Any) -> None:
        """Record the tool output as a span attribute."""
        try:
            self._span.set_attribute("tool.output", str(result))
        except Exception:
            pass

    def set_attribute(self, key: str, value: Any) -> None:
        """Set an arbitrary attribute on the active span."""
        try:
            self._span.set_attribute(key, value)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# LifecycleSpanContext — returned from lifecycle_span
# ---------------------------------------------------------------------------

class LifecycleSpanContext:
    """Handle returned by the lifecycle_span context manager."""

    def __init__(self, span: trace.Span):
        self._span = span

    def complete(self, agent: str, output: str) -> None:
        """Mark the session as successfully completed."""
        try:
            self._span.set_attribute("lifecycle.agent", agent)
            self._span.set_attribute("lifecycle.output", str(output))
            self._span.set_attribute("lifecycle.status", "completed")
        except Exception:
            pass

    def error(self, agent: str, exception: Exception) -> None:
        """Mark the session as errored."""
        try:
            self._span.set_attribute("lifecycle.agent", agent)
            self._span.set_attribute("lifecycle.status", "error")
            self._span.record_exception(exception)
        except Exception:
            pass

    def transition(self, worker: str, from_state: str, to_state: str) -> None:
        """Record a state transition within the lifecycle span."""
        _record_transition_internal(worker, from_state, to_state, reason="lifecycle")


# ---------------------------------------------------------------------------
# child_span
# ---------------------------------------------------------------------------

@contextmanager
def child_span(
    name: str,
    attributes: dict[str, Any] | None = None,
) -> Iterator[trace.Span]:
    """Context manager that creates a child span of the current active span.

    Args:
        name: Span name.
        attributes: Optional dict of span attributes to set at creation.

    Yields:
        The active opentelemetry Span.
    """
    tracer = _get_tracer()
    with tracer.start_as_current_span(name, attributes=attributes or {}) as span:
        yield span


# ---------------------------------------------------------------------------
# tool_span
# ---------------------------------------------------------------------------

@contextmanager
def tool_span(
    ctx,
    tool_name: str,
    server: str,
    inputs: dict[str, Any] | None = None,
    timeout_s: float = 10.0,
) -> Iterator[ToolSpanContext]:
    """Context manager that wraps a tool invocation with tracing and metrics.

    Creates a span, records invocations/duration/timeouts in the finally block.

    Args:
        ctx: FastMCP Context (used for W3C traceparent extraction).
        tool_name: Name of the MCP tool being invoked.
        server: Name of the server hosting the tool.
        inputs: Optional dict of tool inputs (stored as span attributes).
        timeout_s: Timeout in seconds (not enforced here; used as metadata).

    Yields:
        ToolSpanContext with set_output() and set_attribute() helpers.
    """
    parent_ctx = extract_parent_context(ctx)
    tracer = _get_tracer()

    span_name = f"tool/{tool_name}"
    span_attrs = {
        "tool.name": tool_name,
        "tool.server": server,
        "tool.timeout_s": timeout_s,
    }
    if inputs:
        span_attrs["tool.inputs"] = str(inputs)

    token = otel_context.attach(parent_ctx) if parent_ctx else None

    start_time = time.monotonic()
    timed_out = False
    errored = False
    span_ctx = None

    try:
        with tracer.start_as_current_span(span_name, attributes=span_attrs) as span:
            span_ctx = ToolSpanContext(span)
            try:
                yield span_ctx
            except TimeoutError:
                timed_out = True
                errored = True
                span.record_exception(TimeoutError())
                raise
            except Exception as exc:
                errored = True
                span.record_exception(exc)
                raise
    finally:
        elapsed = time.monotonic() - start_time
        labels = {"tool": tool_name, "server": server, "status": "error" if errored else "ok"}

        if _tool_invocations is not None:
            _tool_invocations.add(1, labels)
        if _tool_duration is not None:
            _tool_duration.record(elapsed, labels)
        if timed_out and _tool_timeouts is not None:
            _tool_timeouts.add(1, {"tool": tool_name, "server": server})
        if token is not None:
            otel_context.detach(token)


# ---------------------------------------------------------------------------
# lifecycle_span
# ---------------------------------------------------------------------------

@contextmanager
def lifecycle_span(
    workflow_name: str,
    input: str = "",
) -> Iterator[LifecycleSpanContext]:
    """Context manager that wraps a full agent session with tracing and metrics.

    Args:
        workflow_name: Name of the workflow/agent.
        input: Optional initial input string.

    Yields:
        LifecycleSpanContext with complete(), error(), and transition() helpers.
    """
    tracer = _get_tracer()
    span_attrs: dict[str, Any] = {"lifecycle.workflow": workflow_name}
    if input:
        span_attrs["lifecycle.input"] = input

    start_time = time.monotonic()
    errored = False

    try:
        with tracer.start_as_current_span(f"lifecycle/{workflow_name}", attributes=span_attrs) as span:
            lsc = LifecycleSpanContext(span)
            try:
                yield lsc
            except Exception as exc:
                errored = True
                span.record_exception(exc)
                raise
    finally:
        elapsed = time.monotonic() - start_time
        labels = {"workflow": workflow_name, "status": "error" if errored else "ok"}

        if _session_counter is not None:
            _session_counter.add(1, labels)
        if _session_duration is not None:
            _session_duration.record(elapsed, labels)


# ---------------------------------------------------------------------------
# record_transition
# ---------------------------------------------------------------------------

def _record_transition_internal(
    worker: str,
    from_state: str,
    to_state: str,
    reason: str = "",
) -> None:
    """Internal helper shared by record_transition and LifecycleSpanContext.transition."""
    tracer = _get_tracer()
    span_attrs: dict[str, Any] = {
        "transition.worker": worker,
        "transition.from": from_state,
        "transition.to": to_state,
    }
    if reason:
        span_attrs["transition.reason"] = reason

    with tracer.start_as_current_span(f"transition/{worker}/{from_state}->{to_state}", attributes=span_attrs):
        pass

    labels = {"worker": worker, "from": from_state, "to": to_state}
    if _state_transitions is not None:
        _state_transitions.add(1, labels)

    if _active_workers is not None:
        w_labels = {"worker": worker}
        # Worker transitions INTO active from terminal (e.g. idle->running from done->running)
        if to_state not in _TERMINAL_STATES and from_state in _TERMINAL_STATES:
            _active_workers.add(1, w_labels)
        # Worker transitions OUT OF active into terminal (e.g. running->done)
        elif to_state in _TERMINAL_STATES and from_state not in _TERMINAL_STATES:
            _active_workers.add(-1, w_labels)
        # Both non-terminal: worker is still active, record as +0 sentinel to signal activity
        else:
            _active_workers.add(0, w_labels)


def record_transition(
    worker: str,
    from_state: str,
    to_state: str,
    reason: str = "",
) -> None:
    """Create a transition span and record state_transitions counter + active_workers gauge.

    Args:
        worker: Worker identifier.
        from_state: Previous state label.
        to_state: New state label.
        reason: Optional human-readable reason for the transition.
    """
    _record_transition_internal(worker, from_state, to_state, reason=reason)
