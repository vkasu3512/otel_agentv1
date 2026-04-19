'use client';
import { useState } from 'react';
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

export default function OverviewPanel() {
  const { state, injectTrace } = useTelemetry();
  const { kpi } = state;
  const { p50, p95, p99 } = getLatencyPercentiles(kpi.latencies);
  const tps    = tokenThroughput(kpi);
  const errPct = kpi.traces ? ((kpi.errors / kpi.traces) * 100).toFixed(1) : '0.0';
  const totalMcp = Object.values(kpi.mcpCalls).reduce((s, v) => s + v.calls, 0);

  const [lastInject, setLastInject] = useState('');

  function handleInject(type: TraceType, label: string) {
    injectTrace(type);
    setLastInject(`↗ Injected: ${label}`);
    setTimeout(() => setLastInject(''), 2500);
  }

  return (
    <div className="flex flex-col gap-4 p-4 overflow-y-auto h-full">
      {/* Row 1: primary KPIs */}
      <div className="grid grid-cols-4 gap-3">
        <KpiCard label="Total Traces"      value={kpi.traces.toLocaleString()} sub={`+${(Math.random() * 3 + 0.5).toFixed(1)}/min`} subColor="green" />
        <KpiCard label="LLM Latency p50"   value={p50 ? `${p50}ms` : '—'}     sub={`p95: ${p95}ms · p99: ${p99}ms`} />
        <KpiCard label="Token Throughput"  value={tps}                         sub="tokens / second" />
        <KpiCard label="Error Rate"        value={`${errPct}%`}                sub={kpi.errors > 0 ? `${kpi.errors} total errors` : 'within SLO'} subColor={parseFloat(errPct) > 5 ? 'red' : 'green'} />
      </div>

      {/* Row 2: secondary KPIs */}
      <div className="grid grid-cols-4 gap-3">
        <KpiCard label="MCP Tool Calls"    value={totalMcp.toLocaleString()}  sub="total invocations" />
        <KpiCard label="Prompt Tokens"     value={kpi.promptTokens.toLocaleString()} sub="cumulative" />
        <KpiCard label="Completion Tokens" value={kpi.compTokens.toLocaleString()} sub="cumulative" />
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
