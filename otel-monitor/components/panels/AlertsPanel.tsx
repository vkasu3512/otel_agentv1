'use client';
import clsx from 'clsx';
import { useTelemetry } from '@/lib/store';
import { Button, EmptyState } from '@/components/ui/primitives';
import type { AlertSeverity } from '@/types/telemetry';

const SEV_STYLES: Record<AlertSeverity, { wrap: string; icon: string; iconColor: string }> = {
  error: {
    wrap:      'border-accent-red/25 bg-accent-red/5',
    icon:      '⬤',
    iconColor: 'text-accent-red',
  },
  warn: {
    wrap:      'border-accent-amber/25 bg-accent-amber/5',
    icon:      '▲',
    iconColor: 'text-accent-amber',
  },
  info: {
    wrap:      'border-accent-blue/25 bg-accent-blue/5',
    icon:      '●',
    iconColor: 'text-accent-blue',
  },
};

export default function AlertsPanel() {
  const { state, clearAlerts } = useTelemetry();
  const { alerts } = state;

  return (
    <div className="flex flex-col gap-3 p-4 h-full overflow-hidden">
      <div className="flex items-center justify-between flex-shrink-0">
        <span className="text-[10px] font-mono uppercase tracking-widest text-text-muted">
          Active alerts & SLO violations
        </span>
        {alerts.length > 0 && (
          <Button variant="danger" size="xs" onClick={clearAlerts}>
            Clear all
          </Button>
        )}
      </div>

      <div className="flex-1 overflow-y-auto space-y-2">
        {alerts.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full gap-2">
            <span className="text-2xl">✓</span>
            <EmptyState msg="No active alerts — all SLOs within threshold" />
          </div>
        )}

        {alerts.map(alert => {
          const s = SEV_STYLES[alert.severity];
          return (
            <div
              key={alert.id}
              className={clsx(
                'flex gap-3 p-3 rounded-lg border transition-all animate-slide-up',
                s.wrap,
              )}
            >
              <span className={clsx('mt-0.5 text-xs flex-shrink-0', s.iconColor)}>{s.icon}</span>
              <div className="flex-1 min-w-0">
                <p className="text-xs font-semibold text-text-primary">{alert.title}</p>
                <p className="text-[11px] text-text-secondary mt-0.5">{alert.desc}</p>
                <p className="text-[10px] font-mono text-text-muted mt-1">{alert.ts}</p>
              </div>
              <span className={clsx(
                'text-[10px] font-mono font-medium uppercase tracking-wide flex-shrink-0 mt-0.5',
                s.iconColor,
              )}>
                {alert.severity}
              </span>
            </div>
          );
        })}
      </div>

      {/* SLO thresholds reference */}
      <div className="flex-shrink-0 border-t border-bg-border pt-3">
        <p className="text-[10px] font-mono uppercase tracking-widest text-text-muted mb-2">SLO thresholds</p>
        <div className="grid grid-cols-3 gap-2">
          {[
            { label: 'p99 latency',  threshold: '< 3,000ms', status: 'monitored' },
            { label: 'Error rate',   threshold: '< 5%',      status: 'monitored' },
            { label: 'Span timeout', threshold: '< 5,000ms', status: 'monitored' },
          ].map(slo => (
            <div key={slo.label} className="bg-bg-card border border-bg-border rounded p-2">
              <p className="text-[10px] font-mono text-text-muted">{slo.label}</p>
              <p className="text-xs font-mono text-text-primary mt-0.5">{slo.threshold}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
