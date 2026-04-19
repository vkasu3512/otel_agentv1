'use client';
import { useState, useMemo } from 'react';
import clsx from 'clsx';
import { useTelemetry } from '@/lib/store';
import { Badge, Card, SectionHeader, EmptyState } from '@/components/ui/primitives';
import type { Trace } from '@/types/telemetry';

type Filter = 'all' | 'ok' | 'error' | 'slow';

function statusBadge(trace: Trace) {
  if (trace.status === 'ERROR') return <Badge variant="error">ERROR</Badge>;
  if (trace.dur > 3000)         return <Badge variant="warn">SLOW</Badge>;
  return <Badge variant="ok">OK</Badge>;
}

function AttrTable({ attrs }: { attrs: Record<string, string | number | undefined> }) {
  const entries = Object.entries(attrs).filter(([, v]) => v !== undefined);
  return (
    <div className="space-y-0">
      {entries.map(([k, v]) => (
        <div key={k} className="flex gap-3 py-1 border-b border-bg-border text-xs">
          <span className="text-text-muted font-mono w-52 flex-shrink-0">{k}</span>
          <span className="text-text-primary font-mono break-all">{String(v)}</span>
        </div>
      ))}
    </div>
  );
}

export default function TracesPanel() {
  const { state } = useTelemetry();
  const [filter, setFilter] = useState<Filter>('all');
  const [selected, setSelected] = useState<Trace | null>(null);

  const filtered = useMemo(() => {
    return state.traces.filter(t => {
      if (filter === 'ok')    return t.status === 'OK' && t.dur <= 3000;
      if (filter === 'error') return t.status === 'ERROR';
      if (filter === 'slow')  return t.dur > 3000;
      return true;
    }).slice(0, 20);
  }, [state.traces, filter]);

  const maxDur = Math.max(...filtered.map(t => t.dur), 1);

  const FILTERS: { id: Filter; label: string }[] = [
    { id: 'all',   label: 'All'      },
    { id: 'ok',    label: 'OK'       },
    { id: 'error', label: 'Errors'   },
    { id: 'slow',  label: 'Slow >3s' },
  ];

  return (
    <div className="flex gap-3 p-4 h-full overflow-hidden">
      {/* Left: trace list */}
      <div className="flex flex-col flex-1 min-w-0 gap-3 overflow-hidden">
        <div className="flex items-center gap-2">
          <SectionHeader title="Recent traces" />
          <div className="flex gap-1 ml-auto">
            {FILTERS.map(f => (
              <button
                key={f.id}
                onClick={() => setFilter(f.id)}
                className={clsx(
                  'px-2.5 py-1 text-[10px] font-mono rounded border transition-all duration-100',
                  filter === f.id
                    ? 'bg-accent-blue/10 border-accent-blue/30 text-accent-blue'
                    : 'bg-transparent border-bg-border text-text-muted hover:text-text-secondary',
                )}
              >
                {f.label}
              </button>
            ))}
          </div>
        </div>

        <div className="flex-1 overflow-y-auto space-y-1.5">
          {filtered.length === 0 && <EmptyState msg="No traces match filter" />}
          {filtered.map(trace => (
            <div
              key={trace.traceId}
              onClick={() => setSelected(trace === selected ? null : trace)}
              className={clsx(
                'p-3 rounded-lg border cursor-pointer transition-all duration-100 animate-slide-up',
                selected?.traceId === trace.traceId
                  ? 'border-accent-blue/40 bg-accent-blue/5'
                  : 'border-bg-border bg-bg-card hover:border-bg-border-mid',
              )}
            >
              <div className="flex items-center gap-2 mb-1.5">
                {statusBadge(trace)}
                <span className="text-xs font-mono text-text-primary flex-1 truncate">{trace.name}</span>
                <span className="text-xs font-mono text-text-muted">{trace.dur}ms</span>
                <span className="text-[10px] font-mono text-text-muted">
                  {new Date(trace.ts).toLocaleTimeString()}
                </span>
              </div>

              {/* Duration bar */}
              <div className="h-1 rounded-full bg-bg-hover overflow-hidden mb-1.5">
                <div
                  className="h-full rounded-full transition-all duration-300"
                  style={{
                    width: `${(trace.dur / maxDur) * 100}%`,
                    background: trace.status === 'ERROR' ? '#f87171' : trace.dur > 3000 ? '#fbbf24' : '#34d399',
                  }}
                />
              </div>

              <div className="flex items-center gap-3 text-[10px] font-mono text-text-muted">
                <span className="truncate">{trace.traceId}</span>
                <span>·</span>
                <span>{trace.attrs['gen_ai.request.model']}</span>
                <span>·</span>
                <span>{trace.children.length} spans</span>
                <span>·</span>
                <span>
                  {Number(trace.attrs['gen_ai.usage.prompt_tokens'] ?? 0) +
                   Number(trace.attrs['gen_ai.usage.completion_tokens'] ?? 0)} tokens
                </span>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Right: attribute detail */}
      {selected && (
        <div className="w-80 flex-shrink-0 flex flex-col gap-3 overflow-hidden">
          <Card className="flex-1 overflow-y-auto p-4">
            <div className="flex items-center gap-2 mb-3">
              {statusBadge(selected)}
              <span className="text-xs font-mono text-text-secondary truncate">{selected.spanId}</span>
            </div>
            <p className="text-xs font-semibold text-text-primary mb-3">{selected.name}</p>
            <AttrTable attrs={selected.attrs} />

            {selected.children.length > 0 && (
              <>
                <p className="text-[10px] font-mono uppercase tracking-widest text-text-muted mt-4 mb-2">
                  Child spans ({selected.children.length})
                </p>
                {selected.children.map(ch => (
                  <div key={ch.spanId} className="mb-3 border border-bg-border rounded p-3">
                    <div className="flex items-center gap-2 mb-2">
                      <Badge variant={ch.status === 'ERROR' ? 'error' : 'ok'}>{ch.status}</Badge>
                      <span className="text-[11px] font-mono text-text-secondary">{ch.name}</span>
                      <span className="ml-auto text-[10px] font-mono text-text-muted">{ch.dur}ms</span>
                    </div>
                    <AttrTable attrs={ch.attrs} />
                  </div>
                ))}
              </>
            )}
          </Card>
        </div>
      )}
    </div>
  );
}
