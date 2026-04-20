'use client';
import { Card, SectionHeader, Badge } from '@/components/ui/primitives';
import { KPI_UNIT_HINTS } from '@/lib/kpi-client';
import type { KpiProxyEntry, KpiProxyResultRow } from '@/types/telemetry';

interface Props {
  name:  string;          // e.g. "orchestrator.active_workers"
  entry?: KpiProxyEntry;  // undefined while first fetch is in flight
}

const MAX_ROWS = 10;

function formatValue(raw: string): string {
  const n = parseFloat(raw);
  if (!Number.isFinite(n)) return raw;
  // Show up to 4 significant digits; strip trailing zeros.
  if (Math.abs(n) >= 1000) return n.toFixed(0);
  if (Math.abs(n) >= 1)    return n.toFixed(2).replace(/\.?0+$/, '');
  return n.toPrecision(3);
}

function isScalarRow(row: KpiProxyResultRow): boolean {
  return Object.keys(row.metric).length === 0;
}

export default function KpiProxyCard({ name, entry }: Props) {
  const title = entry?.title ?? name;
  const unit  = KPI_UNIT_HINTS[name];

  // ── Loading: no entry yet ─────────────────────────────────────────────
  if (!entry) {
    return (
      <Card className="p-4">
        <SectionHeader title={title} right={<Badge variant="muted">loading</Badge>} />
        <p className="text-xs font-mono text-text-muted">fetching…</p>
      </Card>
    );
  }

  // ── Error from proxy (per-KPI) ────────────────────────────────────────
  if (entry.error) {
    return (
      <Card className="p-4">
        <SectionHeader title={title} right={<Badge variant="error">query failed</Badge>} />
        <p className="text-[11px] font-mono text-accent-red break-words line-clamp-3">
          {entry.error}
        </p>
      </Card>
    );
  }

  const rows = entry.result ?? [];

  // ── No data (empty result) ────────────────────────────────────────────
  if (rows.length === 0) {
    return (
      <Card className="p-4">
        <SectionHeader title={title} right={<Badge variant="muted">no data</Badge>} />
        <p className="text-xs font-mono text-text-muted">no samples yet</p>
      </Card>
    );
  }

  // ── Scalar: single row with empty labels ──────────────────────────────
  if (rows.length === 1 && isScalarRow(rows[0])) {
    return (
      <Card className="p-4">
        <SectionHeader title={title} />
        <p className="text-2xl font-semibold text-text-primary leading-none">
          {formatValue(rows[0].value[1])}
        </p>
        {unit && (
          <p className="text-[11px] mt-1.5 font-mono text-text-muted">{unit}</p>
        )}
      </Card>
    );
  }

  // ── Multi-series table ────────────────────────────────────────────────
  // Collect the union of label keys across rows, stable-sorted.
  const labelKeys = Array.from(
    new Set(rows.flatMap(r => Object.keys(r.metric))),
  ).sort();
  const shown  = rows.slice(0, MAX_ROWS);
  const hidden = rows.length - shown.length;

  return (
    <Card className="p-4">
      <SectionHeader
        title={title}
        right={<Badge variant="info">{rows.length} series</Badge>}
      />
      <div className="overflow-x-auto">
        <table className="w-full text-[11px] font-mono">
          <thead>
            <tr className="text-text-muted">
              {labelKeys.map(k => (
                <th key={k} className="text-left font-normal pb-1.5 pr-3">{k}</th>
              ))}
              <th className="text-right font-normal pb-1.5">value</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((row, i) => (
              <tr key={i} className="border-t border-bg-border/40">
                {labelKeys.map(k => (
                  <td key={k} className="py-1 pr-3 text-text-secondary">
                    {row.metric[k] ?? '—'}
                  </td>
                ))}
                <td className="py-1 text-right text-text-primary">
                  {formatValue(row.value[1])}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {hidden > 0 && (
        <p className="mt-2 text-[10px] font-mono text-text-muted">+{hidden} more</p>
      )}
    </Card>
  );
}
