"""@traced_tool decorator — auto span, metrics, and context propagation for MCP tools."""
from __future__ import annotations

import contextvars
import functools
import inspect
import logging
import threading
import time
from typing import Any, Callable, Sequence

from opentelemetry import trace

from wd_otel.errors import WdOtelConfigError
from wd_otel import helpers
from wd_otel_mcp.context import extract_parent_context

logger = logging.getLogger("wd_otel_mcp.decorator")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _find_ctx_param(fn: Callable) -> str | None:
    """Return the parameter name annotated with fastmcp.Context, or None.

    Checks annotation by name only (avoids hard import of fastmcp.Context
    at module level so the decorator can be imported even without fastmcp
    available at type-check time).
    """
    hints = {}
    try:
        hints = fn.__annotations__
    except AttributeError:
        pass

    for param_name, ann in hints.items():
        if param_name == "return":
            continue
        # Accept both the class itself and forward-reference strings
        if isinstance(ann, str):
            if ann == "Context" or ann.endswith(".Context"):
                return param_name
        elif hasattr(ann, "__name__") and ann.__name__ == "Context":
            return param_name
        elif hasattr(ann, "__qualname__") and "Context" in ann.__qualname__:
            return param_name
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def current_span() -> trace.Span:
    """Return the currently active OTel span.

    Thin wrapper around ``opentelemetry.trace.get_current_span()``.
    """
    return trace.get_current_span()


def traced_tool(
    tool_name: str,
    *,
    server: str,
    timeout_s: float = 10.0,
    capture_args: Sequence[str] | None = None,
    extra_attributes: dict[str, Any] | None = None,
) -> Callable:
    """Decorator that adds OTel tracing and metrics to a FastMCP tool function.

    At decoration time the function signature is inspected to locate the
    parameter annotated with ``fastmcp.Context``.  A ``WdOtelConfigError``
    is raised immediately if no such parameter is found.

    At call time the decorator:

    1. Extracts W3C trace context from the FastMCP ``ctx`` argument.
    2. Creates a span named ``{tool_name}_operation`` with the parent context.
    3. Records ``input.*`` attributes for all non-ctx arguments (or only those
       listed in *capture_args* when supplied).
    4. Sets any *extra_attributes* on the span.
    5. Executes the wrapped function in a worker thread via
       ``contextvars.copy_context()`` so that Starlette's request ContextVar
       and the OTel span context are both available inside the thread.
    6. Records the ``result`` attribute from the return value.
    7. In the ``finally`` block records ``_tool_invocations`` and
       ``_tool_duration`` metrics; ``_tool_timeouts`` on timeout.
    8. On exception records the exception on the span and re-raises.

    Args:
        tool_name:        MCP tool name (used for span name and metric labels).
        server:           Server name (used as metric label).
        timeout_s:        Thread-join timeout in seconds (default 10).
        capture_args:     If given, only record these argument names as
                          ``input.*`` span attributes.
        extra_attributes: Extra key/value pairs to set on the span.

    Raises:
        WdOtelConfigError: If the decorated function has no parameter
                           annotated with ``fastmcp.Context``.
    """
    def decorator(fn: Callable) -> Callable:
        # ── Decoration-time: find the Context parameter ──────────────────────
        ctx_param = _find_ctx_param(fn)
        if ctx_param is None:
            raise WdOtelConfigError(
                f"@traced_tool: function '{fn.__name__}' has no parameter "
                f"annotated with fastmcp.Context. "
                f"Add 'ctx: Context' to the function signature.",
                hint="Import fastmcp.Context and annotate the ctx parameter.",
            )

        sig = inspect.signature(fn)

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            # ── Call-time: bind args ─────────────────────────────────────────
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()
            arguments = bound.arguments  # ordered dict of param_name -> value

            ctx_value = arguments.get(ctx_param)

            # ── Extract parent context ───────────────────────────────────────
            parent_ctx = extract_parent_context(ctx_value) if ctx_value is not None else None

            tracer = helpers._get_tracer()
            span_name = f"{tool_name}_operation"

            # ── Determine input attributes ───────────────────────────────────
            input_attrs: dict[str, str] = {}
            for param_name, value in arguments.items():
                if param_name == ctx_param:
                    continue
                if capture_args is not None and param_name not in capture_args:
                    continue
                input_attrs[f"input.{param_name}"] = str(value)

            start = time.perf_counter()
            status = "success"

            # Use context manager so we can set attributes and record exceptions
            ctx_token = None
            span_cm = tracer.start_as_current_span(
                span_name,
                context=parent_ctx,
            )

            with span_cm as span:
                # Set input attributes
                for attr_key, attr_val in input_attrs.items():
                    span.set_attribute(attr_key, attr_val)

                # Set extra attributes
                if extra_attributes:
                    for attr_key, attr_val in extra_attributes.items():
                        span.set_attribute(attr_key, attr_val)

                try:
                    # ── Run in worker thread (copies all contextvars) ────────
                    cv_ctx = contextvars.copy_context()
                    result_holder: list[Any] = [None]
                    exc_holder: list[BaseException | None] = [None]

                    def target():
                        try:
                            result_holder[0] = cv_ctx.run(fn, *args, **kwargs)
                        except Exception as exc:
                            exc_holder[0] = exc

                    t = threading.Thread(target=target, daemon=True)
                    t.start()
                    t.join(timeout=timeout_s)

                    if t.is_alive():
                        status = "timeout"
                        helpers._tool_timeouts.add(
                            1, {"tool": tool_name, "server": server}
                        )
                        raise TimeoutError(
                            f"{tool_name} exceeded {timeout_s}s timeout"
                        )

                    if exc_holder[0] is not None:
                        raise exc_holder[0]

                    result = result_holder[0]
                    span.set_attribute("result", str(result))
                    return result

                except TimeoutError:
                    status = "timeout"
                    span.record_exception(TimeoutError(f"{tool_name} timed out"))
                    raise
                except Exception as exc:
                    status = "error"
                    span.record_exception(exc)
                    raise
                finally:
                    elapsed = time.perf_counter() - start
                    helpers._tool_invocations.add(
                        1,
                        {"tool": tool_name, "server": server, "status": status},
                    )
                    helpers._tool_duration.record(
                        elapsed,
                        {"tool": tool_name, "server": server},
                    )

        return wrapper

    return decorator
