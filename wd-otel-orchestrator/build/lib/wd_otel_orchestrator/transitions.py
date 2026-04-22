"""TransitionTracker — records state transitions and active worker metrics."""
from __future__ import annotations
import logging
from wd_otel import helpers

logger = logging.getLogger("wd_otel_orchestrator.transitions")

class TransitionTracker:
    def record_handoff(self, worker_name: str, reason: str = "") -> None:
        """Record idle -> running transition."""
        tracer = helpers._get_tracer()
        with tracer.start_as_current_span("orchestrator.transition", attributes={
            "worker.type": worker_name,
            "worker.from_state": "idle",
            "worker.to_state": "running",
            "handoff.reason": reason,
        }) as span:
            helpers._state_transitions.add(1, {
                "worker_type": worker_name, "from_state": "idle", "to_state": "running",
            })
            helpers._active_workers.add(1, {"worker_type": worker_name})
            span.add_event("state_changed", {"previous": "idle", "current": "running"})

    def record_completion(self, worker_name: str) -> None:
        """Record running -> completed transition."""
        tracer = helpers._get_tracer()
        with tracer.start_as_current_span("orchestrator.transition", attributes={
            "worker.type": worker_name,
            "worker.from_state": "running",
            "worker.to_state": "completed",
        }) as span:
            helpers._state_transitions.add(1, {
                "worker_type": worker_name, "from_state": "running", "to_state": "completed",
            })
            helpers._active_workers.add(-1, {"worker_type": worker_name})
            span.add_event("state_changed", {"previous": "running", "current": "completed"})

    def record_error(self, worker_name: str, error: Exception) -> None:
        """Record running -> error transition."""
        tracer = helpers._get_tracer()
        with tracer.start_as_current_span("orchestrator.transition", attributes={
            "worker.type": worker_name,
            "worker.from_state": "running",
            "worker.to_state": "error",
        }) as span:
            helpers._state_transitions.add(1, {
                "worker_type": worker_name, "from_state": "running", "to_state": "error",
            })
            helpers._active_workers.add(-1, {"worker_type": worker_name})
            helpers._orchestration_errors.add(1, {
                "error_type": type(error).__name__, "worker_type": worker_name,
            })
            span.record_exception(error)
            span.add_event("state_changed", {"previous": "running", "current": "error"})

    def record_sync_failure(self, worker_name: str, error: Exception) -> None:
        helpers._sync_failures.add(1, {
            "failure_type": type(error).__name__, "worker_type": worker_name,
        })
