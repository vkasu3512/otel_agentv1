import { useEffect } from 'react';

export function useAlertTicker() {
  useEffect(() => {
    // Check alerts every 30 seconds
    const interval = setInterval(async () => {
      try {
        const res = await fetch('/api/alerts/check', { cache: 'no-store' });
        const data = await res.json();
        if (data.fired > 0) {
          console.log(`⚠️ Alerts fired: ${data.fired}, sent: ${data.sent}`);
        }
      } catch (err) {
        console.error('Alert check failed:', err);
      }
    }, 30_000);

    return () => clearInterval(interval);
  }, []);
}
