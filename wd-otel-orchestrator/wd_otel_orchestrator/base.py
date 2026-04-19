"""TracedOrchestrator — base class for instrumented multi-agent orchestration."""
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

# ---------------------------------------------------------------------------
# Module-level state for httpx monkey-patch
# ---------------------------------------------------------------------------

_mcp_trace_context = None
_httpx_patched = False


def _ensure_httpx_patch() -> None:
    """Monkey-patch httpx.AsyncClient.send to inject traceparent headers.

    Uses module-level _mcp_trace_context so MCP calls in background tasks
    always pick up the current trace context. Only patches once.
    """
    global _httpx_patched
    if _httpx_patched:
        return

    _original_send = httpx.AsyncClient.send

    async def _send_with_trace(self, request, **kwargs):
        carrier: dict[str, str] = {}
        otel_inject(carrier, context=_mcp_trace_context)
        for k, v in carrier.items():
            request.headers[k] = v
        return await _original_send(self, request, **kwargs)

    httpx.AsyncClient.send = _send_with_trace
    _httpx_patched = True


# ---------------------------------------------------------------------------
# HandoffReason model
# ---------------------------------------------------------------------------

class HandoffReason(BaseModel):
    """Reason the orchestrator is handing off to a specialist."""
    reason: str


# ---------------------------------------------------------------------------
# TracedOrchestrator base class
# ---------------------------------------------------------------------------

class TracedOrchestrator:
    """Base class for instrumented multi-agent orchestration.

    Subclasses must define:
        name: str           — workflow name
        agents: dict        — map of agent name -> Agent instance
        entry_agent: Agent  — the agent that receives the initial input
    """

    name: str = ""
    agents: dict[str, Any] = {}
    entry_agent: Any = None

    def __init__(self) -> None:
        if not self.name:
            raise WdOtelConfigError(
                "TracedOrchestrator requires a non-empty 'name'",
                hint="Set the 'name' class attribute on your orchestrator subclass.",
            )
        if self.entry_agent is None:
            raise WdOtelConfigError(
                "TracedOrchestrator requires a non-None 'entry_agent'",
                hint="Set the 'entry_agent' class attribute to your entry Agent instance.",
            )
        self._tracker = TransitionTracker()
        _ensure_httpx_patch()

    # ── Handoff wiring ────────────────────────────────────────────────────

    def _make_on_handoff(self, worker_name: str):
        """Create a handoff callback that records a transition via the tracker."""
        tracker = self._tracker

        def on_handoff(ctx, input: HandoffReason) -> None:
            tracker.record_handoff(worker_name, reason=input.reason)
            logger.info("[Handoff] %s: idle->running, reason='%s'", worker_name, input.reason)

        return on_handoff

    def _build_handoffs(self) -> list:
        """Build handoff objects for all agents with instrumented callbacks."""
        handoffs = []
        for agent_name, agent in self.agents.items():
            handoffs.append(
                handoff(
                    agent,
                    on_handoff=self._make_on_handoff(agent_name),
                    input_type=HandoffReason,
                )
            )
        return handoffs

    # ── Lifecycle hooks (override in subclasses) ──────────────────────────

    async def on_before_run(self, input: str) -> None:
        """Hook called before Runner.run(). Override for custom logic."""

    async def on_after_run(self, result: Any, elapsed: float) -> None:
        """Hook called after a successful run. Override for custom logic."""

    async def on_error(self, error: Exception, elapsed: float) -> None:
        """Hook called when Runner.run() raises. Override for custom logic."""

    async def sync_status(self, worker_name: str, status: str, output: str) -> None:
        """Hook called to sync status to an external API. Override for custom logic."""

    # ── Main execute method ───────────────────────────────────────────────

    async def execute(self, input: str) -> str:
        """Run the orchestrator with full lifecycle tracing and metrics.

        Creates spans for the full lifecycle, the multi-agent run, and the
        runner invocation. Records session metrics in a finally block so they
        always fire. Returns the final output string or an error message.
        """
        global _mcp_trace_context
        start = time.perf_counter()
        tracer = helpers._get_tracer()

        final_agent_name = "unknown"
        final_output = ""
        lifecycle_status = "unknown"

        with tracer.start_as_current_span("orchestrator.worker.lifecycle") as lifecycle_span:
            lifecycle_span.set_attribute("workflow.name", self.name)
            lifecycle_span.set_attribute("agent.input", input)

            with tracer.start_as_current_span("multi-agent-run") as span:
                span.set_attribute("workflow.name", self.name)
                span.set_attribute("agent.input", input)

                # Capture context for httpx monkey-patch
                _mcp_trace_context = otel_context.get_current()

                await self.on_before_run(input)

                try:
                    with tracer.start_as_current_span("runner.run") as inner:
                        inner.set_attribute("entry.agent", getattr(self.entry_agent, "name", self.name))

                        with agents_trace(workflow_name=self.name):
                            result = await Runner.run(self.entry_agent, input=input)

                    elapsed = time.perf_counter() - start
                    final_output = result.final_output
                    final_agent_name = (
                        result.last_agent.name if result.last_agent else "unknown"
                    )

                    # Record completion transition
                    self._tracker.record_completion(final_agent_name)

                    span.set_attribute("agent.output", final_output)
                    span.set_attribute("duration_seconds", round(elapsed, 3))

                    lifecycle_status = "completed"
                    lifecycle_span.set_attribute("lifecycle.status", lifecycle_status)
                    lifecycle_span.set_attribute("lifecycle.final_agent", final_agent_name)
                    lifecycle_span.set_attribute("lifecycle.duration_s", round(elapsed, 3))

                    await self.on_after_run(result, elapsed)

                    logger.info("[Orchestrator] Done (%.3fs): %s", elapsed, final_output)

                except Exception as e:
                    elapsed = time.perf_counter() - start

                    # Record error transition
                    self._tracker.record_error(final_agent_name, e)

                    span.record_exception(e)
                    lifecycle_status = "error"
                    lifecycle_span.set_attribute("lifecycle.status", lifecycle_status)
                    lifecycle_span.set_attribute("lifecycle.error", str(e))

                    final_output = f"Error: {e}"

                    await self.on_error(e, elapsed)

                    logger.error("[Orchestrator] Error (%.3fs): %s", elapsed, e)

                finally:
                    # Session metrics ALWAYS fire
                    elapsed = time.perf_counter() - start
                    labels = {"workflow": self.name}
                    helpers._session_counter.add(1, labels)
                    helpers._session_duration.record(elapsed, labels)

            # Sync status (outside run span, inside lifecycle span)
            try:
                with tracer.start_as_current_span("orchestrator.sync", attributes={
                    "worker.type": final_agent_name,
                    "sync.status": lifecycle_status,
                }) as sync_span:
                    await self.sync_status(final_agent_name, lifecycle_status, final_output)
                    sync_span.set_attribute("sync.success", True)
            except Exception as sync_err:
                self._tracker.record_sync_failure(final_agent_name, sync_err)
                logger.error("[Sync] Failed to sync %s status: %s", final_agent_name, sync_err)

        return final_output
