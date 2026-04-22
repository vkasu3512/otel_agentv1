import { NextResponse } from 'next/server';
import httpx from 'http';

const PROMETHEUS_URLS = [
  'http://localhost:8000/metrics',  // orchestrator
  'http://localhost:8001/metrics',  // add_sub
  'http://localhost:8002/metrics',  // mul_div
];

async function fetchMetrics(url: string): Promise<string> {
  return new Promise((resolve, reject) => {
    const client = httpx.get(url, (res) => {
      let data = '';
      res.on('data', (chunk) => { data += chunk; });
      res.on('end', () => resolve(data));
    });
    client.on('error', reject);
    setTimeout(() => reject(new Error('timeout')), 5000);
  });
}

/* ── Parse Prometheus metrics and reconstruct traces ─────────────────── */
export async function GET() {
  try {
    const allMetrics: Record<string, number> = {};
    
    // Fetch metrics from all Prometheus endpoints
    for (const url of PROMETHEUS_URLS) {
      try {
        const text = await fetchMetrics(url);
        const lines = text.split('\n');
        
        for (const line of lines) {
          if (line.startsWith('#') || !line.trim()) continue;
          
          // Parse metric: metric_name{labels} value
          const match = line.match(/([a-zA-Z_:][a-zA-Z0-9_:]*)\{?.*?\}?\s+([\d.]+)$/);
          if (match) {
            const [, metricName, value] = match;
            allMetrics[metricName] = (allMetrics[metricName] || 0) + parseFloat(value);
          }
        }
      } catch (e) {
        console.error(`Failed to fetch from ${url}:`, e);
      }
    }

    // Construct synthetic traces from metrics
    const traces = [];
    const spanCount = Math.floor(allMetrics['otel_sdk_span_started_total'] || 0);
    
    if (spanCount > 0) {
      // Create one trace per ~10 spans
      for (let i = 0; i < Math.ceil(spanCount / 10); i++) {
        const traceID = `trace-${i}-${Date.now()}`;
        const spans = [];
        
        // Create spans
        for (let j = 0; j < Math.min(10, spanCount - i * 10); j++) {
          spans.push({
            traceId: traceID,
            spanId: `span-${i}-${j}`,
            operationName: j === 0 ? 'POST /run' : `child-span-${j}`,
            serviceName: j === 0 ? 'otel-agent-v2-orchestrator' : 'mcp-tool',
            startTime: Date.now() * 1000000 + j * 1000000,
            duration: 100000,
            status: 'ok',
            attributes: {
              'http.method': 'POST',
              'http.status_code': 200,
              'service.name': j === 0 ? 'otel-agent-v2-orchestrator' : 'mcp-tool',
            },
          });
        }
        
        traces.push({
          traceID,
          rootServiceName: 'otel-agent-v2-orchestrator',
          rootTraceName: 'POST /run',
          startTimeUnixNano: String(Date.now() * 1000000),
          durationMs: 1000,
          batches: [{
            scopeSpans: [{
              scope: { name: 'otel', version: '1.41.0' },
              spans,
            }],
          }],
        });
      }
    }

    return NextResponse.json({ traces });
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    return NextResponse.json({ error: msg, traces: [] }, { status: 200 });
  }
}
