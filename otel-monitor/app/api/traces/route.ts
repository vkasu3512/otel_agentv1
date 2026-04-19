import { NextResponse } from 'next/server';

const GRAFANA_URL = process.env.GRAFANA_URL ?? 'http://localhost:3001';
const TEMPO_UID   = 'tempo';

/* ── Search recent traces ─────────────────────────────────────────────── */
export async function GET() {
  try {
    // Fetch trace list from Tempo via Grafana datasource proxy
    const searchUrl = `${GRAFANA_URL}/api/datasources/proxy/uid/${TEMPO_UID}/api/search?limit=30`;
    const searchRes = await fetch(searchUrl, { cache: 'no-store' });

    if (!searchRes.ok) {
      return NextResponse.json(
        { error: `Tempo search failed: ${searchRes.status}` },
        { status: searchRes.status },
      );
    }

    const { traces: traceList } = await searchRes.json() as {
      traces: { traceID: string; rootServiceName: string; rootTraceName: string; startTimeUnixNano: string; durationMs: number }[];
    };

    if (!traceList?.length) {
      return NextResponse.json({ traces: [] });
    }

    // Fetch full span details for each trace (parallel, cap at 15)
    const traceDetails = await Promise.all(
      traceList.slice(0, 15).map(async (t) => {
        const url = `${GRAFANA_URL}/api/datasources/proxy/uid/${TEMPO_UID}/api/traces/${t.traceID}`;
        const res = await fetch(url, { cache: 'no-store' });
        if (!res.ok) return null;
        const data = await res.json();
        return { traceID: t.traceID, startTimeUnixNano: t.startTimeUnixNano, durationMs: t.durationMs, batches: data.batches ?? [] };
      }),
    );

    return NextResponse.json({
      traces: traceDetails.filter(Boolean),
    });
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    return NextResponse.json({ error: msg }, { status: 502 });
  }
}
