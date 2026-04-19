"""
Multi-Agent Calculator — orchestrator logic only (no transport, no OTel bootstrap).

Preconditions (enforced by the caller, not this file):
    1. `wd_otel.init("otel_agent_v2/wd-otel-orchestrator.yaml")` has been called.
    2. `OpenAIAgentsInstrumentor().instrument()` has been called.

Both api.py and cli.py set these up before importing this module.

Exports:
    orchestrator     — a singleton CalculatorOrchestrator instance.
                       Call `await orchestrator.execute(question)` to run one session.
    add_sub_server   — MCPServerStreamableHttp handle for the add/subtract server
                       (port 8081). Callers must enter it as an async context
                       manager before calling orchestrator.execute().
    mul_div_server   — MCPServerStreamableHttp handle for the multi-step solver
                       (port 8082). Same async-context-manager contract.
"""
from __future__ import annotations

import logging
import os

from agents import Agent, AsyncOpenAI, OpenAIChatCompletionsModel, handoff
from agents.mcp import MCPServerStreamableHttp

from wd_otel_orchestrator import TracedOrchestrator

logger = logging.getLogger(__name__)

# ── 1. LLM client ────────────────────────────────────────────────────────────
# Swap base_url/api_key to point at any OpenAI-compatible endpoint
# (Groq here; a Bedrock proxy, Ollama, or vLLM would work identically).
_client = AsyncOpenAI(
    api_key=os.environ["API_KEY"],
    base_url=os.environ.get("LLM_BASE_URL", "https://api.groq.com/openai/v1/"),
)
_model = OpenAIChatCompletionsModel(
    model=os.environ.get("LLM_MODEL", "openai/gpt-oss-120b"),
    openai_client=_client,
)

# ── 2. MCP server handles ────────────────────────────────────────────────────
add_sub_server = MCPServerStreamableHttp(
    name="add_sub_server",
    params={"url": "http://localhost:8081/mcp"},
    cache_tools_list=True,
)
mul_div_server = MCPServerStreamableHttp(
    name="mul_div_server",
    params={"url": "http://localhost:8082/mcp"},
    cache_tools_list=True,
)

# ── 3. Specialist agents ─────────────────────────────────────────────────────
add_sub_agent = Agent(
    name="AddSubAgent",
    instructions=(
        "You only handle addition and subtraction. "
        "Always use the add or subtract tool — never calculate mentally. "
        "Return just the numeric result."
    ),
    model=_model,
    mcp_servers=[add_sub_server],
)

solver_agent = Agent(
    name="SolverAgent",
    instructions=(
        "You handle complex arithmetic expressions with multiple operations. "
        "Always use the solve_steps tool — never calculate mentally. "
        "Return the full step-by-step breakdown."
    ),
    model=_model,
    mcp_servers=[mul_div_server],
)

# ── 4. Orchestrator agent (the entry_agent) ──────────────────────────────────
# TracedOrchestrator.execute() wires in on_handoff callbacks that record
# idle→running transitions automatically via TransitionTracker. The base
# class handles input_type=HandoffReason internally when _build_handoffs()
# is called in section 6 below.
_orchestrator_agent = Agent(
    name="OrchestratorAgent",
    instructions=(
        "You are a routing orchestrator for a calculator system. "
        "Given a math question, hand off to the correct specialist:\n"
        "  - AddSubAgent  -> simple addition or subtraction only\n"
        "  - SolverAgent  -> complex expressions with *, /, ** or parentheses\n"
        "Always include a brief reason when handing off. "
        "Never calculate yourself — always hand off."
    ),
    model=_model,
    handoffs=[
        handoff(add_sub_agent),
        handoff(solver_agent),
    ],
)


# ── 5. CalculatorOrchestrator(TracedOrchestrator) ────────────────────────────
class CalculatorOrchestrator(TracedOrchestrator):
    """Concrete orchestrator. The base class handles all lifecycle metrics."""

    name = "multi-agent-calculator"
    agents = {"AddSubAgent": add_sub_agent, "SolverAgent": solver_agent}
    entry_agent = _orchestrator_agent

    async def sync_status(self, worker_name: str, status: str, output: str) -> None:
        """Simulate syncing worker status to an external system.

        Any exception raised here is recorded as a sync_failure by the base
        class automatically (see TracedOrchestrator.execute).
        """
        logger.info(f"[Sync] {worker_name} status='{status}' (output len={len(output)}) synced")


# ── 6. Rebuild handoffs with on_handoff callbacks wired by TracedOrchestrator ─
# The base class's _build_handoffs() generates callbacks that record the
# idle→running transition via TransitionTracker. We overwrite the plain
# handoffs defined above so metrics fire. This pattern is required because
# the Agent object needs the handoff callback bound at construction time,
# but the callback needs a reference to the orchestrator's tracker.
orchestrator = CalculatorOrchestrator()
_orchestrator_agent.handoffs = orchestrator._build_handoffs()
