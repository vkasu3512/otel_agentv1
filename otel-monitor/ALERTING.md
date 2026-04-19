# otel-monitor — Email Alerting Implementation Guide

---

## Current Alert System (Client-Side Only)

Alerts are generated in-memory on the client. No server-side notification exists yet.

Logic lives in two places:

**`lib/tempo-mapper.ts`** — Real mode (from Tempo traces)
- `trace.dur > 5000ms` → severity: warn — "High latency"
- `trace.status === ERROR` → severity: error — "Error trace"
- child tool `status === ERROR` → severity: error — "Tool error"

**`lib/telemetry.ts`** — Simulated mode
- `agentDur > 5000ms` → severity: warn
- `isError` → severity: error
- `errRate > 15%` (probabilistic) → severity: warn

`AlertsPanel.tsx` is a pure display component — reads from React Context, no email or webhook.

---

## Target Architecture

```
Prometheus (:9090)  ←── kpi_proxy.py (:8900)  [already exists]
        ↓
app/api/alerts/check/route.ts   ← NEW: server route, polled every 30s
        ↓ evaluates thresholds
lib/alert-engine.ts             ← NEW: threshold config + dedup state
        ↓ if threshold breached and not already notified
lib/mailer.ts                   ← NEW: nodemailer SMTP client
        ↓
Gmail / any SMTP → inbox
```

- **UI alerts**: real-time, derived from Tempo traces (already works)
- **Email alerts**: server-side, evaluated against Prometheus metrics (to add)

---

## Step 1 — Install nodemailer

```bash
cd otel-monitor
npm install nodemailer
npm install --save-dev @types/nodemailer
```

---

## Step 2 — Add `.env.local`

```bash
# otel-monitor/.env.local
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
SMTP_PASS=your-16-char-app-password    # Gmail App Password — NOT your login password
ALERT_EMAIL_TO=your-email@gmail.com
PROM_URL=http://localhost:9090
KPI_PROXY_URL=http://localhost:8900
GRAFANA_URL=http://localhost:3001
```

> **Gmail App Password**: Google Account → Security → 2-Step Verification → App passwords → Generate (16 chars).
> Do NOT use your regular Gmail login password.

---

## Step 3 — Create `lib/mailer.ts`

```ts
import nodemailer from 'nodemailer';
import type { Alert } from '@/types/telemetry';

const transporter = nodemailer.createTransport({
  host:   process.env.SMTP_HOST,
  port:   Number(process.env.SMTP_PORT ?? 587),
  secure: false,
  auth: {
    user: process.env.SMTP_USER,
    pass: process.env.SMTP_PASS,
  },
});

export async function sendAlertEmail(alerts: Alert[]): Promise<void> {
  const to      = process.env.ALERT_EMAIL_TO!;
  const errors  = alerts.filter(a => a.severity === 'error');
  const warns   = alerts.filter(a => a.severity === 'warn');

  const subject = errors.length > 0
    ? `🔴 [OTel Monitor] ${errors.length} error alert(s) firing`
    : `⚠️ [OTel Monitor] ${warns.length} warning(s) firing`;

  const lines = alerts.map(a =>
    `[${a.severity.toUpperCase()}] ${a.title}\n  ${a.desc}\n  Time: ${a.ts}`
  ).join('\n\n');

  await transporter.sendMail({
    from:    `"OTel Monitor" <${process.env.SMTP_USER}>`,
    to,
    subject,
    text:    `Active Alerts:\n\n${lines}\n\nView dashboard: http://localhost:3000`,
    html:    buildHtml(alerts),
  });
}

function buildHtml(alerts: Alert[]): string {
  const rows = alerts.map(a => `
    <tr style="border-bottom:1px solid #333">
      <td style="padding:8px;color:${a.severity === 'error' ? '#f87171' : '#fbbf24'}">${a.severity.toUpperCase()}</td>
      <td style="padding:8px;color:#e5e7eb;font-weight:bold">${a.title}</td>
      <td style="padding:8px;color:#9ca3af">${a.desc}</td>
      <td style="padding:8px;color:#6b7280;font-size:11px">${a.ts}</td>
    </tr>`).join('');

  return `
    <div style="background:#0f1117;padding:24px;font-family:monospace">
      <h2 style="color:#f1f5f9;margin-bottom:16px">🔔 OTel Monitor — Alert Summary</h2>
      <table style="width:100%;border-collapse:collapse;background:#1a1d27">
        <thead><tr style="background:#252836">
          <th style="padding:8px;color:#94a3b8;text-align:left">Severity</th>
          <th style="padding:8px;color:#94a3b8;text-align:left">Title</th>
          <th style="padding:8px;color:#94a3b8;text-align:left">Description</th>
          <th style="padding:8px;color:#94a3b8;text-align:left">Time</th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
}
```

---

## Step 4 — Create `lib/alert-engine.ts`

```ts
import type { Alert } from '@/types/telemetry';

// Dedup — don't re-email the same alert within cooldown window
const _sent = new Map<string, number>();  // alertKey → timestamp
const COOLDOWN_MS = 5 * 60 * 1000;       // 5 minutes per alert key

export function filterNewAlerts(alerts: Alert[]): Alert[] {
  const now = Date.now();
  return alerts.filter(alert => {
    const key  = `${alert.severity}:${alert.title}`;
    const last = _sent.get(key) ?? 0;
    if (now - last > COOLDOWN_MS) {
      _sent.set(key, now);
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
    promql:   'sum(orchestrator_errors_total)',
    severity: 'error',
    title:    () => 'Orchestration errors detected',
    desc:     (v) => `${v} total orchestration error(s) recorded`,
  },
  {
    name:     'tool_error_rate',
    promql:   'sum(rate(mcp_tool_invocations_total{status="error"}[5m]))',
    severity: 'error',
    title:    () => 'MCP tool error rate spike',
    desc:     (v) => `Tool error rate: ${(v * 60).toFixed(2)}/min`,
  },
  {
    name:     'tool_latency_p95',
    promql:   'histogram_quantile(0.95, sum by(le)(rate(mcp_tool_duration_bucket[5m])))',
    severity: 'warn',
    title:    () => 'Tool latency p95 > 2s',
    desc:     (v) => `p95 latency: ${(v * 1000).toFixed(0)}ms (threshold: 2000ms)`,
  },
  {
    name:     'active_workers_stuck',
    promql:   'sum(orchestrator_active_workers)',
    severity: 'warn',
    title:    () => 'Workers stuck (active_workers > 0)',
    desc:     (v) => `${v} worker(s) currently active — possible hang`,
  },
  {
    name:     'langgraph_failures',
    promql:   'sum(rate(langgraph_step_total{status="failure"}[5m]))',
    severity: 'error',
    title:    () => 'LangGraph node failures',
    desc:     (v) => `LangGraph failure rate: ${(v * 60).toFixed(2)}/min`,
  },
];

export function shouldAlert(threshold: AlertThreshold, value: number): boolean {
  switch (threshold.name) {
    case 'orchestrator_errors':   return value > 0;
    case 'tool_error_rate':       return value > 0.1;   // > 0.1/s = 6/min
    case 'tool_latency_p95':      return value > 2.0;   // > 2 seconds
    case 'active_workers_stuck':  return value > 0;
    case 'langgraph_failures':    return value > 0;
    default:                      return false;
  }
}
```

---

## Step 5 — Create `app/api/alerts/check/route.ts`

```ts
import { NextResponse } from 'next/server';
import { sendAlertEmail } from '@/lib/mailer';
import { filterNewAlerts, ALERT_THRESHOLDS, shouldAlert } from '@/lib/alert-engine';
import type { Alert } from '@/types/telemetry';

const PROM_URL = process.env.PROM_URL ?? 'http://localhost:9090';

async function queryPrometheus(promql: string): Promise<number> {
  const url = `${PROM_URL}/api/v1/query?query=${encodeURIComponent(promql)}`;
  const res  = await fetch(url, { cache: 'no-store' });
  if (!res.ok) return 0;
  const data   = await res.json();
  const result = data?.data?.result?.[0];
  return result ? Number(result.value?.[1] ?? 0) : 0;
}

export async function GET() {
  const fired: Alert[] = [];

  for (const threshold of ALERT_THRESHOLDS) {
    try {
      const value = await queryPrometheus(threshold.promql);
      if (shouldAlert(threshold, value)) {
        fired.push({
          id:       `prom-${threshold.name}-${Date.now()}`,
          severity: threshold.severity,
          title:    threshold.title(value),
          desc:     threshold.desc(value),
          ts:       new Date().toLocaleTimeString(),
        });
      }
    } catch {
      // individual threshold failure should not block others
    }
  }

  const newAlerts = filterNewAlerts(fired);

  if (newAlerts.length > 0) {
    await sendAlertEmail(newAlerts);
  }

  return NextResponse.json({
    checked: ALERT_THRESHOLDS.length,
    fired:   fired.length,
    emailed: newAlerts.length,
    alerts:  newAlerts,
  });
}
```

---

## Step 6 — Trigger Polling from the UI

Add inside `TelemetryProvider` in `lib/store.tsx`:

```ts
// Poll server-side alert check every 30s
React.useEffect(() => {
  const checkAlerts = () => fetch('/api/alerts/check').catch(() => {});
  checkAlerts();
  const id = setInterval(checkAlerts, 30_000);
  return () => clearInterval(id);
}, []);
```

This silently hits the server route every 30 seconds. Emails fire server-side — no UI change needed.

---

## Alert Flow

```
Every 30s (triggered by UI poll)
        ↓
GET /api/alerts/check
        ↓
Queries Prometheus for 5 KPI thresholds (PromQL)
        ↓
If threshold breached AND not sent in last 5 min
        ↓
nodemailer → Gmail SMTP → inbox
        ↓
Returns { fired, emailed, alerts[] } to UI
```

---

## Alerts That Fire

| Alert | Condition | Severity |
|-------|-----------|----------|
| Orchestration errors detected | `orchestrator_errors_total > 0` | error |
| MCP tool error rate spike | `rate(mcp_tool_invocations_total{status="error"}[5m]) > 0.1/s` | error |
| LangGraph node failures | `rate(langgraph_step_total{status="failure"}[5m]) > 0` | error |
| Tool latency p95 > 2s | `histogram_quantile(0.95, ...) > 2.0` | warn |
| Workers stuck | `orchestrator_active_workers > 0` | warn |

---

## Files to Create

```
otel-monitor/
  .env.local                        ← SMTP + Prometheus config
  lib/
    mailer.ts                       ← nodemailer transporter + sendAlertEmail
    alert-engine.ts                 ← thresholds, dedup, shouldAlert
  app/
    api/
      alerts/
        check/
          route.ts                  ← GET handler: query Prometheus, send email
```

---

## Notes

- The dedup `Map` in `alert-engine.ts` is in-memory — it resets on server restart.
  For production, replace with a Redis key or a simple JSON file.
- Add `.env.local` to `.gitignore` — never commit SMTP credentials.
- Test the email connection independently before wiring the full flow:
  ```ts
  await transporter.verify();  // throws if SMTP config is wrong
  ```
- To test without triggering real alerts, call the endpoint manually:
  ```bash
  curl http://localhost:3000/api/alerts/check
  ```
