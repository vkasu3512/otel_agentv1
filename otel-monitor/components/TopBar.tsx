'use client';
import { useTelemetry } from '@/lib/store';
import { getLatencyPercentiles } from '@/lib/telemetry';
import { StatusDot, Badge } from '@/components/ui/primitives';

export default function TopBar() {
  const { state, setMode } = useTelemetry();
  const { kpi } = state;
  const { p99 } = getLatencyPercentiles(kpi.latencies);
  const errPct = kpi.traces ? ((kpi.errors / kpi.traces) * 100).toFixed(1) : '0.0';

  return (
    <header className="flex items-center gap-3 px-5 h-12 bg-bg-secondary border-b border-bg-border flex-shrink-0">
      {/* Logo */}
      <div className="flex items-center gap-2.5 mr-3">
        <div className="w-6 h-6 rounded-md bg-gradient-to-br from-accent-blue to-accent-purple flex items-center justify-center text-[11px] font-bold text-white">
          ⬡
        </div>
        <span className="font-semibold text-sm text-text-primary tracking-tight">
          OTel LLM Monitor
        </span>
      </div>

      <div className="h-4 w-px bg-bg-border mx-1" />

      {/* Mode toggle */}
      <div className="flex items-center gap-1 bg-bg-primary rounded-md p-0.5">
        <button
          onClick={() => setMode('real')}
          className={`px-2 py-0.5 text-[10px] font-mono uppercase tracking-wider rounded transition-colors ${
            state.mode === 'real'
              ? 'bg-accent-green/20 text-accent-green'
              : 'text-text-muted hover:text-text-secondary'
          }`}
        >
          Tempo
        </button>
        <button
          onClick={() => setMode('simulated')}
          className={`px-2 py-0.5 text-[10px] font-mono uppercase tracking-wider rounded transition-colors ${
            state.mode === 'simulated'
              ? 'bg-accent-purple/20 text-accent-purple'
              : 'text-text-muted hover:text-text-secondary'
          }`}
        >
          Demo
        </button>
      </div>

      <div className="h-4 w-px bg-bg-border mx-1" />

      {/* Live indicator */}
      <div className="flex items-center gap-1.5">
        <StatusDot active />
        <span className="text-[10px] font-mono text-text-muted uppercase tracking-widest">
          {state.mode === 'real' ? 'Live' : 'Sim'}
        </span>
      </div>

      <div className="flex-1" />

      {/* Stats pills */}
      <div className="flex items-center gap-2">
        <Badge variant="muted">
          {kpi.traces.toLocaleString()} traces
        </Badge>
        <Badge variant={p99 > 5000 ? 'error' : p99 > 3000 ? 'warn' : 'ok'}>
          p99 {p99 ? `${p99}ms` : '—'}
        </Badge>
        <Badge variant={parseFloat(errPct) > 10 ? 'error' : parseFloat(errPct) > 5 ? 'warn' : 'ok'}>
          err {errPct}%
        </Badge>
        <Badge variant="info">
          {(kpi.promptTokens + kpi.compTokens).toLocaleString()} tok
        </Badge>
      </div>
    </header>
  );
}
