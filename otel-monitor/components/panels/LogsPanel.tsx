'use client';
import { useState, useMemo, useRef, useEffect } from 'react';
import clsx from 'clsx';
import { useTelemetry } from '@/lib/store';
import { Card } from '@/components/ui/primitives';
import type { LogLevel } from '@/types/telemetry';

const LEVEL_COLOR: Record<LogLevel, string> = {
  DEBUG: 'text-text-muted',
  INFO:  'text-accent-green',
  WARN:  'text-accent-amber',
  ERROR: 'text-accent-red',
};

const FILTERS: { id: LogLevel | 'all'; label: string }[] = [
  { id: 'all',   label: 'All'   },
  { id: 'INFO',  label: 'INFO'  },
  { id: 'WARN',  label: 'WARN'  },
  { id: 'ERROR', label: 'ERROR' },
];

export default function LogsPanel() {
  const { state } = useTelemetry();
  const [filter, setFilter]   = useState<LogLevel | 'all'>('all');
  const [paused, setPaused]   = useState(false);
  const [search, setSearch]   = useState('');
  const bottomRef = useRef<HTMLDivElement>(null);

  const logs = useMemo(() => {
    return state.logs
      .filter(l => filter === 'all' || l.level === filter)
      .filter(l => !search || l.msg.toLowerCase().includes(search.toLowerCase()) || l.traceId.includes(search))
      .slice(0, 200);
  }, [state.logs, filter, search]);

  // Auto-scroll to bottom unless paused
  useEffect(() => {
    if (!paused) bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs, paused]);

  return (
    <div className="flex flex-col gap-3 p-4 h-full overflow-hidden">
      {/* Controls */}
      <div className="flex items-center gap-2 flex-shrink-0">
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
        <input
          type="text"
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="Search logs…"
          className="flex-1 bg-bg-card border border-bg-border rounded px-3 py-1 text-xs font-mono text-text-primary placeholder-text-muted outline-none focus:border-accent-blue/50 transition-colors"
        />
        <button
          onClick={() => setPaused(p => !p)}
          className={clsx(
            'px-3 py-1 text-[10px] font-mono rounded border transition-all',
            paused
              ? 'bg-accent-amber/10 border-accent-amber/30 text-accent-amber'
              : 'bg-transparent border-bg-border text-text-muted hover:text-text-secondary',
          )}
        >
          {paused ? '▶ Resume' : '⏸ Pause'}
        </button>
        <span className="text-[10px] font-mono text-text-muted">{logs.length} entries</span>
      </div>

      {/* Log stream */}
      <Card className="flex-1 overflow-y-auto p-3">
        <div className="space-y-0.5 font-mono text-[11px]">
          {logs.map(log => (
            <div
              key={log.id}
              className="flex gap-3 py-0.5 hover:bg-bg-hover rounded px-1 transition-colors group animate-fade-in"
            >
              <span className="text-text-muted flex-shrink-0 w-24">{log.ts}</span>
              <span className={clsx('flex-shrink-0 w-10 font-medium', LEVEL_COLOR[log.level])}>
                {log.level}
              </span>
              <span className="text-accent-blue/70 flex-shrink-0 w-20 truncate">[{log.traceId}]</span>
              <span className="text-text-secondary group-hover:text-text-primary transition-colors break-all">
                {log.msg}
              </span>
            </div>
          ))}
          <div ref={bottomRef} />
        </div>
      </Card>
    </div>
  );
}
