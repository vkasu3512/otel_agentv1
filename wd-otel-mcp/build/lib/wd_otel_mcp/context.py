"""Extract W3C trace context from FastMCP request headers."""
from __future__ import annotations
import logging
from typing import Any
from opentelemetry.propagate import extract as otel_extract

logger = logging.getLogger("wd_otel_mcp.context")

def extract_parent_context(ctx: Any) -> Any:
    """Extract W3C trace context from a FastMCP Context's request headers.
    Returns an OTel context if traceparent is present, None otherwise."""
    try:
        headers = dict(ctx.request_context.request.headers)
        tp = headers.get("traceparent")
        if not tp:
            logger.warning("[wd-otel] traceparent header missing — span will be a root")
            return None
        parent_ctx = otel_extract(headers)
        logger.debug(f"[wd-otel] traceparent={tp} -> linked")
        return parent_ctx
    except Exception as exc:
        logger.warning(f"[wd-otel] Failed to extract parent context: {exc}")
        return None
