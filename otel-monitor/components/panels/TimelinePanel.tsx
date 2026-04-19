'use client';
import { useState, useMemo } from 'react';
import { useTelemetry } from '@/lib/store';
import { Card, Badge, EmptyState } from '@/components/ui/primitives';
import type { Trace, ChildSpan } from '@/types/telemetry';

interface SpanRow {
  name:   string;
  spanId: string;
  dur:    number;
  offset: number;
  status: 'OK' | 'ERROR' | 'UNSET';
  attrs:  Record<string, string | number | undefined>;
  depth:  number;
}

function buildRows(trace: Trace): SpanRow[] {
  return [
    { name: trace.name, spanId: trace.spanId, dur: trace.dur, offset: 0, status: trace.status, attrs: trace.attrs, depth: 0 },
    ...trace.children.map((c: ChildSpan) => ({
      name: c.name, spanId: c.spanId, dur: c.dur, offset: c.offset,
      status: c.status, attrs: c.attrs, depth: 1,
    })),
  ];
}

const SPAN_COLOR: Record<string, string> = {
  OK: '#4f9cf9', ERROR: '#f87171', UNSET: '#7c8599',
};

export default function TimelinePanel() {
  const { state } = useTelemetry();
  const [selectedTrace, setSelectedTrace] = useState<string>('');
  const [selectedSpan, setSelectedSpan]   = useState<SpanRow | null>(null);

  const trace = useMemo(() => {
    if (selectedTrace) return state.traces.find(t => t.traceId === selectedTrace) ?? state.traces[0];
    return state.traces[0];
  }, [state.traces, selectedTrace]);

  const rows = useMemo(() => trace ? buildRows(trace) : [], [trace]);
  const maxDur = trace?.dur ?? 1;

  const W = 560, LABEL_W = 180, BAR_W = W - LABEL_W - 10;
  const ROW_H = 34, PAD = 24;
  const svgH = rows.length * ROW_H + PAD * 2 + 20;

  return (
    <div className="flex flex-col gap-3 p-4 h-full overflow-hidden">
      {/* Trace selector */}
      <div className="flex items-center gap-2">
        <span className="text-[10px] font-mono uppercase tracking-widest text-text-muted">Trace</span>
        <select
          value={selectedTrace || state.traces[0]?.traceId || ''}
          onChange={e => { setSelectedTrace(e.target.value); setSelectedSpan(null); }}
          className="flex-1 bg-bg-card border border-bg-border rounded px-2 py-1 text-xs font-mono text-text-primary outline-none focus:border-accent-blue/50"
        >
          {state.traces.slice(0, 20).map(t => (
            <option key={t.traceId} value={t.traceId}>
              {t.traceId.slice(0, 16)}… — {t.name} — {t.dur}ms — {t.status} — {new Date(t.ts).toLocaleTimeString()}
            </option>
          ))}
        </select>
      </div>

      {!trace && <EmptyState msg="No traces yet" />}

      {trace && (
        <div className="flex gap-3 flex-1 overflow-hidden">
          {/* Waterfall SVG */}
          <Card className="flex-1 overflow-auto p-4">
            <svg
              viewBox={`0 0 ${W} ${svgH}`}
              width="100%"
              style={{ minWidth: 480 }}
            >
              {/* Time axis ticks */}
              {[0, 1, 2, 3, 4].map(i => {
                const x = LABEL_W + (BAR_W / 4) * i;
                const ms = Math.round((maxDur / 4) * i);
                return (
                  <g key={i}>
                    <line x1={x} y1={PAD} x2={x} y2={svgH - 10}
                      stroke="rgba(255,255,255,0.05)" strokeWidth="1" />
                    <text x={x} y={PAD - 5}
                      textAnchor="middle" fontSize="9"
                      fill="rgba(255,255,255,0.25)" fontFamily="JetBrains Mono, monospace">
                      {ms}ms
                    </text>
                  </g>
                );
              })}

              {/* Span rows */}
              {rows.map((sp, i) => {
                const y   = PAD + i * ROW_H;
                const x0  = LABEL_W + (sp.offset / maxDur) * BAR_W;
                const bw  = Math.max(6, (sp.dur / maxDur) * BAR_W);
                const col = SPAN_COLOR[sp.status];
                const isSelected = selectedSpan?.spanId === sp.spanId;

                return (
                  <g key={sp.spanId} style={{ cursor: 'pointer' }}
                    onClick={() => setSelectedSpan(isSelected ? null : sp)}>
                    {/* Depth indent line */}
                    {sp.depth > 0 && (
                      <line
                        x1={LABEL_W - 8} y1={y + ROW_H / 2}
                        x2={LABEL_W - 4} y2={y + ROW_H / 2}
                        stroke="rgba(255,255,255,0.15)" strokeWidth="1"
                      />
                    )}

                    {/* Label */}
                    <text
                      x={LABEL_W - 10} y={y + ROW_H / 2 + 4}
                      textAnchor="end" fontSize="11"
                      fill={isSelected ? col : 'rgba(255,255,255,0.5)'}
                      fontFamily="JetBrains Mono, monospace"
                      fontWeight={isSelected ? '500' : '400'}
                    >
                      {sp.name.length > 22 ? sp.name.slice(0, 21) + '…' : sp.name}
                    </text>

                    {/* Bar */}
                    <rect
                      x={x0} y={y + 8}
                      width={bw} height={ROW_H - 16}
                      rx="3"
                      fill={col}
                      opacity={isSelected ? 0.9 : 0.65}
                    />
                    {isSelected && (
                      <rect
                        x={x0 - 1} y={y + 7}
                        width={bw + 2} height={ROW_H - 14}
                        rx="4"
                        fill="none"
                        stroke={col}
                        strokeWidth="1.5"
                      />
                    )}

                    {/* Duration label */}
                    <text
                      x={x0 + bw + 5} y={y + ROW_H / 2 + 4}
                      fontSize="9"
                      fill="rgba(255,255,255,0.3)"
                      fontFamily="JetBrains Mono, monospace"
                    >
                      {sp.dur}ms
                    </text>
                  </g>
                );
              })}
            </svg>
          </Card>

          {/* Span detail */}
          <div className="w-72 flex-shrink-0">
            <Card className="p-4 h-full overflow-y-auto">
              {!selectedSpan ? (
                <p className="text-[11px] font-mono text-text-muted">Click a span bar to inspect attributes</p>
              ) : (
                <>
                  <div className="flex items-center gap-2 mb-3">
                    <Badge variant={selectedSpan.status === 'ERROR' ? 'error' : 'ok'}>
                      {selectedSpan.status}
                    </Badge>
                    <span className="text-[10px] font-mono text-text-muted truncate">{selectedSpan.spanId}</span>
                  </div>
                  <p className="text-xs font-semibold text-text-primary mb-1">{selectedSpan.name}</p>
                  <p className="text-[10px] font-mono text-accent-blue mb-3">{selectedSpan.dur}ms</p>
                  <div className="space-y-0">
                    {Object.entries(selectedSpan.attrs)
                      .filter(([, v]) => v !== undefined)
                      .map(([k, v]) => (
                        <div key={k} className="flex gap-2 py-1 border-b border-bg-border text-[11px]">
                          <span className="text-text-muted font-mono w-36 flex-shrink-0 truncate">{k}</span>
                          <span className="text-text-primary font-mono break-all">{String(v)}</span>
                        </div>
                      ))}
                  </div>
                </>
              )}
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}
