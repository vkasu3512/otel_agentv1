import type {
  Trace, ChildSpan, LogEntry, Alert, KpiState,
  SpanStatus, TraceType, McpToolStats,
} from '@/types/telemetry';

// ── Constants ───────────────────────────────────────────────────────────────

export const MCP_TOOLS = [
  'web_search', 'file_read', 'code_exec',
  'db_query',   'send_email', 'calendar_get',
] as const;

export const TOOL_COLORS: Record<string, string> = {
  web_search:   '#4f9cf9',
  file_read:    '#34d399',
  code_exec:    '#fbbf24',
  db_query:     '#f87171',
  send_email:   '#fb7185',
  calendar_get: '#a78bfa',
};

export const LLM_MODELS = [
  'claude-sonnet-4-20250514',
  'gpt-4o-2024-11-20',
  'gemini-2.0-flash',
] as const;

// ── ID generators ───────────────────────────────────────────────────────────

export function genTraceId(): string {
  return Array.from({ length: 16 }, () =>
    Math.floor(Math.random() * 16).toString(16)
  ).join('');
}

export function genSpanId(): string {
  return Array.from({ length: 8 }, () =>
    Math.floor(Math.random() * 16).toString(16)
  ).join('');
}

export function genId(): string {
  return Math.random().toString(36).slice(2, 10);
}

// ── Initial KPI state ───────────────────────────────────────────────────────

export function createInitialKpi(): KpiState {
  const mcpCalls: Record<string, McpToolStats> = {};
  // Initialize with mock tools for simulated mode
  MCP_TOOLS.forEach(t => {
    mcpCalls[t] = { calls: 0, errors: 0, totalMs: 0, history: [] };
  });
  return {
    traces: 0, promptTokens: 0, compTokens: 0,
    errors: 0, activeSpans: 0, latencies: [], mcpCalls,
  };
}

// ── Trace generator ─────────────────────────────────────────────────────────

export function generateTrace(
  type: TraceType,
  kpi: KpiState,
): { trace: Trace; logs: LogEntry[]; alerts: Alert[]; updatedKpi: KpiState } {
  const newKpi = structuredClone(kpi);

  const traceId = genTraceId();
  const now     = Date.now();
  const model   = LLM_MODELS[Math.floor(Math.random() * LLM_MODELS.length)];

  const isError = type === 'error';
  const isSlow  = type === 'slow';
  const isMulti = type === 'multi';

  const agentDur  = isError ? 220 : isSlow ? 8800 : isMulti ? 5400 : 800 + Math.random() * 1400;
  const llmDur    = isSlow  ? 7400 : isError ? 190 : 600 + Math.random() * 900;
  const promptTok = 200 + Math.floor(Math.random() * 800);
  const compTok   = isError ? 0 : 150 + Math.floor(Math.random() * 400);
  const toolCount = isMulti ? 3 : Math.random() > 0.4 ? 1 : 0;

  const children: ChildSpan[] = [];

  // LLM span
  children.push({
    name:   'llm.chat',
    spanId: genSpanId(),
    dur:    Math.round(llmDur),
    offset: 40,
    status: isError ? 'ERROR' : 'OK',
    attrs: {
      'gen_ai.request.model':           model,
      'gen_ai.usage.prompt_tokens':     promptTok,
      'gen_ai.usage.completion_tokens': compTok,
      'http.status_code':               isError ? 500 : 200,
      'llm.latency_ms':                 Math.round(llmDur),
    },
  });

  // Tool spans
  for (let i = 0; i < toolCount; i++) {
    const toolName = MCP_TOOLS[Math.floor(Math.random() * MCP_TOOLS.length)];
    const toolDur  = 80 + Math.floor(Math.random() * 300);
    const toolErr  = isError && i === 0;
    const tStatus: SpanStatus = toolErr ? 'ERROR' : 'OK';

    children.push({
      name:   `mcp.${toolName}`,
      spanId: genSpanId(),
      dur:    toolDur,
      offset: 120 + i * 340,
      status: tStatus,
      attrs: {
        'mcp.tool.name':   toolName,
        'mcp.tool.input':  `{"query":"sample_request_${i}"}`,
        'mcp.tool.output': toolErr ? '{"error":"timeout","code":504}' : '{"result":"ok","items":3}',
        'http.status_code': toolErr ? 504 : 200,
      },
    });

    newKpi.mcpCalls[toolName].calls++;
    newKpi.mcpCalls[toolName].totalMs += toolDur;
    if (toolErr) newKpi.mcpCalls[toolName].errors++;
  }

  const status: SpanStatus = isError ? 'ERROR' : 'OK';

  const trace: Trace = {
    traceId,
    spanId: genSpanId(),
    name:   isMulti ? 'agent.multi_tool_chain' : `agent.${isError ? 'error_run' : 'run'}`,
    model,
    status,
    dur:    Math.round(agentDur),
    ts:     now,
    attrs: {
      'gen_ai.system':                  model.includes('gpt') ? 'openai' : model.includes('gemini') ? 'google' : 'anthropic',
      'gen_ai.request.model':           model,
      'gen_ai.usage.prompt_tokens':     promptTok,
      'gen_ai.usage.completion_tokens': compTok,
      'llm.latency_ms':                 Math.round(llmDur),
      'agent.tool_count':               toolCount,
      'service.name':                   'llm-agent-service',
      'otel.status_code':               status,
    },
    children,
  };

  // Update KPIs
  newKpi.traces++;
  newKpi.promptTokens  += promptTok;
  newKpi.compTokens    += compTok;
  if (isError) newKpi.errors++;
  newKpi.latencies = [...newKpi.latencies.slice(-49), Math.round(agentDur)];
  newKpi.activeSpans = Math.max(0, Math.floor(Math.random() * 4));

  // Update MCP history for chart
  MCP_TOOLS.forEach(t => {
    newKpi.mcpCalls[t].history = [
      ...newKpi.mcpCalls[t].history.slice(-29),
      newKpi.mcpCalls[t].calls,
    ];
  });

  // Logs
  const tsStr = new Date().toISOString().slice(11, 23);
  const level = isError ? 'ERROR' : isSlow ? 'WARN' : 'INFO';
  const logs: LogEntry[] = [
    {
      id:      genId(),
      ts:      tsStr,
      level,
      traceId: traceId.slice(0, 8),
      msg:     `${trace.name} completed — status=${status} dur=${Math.round(agentDur)}ms model=${model}`,
    },
  ];

  if (isError) {
    logs.push({
      id: genId(), ts: tsStr, level: 'ERROR', traceId: traceId.slice(0, 8),
      msg: `tool_error: ${children.find(c => c.status === 'ERROR')?.attrs['mcp.tool.name'] ?? 'unknown'} returned HTTP 504 (timeout)`,
    });
  }
  if (isSlow) {
    logs.push({
      id: genId(), ts: tsStr, level: 'WARN', traceId: traceId.slice(0, 8),
      msg: `SLO_BREACH: llm_latency=${Math.round(llmDur)}ms exceeds p99_threshold=3000ms`,
    });
  }

  // Alerts
  const alerts: Alert[] = [];
  if (agentDur > 5000) {
    alerts.push({
      id: genId(), severity: 'warn',
      title: `High latency: ${trace.name}`,
      desc:  `Span duration ${Math.round(agentDur)}ms breaches 5s SLO`,
      ts:    new Date().toLocaleTimeString(),
    });
  }
  if (isError) {
    alerts.push({
      id: genId(), severity: 'error',
      title: `Error trace: ${trace.name}`,
      desc:  `Trace ${traceId.slice(0, 8)} terminated with ERROR status`,
      ts:    new Date().toLocaleTimeString(),
    });
  }
  const errRate = newKpi.errors / Math.max(1, newKpi.traces);
  if (errRate > 0.15 && Math.random() > 0.72) {
    alerts.push({
      id: genId(), severity: 'warn',
      title: 'Error rate exceeds 15%',
      desc:  `Current error rate: ${(errRate * 100).toFixed(1)}% — SLO threshold breached`,
      ts:    new Date().toLocaleTimeString(),
    });
  }

  return { trace, logs, alerts, updatedKpi: newKpi };
}

// ── Percentile helpers ──────────────────────────────────────────────────────

export function percentile(sorted: number[], p: number): number {
  if (!sorted.length) return 0;
  const idx = Math.floor(sorted.length * p);
  return sorted[Math.min(idx, sorted.length - 1)];
}

export function getLatencyPercentiles(latencies: number[]) {
  const sorted = [...latencies].sort((a, b) => a - b);
  return {
    p50: percentile(sorted, 0.5),
    p95: percentile(sorted, 0.95),
    p99: percentile(sorted, 0.99),
  };
}

export function tokenThroughput(kpi: KpiState): number {
  return Math.round((kpi.promptTokens + kpi.compTokens) / Math.max(1, kpi.traces / 10));
}
