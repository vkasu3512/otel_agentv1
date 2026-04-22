import type { Alert } from '@/types/telemetry';

// Deduplication — avoid spamming same alert
const _alertsSent = new Map<string, number>();
const COOLDOWN_MS = 5 * 60 * 1000;  // 5 minutes

export function filterNewAlerts(alerts: Alert[]): Alert[] {
  const now = Date.now();
  return alerts.filter(alert => {
    const key  = `${alert.severity}:${alert.title}`;
    const last = _alertsSent.get(key) ?? 0;
    if (now - last > COOLDOWN_MS) {
      _alertsSent.set(key, now);
      return true;
    }
    return false;
  });
}

export interface AlertThreshold {
  name:     string;
  promql:   string;
  severity: 'warn' | 'error';
  title:    (val: number) => string;
  desc:     (val: number) => string;
}

export const ALERT_THRESHOLDS: AlertThreshold[] = [
  {
    name:     'orchestrator_errors',
    promql:   'sum(increase(wd_otel_errors_total[5m]))',
    severity: 'error',
    title:    () => '🔴 Orchestration Errors',
    desc:     (v) => `${Math.floor(v)} errors recorded in last 5min`,
  },
  {
    name:     'tool_errors',
    promql:   'sum(increase(mcp_tool_errors_total[5m]))',
    severity: 'error',
    title:    () => '🔴 MCP Tool Failures',
    desc:     (v) => `${Math.floor(v)} failed tool calls in last 5min`,
  },
  {
    name:     'latency_p95',
    promql:   'histogram_quantile(0.95, sum(rate(langgraph_execution_duration_seconds_bucket[5m])))',
    severity: 'warn',
    title:    () => '⚠️ High Latency (p95)',
    desc:     (v) => `${(v * 1000).toFixed(0)}ms (threshold: 3000ms)`,
  },
  {
    name:     'active_workers',
    promql:   'sum(wd_otel_workers_active)',
    severity: 'warn',
    title:    () => '⚠️ Workers Stuck',
    desc:     (v) => `${Math.floor(v)} worker(s) stuck > 10s`,
  },
];

export function shouldAlert(threshold: AlertThreshold, value: number): boolean {
  switch (threshold.name) {
    case 'orchestrator_errors':   return value > 0;
    case 'tool_errors':           return value > 2;    // More than 2 errors
    case 'latency_p95':           return value > 3.0;  // More than 3 seconds
    case 'active_workers':        return value > 0;
    default:                      return false;
  }
}
