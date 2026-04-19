'use client';
import { useTelemetry } from '@/lib/store';
import { MCP_TOOLS, TOOL_COLORS } from '@/lib/telemetry';
import { Card, SectionHeader } from '@/components/ui/primitives';
import McpInvocationChart from '@/components/charts/McpInvocationChart';

export default function McpPanel() {
  const { state } = useTelemetry();
  const { mcpCalls } = state.kpi;
  const maxCalls = Math.max(...MCP_TOOLS.map(t => mcpCalls[t].calls), 1);

  return (
    <div className="flex flex-col gap-4 p-4 h-full overflow-y-auto">
      <div className="grid grid-cols-3 gap-3">
        {MCP_TOOLS.map(tool => {
          const d = mcpCalls[tool];
          const errPct = d.calls ? ((d.errors / d.calls) * 100).toFixed(0) : '0';
          const avgMs  = d.calls ? Math.round(d.totalMs / d.calls) : 0;
          const pct    = (d.calls / maxCalls) * 100;
          const color  = TOOL_COLORS[tool];

          return (
            <Card key={tool} className="p-4">
              <div className="flex items-center gap-2 mb-3">
                <span className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ background: color }} />
                <span className="text-xs font-mono font-medium text-text-primary">{tool}</span>
              </div>
              <div className="grid grid-cols-2 gap-x-4 gap-y-1 mb-3 text-[11px] font-mono">
                <span className="text-text-muted">Calls</span>
                <span className="text-text-primary text-right">{d.calls}</span>
                <span className="text-text-muted">Avg latency</span>
                <span className="text-text-primary text-right">{avgMs}ms</span>
                <span className="text-text-muted">Errors</span>
                <span className="text-right" style={{ color: d.errors > 0 ? '#f87171' : '#34d399' }}>
                  {d.errors} ({errPct}%)
                </span>
              </div>
              <div className="h-1 rounded-full bg-bg-hover overflow-hidden">
                <div
                  className="h-full rounded-full transition-all duration-500"
                  style={{ width: `${pct.toFixed(1)}%`, background: color }}
                />
              </div>
            </Card>
          );
        })}
      </div>

      <Card className="p-4">
        <SectionHeader title="Cumulative invocations over time" />
        <McpInvocationChart />
      </Card>
    </div>
  );
}
