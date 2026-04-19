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
        helpers._active_workers.add.assert_called_once_with(1, {"worker_type": "AddSubAgent"})
        assert any(s.name == "orchestrator.transition" for s in exporter.get_finished_spans())

    def test_record_completion_decrements_active_workers(self, setup_test_otel):
        tracker = TransitionTracker()
        tracker.record_completion("AddSubAgent")
        helpers._active_workers.add.assert_called_once_with(-1, {"worker_type": "AddSubAgent"})

    def test_record_error_decrements_workers_and_counts_error(self, setup_test_otel):
        tracker = TransitionTracker()
        tracker.record_error("AddSubAgent", RuntimeError("boom"))
        helpers._active_workers.add.assert_called_once_with(-1, {"worker_type": "AddSubAgent"})
        helpers._orchestration_errors.add.assert_called_once()

    def test_record_sync_failure(self, setup_test_otel):
        tracker = TransitionTracker()
        tracker.record_sync_failure("AddSubAgent", RuntimeError("sync fail"))
        helpers._sync_failures.add.assert_called_once()
