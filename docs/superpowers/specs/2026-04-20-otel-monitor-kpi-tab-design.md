# otel-monitor KPI tab — design

**Date:** 2026-04-20
**Status:** Approved (pending user spec review)
**Owner:** Charikshith

## Context

`otel-monitor/` (Next.js 14 App Router) is the local observability UI. It
currently tracks LLM-oriented KPIs (token usage, latency percentiles,
per-tool call counts) derived from Jaeger traces. None of the 11 KPIs
exposed by `otel_agent_v2/kpi_proxy.py` (port 8900) are surfaced in the
UI today.

`kpi_proxy.py`'s `/kpi/all` endpoint returns a dict keyed by 11 KPI names
(4 `orchestrator.*`, 4 `langgraph.*`, 3 `mcp.*`), each carrying
`{area, title, query, result}`. Most queries return multi-series
results (`sum by (tool, server, status)` and similar); only
`langgraph.build_duration_avg` and `langgraph.execution_duration_p95`
are scalars.

`ALERTING.md` already sketches an integration pattern for consuming
`kpi_proxy` from `otel-monitor`, but the integration for a KPI display
has not been designed.

## Goal

Add a new top-level tab ("KPIs") to `otel-monitor/` that displays all 11
KPIs in three sections. Data flows through a new Next.js server route
that proxies `kpi_proxy.py`. Each KPI renders as a single Card (snapshot
values; no time-series, no charts).

## Non-goals

- No inline sparklines or time-series charts. `/kpi/{name}/range` is
  not used in this iteration.
- No alerting. `ALERTING.md` is a separate workstream.
- No changes to `kpi_proxy.py` or any Python code in `otel_agent_v2/`.
- No authentication on the new API route — local-dev tool, matches
  `/api/traces` convention.
- No changes to the existing Overview / Traces / Timeline / MCP / Logs
  / Alerts tabs. KPIs are purely additive.

## Architecture

```
kpi_proxy.py (:8900)              ← already exists
       ↑
Next.js server route
  app/api/kpi/route.ts            ← NEW: GET proxies /kpi/all
       ↑
TelemetryContext (lib/store.tsx)
  state.kpiProxy { data, error,   ← NEW slice
                   lastFetchedAt }
       ↑
components/panels/KpiPanel.tsx    ← NEW: 3 sections, 11 Cards
  └─ components/panels/kpi/
        KpiCard.tsx               ← NEW: scalar | multi-series | error
```

Mirrors the existing `/api/traces` → `TelemetryProvider` → `*Panel`
pattern. Going through a server route (rather than browser-direct to
`localhost:8900`) keeps the proxy URL out of client code and matches
the `/api/traces` convention.

## Files

| Path | Role | Notes |
|---|---|---|
| `app/api/kpi/route.ts` | NEW | `GET` handler; reads `process.env.KPI_PROXY_URL` (default `http://localhost:8900`); fetches `/kpi/all`; returns `{data, error}`. |
| `lib/kpi-client.ts` | NEW | Client-side `fetchAllKpis()` helper + type definitions. |
| `lib/store.tsx` | MODIFY | Add `kpiProxy` slice to `TelemetryState`; add `FETCH_KPI_OK` / `FETCH_KPI_ERR` actions; add polling effect gated on tab visibility. |
| `types/telemetry.ts` | MODIFY | Add `KpiProxyEntry`, `KpiProxyState` interfaces. |
| `components/TabBar.tsx` | MODIFY | Add `'kpi'` to `TabId` union; add `{ id: 'kpi', label: 'KPIs' }` entry. |
| `app/page.tsx` | MODIFY | One-line wiring: `{activeTab === 'kpi' && <KpiPanel />}`. Also lifts `activeTab` into `TelemetryContext` OR passes to provider for tab-gated polling (see Polling section). |
| `components/panels/KpiPanel.tsx` | NEW | Three section headers + 11 Cards in a 2-column layout per section (MCP row uses 3 cols since it has 3 KPIs). Shows last-updated timestamp in the header. Shows a full-panel banner if `kpiProxy.error` indicates proxy unreachable. |
| `components/panels/kpi/KpiCard.tsx` | NEW | One card. Renders scalar vs. multi-series vs. error vs. empty states. |

**Why split `KpiCard` from `KpiPanel`:** rendering scalar vs.
multi-series vs. error branches is enough logic that bundling it into
the panel would push the panel past 150 lines and make the cases hard
to reason about separately.

## Data shape

Server route returns a superset of the `kpi_proxy` response:

```ts
// types/telemetry.ts (additions)
export interface KpiProxyEntry {
  area:    'orchestrator' | 'langgraph' | 'mcp';
  title:   string;
  query:   string;
  result?: Array<{
    metric: Record<string, string>;
    value:  [number, string];      // [unix_ts, stringified_float]
  }>;
  error?:  string;
}

export interface KpiProxyState {
  data:            Record<string, KpiProxyEntry> | null;
  fetchError:      string | null;  // null on success, error text when proxy unreachable
  lastFetchedAt:   number | null;  // epoch ms
}
```

`lastFetchedAt` is used by the panel header to show "updated 3s ago"
and by the polling effect to decide when to retry after an error.

## KpiCard rendering rules

| Case | Render |
|---|---|
| `entry.error` truthy | Red badge "query failed" + error text (monospace, line-clamp-3) |
| `result` missing or `[]` | Muted placeholder: "no data yet" |
| `result.length === 1` and `metric` dict is empty | Big centered number: `parseFloat(value[1])` formatted with unit hint derived from KPI name (`_duration` → seconds, `_rate` → "/min", bare → count) |
| `result.length >= 1` with any labels | Mini-table. Columns: one per label key (stable-sorted), last column = value. Max 10 rows. If more, show "+N more" footer. |

Unit-hint derivation is a small lookup keyed on the KPI name:

```ts
const UNIT_HINTS: Record<string, string> = {
  'langgraph.build_duration_avg':      'seconds',
  'langgraph.execution_duration_p95':  'seconds',
  'mcp.duration_p95':                  'seconds',
  'orchestrator.sync_failures_1h':     'errors (1h)',
  // everything else: no unit
};
```

## Polling

- **Interval:** 5 seconds.
- **Gated on tab visibility:** polling effect only runs while `activeTab === 'kpi'`. Rationale: avoids hammering `kpi_proxy` when the user is on another tab. Prometheus scrape intervals are already high-throughput for this data.
- **Tab activation:** when the user switches to the KPI tab, fire one immediate fetch, then start the 5s interval. Clean up interval on tab deactivation.
- **On fetch error:** keep last-successful `data` visible; set `fetchError` on the slice; continue polling (so recovery is automatic).
- **On fetch success:** clear `fetchError`, replace `data`, update `lastFetchedAt`.

Implementation sketch:

```tsx
// lib/store.tsx
useEffect(() => {
  if (activeTab !== 'kpi') return;
  const tick = async () => {
    try {
      const data = await fetchAllKpis();
      dispatch({ type: 'FETCH_KPI_OK', data });
    } catch (e) {
      dispatch({ type: 'FETCH_KPI_ERR', error: String(e) });
    }
  };
  tick();
  const id = setInterval(tick, 5000);
  return () => clearInterval(id);
}, [activeTab]);
```

`activeTab` must be observable to the provider — either lifted into
context, or exposed via a small `useActiveTab()` hook. Choosing the
simpler option: pass `activeTab` into `TelemetryProvider` as a prop
from `page.tsx`.

## Layout

```
┌─────────────────────────────────────────────────────────────────┐
│ KPIs                                    updated 3s ago • retry │
├─────────────────────────────────────────────────────────────────┤
│ DW Orchestrator                                                 │
│ ┌─────────────────┐ ┌─────────────────┐                         │
│ │ active_workers  │ │ state_trans /m  │                         │
│ └─────────────────┘ └─────────────────┘                         │
│ ┌─────────────────┐ ┌─────────────────┐                         │
│ │ errors_total    │ │ sync_failures_1h│                         │
│ └─────────────────┘ └─────────────────┘                         │
│                                                                 │
│ Worker Runner / LangGraph                                       │
│ ┌─────────────────┐ ┌─────────────────┐                         │
│ │ build_duration  │ │ step_rate       │                         │
│ └─────────────────┘ └─────────────────┘                         │
│ ┌─────────────────┐ ┌─────────────────┐                         │
│ │ exec_p95        │ │ step_retries /m │                         │
│ └─────────────────┘ └─────────────────┘                         │
│                                                                 │
│ MCP Tool Server                                                 │
│ ┌──────────┐ ┌──────────┐ ┌──────────┐                          │
│ │ invoc /m │ │ p95      │ │ timeouts │                          │
│ └──────────┘ └──────────┘ └──────────┘                          │
└─────────────────────────────────────────────────────────────────┘
```

- 2×2 grid for orchestrator section
- 2×2 grid for langgraph section
- 1×3 grid for MCP section
- Card styling: reuse `<Card>` and `<SectionHeader>` primitives already
  used in `McpPanel.tsx` and `OverviewPanel.tsx`.
- Panel container: `flex flex-col gap-4 p-4 h-full overflow-y-auto`,
  matching `McpPanel`.

## Error handling

| Failure | Behavior |
|---|---|
| `/api/kpi` returns 5xx (proxy unreachable) | Full-panel banner: "kpi_proxy unreachable at http://localhost:8900. Is it running?" with a retry button. Cards render from last-known `data` if available, otherwise show a skeleton layout with "waiting for data". |
| Proxy returns JSON, but one KPI has `error` field | That card shows red "query failed" badge + error text. Other cards unaffected. |
| Proxy returns `result: []` | Card shows "no data yet" — expected before first request has flowed through the stack. |
| Label schema mismatch (query groups by `worker_type` but Prometheus emits `worker`) | Card shows `result: []` → "no data yet". UI cannot distinguish this from "no traffic yet". Documented as a known limitation. |

## Open defaults (approved)

1. **Tab label:** "KPIs".
2. **Poll interval:** 5 seconds.
3. **Poll gating:** only while KPI tab is active.
4. **Proxy URL:** `process.env.KPI_PROXY_URL` with default `http://localhost:8900`.

## Known limitations

- No time-series view. Users wanting trends should keep using Grafana
  (which scrapes the same Prometheus). A future iteration can add
  sparklines via `/kpi/{name}/range`.
- Label-mismatch "no data" is indistinguishable from "no traffic yet"
  in the UI. Operators must use `curl http://localhost:8000/metrics`
  (and equivalents) to diagnose.
- The polling gate means the data goes stale whenever the user is on
  another tab. On return, the first fetch restores freshness within ~1s.

## Out-of-scope follow-ups

- Time-series sparklines per card (approach B from brainstorming).
- Per-KPI detail drawer that shows the PromQL + range query.
- Alert integration per `ALERTING.md`.
- Shared `<StatRow>` primitive if multi-series display ends up
  duplicated between panels.
