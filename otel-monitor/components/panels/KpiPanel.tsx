'use client';
import { useEffect, useState, useCallback } from 'react';
import { Card, SectionHeader, Button, EmptyState } from '@/components/ui/primitives';
import KpiProxyCard from '@/components/panels/kpi/KpiProxyCard';
import { fetchAllKpis, KPI_SECTIONS } from '@/lib/kpi-client';
import type { KpiProxyEntry } from '@/types/telemetry';

const POLL_MS = 5000;

// Static Tailwind class lookup so JIT picks up the classes at build time.
// DO NOT switch this to a template literal — Tailwind cannot see dynamically
// constructed class names.
const GRID_COLS: Record<number, string> = {
  2: 'grid-cols-2',
  3: 'grid-cols-3',
};

function formatAge(ms: number): string {
  const sec = Math.floor(ms / 1000);
  if (sec < 60)  return `${sec}s ago`;
  const min = Math.floor(sec / 60);
  return `${min}m ${sec % 60}s ago`;
}

export default function KpiPanel() {
  const [data, setData]               = useState<Record<string, KpiProxyEntry> | null>(null);
  const [fetchError, setFetchError]   = useState<string | null>(null);
  const [lastFetchedAt, setLastFetchedAt] = useState<number | null>(null);
  const [now, setNow]                 = useState<number>(() => Date.now());

  const tick = useCallback(async () => {
    const { data, error } = await fetchAllKpis();
    if (error) {
      setFetchError(error);
      // Keep last-successful `data` visible.
    } else {
      setData(data);
      setFetchError(null);
      setLastFetchedAt(Date.now());
    }
  }, []);

  useEffect(() => {
    tick(); // immediate fetch on mount
    const id = setInterval(tick, POLL_MS);
    return () => clearInterval(id);
  }, [tick]);

  // Separate 1s interval to refresh the "updated Xs ago" label smoothly.
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  const ageLabel = lastFetchedAt === null
    ? 'never fetched'
    : `updated ${formatAge(now - lastFetchedAt)}`;

  return (
    <div className="flex flex-col gap-4 p-4 h-full overflow-y-auto">
      {/* Top status bar */}
      <div className="flex items-center justify-between flex-shrink-0">
        <span className="text-xs font-mono text-text-muted">
          Snapshot of 11 KPIs from kpi_proxy (localhost:8900). Polling every {POLL_MS / 1000}s.
        </span>
        <span className="flex items-center gap-2">
          <span className="text-[11px] font-mono text-text-muted">{ageLabel}</span>
          <Button size="xs" onClick={tick}>retry</Button>
        </span>
      </div>

      {/* Full-panel banner on proxy unreachable */}
      {fetchError && (
        <Card className="p-3 border-accent-red/40 bg-accent-red/5">
          <p className="text-xs font-mono text-accent-red">
            kpi_proxy error: {fetchError}
          </p>
          <p className="text-[10px] font-mono text-text-muted mt-1">
            Is <code>python otel_agent_v2/kpi_proxy.py</code> running on localhost:8900?
          </p>
        </Card>
      )}

      {/* Empty state: never fetched, no banner yet */}
      {!data && !fetchError && (
        <EmptyState msg="loading KPIs..." />
      )}

      {/* Sections */}
      {data && KPI_SECTIONS.map(section => (
        <section key={section.title} className="flex flex-col gap-3">
          <SectionHeader title={section.title} />
          <div className={`grid gap-3 ${GRID_COLS[section.cols] ?? 'grid-cols-2'}`}>
            {section.keys.map(k => (
              <KpiProxyCard key={k} name={k} entry={data[k]} />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
