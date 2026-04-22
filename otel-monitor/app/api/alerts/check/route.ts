import { NextResponse } from 'next/server';
import { sendAlertEmail } from '@/lib/mailer';
import { filterNewAlerts, ALERT_THRESHOLDS, shouldAlert } from '@/lib/alert-engine';
import type { Alert } from '@/types/telemetry';

const PROM_URL = process.env.PROM_URL ?? 'http://localhost:9090';

async function queryPrometheus(promql: string): Promise<number> {
  try {
    const url = `${PROM_URL}/api/v1/query?query=${encodeURIComponent(promql)}`;
    const res = await fetch(url, { cache: 'no-store' });
    if (!res.ok) return 0;
    
    const data = await res.json();
    const result = data?.data?.result?.[0];
    return result ? Number(result.value?.[1] ?? 0) : 0;
  } catch (err) {
    console.error(`Prometheus query failed: ${promql}`, err);
    return 0;
  }
}

export async function GET() {
  const fired: Alert[] = [];

  // Query each threshold
  for (const threshold of ALERT_THRESHOLDS) {
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
  }

  // Dedup and send emails
  if (fired.length > 0) {
    const toSend = filterNewAlerts(fired);
    if (toSend.length > 0) {
      try {
        await sendAlertEmail(toSend);
      } catch (err) {
        console.error('Email send failed:', err);
        return NextResponse.json({ error: String(err) }, { status: 500 });
      }
    }
  }

  return NextResponse.json({ fired: fired.length, sent: fired.length });
}
