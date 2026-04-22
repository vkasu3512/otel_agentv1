const nodemailer = require('nodemailer');

// Configuration from .env.local
const transporter = nodemailer.createTransport({
  host: 'smtp.gmail.com',
  port: 587,
  secure: false,
  auth: {
    user: 'samplealertsemail@gmail.com',
    pass: 'dfkx vprt dzfw bgzj'
  }
});

// Sample alerts
const sampleAlerts = [
  {
    id: 'alert-1',
    title: '🔴 ORCHESTRATION ERROR DETECTED',
    severity: 'ERROR',
    value: 1,
    timestamp: new Date().toISOString(),
    message: 'Orchestrator has encountered 1 error in the last 5 minutes'
  },
  {
    id: 'alert-2', 
    title: '⚠️  HIGH LATENCY DETECTED',
    severity: 'WARNING',
    value: 3500,
    timestamp: new Date().toISOString(),
    message: 'API latency (p95) is 3500ms - exceeds threshold of 3000ms'
  }
];

// HTML template
function buildHtml(alerts) {
  const alertRows = alerts.map(a => `
    <tr style="background: ${a.severity === 'ERROR' ? '#ffe6e6' : '#fff3cd'};">
      <td style="padding: 10px; border: 1px solid #ddd;">${a.title}</td>
      <td style="padding: 10px; border: 1px solid #ddd;">${a.severity}</td>
      <td style="padding: 10px; border: 1px solid #ddd;">${a.value}</td>
      <td style="padding: 10px; border: 1px solid #ddd;">${new Date(a.timestamp).toLocaleString()}</td>
    </tr>
  `).join('');

  return `
    <!DOCTYPE html>
    <html>
    <head>
      <style>
        body { font-family: Arial, sans-serif; background: #f5f5f5; }
        .container { max-width: 800px; margin: 20px auto; background: white; padding: 20px; border-radius: 8px; }
        h1 { color: #d32f2f; }
        table { width: 100%; border-collapse: collapse; }
        th { background: #333; color: white; padding: 10px; text-align: left; }
        .footer { margin-top: 20px; font-size: 12px; color: #666; }
      </style>
    </head>
    <body>
      <div class="container">
        <h1>🚨 SYSTEM ALERTS</h1>
        <p>The following alerts have been triggered on your LLM Agent monitoring system:</p>
        <table>
          <thead>
            <tr>
              <th>Alert</th>
              <th>Severity</th>
              <th>Value</th>
              <th>Time</th>
            </tr>
          </thead>
          <tbody>
            ${alertRows}
          </tbody>
        </table>
        <div class="footer">
          <p>Alert System | samplealertsemail@gmail.com</p>
          <p>This is a test alert from your monitoring system.</p>
        </div>
      </div>
    </body>
    </html>
  `;
}

// Send email
async function sendTestAlert() {
  try {
    console.log('[TEST] Preparing to send sample alert email...');
    
    const mailOptions = {
      from: 'samplealertsemail@gmail.com',
      to: 'samplealertsemail@gmail.com',
      subject: '🔴 TEST ALERT: Sample Notification from Monitoring System',
      html: buildHtml(sampleAlerts)
    };

    console.log('[TEST] Connecting to Gmail SMTP...');
    const info = await transporter.sendMail(mailOptions);
    
    console.log('');
    console.log('✅ SUCCESS - Email sent!');
    console.log('');
    console.log('Email Details:');
    console.log(`  To: samplealertsemail@gmail.com`);
    console.log(`  Subject: ${mailOptions.subject}`);
    console.log(`  Message ID: ${info.messageId}`);
    console.log(`  Response: ${info.response}`);
    console.log('');
    console.log('Check your email inbox at https://gmail.com');
    console.log('');
    
  } catch (error) {
    console.error('❌ FAILED - Error sending email:');
    console.error(`  Error: ${error.message}`);
    console.error(`  Code: ${error.code}`);
    if (error.response) {
      console.error(`  Response: ${error.response}`);
    }
  }
}

sendTestAlert();
