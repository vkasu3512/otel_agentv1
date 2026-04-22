'use client';
import { useState, useEffect } from 'react';
import { useTelemetry } from '@/lib/store';
import { getLatencyPercentiles, tokenThroughput } from '@/lib/telemetry';
import { KpiCard, Card, Button, SectionHeader } from '@/components/ui/primitives';
import LatencyChart from '@/components/charts/LatencyChart';
import type { TraceType } from '@/types/telemetry';

const INJECT_ACTIONS: { type: TraceType; label: string; desc: string }[] = [
  { type: 'normal', label: 'Normal trace',   desc: 'Healthy agent run'      },
  { type: 'slow',   label: 'Slow LLM',       desc: 'Latency SLO breach'     },
  { type: 'error',  label: 'Tool error',     desc: 'MCP tool failure'       },
  { type: 'multi',  label: 'Multi-tool',     desc: '3-tool chained call'    },
];

// Parse KPI proxy response for direct metric display
interface KpiProxyValue {
  area: string;
  title: string;
  result: Array<{ metric: string; value: string }>;
}

function extractKpiValue(data: KpiProxyValue | undefined): number {
  try {
    if (!data?.result?.length) return 0;
    const valueStr = data.result[0]?.value;
    if (!valueStr || typeof valueStr !== 'string') return 0;
    const parts = valueStr.split(' ');
    const numStr = parts[parts.length - 1];
    const num = parseFloat(numStr);
    return isNaN(num) ? 0 : num;
  } catch {
    return 0;
  }
}

export default function OverviewPanel() {
  const { state, injectTrace } = useTelemetry();
  const { kpi } = state;
  const { p50, p95, p99 } = getLatencyPercentiles(kpi.latencies);
  const tps    = tokenThroughput(kpi);
  const errPct = kpi.traces ? ((kpi.errors / kpi.traces) * 100).toFixed(1) : '0.0';
  const totalMcp = Object.values(kpi.mcpCalls).reduce((s, v) => s + v.calls, 0);

  // Fetch direct KPI data from proxy
  const [kpiProxyData, setKpiProxyData] = useState<Record<string, KpiProxyValue>>({});
  useEffect(() => {
    const fetchKpi = async () => {
      try {
        const res = await fetch('/api/kpi', { cache: 'no-store' });
        if (res.ok) {
          const data = await res.json();
          setKpiProxyData(data);
        }
      } catch (e) {
        console.error('Failed to fetch KPI proxy:', e);
      }
    };
    fetchKpi();
    const id = setInterval(fetchKpi, 5000);
    return () => clearInterval(id);
  }, []);

  const [lastInject, setLastInject] = useState('');

  // Use direct KPI proxy values as fallback when trace parsing isn't complete
  const orchestratorWorkers = extractKpiValue(kpiProxyData['orchestrator.active_workers'] as KpiProxyValue);
  const langgraphBuildDur = extractKpiValue(kpiProxyData['langgraph.build_duration_avg'] as KpiProxyValue);
  const mcpInvRate = extractKpiValue(kpiProxyData['mcp.invocations_rate'] as KpiProxyValue);
  const langgraphExecP95 = extractKpiValue(kpiProxyData['langgraph.execution_duration_p95'] as KpiProxyValue);
  const mcpDurP95 = extractKpiValue(kpiProxyData['mcp.duration_p95'] as KpiProxyValue);

  function handleInject(type: TraceType, label: string) {
    injectTrace(type);
    setLastInject(`↗ Injected: ${label}`);
    setTimeout(() => setLastInject(''), 2500);
  }

  return (
    <div className="flex flex-col gap-4 p-4 overflow-y-auto h-full">
      {/* Row 1: primary KPIs — use proxy data as fallback */}
      <div className="grid grid-cols-4 gap-3">
        <KpiCard label="Total Traces"      value={kpi.traces > 0 ? kpi.traces.toLocaleString() : '—'} sub={`active workers: ${Math.max(0, orchestratorWorkers).toFixed(0)}`} subColor="muted" />
        <KpiCard label="LLM Latency p50"   value={p50 ? `${p50}ms` : '—'}     sub={`p95: ${p95}ms · p99: ${p99}ms`} />
        <KpiCard label="Graph Build Avg"  value={`${Math.max(0, langgraphBuildDur * 1000).toFixed(0)}ms`}  sub="LangGraph init" />
        <KpiCard label="Error Rate"        value={`${errPct}%`}                sub={kpi.errors > 0 ? `${kpi.errors} total errors` : 'within SLO'} subColor={parseFloat(errPct) > 5 ? 'red' : 'green'} />
      </div>

      {/* Row 2: secondary KPIs — use proxy data */}
      <div className="grid grid-cols-4 gap-3">
        <KpiCard label="MCP Tool Calls"    value={totalMcp > 0 ? totalMcp.toLocaleString() : `${Math.max(0, mcpInvRate).toFixed(0)}/min`}  sub="total invocations" />
        <KpiCard label="LangGraph p95"     value={`${Math.max(0, langgraphExecP95).toFixed(2)}s`} sub="execution latency" />
        <KpiCard label="MCP Tool p95"      value={`${Math.max(0, mcpDurP95).toFixed(2)}s`} sub="tool latency" />
        <KpiCard label="Active Spans"      value={kpi.activeSpans}            sub="in-flight" subColor={kpi.activeSpans > 2 ? 'green' : 'muted'} />
      </div>

      {/* Latency histogram */}
      <Card className="p-4">
        <SectionHeader title={`Latency histogram — last ${kpi.latencies.length} requests`} />
        <LatencyChart />
        <div className="flex items-center gap-4 mt-2">
          {[
            { label: '≤ 3s', color: 'bg-accent-blue' },
            { label: '3–5s', color: 'bg-accent-amber' },
            { label: '> 5s', color: 'bg-accent-red' },
          ].map(l => (
            <div key={l.label} className="flex items-center gap-1.5">
              <span className={`w-2.5 h-2.5 rounded-sm ${l.color} opacity-70`} />
              <span className="text-[10px] font-mono text-text-muted">{l.label}</span>
            </div>
          ))}
        </div>
      </Card>

      {/* Inject controls */}
      <Card className="p-4">
        <SectionHeader title="Simulate traces" />
        <div className="flex flex-wrap items-center gap-2">
          {INJECT_ACTIONS.map(a => (
            <Button key={a.type} onClick={() => handleInject(a.type, a.label)} size="sm">
              {a.label}
              <span className="text-text-muted">· {a.desc}</span>
            </Button>
          ))}
          {lastInject && (
            <span className="ml-auto text-[11px] font-mono text-accent-green animate-fade-in">
              {lastInject}
            </span>
          )}
        </div>
      </Card>
    </div>
  );
}
