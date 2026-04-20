import { NextResponse } from 'next/server';

const KPI_PROXY_URL = process.env.KPI_PROXY_URL ?? 'http://localhost:8900';

/**
 * GET /api/kpi — Proxies kpi_proxy.py's /kpi/all endpoint.
 *
 * Returns 200 with the raw kpi_proxy JSON on success.
 * Returns 502 with `{ error: string }` when the upstream is unreachable.
 *
 * Per-KPI errors (query failures) surface inside the 200 body as an
 * `error` field on the individual KPI entry — they are not hoisted here.
 */
export async function GET() {
  const url = `${KPI_PROXY_URL}/kpi/all`;
  try {
    const res = await fetch(url, { cache: 'no-store' });
    if (!res.ok) {
      return NextResponse.json(
        { error: `kpi_proxy ${res.status} at ${url}` },
        { status: 502 },
      );
    }
    const data = await res.json();
    return NextResponse.json(data);
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    return NextResponse.json(
      { error: `kpi_proxy unreachable at ${url}: ${msg}` },
      { status: 502 },
    );
  }
}
