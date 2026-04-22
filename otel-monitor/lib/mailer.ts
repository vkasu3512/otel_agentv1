import nodemailer from 'nodemailer';
import type { Alert } from '@/types/telemetry';

const transporter = nodemailer.createTransport({
  host:   process.env.SMTP_HOST,
  port:   Number(process.env.SMTP_PORT ?? 587),
  secure: false,  // TLS, not SSL
  auth: {
    user: process.env.SMTP_USER,
    pass: process.env.SMTP_PASS,
  },
});

export async function sendAlertEmail(alerts: Alert[]): Promise<void> {
  if (!process.env.ALERT_EMAIL_TO) {
    console.warn('ALERT_EMAIL_TO not set, skipping email');
    return;
  }

  const to      = process.env.ALERT_EMAIL_TO;
  const errors  = alerts.filter(a => a.severity === 'error');
  const warns   = alerts.filter(a => a.severity === 'warn');

  const subject = errors.length > 0
    ? `🔴 [OTel Monitor] ${errors.length} ERROR alert(s)`
    : `⚠️ [OTel Monitor] ${warns.length} warning(s)`;

  const lines = alerts.map(a =>
    `[${a.severity.toUpperCase()}] ${a.title}\n  ${a.desc}\n  Time: ${a.ts}`
  ).join('\n\n');

  await transporter.sendMail({
    from:    `"OTel Monitor" <${process.env.SMTP_USER}>`,
    to,
    subject,
    text:    `Active Alerts:\n\n${lines}\n\nView: ${process.env.GRAFANA_URL}`,
    html:    buildHtml(alerts),
  });

  console.log(`✅ Email sent to ${to}`);
}

function buildHtml(alerts: Alert[]): string {
  const rows = alerts.map(a => `
    <tr style="border-bottom:1px solid #333">
      <td style="padding:8px;color:${a.severity === 'error' ? '#f87171' : '#fbbf24'}">${a.severity.toUpperCase()}</td>
      <td style="padding:8px;color:#e5e7eb;font-weight:bold">${a.title}</td>
      <td style="padding:8px;color:#9ca3af">${a.desc}</td>
    </tr>`).join('');

  return `
    <div style="background:#0f1117;padding:24px;font-family:monospace">
      <h2 style="color:#f1f5f9">🔔 OTel Monitor — Alerts</h2>
      <table style="width:100%;border-collapse:collapse;background:#1a1d27">
        <thead><tr style="background:#252836">
          <th style="padding:8px;color:#94a3b8">Severity</th>
          <th style="padding:8px;color:#94a3b8">Title</th>
          <th style="padding:8px;color:#94a3b8">Details</th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
}
