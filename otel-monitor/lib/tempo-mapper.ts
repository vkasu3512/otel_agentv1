/**
 * Maps raw OTLP / Tempo JSON trace data into the dashboard's Trace & ChildSpan types.
 */
import type { Trace, ChildSpan, SpanStatus, SpanAttributes, LogEntry, Alert } from '@/types/telemetry';

// ── Raw OTLP types from Tempo ────────────────────────────────────────────────

interface OtlpValue { stringValue?: string; intValue?: string; doubleValue?: number; boolValue?: boolean }
interface OtlpAttr  { key: string; value: OtlpValue }

interface OtlpSpan {
  traceId:            string;
  spanId:             string;
  parentSpanId?:      string;
  name:               string;
  kind?:              string;
  startTimeUnixNano:  string;
  endTimeUnixNano:    string;
  status?:            { code?: string };
  attributes?:        OtlpAttr[];
  events?:            unknown[];
}

interface OtlpScopeSpans {
  scope: { name: string };
  spans: OtlpSpan[];
}

interface OtlpBatch {
  resource: { attributes: OtlpAttr[] };
  scopeSpans: OtlpScopeSpans[];
}

export interface RawTraceData {
  traceID:           string;
  startTimeUnixNano: string;
  durationMs:        number;
  batches:           OtlpBatch[];
}

// ── Attribute extraction ─────────────────────────────────────────────────────

function attrValue(attr: OtlpAttr): string | number {
  const v = attr.value;
  if (v.stringValue !== undefined) return v.stringValue;
  if (v.intValue    !== undefined) return Number(v.intValue);
  if (v.doubleValue !== undefined) return v.doubleValue;
  if (v.boolValue   !== undefined) return String(v.boolValue);
  return '';
}

function toAttrs(attrs?: OtlpAttr[]): SpanAttributes {
  const out: SpanAttributes = {};
  if (!attrs) return out;
  for (const a of attrs) {
    out[a.key] = attrValue(a);
  }
  return out;
}

function spanDurMs(span: OtlpSpan): number {
  const start = BigInt(span.startTimeUnixNano);
  const end   = BigInt(span.endTimeUnixNano);
  return Number(end - start) / 1e6;
}

function spanStatus(span: OtlpSpan): SpanStatus {
  const code = span.status?.code;
  if (code === 'STATUS_CODE_ERROR' || code === 'ERROR') return 'ERROR';
  if (code === 'STATUS_CODE_OK' || code === 'OK') return 'OK';
  return 'OK'; // treat UNSET as OK for display
}

// ── Known MCP tool names in the real backend ────────────────────────────────

export const REAL_MCP_TOOLS = [
  'add', 'subtract', 'solve_steps',
] as const;

export const REAL_TOOL_COLORS: Record<string, string> = {
  add:         '#34d399',
  subtract:    '#4f9cf9',
  solve_steps: '#fbbf24',
};

// ── Mapping ─────────────────────────────────────────────────────────────────

export function mapTempoTrace(raw: RawTraceData): Trace | null {
  // Flatten all spans from all batches
  const allSpans: OtlpSpan[] = [];
  for (const batch of raw.batches) {
    for (const ss of batch.scopeSpans) {
      for (const span of ss.spans) {
        allSpans.push(span);
      }
    }
  }
  if (allSpans.length === 0) return null;

  // Find the root span — the one with no parentSpanId or whose parent isn't in the set
  const spanIds = new Set(allSpans.map(s => s.spanId));
  const rootSpan = allSpans.find(s => !s.parentSpanId || !spanIds.has(s.parentSpanId))
    ?? allSpans.reduce((a, b) => spanDurMs(a) > spanDurMs(b) ? a : b);

  const rootStart = BigInt(rootSpan.startTimeUnixNano);
  const rootDur   = spanDurMs(rootSpan);

  // Build children from all non-root spans
  const children: ChildSpan[] = allSpans
    .filter(s => s.spanId !== rootSpan.spanId)
    .map(s => {
      const offset = Number(BigInt(s.startTimeUnixNano) - rootStart) / 1e6;
      return {
        name:   s.name,
        spanId: s.spanId,
        dur:    Math.round(spanDurMs(s)),
        offset: Math.max(0, Math.round(offset)),
        status: spanStatus(s),
        attrs:  toAttrs(s.attributes),
      };
    })
    .sort((a, b) => a.offset - b.offset);

  const rootAttrs = toAttrs(rootSpan.attributes);

  // Extract model name from children's attrs
  const model = children.reduce<string>((m, c) => {
    if (m) return m;
    return String(c.attrs['llm.model_name'] ?? c.attrs['gen_ai.request.model'] ?? '');
  }, '') || String(rootAttrs['gen_ai.request.model'] ?? 'unknown');

  // Compute token totals from generation spans
  let promptTokens = 0;
  let compTokens   = 0;
  for (const s of allSpans) {
    const a = toAttrs(s.attributes);
    promptTokens += Number(a['gen_ai.usage.prompt_tokens'] ?? a['llm.token_count.prompt'] ?? 0);
    compTokens   += Number(a['gen_ai.usage.completion_tokens'] ?? a['llm.token_count.completion'] ?? 0);
  }

  // Enrich root attributes with aggregated data
  rootAttrs['gen_ai.request.model']           = model;
  rootAttrs['gen_ai.usage.prompt_tokens']     = promptTokens;
  rootAttrs['gen_ai.usage.completion_tokens'] = compTokens;
  rootAttrs['agent.tool_count']               = children.filter(c =>
    c.name.includes('_operation') || c.name.startsWith('mcp.') || c.attrs['tool.name']).length;
  rootAttrs['service.name']                   = rootAttrs['service.name'] ?? 'multi-agent-calculator';
  rootAttrs['otel.status_code']               = spanStatus(rootSpan);

  const trace: Trace = {
    traceId:  raw.traceID,
    spanId:   rootSpan.spanId,
    name:     rootSpan.name,
    model,
    status:   spanStatus(rootSpan),
    dur:      Math.round(rootDur),
    ts:       Number(BigInt(raw.startTimeUnixNano) / 1_000_000n),
    attrs:    rootAttrs,
    children,
  };

  return trace;
}

// ── Derive logs from a trace ────────────────────────────────────────────────

let _logCounter = 0;

export function deriveLogsFromTrace(trace: Trace): LogEntry[] {
  const tsStr = new Date(trace.ts).toISOString().slice(11, 23);
  const logs: LogEntry[] = [];

  const id = () => `real-${++_logCounter}`;

  // Main completion log
  logs.push({
    id:      id(),
    ts:      tsStr,
    level:   trace.status === 'ERROR' ? 'ERROR' : trace.dur > 5000 ? 'WARN' : 'INFO',
    traceId: trace.traceId.slice(0, 8),
    msg:     `${trace.name} completed — status=${trace.status} dur=${trace.dur}ms agent=${trace.attrs['lifecycle.final_agent'] ?? 'unknown'}`,
  });

  // Log handoffs
  for (const ch of trace.children) {
    if (ch.name === 'orchestrator.transition') {
      const from = ch.attrs['worker.from_state'] ?? '';
      const to   = ch.attrs['worker.to_state'] ?? '';
      const worker = ch.attrs['worker.type'] ?? '';
      logs.push({
        id: id(), ts: tsStr, level: 'INFO',
        traceId: trace.traceId.slice(0, 8),
        msg: `[Handoff] ${worker}: ${from}→${to}`,
      });
    }

    // Log tool operations
    if (ch.name.includes('_operation')) {
      logs.push({
        id: id(), ts: tsStr, level: ch.status === 'ERROR' ? 'ERROR' : 'INFO',
        traceId: trace.traceId.slice(0, 8),
        msg: `[MCP Tool] ${ch.name} dur=${ch.dur}ms status=${ch.status}`,
      });
    }

    // Log LangGraph nodes
    if (ch.name.startsWith('langgraph_')) {
      logs.push({
        id: id(), ts: tsStr, level: 'INFO',
        traceId: trace.traceId.slice(0, 8),
        msg: `[LangGraph] ${ch.name} dur=${ch.dur}ms status=${ch.attrs['status'] ?? 'ok'}`,
      });
    }

    // Log LLM generations
    if (ch.name === 'generation') {
      logs.push({
        id: id(), ts: tsStr, level: 'INFO',
        traceId: trace.traceId.slice(0, 8),
        msg: `[LLM] ${ch.attrs['llm.model_name'] ?? 'unknown'} dur=${ch.dur}ms`,
      });
    }
  }

  // SLO breach
  if (trace.dur > 5000) {
    logs.push({
      id: id(), ts: tsStr, level: 'WARN',
      traceId: trace.traceId.slice(0, 8),
      msg: `SLO_BREACH: trace_duration=${trace.dur}ms exceeds 5000ms threshold`,
    });
  }

  return logs;
}

// ── Derive alerts from a trace ──────────────────────────────────────────────

let _alertCounter = 0;

export function deriveAlertsFromTrace(trace: Trace): Alert[] {
  const alerts: Alert[] = [];
  const id = () => `alert-${++_alertCounter}`;

  if (trace.dur > 5000) {
    alerts.push({
      id: id(), severity: 'warn',
      title: `High latency: ${trace.name}`,
      desc: `Span duration ${trace.dur}ms breaches 5s SLO`,
      ts: new Date(trace.ts).toLocaleTimeString(),
    });
  }

  if (trace.status === 'ERROR') {
    alerts.push({
      id: id(), severity: 'error',
      title: `Error trace: ${trace.name}`,
      desc: `Trace ${trace.traceId.slice(0, 8)} terminated with ERROR status`,
      ts: new Date(trace.ts).toLocaleTimeString(),
    });
  }

  for (const ch of trace.children) {
    if (ch.status === 'ERROR' && ch.name.includes('_operation')) {
      alerts.push({
        id: id(), severity: 'error',
        title: `Tool error: ${ch.name}`,
        desc: `MCP tool ${ch.name} failed after ${ch.dur}ms`,
        ts: new Date(trace.ts).toLocaleTimeString(),
      });
    }
  }

  return alerts;
}
