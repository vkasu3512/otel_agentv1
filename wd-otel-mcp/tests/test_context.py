from unittest.mock import MagicMock
from wd_otel_mcp.context import extract_parent_context

class TestExtractParentContext:
    def test_returns_none_when_no_traceparent(self):
        ctx = MagicMock()
        ctx.request_context.request.headers = {}
        result = extract_parent_context(ctx)
        assert result is None

    def test_returns_context_when_traceparent_present(self):
        ctx = MagicMock()
        ctx.request_context.request.headers = {
            "traceparent": "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"
        }
        result = extract_parent_context(ctx)
        assert result is not None

    def test_returns_none_on_exception(self):
        ctx = MagicMock()
        type(ctx.request_context.request).headers = property(lambda self: (_ for _ in ()).throw(RuntimeError()))
        result = extract_parent_context(ctx)
        assert result is None
