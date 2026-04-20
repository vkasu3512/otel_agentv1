import type { KpiProxyEntry, KpiProxyResponse } from '@/types/telemetry';

/**
 * Client-side helper that fetches /api/kpi and normalises the response
 * into `{ data, error }`. Never throws — proxy or network failures are
 * reported via the `error` field.
 */
export async function fetchAllKpis(): Promise<KpiProxyResponse> {
  try {
    const res = await fetch('/api/kpi', { cache: 'no-store' });
    const body = await res.json();
    if (!res.ok) {
      const msg = typeof body?.error === 'string' ? body.error : `HTTP ${res.status}`;
      return { data: null, error: msg };
    }
    // body IS the kpi_proxy JSON directly (Record<string, KpiProxyEntry>).
    return { data: body as Record<string, KpiProxyEntry>, error: null };
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    return { data: null, error: msg };
  }
}

/**
 * Unit hint shown under scalar values in KpiProxyCard.
 * Keys are kpi_proxy key names (e.g. `"mcp.duration_p95"`).
 * Missing keys → no unit shown.
 */
export const KPI_UNIT_HINTS: Record<string, string> = {
  'langgraph.build_duration_avg':     'seconds',
  'langgraph.execution_duration_p95': 'seconds',
  'mcp.duration_p95':                 'seconds',
  'orchestrator.sync_failures_1h':    'errors (1h)',
};

/**
 * Section grouping used by KpiPanel. Order determines render order.
 * KPI keys not listed here are rendered in a final "Other" section — but
 * in practice kpi_proxy only emits the 11 keys below.
 */
export const KPI_SECTIONS: Array<{
  title: string;
  cols:  number;
  keys:  string[];
}> = [
  {
    title: 'DW Orchestrator',
    cols:  2,
    keys: [
      'orchestrator.active_workers',
      'orchestrator.state_transitions_rate',
      'orchestrator.errors_total',
      'orchestrator.sync_failures_1h',
    ],
  },
  {
    title: 'Worker Runner / LangGraph',
    cols:  2,
    keys: [
      'langgraph.build_duration_avg',
      'langgraph.step_rate',
      'langgraph.execution_duration_p95',
      'langgraph.step_retries_rate',
    ],
  },
  {
    title: 'MCP Tool Server',
    cols:  3,
    keys: [
      'mcp.invocations_rate',
      'mcp.duration_p95',
      'mcp.timeouts_rate',
    ],
  },
];
