import { NextResponse } from 'next/server';

const TEMPO_URL = 'http://localhost:3200';

interface TempoSearchResult {
  traceID: string;
  rootServiceName: string;
  rootTraceName: string;
  startTimeUnixNano: string;
  durationMs: number;
}

interface TempoTraceDetail {
  traceID: string;
  startTimeUnixNano: string;
  durationMs: number;
  batches: any[];
}

/**
 * Fetch trace list from Tempo search API and then fetch full details for each trace.
 */
async function fetchTracesFromTempo(): Promise<TempoTraceDetail[]> {
  try {
    // 1. Search for traces
    const searchRes = await fetch(`${TEMPO_URL}/api/search`, { cache: 'no-store' });
    if (!searchRes.ok) {
      console.warn(`Tempo search failed: ${searchRes.status}`);
      return [];
    }

    const searchData = (await searchRes.json()) as { traces?: TempoSearchResult[] };
    const traceList = searchData.traces ?? [];

    if (traceList.length === 0) {
      return [];
    }

    // 2. Fetch full details for each trace
    const detailedTraces: TempoTraceDetail[] = [];
    for (const summary of traceList) {
      try {
        const traceRes = await fetch(`${TEMPO_URL}/api/traces/${summary.traceID}`, {
          cache: 'no-store',
        });
        if (traceRes.ok) {
          const traceDetail = (await traceRes.json()) as any;
          // Combine summary metadata with detailed trace data
          detailedTraces.push({
            traceID: summary.traceID,
            startTimeUnixNano: summary.startTimeUnixNano,
            durationMs: summary.durationMs,
            batches: traceDetail.batches || [],
          });
        }
      } catch (e) {
        console.warn(`Failed to fetch trace ${summary.traceID}:`, e);
      }
    }

    return detailedTraces;
  } catch (err: unknown) {
    console.error('Failed to fetch traces from Tempo:', err);
    return [];
  }
}

/**
 * GET /api/traces — Returns array of traces from Tempo.
 */
export async function GET() {
  try {
    const traces = await fetchTracesFromTempo();
    return NextResponse.json({ traces });
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    console.error('Traces API error:', msg);
    return NextResponse.json({ error: msg, traces: [] }, { status: 200 });
  }
}
