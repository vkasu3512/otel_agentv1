"""
Calculator Agent — OpenTelemetry version (manual spans only, no Langfuse).

Replaces model_mcp.py using native OTel instrumentation:
  - Traces  → manual tracer.start_as_current_span() calls
  - Metrics → agent.runs.total (counter) + agent.run.duration (histogram)
  - Logs    → Python logging correlated with trace_id/span_id

MCP Servers (start these first from the parent Appraoch_ne/ directory):
    python mcp_tool.py add_sub   # → localhost:8081
    python mcp_tool.py mul_div   # → localhost:8082

OTLP backend (example — Jaeger all-in-one):
    docker run -d -p 4317:4317 -p 16686:16686 jaegertracing/all-in-one:latest

Run:
    python agent.py
"""

import asyncio
import logging
import os
import time
from dotenv import load_dotenv

load_dotenv()

# ── 1. OTel bootstrap (MUST happen before agents SDK imports) ─────────────────
from otel_setup import init_otel, get_tracer, get_meter

trace_provider, metrics_provider = init_otel("calculator-agent")

tracer = get_tracer("otel_agent.agent")
meter  = get_meter("otel_agent.agent")
logger = logging.getLogger(__name__)

# ── 2. Metrics instruments ────────────────────────────────────────────────────
run_counter = meter.create_counter(
    "agent.runs.total",
    unit="1",
    description="Total number of calculator agent runs",
)
run_duration = meter.create_histogram(
    "agent.run.duration",
    unit="s",
    description="Wall-clock duration of each run_agent() call in seconds",
)

# ── 3. Agent + MCP setup ──────────────────────────────────────────────────────
from agents import AsyncOpenAI, OpenAIChatCompletionsModel, Agent, Runner
from agents import set_tracing_disabled
from agents.mcp import MCPServerStreamableHttp

# Disable the agents SDK's built-in OpenAI trace exporter — we use OTel instead.
# Without this it warns "OPENAI_API_KEY is not set, skipping trace export"
# because we're using Groq, not OpenAI's backend.
set_tracing_disabled(True)

client = AsyncOpenAI(
    api_key=os.environ["API_KEY"],
    base_url="https://api.groq.com/openai/v1/",
)
model = OpenAIChatCompletionsModel(
    model="openai/gpt-oss-120b",
    openai_client=client,
)

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

agent = Agent(
    name="CalculatorAgent",
    instructions=(
        "You are a calculator assistant. "
        "Use the add/subtract tools for addition and subtraction, "
        "and the multiply/divide tools for multiplication and division. "
        "Always use a tool to compute — never calculate mentally."
    ),
    model=model,
    mcp_servers=[add_sub_server, mul_div_server],
)

# ── 4. Traced runner ──────────────────────────────────────────────────────────
async def run_agent(user_message: str) -> str:
    """
    Run the calculator agent with full OTel tracing (manual spans).

    Span hierarchy produced:
      calculator-agent-run          ← outer span (workflow level)
        runner.run                  ← inner span (SDK execution level)
    """
    start = time.perf_counter()

    with tracer.start_as_current_span("calculator-agent-run") as span:
        span.set_attribute("workflow.name", "calculator-agent-run")
        span.set_attribute("agent.input", user_message)

        logger.info(f"Agent run started: {user_message}")

        with tracer.start_as_current_span("runner.run") as inner:
            inner.set_attribute("agent.name", "CalculatorAgent")
            result = await Runner.run(agent, input=user_message)

        final_output = result.final_output
        elapsed = time.perf_counter() - start

        span.set_attribute("agent.output", final_output)

        run_counter.add(1, {"agent": "CalculatorAgent"})
        run_duration.record(elapsed, {"agent": "CalculatorAgent"})

        logger.info(f"Agent run complete ({elapsed:.3f}s): {final_output}")

    return final_output

# ── 5. Entry point ────────────────────────────────────────────────────────────
async def main():
    questions = ["Solve step by step: (3 + 5) * 2 - 4 / 2"
                 
        # "What is 42 + 58?",
        # "What is 100 - 37?",
        # "What is 6 multiplied by 9?",
        # "What is 144 divided by 12?",
        # "What is (25 + 75) * 4?",   # multi-step: uses both MCP servers
    ]

    async with add_sub_server, mul_div_server:
        # Warm up tool list cache once before the loop
        await add_sub_server.list_tools()
        await mul_div_server.list_tools()

        for question in questions:
            print(f"\nUser: {question}")
            response = await run_agent(question)
            print(f"Agent: {response}")

    # Flush all pending spans and shut down metrics before exit
    # (replaces langfuse.flush())
    trace_provider.force_flush()   # synchronous — do NOT await
    metrics_provider.shutdown()    # MeterProvider has no force_flush(), use shutdown()


if __name__ == "__main__":
    asyncio.run(main())
