// ── OTel Semantic Convention Types ─────────────────────────────────────────

export type SpanStatus = 'OK' | 'ERROR' | 'UNSET';
export type TraceType  = 'normal' | 'slow' | 'error' | 'multi';
export type LogLevel   = 'DEBUG' | 'INFO' | 'WARN' | 'ERROR';
export type AlertSeverity = 'info' | 'warn' | 'error';

export interface SpanAttributes {
  'gen_ai.system'?:                   string;
  'gen_ai.request.model'?:            string;
  'gen_ai.usage.prompt_tokens'?:      number;
  'gen_ai.usage.completion_tokens'?:  number;
  'llm.latency_ms'?:                  number;
  'agent.tool_count'?:                number;
  'service.name'?:                    string;
  'otel.status_code'?:                SpanStatus;
  'http.status_code'?:                number;
  'mcp.tool.name'?:                   string;
  'mcp.tool.input'?:                  string;
  'mcp.tool.output'?:                 string;
  [key: string]: string | number | undefined;
}

export interface ChildSpan {
  name:    string;
  spanId:  string;
  dur:     number;
  offset:  number;
  status:  SpanStatus;
  attrs:   SpanAttributes;
}

export interface Trace {
  traceId:  string;
  spanId:   string;
  name:     string;
  model:    string;
  status:   SpanStatus;
  dur:      number;
  ts:       number;
  attrs:    SpanAttributes;
  children: ChildSpan[];
}

export interface LogEntry {
  id:      string;
  ts:      string;
  level:   LogLevel;
  msg:     string;
  traceId: string;
}

export interface Alert {
  id:       string;
  severity: AlertSeverity;
  title:    string;
  desc:     string;
  ts:       string;
}

export interface McpToolStats {
  calls:   number;
  errors:  number;
  totalMs: number;
  history: number[];
}

export interface KpiState {
  traces:        number;
  promptTokens:  number;
  compTokens:    number;
  errors:        number;
  activeSpans:   number;
  latencies:     number[];
  mcpCalls:      Record<string, McpToolStats>;
}

// ── KPI proxy (snapshot from otel_agent_v2/kpi_proxy.py) ───────────────────

export type KpiProxyArea = 'orchestrator' | 'langgraph' | 'mcp';

export interface KpiProxyResultRow {
  metric: Record<string, string>;   // e.g. {worker_type: "AddSubAgent"}; {} for scalars
  value:  [number, string];          // [unix_ts, stringified_float]
}

export interface KpiProxyEntry {
  area:    KpiProxyArea;
  title:   string;
  query:   string;
  result?: KpiProxyResultRow[];
  error?:  string;
}

/**
 * Shape returned by /api/kpi. `data` is the raw kpi_proxy response
 * (keyed by KPI name). `error` is set when the proxy itself is unreachable.
 */
export interface KpiProxyResponse {
  data:  Record<string, KpiProxyEntry> | null;
  error: string | null;
}
