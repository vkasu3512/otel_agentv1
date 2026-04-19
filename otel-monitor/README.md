# OTel LLM Agent Monitor

A production-grade OpenTelemetry observability dashboard for LLM agents with MCP (Model Context Protocol) tools, built with **Next.js 14**, **React 18**, **TypeScript**, **Tailwind CSS**, and **Chart.js**.

## Features

- **Real-time trace ingestion** — auto-emits OTel-spec traces every 2.2s with configurable error/slow/multi-tool scenarios
- **6 monitoring panels** — Overview KPIs, Trace Explorer, Span Waterfall, MCP Tools, Log Stream, Alerts
- **OpenTelemetry semantic conventions** — `gen_ai.*`, `llm.*`, `mcp.*`, `service.*` attributes on every span
- **Live KPI dashboard** — p50/p95/p99 latency, token throughput, error rate, active spans
- **Span waterfall** — interactive SVG timeline with per-span attribute drill-down
- **MCP tool analytics** — per-tool call count, error rate, avg latency, invocation trend chart
- **Structured log stream** — filterable by level (INFO/WARN/ERROR), searchable, with trace ID correlation
- **Alert feed** — SLO violation detection for latency breaches, error spikes, timeout events
- **Trace simulation** — inject Normal / Slow LLM / Tool Error / Multi-tool chain traces on demand

## Project Structure

```
otel-llm-agent-monitor/
├── app/
│   ├── layout.tsx          # Root layout with TelemetryProvider
│   ├── page.tsx            # Main page with tab routing
│   └── globals.css         # Base styles, fonts, keyframes
├── components/
│   ├── TopBar.tsx          # Header with live stats badges
│   ├── TabBar.tsx          # Tab navigation with alert count
│   ├── ui/
│   │   └── primitives.tsx  # Badge, Card, KpiCard, Button, etc.
│   ├── charts/
│   │   ├── LatencyChart.tsx        # Chart.js bar histogram
│   │   └── McpInvocationChart.tsx  # Chart.js multi-line trend
│   └── panels/
│       ├── OverviewPanel.tsx   # KPIs + histogram + inject controls
│       ├── TracesPanel.tsx     # Trace list + attribute drill-down
│       ├── TimelinePanel.tsx   # SVG waterfall + span inspector
│       ├── McpPanel.tsx        # MCP tool stats cards + chart
│       ├── LogsPanel.tsx       # Log stream with filter/search/pause
│       └── AlertsPanel.tsx     # SLO violation alerts + thresholds
├── lib/
│   ├── telemetry.ts    # Trace/span generation engine, KPI helpers
│   └── store.tsx       # React Context + useReducer state store
├── types/
│   └── telemetry.ts    # TypeScript interfaces for all OTel types
├── tailwind.config.js
├── tsconfig.json
├── next.config.js
└── package.json
```

## Quick Start

### 1. Install dependencies

```bash
npm install
# or
yarn install
# or
pnpm install
```

### 2. Run the development server

```bash
npm run dev
```

Open [http://localhost:3000](http://localhost:3000)

### 3. Build for production

```bash
npm run build
npm start
```

## Connecting a Real OTel Backend

The current implementation uses an in-browser simulation engine (`lib/telemetry.ts`). To connect real OpenTelemetry data:

### Option A — OTel Collector → API Route

1. Add a Next.js API route at `app/api/traces/route.ts` to receive OTLP/HTTP spans
2. Configure your OTel Collector to export to `http://localhost:3000/api/traces`
3. Replace the `generateTrace` simulation with real span ingestion in `lib/store.tsx`

### Option B — Jaeger / Tempo backend

```bash
npm install @opentelemetry/sdk-node @opentelemetry/exporter-jaeger
```

Then query the Jaeger HTTP API from a server component or API route:

```ts
// app/api/traces/route.ts
const res = await fetch('http://jaeger:16686/api/traces?service=llm-agent&limit=20');
const { data } = await res.json();
```

### Option C — Instrument your LLM agent

Use the OTel GenAI semantic conventions:

```ts
import { trace, SpanStatusCode } from '@opentelemetry/api';

const tracer = trace.getTracer('llm-agent');

const span = tracer.startSpan('llm.chat', {
  attributes: {
    'gen_ai.system':                  'anthropic',
    'gen_ai.request.model':           'claude-sonnet-4-20250514',
    'gen_ai.usage.prompt_tokens':     promptTokens,
    'gen_ai.usage.completion_tokens': completionTokens,
  },
});

// ... your LLM call ...

span.setStatus({ code: SpanStatusCode.OK });
span.end();
```

## OTel Semantic Conventions Used

| Attribute | Description |
|---|---|
| `gen_ai.system` | LLM provider (anthropic, openai, google) |
| `gen_ai.request.model` | Model identifier |
| `gen_ai.usage.prompt_tokens` | Input token count |
| `gen_ai.usage.completion_tokens` | Output token count |
| `llm.latency_ms` | Time-to-first-token + generation time |
| `mcp.tool.name` | MCP tool identifier |
| `mcp.tool.input` | JSON-serialised tool input |
| `mcp.tool.output` | JSON-serialised tool output |
| `agent.tool_count` | Number of tool calls in this trace |
| `service.name` | Service identifier |
| `otel.status_code` | OK \| ERROR \| UNSET |

## License

MIT
