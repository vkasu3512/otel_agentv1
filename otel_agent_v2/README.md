# otel_agent_v2

Working rewrite of `otel_agent/` using the `wd-otel-core`, `wd-otel-mcp`,
and `wd-otel-orchestrator` packages. Not a Python package — just working
code to study and modify.

See `docs/superpowers/specs/2026-04-19-otel-agent-v2-design.md` for the
full rationale.

## File map

| File | Role | Notable pattern |
|---|---|---|
| `mcp_server.py` | MCP tool servers (add_sub \| mul_div) | `@traced_tool(...)` replaces manual span/thread plumbing |
| `orchestrator.py` | Agent definitions + `CalculatorOrchestrator(TracedOrchestrator)` | Subclass a base, override `sync_status`, done |
| `api.py` | FastAPI transport | No OTel, no agent defs — just imports `orchestrator` |
| `cli.py` | CLI smoke runner | Same orchestrator, different entry point |
| `kpi_proxy.py` | Prometheus → REST proxy for the 11 KPIs | Queries updated for `wd_otel_*` metric names |
| `wd-otel-*.yaml` | One config per process (distinct Prom ports) | `wd_otel.init("<yaml>")` reads this |

## Prerequisites

- Python 3.10+
- `API_KEY` env var (Groq key, or swap `LLM_BASE_URL` to your Bedrock/etc. proxy)
- `pip install -e wd-otel-core wd-otel-mcp wd-otel-orchestrator`
- `pip install -r otel_agent_v2/requirements.txt`
- Optional: Tempo on `localhost:4317`, Loki on `localhost:3100`, Prometheus
  scraping ports 8000/8001/8002. See `Grafana_stackv1/` for a ready stack.

## Run

Four terminals from the repo root.

```bash
# Terminal 1 — add/subtract MCP server
python otel_agent_v2/mcp_server.py add_sub

# Terminal 2 — multi-step solver MCP server
python otel_agent_v2/mcp_server.py mul_div

# Terminal 3 — FastAPI
uvicorn otel_agent_v2.api:app --host 0.0.0.0 --port 8080

# Terminal 4 — fire a request
curl -X POST http://localhost:8080/run \
  -H "Content-Type: application/json" \
  -d '{"question":"What is (3+5)*2 - 4/2?"}'
```

CLI smoke test (no FastAPI):
```bash
python otel_agent_v2/cli.py "What is 100 - 37?"
```

KPI proxy (after traffic has flowed):
```bash
python otel_agent_v2/kpi_proxy.py
curl http://localhost:8900/kpi/all
```

## Port map

| Port | Purpose |
|---|---|
| 8000 | Prometheus scrape — orchestrator API |
| 8001 | Prometheus scrape — add_sub MCP server |
| 8002 | Prometheus scrape — mul_div MCP server |
| 8080 | FastAPI |
| 8081 | add_sub MCP HTTP |
| 8082 | mul_div MCP HTTP |
| 8900 | KPI proxy |
| 4317 | OTLP gRPC → Tempo |
| 3100 | Loki HTTP |

## Provider notes

The orchestrator talks to any OpenAI-compatible endpoint. Default is Groq:

```python
# orchestrator.py
_client = AsyncOpenAI(
    api_key=os.environ["API_KEY"],
    base_url=os.environ.get("LLM_BASE_URL", "https://api.groq.com/openai/v1/"),
)
```

To route to an AWS Bedrock proxy that mimics the Chat Completions API, set:

```
LLM_BASE_URL=https://your-bedrock-proxy.example.com/v1
LLM_MODEL=anthropic.claude-3-5-sonnet-20241022-v2:0
```

No OTel changes needed — spans and metrics are provider-agnostic.

## 11 KPIs — where they come from now

| KPI | Source in new code |
|---|---|
| `orchestrator.active_workers` | `TransitionTracker` (auto) |
| `orchestrator.state_transitions_rate` | `TransitionTracker` (auto on handoff / completion / error) |
| `orchestrator.errors_total` | `TracedOrchestrator.execute` exception path (auto) |
| `orchestrator.sync_failures_1h` | `TracedOrchestrator.execute` sync phase (auto when `sync_status` raises) |
| `mcp.invocations_rate` | `@traced_tool` finally block (auto) |
| `mcp.duration_p95` | `@traced_tool` finally block (auto) |
| `mcp.timeouts_rate` | `@traced_tool` on thread-join timeout (auto) |
| `langgraph.*` (×4) | `mcp_server.py` — **still custom**, candidate for future helper |

## Known limitations

- **Concurrent requests on `POST /run` can cross-contaminate trace IDs.**
  `TracedOrchestrator` stores the active OTel context in a module-level
  variable so the httpx monkey-patch can read it from an MCP background
  task. If Request B overwrites that variable before Request A's MCP call
  fires, A's tool spans appear under B's trace.

  Safe for the demo / sequential CLI flow. Not safe for concurrent
  production traffic. Full analysis and candidate fixes live in
  `wd-otel-orchestrator/wd_otel_orchestrator/base.py`.
