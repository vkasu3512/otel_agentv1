'use client';

import React, {
  createContext, useContext, useReducer, useCallback, useRef,
} from 'react';
import type { Trace, LogEntry, Alert, KpiState, TraceType, McpToolStats } from '@/types/telemetry';
import {
  generateTrace, createInitialKpi, MCP_TOOLS,
} from '@/lib/telemetry';
import {
  mapTempoTrace, deriveLogsFromTrace, deriveAlertsFromTrace,
  REAL_MCP_TOOLS, type RawTraceData,
} from '@/lib/tempo-mapper';

// ── State & Actions ─────────────────────────────────────────────────────────

interface TelemetryState {
  traces:  Trace[];
  logs:    LogEntry[];
  alerts:  Alert[];
  kpi:     KpiState;
  mode:    'real' | 'simulated';
}

type Action =
  | { type: 'INJECT_TRACE'; traceType: TraceType }
  | { type: 'SET_REAL_TRACES'; traces: Trace[]; logs: LogEntry[]; alerts: Alert[] }
  | { type: 'CLEAR_ALERTS' }
  | { type: 'SET_MODE'; mode: 'real' | 'simulated' };

function buildKpiFromTraces(traces: Trace[]): KpiState {
  const mcpCalls: Record<string, McpToolStats> = {};
  // Include both simulated and real MCP tools
  const allTools = [...MCP_TOOLS, ...REAL_MCP_TOOLS];
  const seen = new Set<string>();
  for (const t of allTools) {
    if (seen.has(t)) continue;
    seen.add(t);
    mcpCalls[t] = { calls: 0, errors: 0, totalMs: 0, history: [] };
  }

  let errors = 0;
  let promptTokens = 0;
  let compTokens = 0;
  const latencies: number[] = [];

  for (const trace of traces) {
    latencies.push(trace.dur);
    if (trace.status === 'ERROR') errors++;
    promptTokens += Number(trace.attrs['gen_ai.usage.prompt_tokens'] ?? 0);
    compTokens   += Number(trace.attrs['gen_ai.usage.completion_tokens'] ?? 0);

    for (const ch of trace.children) {
      // Match tool spans by name pattern
      let toolName = '';
      if (ch.name === 'add_operation')      toolName = 'add';
      else if (ch.name === 'subtract_operation') toolName = 'subtract';
      else if (ch.name === 'solve_steps_operation') toolName = 'solve_steps';
      else if (ch.name.startsWith('mcp.'))  toolName = ch.name.replace('mcp.', '');
      else if (ch.attrs['mcp.tool.name'])   toolName = String(ch.attrs['mcp.tool.name']);
      else if (ch.attrs['tool.name'])        toolName = String(ch.attrs['tool.name']);

      if (toolName && mcpCalls[toolName]) {
        mcpCalls[toolName].calls++;
        mcpCalls[toolName].totalMs += ch.dur;
        if (ch.status === 'ERROR') mcpCalls[toolName].errors++;
      }
    }
  }

  // Build history snapshots
  for (const t of Object.keys(mcpCalls)) {
    mcpCalls[t].history = [mcpCalls[t].calls];
  }

  return {
    traces: traces.length,
    promptTokens,
    compTokens,
    errors,
    activeSpans: 0,
    latencies: latencies.slice(-50),
    mcpCalls,
  };
}

function reducer(state: TelemetryState, action: Action): TelemetryState {
  switch (action.type) {
    case 'INJECT_TRACE': {
      const { trace, logs, alerts, updatedKpi } = generateTrace(action.traceType, state.kpi);
      return {
        ...state,
        traces:  [trace, ...state.traces].slice(0, 100),
        logs:    [...logs, ...state.logs].slice(0, 300),
        alerts:  [...alerts, ...state.alerts].slice(0, 30),
        kpi:     updatedKpi,
      };
    }
    case 'SET_REAL_TRACES': {
      const allTraces = [...action.traces, ...state.traces.filter(
        t => !action.traces.find(rt => rt.traceId === t.traceId)
      )].slice(0, 100);
      const kpi = buildKpiFromTraces(allTraces);
      return {
        ...state,
        traces:  allTraces,
        logs:    [...action.logs, ...state.logs].slice(0, 300),
        alerts:  [...action.alerts, ...state.alerts].slice(0, 30),
        kpi,
      };
    }
    case 'SET_MODE':
      return { ...state, mode: action.mode };
    case 'CLEAR_ALERTS':
      return { ...state, alerts: [] };
    default:
      return state;
  }
}

function buildInitialState(): TelemetryState {
  return {
    traces: [], logs: [], alerts: [], kpi: createInitialKpi(), mode: 'real',
  };
}

// ── Context ─────────────────────────────────────────────────────────────────

interface TelemetryContextValue {
  state:       TelemetryState;
  injectTrace: (type: TraceType) => void;
  clearAlerts: () => void;
  setMode:     (mode: 'real' | 'simulated') => void;
}

const TelemetryContext = createContext<TelemetryContextValue | null>(null);

async function fetchRealTraces(): Promise<{ traces: Trace[]; logs: LogEntry[]; alerts: Alert[] }> {
  try {
    const res = await fetch('/api/traces', { cache: 'no-store' });
    if (!res.ok) return { traces: [], logs: [], alerts: [] };
    const data = await res.json() as { traces: RawTraceData[] };
    if (!data.traces?.length) return { traces: [], logs: [], alerts: [] };

    const traces: Trace[] = [];
    const logs: LogEntry[] = [];
    const alerts: Alert[] = [];

    for (const raw of data.traces) {
      const trace = mapTempoTrace(raw);
      if (trace) {
        traces.push(trace);
        logs.push(...deriveLogsFromTrace(trace));
        alerts.push(...deriveAlertsFromTrace(trace));
      }
    }

    return { traces, logs, alerts };
  } catch {
    return { traces: [], logs: [], alerts: [] };
  }
}

export function TelemetryProvider({ children }: { children: React.ReactNode }) {
  const [state, dispatch] = useReducer(reducer, undefined, buildInitialState);

  const injectTrace = useCallback((type: TraceType) => {
    dispatch({ type: 'INJECT_TRACE', traceType: type });
  }, []);

  const clearAlerts = useCallback(() => {
    dispatch({ type: 'CLEAR_ALERTS' });
  }, []);

  const setMode = useCallback((mode: 'real' | 'simulated') => {
    dispatch({ type: 'SET_MODE', mode });
  }, []);

  const stateRef = useRef(state);
  stateRef.current = state;

  const seenTraceIds = useRef(new Set<string>());

  // Poll real traces from Tempo every 4 seconds
  React.useEffect(() => {
    // Initial fetch immediately
    fetchRealTraces().then(({ traces, logs, alerts }) => {
      if (traces.length > 0) {
        traces.forEach(t => seenTraceIds.current.add(t.traceId));
        dispatch({ type: 'SET_REAL_TRACES', traces, logs, alerts });
      }
    });

    const id = setInterval(async () => {
      if (stateRef.current.mode !== 'real') return;
      const { traces, logs, alerts } = await fetchRealTraces();
      // Only add genuinely new traces
      const newTraces = traces.filter(t => !seenTraceIds.current.has(t.traceId));
      if (newTraces.length > 0) {
        newTraces.forEach(t => seenTraceIds.current.add(t.traceId));
        const newLogs = logs.filter(l => newTraces.some(t => l.traceId === t.traceId.slice(0, 8)));
        const newAlerts = alerts.filter(a => newTraces.some(t => a.desc?.includes(t.traceId.slice(0, 8))));
        dispatch({ type: 'SET_REAL_TRACES', traces: newTraces, logs: newLogs, alerts: newAlerts });
      }
    }, 4000);
    return () => clearInterval(id);
  }, []);

  // Simulated auto-emit when in simulated mode
  React.useEffect(() => {
    if (state.mode !== 'simulated') return;
    const TYPES: TraceType[] = ['normal','normal','normal','normal','multi','slow','error'];
    const id = setInterval(() => {
      const weights = [0.55, 0.55, 0.55, 0.55, 0.15, 0.10, 0.08];
      const r = Math.random();
      let cum = 0;
      let pick: TraceType = 'normal';
      for (let i = 0; i < TYPES.length; i++) {
        cum += weights[i];
        if (r < cum) { pick = TYPES[i]; break; }
      }
      dispatch({ type: 'INJECT_TRACE', traceType: pick });
    }, 2200);
    return () => clearInterval(id);
  }, [state.mode]);

  return (
    <TelemetryContext.Provider value={{ state, injectTrace, clearAlerts, setMode }}>
      {children}
    </TelemetryContext.Provider>
  );
}

export function useTelemetry() {
  const ctx = useContext(TelemetryContext);
  if (!ctx) throw new Error('useTelemetry must be used within TelemetryProvider');
  return ctx;
}
