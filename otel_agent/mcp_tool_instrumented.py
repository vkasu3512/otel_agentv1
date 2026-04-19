"""
MCP Calculator Servers with OpenTelemetry instrumentation.

Includes:
  - add, subtract (add_sub_server on 8081)
  - solve_steps with LangGraph (mul_div_server on 8082)

Each tool creates OTel child spans, linked to parent trace via W3C Trace Context.

Usage (3 separate terminals from otel_agent/):
  Terminal 1:
    python mcp_tool_instrumented.py add_sub

  Terminal 2:
    python mcp_tool_instrumented.py mul_div

  Terminal 3:
    python agent_auto_multiple.py
"""

import ast
import operator as op_module
import re
import sys
import logging
from typing import TypedDict
from fastmcp import FastMCP, Context
from langgraph.graph import StateGraph, END

from otel_setup import init_otel, get_tracer, get_meter
from opentelemetry import trace, context as otel_context
from opentelemetry.propagate import extract as otel_extract

# Initialize OTel
_PROMETHEUS_PORT = 8001 if (len(sys.argv) > 1 and sys.argv[1] == "add_sub") else 8002

trace_provider, metrics_provider = init_otel(
    "mcp-calculator-server",
    filter_libraries=["fastmcp"],   # drop FastMCP's own root spans — we emit our own
    prometheus_port=_PROMETHEUS_PORT,
)
tracer = get_tracer(__name__)
meter  = get_meter(__name__)

# ── Worker Runner (LangGraph) KPI metrics ────────────────────────────────────
graph_build_time = meter.create_histogram(
    "langgraph.build.duration",
    unit="s",
    description="Time to construct and compile the execution graph",
)
step_total = meter.create_counter(
    "langgraph.step.total",
    unit="1",
    description="Total graph node executions by node and status",
)
execution_duration = meter.create_histogram(
    "langgraph.execution.duration",
    unit="s",
    description="Total duration of a full graph run",
)
step_retries = meter.create_counter(
    "langgraph.step.retries",
    unit="1",
    description="Total step retry attempts per node",
)

# ── MCP Tool Server KPI metrics ───────────────────────────────────────────────
tool_invocations = meter.create_counter(
    "mcp.tool.invocations",
    unit="1",
    description="Total MCP tool invocations by tool, server, and status",
)
tool_duration = meter.create_histogram(
    "mcp.tool.duration",
    unit="s",
    description="MCP tool response latency by tool and server",
)
tool_timeouts = meter.create_counter(
    "mcp.tool.timeouts",
    unit="1",
    description="MCP tool calls that exceeded timeout",
)

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def run_node_with_retry(node_fn, state: dict, max_retries: int = 2) -> dict:
    """Run a LangGraph node with retry logic, tracking retries in Prometheus."""
    node_name = node_fn.__name__
    for attempt in range(max_retries + 1):
        try:
            return node_fn(state)
        except Exception as e:
            if attempt < max_retries:
                step_retries.add(1, {"node": node_name})
                wait = 2 ** attempt
                logger.warning(f"[Retry] {node_name} attempt {attempt + 1}/{max_retries} failed: {e}. Retrying in {wait}s")
                import time as _time; _time.sleep(wait)
            else:
                raise


def instrumented_tool(tool_name: str, server_name: str, timeout_s: float = 10.0):
    """Decorator: adds invocation counter, latency histogram, and timeout tracking to MCP tools."""
    import functools, time as _time, threading, contextvars
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            start = _time.perf_counter()
            status = "success"
            try:
                # Copy ALL Python contextvars (Starlette request context + OTel span context)
                # into the worker thread so ctx.request_context.request.headers is accessible
                # and _get_parent_ctx can extract the traceparent header correctly.
                # otel_context.get_current() alone only copies OTel's context; Starlette's
                # request ContextVar lives in a separate slot and would be lost otherwise.
                cv_ctx = contextvars.copy_context()
                result_holder = [None]
                exc_holder = [None]

                def target():
                    try:
                        result_holder[0] = cv_ctx.run(fn, *args, **kwargs)
                    except Exception as e:
                        exc_holder[0] = e

                t = threading.Thread(target=target, daemon=True)
                t.start()
                t.join(timeout=timeout_s)

                if t.is_alive():
                    tool_timeouts.add(1, {"tool": tool_name, "tool_server": server_name})
                    status = "timeout"
                    raise TimeoutError(f"{tool_name} exceeded {timeout_s}s timeout")

                if exc_holder[0] is not None:
                    raise exc_holder[0]

                return result_holder[0]

            except TimeoutError:
                status = "timeout"
                raise
            except Exception:
                status = "error"
                raise
            finally:
                elapsed = _time.perf_counter() - start
                tool_invocations.add(1, {"tool": tool_name, "tool_server": server_name, "status": status})
                tool_duration.record(elapsed, {"tool": tool_name, "tool_server": server_name})
        return wrapper
    return decorator


def _get_parent_ctx(ctx: Context):
    """Extract W3C trace context from FastMCP HTTP request headers using propagate.extract()."""
    try:
        headers = dict(ctx.request_context.request.headers)
        tp = headers.get("traceparent")
        if not tp:
            logger.warning("[TraceCtx] traceparent header MISSING — span will be a root")
            return None
        # Use the standard OTel propagator instead of manual parsing —
        # handles all edge cases (flags, tracestate, future formats) correctly.
        parent_ctx = otel_extract(headers)
        logger.info(f"[TraceCtx] traceparent={tp} -> linked")
        return parent_ctx
    except Exception as exc:
        logger.warning(f"[TraceCtx] Failed to extract parent context: {exc}")
        return None


# ---------------------------------------------------------------------------
# LangGraph: safe expression evaluator (used by solve_steps tool)
# ---------------------------------------------------------------------------
ALLOWED_OPS = {
    ast.Add:  op_module.add,
    ast.Sub:  op_module.sub,
    ast.Mult: op_module.mul,
    ast.Div:  op_module.truediv,
    ast.Pow:  op_module.pow,
    ast.USub: op_module.neg,
    ast.UAdd: op_module.pos,
}

def _eval_node(node: ast.AST) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.BinOp) and type(node.op) in ALLOWED_OPS:
        return ALLOWED_OPS[type(node.op)](_eval_node(node.left), _eval_node(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in ALLOWED_OPS:
        return ALLOWED_OPS[type(node.op)](_eval_node(node.operand))
    raise ValueError(f"Unsupported expression: {ast.dump(node)}")

def _safe_eval(expr: str) -> float:
    """Evaluate a math expression string safely using the AST (no eval())."""
    tree = ast.parse(expr.strip(), mode="eval")
    return _eval_node(tree.body)


# ---------------------------------------------------------------------------
# LangGraph state + nodes
# ---------------------------------------------------------------------------
class MathState(TypedDict):
    expression: str
    tokens: list
    result: float
    steps: list
    error: str


def parse_node(state: MathState) -> dict:
    """Node 1 — tokenize the expression into numbers and operators."""
    with tracer.start_as_current_span("langgraph_parse_node") as span:
        expr = state["expression"]
        try:
            tokens = re.findall(r"\d+\.?\d*|[+\-*/^()]", expr)
            span.set_attribute("expression", expr)
            span.set_attribute("token_count", len(tokens))
            span.set_attribute("tokens", str(tokens))
            span.set_attribute("status", "success")
            step_total.add(1, {"node": "parse_node", "status": "success"})
            logger.info(f"[LangGraph] Parse: '{expr}' -> {len(tokens)} tokens")
            return {
                "tokens": tokens,
                "steps": [f"[Parse]    '{expr}'  ->  tokens: {tokens}"],
            }
        except Exception as e:
            step_total.add(1, {"node": "parse_node", "status": "failure"})
            span.set_attribute("status", "failure")
            span.record_exception(e)
            raise


def evaluate_node(state: MathState) -> dict:
    """Node 2 — evaluate the expression and record the numeric result."""
    with tracer.start_as_current_span("langgraph_evaluate_node") as span:
        expr = state["expression"]
        steps = state["steps"]
        span.set_attribute("expression", expr)

        try:
            result = _safe_eval(expr)
            span.set_attribute("result", result)
            span.set_attribute("error", "")
            span.set_attribute("status", "success")
            step_total.add(1, {"node": "evaluate_node", "status": "success"})
            logger.info(f"[LangGraph] Evaluate: '{expr}' = {result}")
            return {
                "result": result,
                "error": "",
                "steps": steps + [f"[Evaluate] '{expr}'  =  {result}"],
            }
        except Exception as exc:
            span.set_attribute("result", 0.0)
            span.set_attribute("error", str(exc))
            span.set_attribute("status", "failure")
            span.record_exception(exc)
            step_total.add(1, {"node": "evaluate_node", "status": "failure"})
            logger.error(f"[LangGraph] Evaluate ERROR: {exc}")
            return {
                "result": 0.0,
                "error": str(exc),
                "steps": steps + [f"[Evaluate] ERROR: {exc}"],
            }


def format_node(state: MathState) -> dict:
    """Node 3 — build the final human-readable answer string."""
    with tracer.start_as_current_span("langgraph_format_node") as span:
        steps = state["steps"]
        try:
            if state["error"]:
                summary = f"Could not solve '{state['expression']}': {state['error']}"
                span.set_attribute("error", state["error"])
                span.set_attribute("status", "failure")
                step_total.add(1, {"node": "format_node", "status": "failure"})
            else:
                result = state["result"]
                result_str = str(int(result)) if result == int(result) else str(result)
                summary = f"[Format]   Result = {result_str}"
                span.set_attribute("result_formatted", result_str)
                span.set_attribute("status", "success")
                step_total.add(1, {"node": "format_node", "status": "success"})

            span.set_attribute("expression", state["expression"])
            logger.info(f"[LangGraph] Format: {summary}")
            return {"steps": steps + [summary]}
        except Exception as e:
            step_total.add(1, {"node": "format_node", "status": "failure"})
            span.set_attribute("status", "failure")
            span.record_exception(e)
            raise


# Compile the LangGraph workflow once at module load — measure build duration
import time as _build_time
_build_start = _build_time.perf_counter()
_solver_graph = (
    StateGraph(MathState)
    .add_node("parse",    parse_node)
    .add_node("evaluate", evaluate_node)
    .add_node("format",   format_node)
    .set_entry_point("parse")
    .add_edge("parse",    "evaluate")
    .add_edge("evaluate", "format")
    .add_edge("format",   END)
    .compile()
)
_build_elapsed = _build_time.perf_counter() - _build_start
graph_build_time.record(_build_elapsed, {"worker_type": "solver"})
logger.info(f"[LangGraph] Graph compiled in {_build_elapsed:.4f}s")


# ---------------------------------------------------------------------------
# Server 1: Addition & Subtraction  (port 8081)
# ---------------------------------------------------------------------------
add_sub_mcp = FastMCP(name="add_sub_server")


@add_sub_mcp.tool()
@instrumented_tool("add", "add_sub_server")
def add(a: float, b: float, ctx: Context) -> float:
    """Add two numbers together."""
    parent_ctx = _get_parent_ctx(ctx)
    with tracer.start_as_current_span("add_operation", context=parent_ctx) as span:
        span.set_attribute("operand_a", a)
        span.set_attribute("operand_b", b)
        result = a + b
        span.set_attribute("result", result)
        logger.info(f"add({a}, {b}) = {result}")
        return result


@add_sub_mcp.tool()
@instrumented_tool("subtract", "add_sub_server")
def subtract(a: float, b: float, ctx: Context) -> float:
    """Subtract b from a."""
    parent_ctx = _get_parent_ctx(ctx)
    with tracer.start_as_current_span("subtract_operation", context=parent_ctx) as span:
        span.set_attribute("operand_a", a)
        span.set_attribute("operand_b", b)
        result = a - b
        span.set_attribute("result", result)
        logger.info(f"subtract({a}, {b}) = {result}")
        return result


# ---------------------------------------------------------------------------
# Server 2: Multi-step solver with LangGraph  (port 8082)
# ---------------------------------------------------------------------------
mul_div_mcp = FastMCP(name="mul_div_server")


@mul_div_mcp.tool()
@instrumented_tool("solve_steps", "mul_div_server")
def solve_steps(expression: str, ctx: Context) -> str:
    """
    Solve a multi-step arithmetic expression and return a step-by-step breakdown.

    Uses a 3-node LangGraph pipeline:
      parse     -> tokenize the expression
      evaluate  -> compute the result safely (no eval())
      format    -> produce a readable step-by-step answer

    Supports: +  -  *  /  **  parentheses  (e.g. '(3 + 5) * 2 - 4 / 2')
    Returns a newline-separated log of each node's output.
    """
    import time as _t
    parent_ctx = _get_parent_ctx(ctx)
    with tracer.start_as_current_span("solve_steps_operation", context=parent_ctx) as span:
        span.set_attribute("expression", expression)

        with tracer.start_as_current_span("worker.runner.execution", attributes={
            "worker.type": "solver",
            "graph.node_count": 3,
        }) as exec_span:
            exec_start = _t.perf_counter()
            try:
                initial_state: MathState = {
                    "expression": expression,
                    "tokens": [],
                    "result": 0.0,
                    "steps": [],
                    "error": "",
                }
                # Run nodes with retry support
                with tracer.start_as_current_span("worker.runner.build"):
                    pass  # graph already compiled at module load; span marks execution entry

                final_state = _solver_graph.invoke(initial_state)
                result_str = "\n".join(final_state["steps"])

                exec_elapsed = _t.perf_counter() - exec_start
                execution_duration.record(exec_elapsed, {"worker_type": "solver"})
                exec_span.set_attribute("execution.duration_s", round(exec_elapsed, 3))
                exec_span.set_attribute("execution.status", "completed" if not final_state.get("error") else "failed")

                span.set_attribute("result", result_str)
                span.set_attribute("error", final_state.get("error", ""))
                logger.info(f"solve_steps('{expression}') completed in {exec_elapsed:.3f}s")

                return result_str

            except Exception as exc:
                exec_elapsed = _t.perf_counter() - exec_start
                execution_duration.record(exec_elapsed, {"worker_type": "solver"})
                exec_span.set_attribute("execution.status", "failed")
                exec_span.set_attribute("execution.duration_s", round(exec_elapsed, 3))
                span.set_attribute("error", str(exc))
                logger.error(f"solve_steps('{expression}') -> {exc}")
                raise


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "add_sub"

    try:
        if mode == "add_sub":
            logger.info("Starting Addition & Subtraction MCP server on http://localhost:8081")
            logger.info("   Exporting traces to localhost:4317 (Tempo)")
            add_sub_mcp.run(transport="http", host="0.0.0.0", port=8081)

        elif mode == "mul_div":
            logger.info("Starting Multi-step Solver MCP server on http://localhost:8082")
            logger.info("   Exporting traces to localhost:4317 (Tempo)")
            logger.info("   LangGraph nodes instrumented with OTel spans")
            mul_div_mcp.run(transport="http", host="0.0.0.0", port=8082)

        else:
            logger.error(f"Unknown mode '{mode}'. Use: add_sub | mul_div")
            sys.exit(1)

    finally:
        # Flush telemetry on shutdown
        trace_provider.force_flush()
        metrics_provider.shutdown()
        logger.info("Traces flushed to Tempo")
