"""
MCP Calculator Servers — instrumented via wd-otel-mcp.

Two sub-servers, each in its own process:
    python mcp_server.py add_sub   # → localhost:8081 ; Prometheus :8001
    python mcp_server.py mul_div   # → localhost:8082 ; Prometheus :8002

Shape mirrors `otel_agent/mcp_tool_instrumented.py` but swaps the hand-rolled
`@instrumented_tool` decorator for `@traced_tool` from `wd_otel_mcp`.

The 4 LangGraph KPI metrics (graph_build_time, step_total, execution_duration,
step_retries) are NOT covered by the wd-otel-* packages today, so they are
created locally. TODO: move to a future `wd-otel-langgraph` helper.
"""
from __future__ import annotations

import ast
import logging
import operator as op_module
import re
import sys
import time as _t
from typing import TypedDict

# ── 1. OTel bootstrap — MUST run before importing anything that touches OTel ──
import wd_otel

_MODE = sys.argv[1] if len(sys.argv) > 1 else "add_sub"
_CONFIG = {
    "add_sub": "otel_agent_v2/wd-otel-mcp-addsub.yaml",
    "mul_div": "otel_agent_v2/wd-otel-mcp-muldiv.yaml",
}.get(_MODE)
if _CONFIG is None:
    print(f"Unknown mode '{_MODE}'. Use: add_sub | mul_div", file=sys.stderr)
    sys.exit(1)

wd_otel.init(_CONFIG)

tracer = wd_otel.tracer("otel_agent_v2.mcp_server")
meter = wd_otel.meter("otel_agent_v2.mcp_server")
logger = logging.getLogger(__name__)

# ── 2. LangGraph-specific metrics (not covered by wd-otel yet) ───────────────
# TODO: move to a wd-otel-langgraph helper when that package exists.
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

# ── 3. Imports that rely on OTel being live ──────────────────────────────────
from fastmcp import Context, FastMCP
from langgraph.graph import END, StateGraph
from wd_otel_mcp import traced_tool

# ── 4. LangGraph: safe expression evaluator ──────────────────────────────────
ALLOWED_OPS = {
    ast.Add: op_module.add,
    ast.Sub: op_module.sub,
    ast.Mult: op_module.mul,
    ast.Div: op_module.truediv,
    ast.Pow: op_module.pow,
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
    tree = ast.parse(expr.strip(), mode="eval")
    return _eval_node(tree.body)


# ── 5. LangGraph state + nodes ───────────────────────────────────────────────
class MathState(TypedDict):
    expression: str
    tokens: list
    result: float
    steps: list
    error: str


def parse_node(state: MathState) -> dict:
    with tracer.start_as_current_span("langgraph_parse_node") as span:
        expr = state["expression"]
        try:
            tokens = re.findall(r"\d+\.?\d*|[+\-*/^()]", expr)
            span.set_attribute("expression", expr)
            span.set_attribute("token_count", len(tokens))
            step_total.add(1, {"node": "parse_node", "status": "success"})
            return {"tokens": tokens, "steps": [f"[Parse]    '{expr}'  ->  tokens: {tokens}"]}
        except Exception as e:
            step_total.add(1, {"node": "parse_node", "status": "failure"})
            span.record_exception(e)
            raise


def evaluate_node(state: MathState) -> dict:
    with tracer.start_as_current_span("langgraph_evaluate_node") as span:
        expr = state["expression"]
        steps = state["steps"]
        span.set_attribute("expression", expr)
        try:
            result = _safe_eval(expr)
            span.set_attribute("result", result)
            step_total.add(1, {"node": "evaluate_node", "status": "success"})
            return {"result": result, "error": "", "steps": steps + [f"[Evaluate] '{expr}'  =  {result}"]}
        except Exception as exc:
            span.set_attribute("error", str(exc))
            span.record_exception(exc)
            step_total.add(1, {"node": "evaluate_node", "status": "failure"})
            return {"result": 0.0, "error": str(exc), "steps": steps + [f"[Evaluate] ERROR: {exc}"]}


def format_node(state: MathState) -> dict:
    with tracer.start_as_current_span("langgraph_format_node") as span:
        steps = state["steps"]
        try:
            if state["error"]:
                summary = f"Could not solve '{state['expression']}': {state['error']}"
                step_total.add(1, {"node": "format_node", "status": "failure"})
            else:
                result = state["result"]
                result_str = str(int(result)) if result == int(result) else str(result)
                summary = f"[Format]   Result = {result_str}"
                step_total.add(1, {"node": "format_node", "status": "success"})
            span.set_attribute("expression", state["expression"])
            return {"steps": steps + [summary]}
        except Exception as e:
            step_total.add(1, {"node": "format_node", "status": "failure"})
            span.record_exception(e)
            raise


# Compile the graph once at import — record build duration
_build_start = _t.perf_counter()
_solver_graph = (
    StateGraph(MathState)
    .add_node("parse", parse_node)
    .add_node("evaluate", evaluate_node)
    .add_node("format", format_node)
    .set_entry_point("parse")
    .add_edge("parse", "evaluate")
    .add_edge("evaluate", "format")
    .add_edge("format", END)
    .compile()
)
graph_build_time.record(_t.perf_counter() - _build_start, {"worker_type": "solver"})


# ── 6. Server 1: Addition & Subtraction  (port 8081) ─────────────────────────
add_sub_mcp = FastMCP(name="add_sub_server")


@add_sub_mcp.tool()
@traced_tool("add", server="add_sub_server")
def add(a: float, b: float, ctx: Context) -> float:
    """Add two numbers together."""
    result = a + b
    logger.info(f"add({a}, {b}) = {result}")
    return result


@add_sub_mcp.tool()
@traced_tool("subtract", server="add_sub_server")
def subtract(a: float, b: float, ctx: Context) -> float:
    """Subtract b from a."""
    result = a - b
    logger.info(f"subtract({a}, {b}) = {result}")
    return result


# ── 7. Server 2: Multi-step solver with LangGraph  (port 8082) ───────────────
mul_div_mcp = FastMCP(name="mul_div_server")


@mul_div_mcp.tool()
@traced_tool("solve_steps", server="mul_div_server", timeout_s=30.0)
def solve_steps(expression: str, ctx: Context) -> str:
    """Solve a multi-step arithmetic expression with a 3-node LangGraph pipeline."""
    exec_start = _t.perf_counter()
    initial_state: MathState = {
        "expression": expression,
        "tokens": [],
        "result": 0.0,
        "steps": [],
        "error": "",
    }
    try:
        final_state = _solver_graph.invoke(initial_state)
        result_str = "\n".join(final_state["steps"])
        execution_duration.record(_t.perf_counter() - exec_start, {"worker_type": "solver"})
        logger.info(f"solve_steps('{expression}') -> ok")
        return result_str
    except Exception as exc:
        execution_duration.record(_t.perf_counter() - exec_start, {"worker_type": "solver"})
        logger.error(f"solve_steps('{expression}') -> {exc}")
        raise


# ── 8. Entry point ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    try:
        if _MODE == "add_sub":
            logger.info("Starting add_sub MCP server on http://localhost:8081 (metrics :8001)")
            add_sub_mcp.run(transport="http", host="0.0.0.0", port=8081)
        elif _MODE == "mul_div":
            logger.info("Starting mul_div MCP server on http://localhost:8082 (metrics :8002)")
            mul_div_mcp.run(transport="http", host="0.0.0.0", port=8082)
    finally:
        wd_otel.shutdown()
