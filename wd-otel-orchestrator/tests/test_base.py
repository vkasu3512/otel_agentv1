import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from wd_otel import helpers
from wd_otel.errors import WdOtelConfigError
from wd_otel_orchestrator.base import TracedOrchestrator

class TestValidation:
    def test_missing_name_raises(self):
        with pytest.raises(WdOtelConfigError, match="name"):
            class Bad(TracedOrchestrator):
                agents = {}
                entry_agent = MagicMock()
            Bad()

    def test_missing_entry_agent_raises(self):
        with pytest.raises(WdOtelConfigError, match="entry_agent"):
            class Bad(TracedOrchestrator):
                name = "test"
                agents = {}
            Bad()

class TestExecute:
    @pytest.mark.asyncio
    async def test_returns_result(self, setup_test_otel):
        mock_result = MagicMock()
        mock_result.final_output = "42"
        mock_result.last_agent = MagicMock()
        mock_result.last_agent.name = "AgentA"
        with patch("wd_otel_orchestrator.base.Runner") as MockRunner:
            MockRunner.run = AsyncMock(return_value=mock_result)
            class TestOrch(TracedOrchestrator):
                name = "test-wf"
                agents = {"AgentA": MagicMock()}
                entry_agent = MagicMock()
            result = await TestOrch().execute("test")
            assert result == "42"

    @pytest.mark.asyncio
    async def test_records_session_metrics(self, setup_test_otel):
        mock_result = MagicMock()
        mock_result.final_output = "42"
        mock_result.last_agent = MagicMock()
        mock_result.last_agent.name = "A"
        with patch("wd_otel_orchestrator.base.Runner") as MockRunner:
            MockRunner.run = AsyncMock(return_value=mock_result)
            class TestOrch(TracedOrchestrator):
                name = "test-wf"
                agents = {"A": MagicMock()}
                entry_agent = MagicMock()
            await TestOrch().execute("test")
        helpers._session_counter.add.assert_called()
        helpers._session_duration.record.assert_called()

    @pytest.mark.asyncio
    async def test_records_completion_transition(self, setup_test_otel):
        mock_result = MagicMock()
        mock_result.final_output = "ok"
        mock_result.last_agent = MagicMock()
        mock_result.last_agent.name = "A"
        with patch("wd_otel_orchestrator.base.Runner") as MockRunner:
            MockRunner.run = AsyncMock(return_value=mock_result)
            class TestOrch(TracedOrchestrator):
                name = "test-wf"
                agents = {"A": MagicMock()}
                entry_agent = MagicMock()
            await TestOrch().execute("test")
        helpers._active_workers.add.assert_called()

    @pytest.mark.asyncio
    async def test_records_error_on_exception(self, setup_test_otel):
        with patch("wd_otel_orchestrator.base.Runner") as MockRunner:
            MockRunner.run = AsyncMock(side_effect=RuntimeError("LLM error"))
            class TestOrch(TracedOrchestrator):
                name = "test-wf"
                agents = {"A": MagicMock()}
                entry_agent = MagicMock()
            result = await TestOrch().execute("test")
            assert "Error:" in result
        helpers._orchestration_errors.add.assert_called()

    @pytest.mark.asyncio
    async def test_calls_hooks(self, setup_test_otel):
        mock_result = MagicMock()
        mock_result.final_output = "42"
        mock_result.last_agent = MagicMock()
        mock_result.last_agent.name = "A"
        with patch("wd_otel_orchestrator.base.Runner") as MockRunner:
            MockRunner.run = AsyncMock(return_value=mock_result)
            class TestOrch(TracedOrchestrator):
                name = "test-wf"
                agents = {"A": MagicMock()}
                entry_agent = MagicMock()
                on_before_run = AsyncMock()
                on_after_run = AsyncMock()
                sync_status = AsyncMock()
            orch = TestOrch()
            await orch.execute("test")
            orch.on_before_run.assert_called_once()
            orch.on_after_run.assert_called_once()
            orch.sync_status.assert_called_once()

    @pytest.mark.asyncio
    async def test_calls_on_error_hook(self, setup_test_otel):
        with patch("wd_otel_orchestrator.base.Runner") as MockRunner:
            MockRunner.run = AsyncMock(side_effect=RuntimeError("fail"))
            class TestOrch(TracedOrchestrator):
                name = "test-wf"
                agents = {"A": MagicMock()}
                entry_agent = MagicMock()
                on_error = AsyncMock()
                sync_status = AsyncMock()
            orch = TestOrch()
            await orch.execute("test")
            orch.on_error.assert_called_once()
            orch.sync_status.assert_called_once()
