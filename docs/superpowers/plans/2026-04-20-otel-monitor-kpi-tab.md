# otel-monitor KPI Tab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "KPIs" tab to `otel-monitor/` that surfaces all 11 metrics from `otel_agent_v2/kpi_proxy.py` as snapshot cards, polling every 5 seconds while the tab is visible.

**Architecture:** Next.js server route (`/api/kpi`) proxies `http://localhost:8900/kpi/all`. A new `KpiPanel` component polls that route with `useEffect` + `setInterval`, owns local state (no store changes), and renders 11 `KpiProxyCard` components grouped in 3 sections. Scalar vs. multi-series branching lives in `KpiProxyCard`.

**Tech Stack:** Next.js 14 App Router, React 18, TypeScript 5, Tailwind CSS 3, `clsx` for class merging. No new dependencies.

**Conventions:**
- No test suite exists in this codebase. Smoke-verify uses `npx tsc --noEmit` for types and `npm run dev` + browser / `curl` for runtime. Matches the pattern used in `otel_agent_v2/`.
- Repo root: `C:\Users\Charikshith\Downloads\NURO\New folder\W3D\otel_agentv1`. All paths below are relative to it.
- Shell: bash on Windows (forward slashes; `/dev/null` not `NUL`).
- Branch: `main` (user-authorized).
- Each task ends with a single commit. Match the `feat(otel-monitor):` / `docs(otel-monitor):` prefix style already used in the repo.

---

## File structure

```
otel-monitor/
├── types/
│   └── telemetry.ts                          # MODIFY  Task 1
├── app/
│   ├── api/
│   │   └── kpi/
│   │       └── route.ts                      # CREATE  Task 2
│   └── page.tsx                              # MODIFY  Task 6
├── lib/
│   └── kpi-client.ts                         # CREATE  Task 3
└── components/
    ├── TabBar.tsx                            # MODIFY  Task 6
    └── panels/
        ├── KpiPanel.tsx                      # CREATE  Task 5
        └── kpi/
            └── KpiProxyCard.tsx              # CREATE  Task 4
```

Responsibilities:
- `types/telemetry.ts`: adds `KpiProxyEntry` + `KpiProxyResult`. Existing types unchanged.
- `app/api/kpi/route.ts`: pure proxy to `kpi_proxy.py`, 502 on upstream error.
- `lib/kpi-client.ts`: one `fetchAllKpis()` function + unit-hint lookup. Client-side fetch wrapper.
- `components/panels/kpi/KpiProxyCard.tsx`: renders one `KpiProxyEntry`. Handles scalar / multi-series / empty / error branches.
- `components/panels/KpiPanel.tsx`: owns the polling lifecycle (useEffect), groups cards into 3 sections, renders full-panel banner on proxy failure.
- `components/TabBar.tsx`: adds `'kpi'` to `TabId` + one entry in the tabs array.
- `app/page.tsx`: adds `{activeTab === 'kpi' && <KpiPanel />}`.

---

## Task 1: Add `KpiProxy*` types to `types/telemetry.ts`

**Files:**
- Modify: `otel-monitor/types/telemetry.ts`

**Why:** Every later task references these types. Adding them first means subsequent TypeScript checks have something to validate against.

- [ ] **Step 1.1: Append the new types at the bottom of `otel-monitor/types/telemetry.ts`**

Add these interfaces after the existing `KpiState` interface (keep all existing exports untouched):

```ts
// ── KPI proxy (snapshot from otel_agent_v2/kpi_proxy.py) ───────────────────

export type KpiProxyArea = 'orchestrator' | 'langgraph' | 'mcp';

export interface KpiProxyResultRow {
  metric: Record<string, string>;   // e.g. {worker_type: "AddSubAgent"}; {} for scalars
  value:  [number, string];          // [unix_ts, stringified_float]
}

export interface KpiProxyEntry {
  area:    KpiProxyArea;
  title:   string;
  query:   string;
  result?: KpiProxyResultRow[];
  error?:  string;
}

/**
 * Shape returned by /api/kpi. `data` is the raw kpi_proxy response
 * (keyed by KPI name). `error` is set when the proxy itself is unreachable.
 */
export interface KpiProxyResponse {
  data:  Record<string, KpiProxyEntry> | null;
  error: string | null;
}
```

- [ ] **Step 1.2: Type-check the whole project**

Run: `cd otel-monitor && npx tsc --noEmit`
Expected: exits 0 with no output. (Adds types without touching any existing code, so no existing files should newly fail.)

- [ ] **Step 1.3: Commit**

```bash
git add otel-monitor/types/telemetry.ts
git commit -m "feat(otel-monitor): add KpiProxy* types for kpi_proxy integration"
```

---

## Task 2: Create `app/api/kpi/route.ts` server proxy

**Files:**
- Create: `otel-monitor/app/api/kpi/route.ts`

**Why:** Pure server-side fetch hides the `kpi_proxy` URL from client code and matches the existing `/api/traces` pattern. Once this exists, the route can be hit independently of the UI for verification.

- [ ] **Step 2.1: Write `otel-monitor/app/api/kpi/route.ts`**

```ts
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
```

- [ ] **Step 2.2: Type-check**

Run: `cd otel-monitor && npx tsc --noEmit`
Expected: exit 0.

- [ ] **Step 2.3: Smoke-verify the route (dev server)**

Terminal 1 (leave running):
```bash
cd otel-monitor && npm run dev
```
Wait for `Ready in ...`.

Terminal 2 — case A (proxy NOT running):
```bash
curl -s http://localhost:3000/api/kpi | python -m json.tool
```
Expected: JSON `{"error": "kpi_proxy unreachable at http://localhost:8900/kpi/all: ..."}` with HTTP status 502. Confirm status with: `curl -s -o /dev/null -w "%{http_code}" http://localhost:3000/api/kpi` → prints `502`.

Terminal 2 — case B (proxy running; optional): start `python otel_agent_v2/kpi_proxy.py` in another terminal, then re-run the curl. Expect HTTP 200 and JSON with 11 keyed entries. Not required for this task — case A is sufficient to confirm the route is wired.

Stop the dev server (Ctrl+C).

- [ ] **Step 2.4: Commit**

```bash
git add otel-monitor/app/api/kpi/route.ts
git commit -m "feat(otel-monitor): add /api/kpi server route proxying kpi_proxy"
```

---

## Task 3: Create `lib/kpi-client.ts` client helper

**Files:**
- Create: `otel-monitor/lib/kpi-client.ts`

**Why:** Centralises the client-side fetch call and the unit-hint lookup. Keeps `KpiPanel.tsx` free of fetch boilerplate.

- [ ] **Step 3.1: Write `otel-monitor/lib/kpi-client.ts`**

```ts
import type { KpiProxyEntry, KpiProxyResponse } from '@/types/telemetry';

/**
 * Client-side helper that fetches /api/kpi and normalises the response
 * into `{ data, error }`. Never throws — proxy or network failures are
 * reported via the `error` field.
 */
export async function fetchAllKpis(): Promise<KpiProxyResponse> {
  try {
    const res = await fetch('/api/kpi', { cache: 'no-store' });
    const body = await res.json();
    if (!res.ok) {
      const msg = typeof body?.error === 'string' ? body.error : `HTTP ${res.status}`;
      return { data: null, error: msg };
    }
    // body IS the kpi_proxy JSON directly (Record<string, KpiProxyEntry>).
    return { data: body as Record<string, KpiProxyEntry>, error: null };
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    return { data: null, error: msg };
  }
}

/**
 * Unit hint shown under scalar values in KpiProxyCard.
 * Keys are kpi_proxy key names (e.g. `"mcp.duration_p95"`).
 * Missing keys → no unit shown.
 */
export const KPI_UNIT_HINTS: Record<string, string> = {
  'langgraph.build_duration_avg':     'seconds',
  'langgraph.execution_duration_p95': 'seconds',
  'mcp.duration_p95':                 'seconds',
  'orchestrator.sync_failures_1h':    'errors (1h)',
};

/**
 * Section grouping used by KpiPanel. Order determines render order.
 * KPI keys not listed here are rendered in a final "Other" section — but
 * in practice kpi_proxy only emits the 11 keys below.
 */
export const KPI_SECTIONS: Array<{
  title: string;
  cols:  number;
  keys:  string[];
}> = [
  {
    title: 'DW Orchestrator',
    cols:  2,
    keys: [
      'orchestrator.active_workers',
      'orchestrator.state_transitions_rate',
      'orchestrator.errors_total',
      'orchestrator.sync_failures_1h',
    ],
  },
  {
    title: 'Worker Runner / LangGraph',
    cols:  2,
    keys: [
      'langgraph.build_duration_avg',
      'langgraph.step_rate',
      'langgraph.execution_duration_p95',
      'langgraph.step_retries_rate',
    ],
  },
  {
    title: 'MCP Tool Server',
    cols:  3,
    keys: [
      'mcp.invocations_rate',
      'mcp.duration_p95',
      'mcp.timeouts_rate',
    ],
  },
];
```

- [ ] **Step 3.2: Type-check**

Run: `cd otel-monitor && npx tsc --noEmit`
Expected: exit 0.

- [ ] **Step 3.3: Commit**

```bash
git add otel-monitor/lib/kpi-client.ts
git commit -m "feat(otel-monitor): add kpi-client helpers (fetch + section layout)"
```

---

## Task 4: Create `components/panels/kpi/KpiProxyCard.tsx`

**Files:**
- Create: `otel-monitor/components/panels/kpi/KpiProxyCard.tsx`

**Why:** Isolates the scalar-vs-multi-series-vs-error branching. Panel becomes a thin grouping layer in Task 5.

- [ ] **Step 4.1: Write `otel-monitor/components/panels/kpi/KpiProxyCard.tsx`**

```tsx
'use client';
import { Card, SectionHeader, Badge } from '@/components/ui/primitives';
import { KPI_UNIT_HINTS } from '@/lib/kpi-client';
import type { KpiProxyEntry, KpiProxyResultRow } from '@/types/telemetry';

interface Props {
  name:  string;          // e.g. "orchestrator.active_workers"
  entry?: KpiProxyEntry;  // undefined while first fetch is in flight
}

const MAX_ROWS = 10;

function formatValue(raw: string): string {
  const n = parseFloat(raw);
  if (!Number.isFinite(n)) return raw;
  // Show up to 4 significant digits; strip trailing zeros.
  if (Math.abs(n) >= 1000) return n.toFixed(0);
  if (Math.abs(n) >= 1)    return n.toFixed(2).replace(/\.?0+$/, '');
  return n.toPrecision(3);
}

function isScalarRow(row: KpiProxyResultRow): boolean {
  return Object.keys(row.metric).length === 0;
}

export default function KpiProxyCard({ name, entry }: Props) {
  const title = entry?.title ?? name;
  const unit  = KPI_UNIT_HINTS[name];

  // ── Loading: no entry yet ─────────────────────────────────────────────
  if (!entry) {
    return (
      <Card className="p-4">
        <SectionHeader title={title} right={<Badge variant="muted">loading</Badge>} />
        <p className="text-xs font-mono text-text-muted">fetching…</p>
      </Card>
    );
  }

  // ── Error from proxy (per-KPI) ────────────────────────────────────────
  if (entry.error) {
    return (
      <Card className="p-4">
        <SectionHeader title={title} right={<Badge variant="error">query failed</Badge>} />
        <p className="text-[11px] font-mono text-accent-red break-words line-clamp-3">
          {entry.error}
        </p>
      </Card>
    );
  }

  const rows = entry.result ?? [];

  // ── No data (empty result) ────────────────────────────────────────────
  if (rows.length === 0) {
    return (
      <Card className="p-4">
        <SectionHeader title={title} right={<Badge variant="muted">no data</Badge>} />
        <p className="text-xs font-mono text-text-muted">no samples yet</p>
      </Card>
    );
  }

  // ── Scalar: single row with empty labels ──────────────────────────────
  if (rows.length === 1 && isScalarRow(rows[0])) {
    return (
      <Card className="p-4">
        <SectionHeader title={title} />
        <p className="text-2xl font-semibold text-text-primary leading-none">
          {formatValue(rows[0].value[1])}
        </p>
        {unit && (
          <p className="text-[11px] mt-1.5 font-mono text-text-muted">{unit}</p>
        )}
      </Card>
    );
  }

  // ── Multi-series table ────────────────────────────────────────────────
  // Collect the union of label keys across rows, stable-sorted.
  const labelKeys = Array.from(
    new Set(rows.flatMap(r => Object.keys(r.metric))),
  ).sort();
  const shown  = rows.slice(0, MAX_ROWS);
  const hidden = rows.length - shown.length;

  return (
    <Card className="p-4">
      <SectionHeader
        title={title}
        right={<Badge variant="info">{rows.length} series</Badge>}
      />
      <div className="overflow-x-auto">
        <table className="w-full text-[11px] font-mono">
          <thead>
            <tr className="text-text-muted">
              {labelKeys.map(k => (
                <th key={k} className="text-left font-normal pb-1.5 pr-3">{k}</th>
              ))}
              <th className="text-right font-normal pb-1.5">value</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((row, i) => (
              <tr key={i} className="border-t border-bg-border/40">
                {labelKeys.map(k => (
                  <td key={k} className="py-1 pr-3 text-text-secondary">
                    {row.metric[k] ?? '—'}
                  </td>
                ))}
                <td className="py-1 text-right text-text-primary">
                  {formatValue(row.value[1])}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {hidden > 0 && (
        <p className="mt-2 text-[10px] font-mono text-text-muted">+{hidden} more</p>
      )}
    </Card>
  );
}
```

- [ ] **Step 4.2: Type-check**

Run: `cd otel-monitor && npx tsc --noEmit`
Expected: exit 0.

- [ ] **Step 4.3: Commit**

```bash
git add otel-monitor/components/panels/kpi/KpiProxyCard.tsx
git commit -m "feat(otel-monitor): add KpiProxyCard with scalar/multi-series/error branches"
```

---

## Task 5: Create `components/panels/KpiPanel.tsx`

**Files:**
- Create: `otel-monitor/components/panels/KpiPanel.tsx`

**Why:** This is the tab's root component. It owns the polling lifecycle — useEffect starts a 5s interval on mount, clears it on unmount. Because the component is only mounted while the KPI tab is active (`page.tsx` uses conditional rendering), this naturally satisfies the spec's "poll only while tab is active" requirement.

- [ ] **Step 5.1: Write `otel-monitor/components/panels/KpiPanel.tsx`**

```tsx
'use client';
import { useEffect, useState, useCallback } from 'react';
import { Card, SectionHeader, Button, EmptyState } from '@/components/ui/primitives';
import KpiProxyCard from '@/components/panels/kpi/KpiProxyCard';
import { fetchAllKpis, KPI_SECTIONS } from '@/lib/kpi-client';
import type { KpiProxyEntry } from '@/types/telemetry';

const POLL_MS = 5000;

// Static Tailwind class lookup so JIT picks up the classes at build time.
// DO NOT switch this to a template literal — Tailwind cannot see dynamically
// constructed class names.
const GRID_COLS: Record<number, string> = {
  2: 'grid-cols-2',
  3: 'grid-cols-3',
};

function formatAge(ms: number): string {
  const sec = Math.floor(ms / 1000);
  if (sec < 60)  return `${sec}s ago`;
  const min = Math.floor(sec / 60);
  return `${min}m ${sec % 60}s ago`;
}

export default function KpiPanel() {
  const [data, setData]               = useState<Record<string, KpiProxyEntry> | null>(null);
  const [fetchError, setFetchError]   = useState<string | null>(null);
  const [lastFetchedAt, setLastFetchedAt] = useState<number | null>(null);
  const [now, setNow]                 = useState<number>(() => Date.now());

  const tick = useCallback(async () => {
    const { data, error } = await fetchAllKpis();
    if (error) {
      setFetchError(error);
      // Keep last-successful `data` visible.
    } else {
      setData(data);
      setFetchError(null);
      setLastFetchedAt(Date.now());
    }
  }, []);

  useEffect(() => {
    tick(); // immediate fetch on mount
    const id = setInterval(tick, POLL_MS);
    return () => clearInterval(id);
  }, [tick]);

  // Separate 1s interval to refresh the "updated Xs ago" label smoothly.
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  const ageLabel = lastFetchedAt === null
    ? 'never fetched'
    : `updated ${formatAge(now - lastFetchedAt)}`;

  return (
    <div className="flex flex-col gap-4 p-4 h-full overflow-y-auto">
      {/* Top status bar */}
      <div className="flex items-center justify-between flex-shrink-0">
        <span className="text-xs font-mono text-text-muted">
          Snapshot of 11 KPIs from kpi_proxy (localhost:8900). Polling every {POLL_MS / 1000}s.
        </span>
        <span className="flex items-center gap-2">
          <span className="text-[11px] font-mono text-text-muted">{ageLabel}</span>
          <Button size="xs" onClick={tick}>retry</Button>
        </span>
      </div>

      {/* Full-panel banner on proxy unreachable */}
      {fetchError && (
        <Card className="p-3 border-accent-red/40 bg-accent-red/5">
          <p className="text-xs font-mono text-accent-red">
            kpi_proxy error: {fetchError}
          </p>
          <p className="text-[10px] font-mono text-text-muted mt-1">
            Is <code>python otel_agent_v2/kpi_proxy.py</code> running on localhost:8900?
          </p>
        </Card>
      )}

      {/* Empty state: never fetched, no banner yet */}
      {!data && !fetchError && (
        <EmptyState msg="loading KPIs..." />
      )}

      {/* Sections */}
      {data && KPI_SECTIONS.map(section => (
        <section key={section.title} className="flex flex-col gap-3">
          <SectionHeader title={section.title} />
          <div className={`grid gap-3 ${GRID_COLS[section.cols] ?? 'grid-cols-2'}`}>
            {section.keys.map(k => (
              <KpiProxyCard key={k} name={k} entry={data[k]} />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
```

**Note on grid-cols class selection:** Tailwind JIT only ships class names it can statically detect in source. `grid-cols-3` is already used in `McpPanel.tsx:14`, but `grid-cols-2` is not currently in the codebase. The `GRID_COLS` lookup declares both as string literals so JIT picks them up at build. If a future section uses a new `cols` value, add it to `GRID_COLS` with a matching literal class string.

- [ ] **Step 5.2: Type-check**

Run: `cd otel-monitor && npx tsc --noEmit`
Expected: exit 0.

- [ ] **Step 5.3: Commit**

```bash
git add otel-monitor/components/panels/KpiPanel.tsx
git commit -m "feat(otel-monitor): add KpiPanel with 5s polling and 3-section layout"
```

---

## Task 6: Wire the tab into `TabBar.tsx` and `app/page.tsx`

**Files:**
- Modify: `otel-monitor/components/TabBar.tsx`
- Modify: `otel-monitor/app/page.tsx`

**Why:** This activates the panel in the UI. Two tiny edits plus an import.

- [ ] **Step 6.1: Edit `otel-monitor/components/TabBar.tsx`**

Change 1 — `TabId` union. Replace line 5:
```ts
export type TabId = 'overview' | 'traces' | 'timeline' | 'mcp' | 'logs' | 'alerts';
```
with:
```ts
export type TabId = 'overview' | 'traces' | 'timeline' | 'mcp' | 'kpi' | 'logs' | 'alerts';
```

Change 2 — TABS array. Replace lines 7–14:
```ts
const TABS: { id: TabId; label: string }[] = [
  { id: 'overview',  label: 'Overview'  },
  { id: 'traces',    label: 'Traces'    },
  { id: 'timeline',  label: 'Timeline'  },
  { id: 'mcp',       label: 'MCP Tools' },
  { id: 'logs',      label: 'Logs'      },
  { id: 'alerts',    label: 'Alerts'    },
];
```
with:
```ts
const TABS: { id: TabId; label: string }[] = [
  { id: 'overview',  label: 'Overview'  },
  { id: 'traces',    label: 'Traces'    },
  { id: 'timeline',  label: 'Timeline'  },
  { id: 'mcp',       label: 'MCP Tools' },
  { id: 'kpi',       label: 'KPIs'      },
  { id: 'logs',      label: 'Logs'      },
  { id: 'alerts',    label: 'Alerts'    },
];
```

- [ ] **Step 6.2: Edit `otel-monitor/app/page.tsx`**

Change 1 — add the import. Current imports block (lines 3–10):
```ts
import TopBar        from '@/components/TopBar';
import TabBar, { type TabId } from '@/components/TabBar';
import OverviewPanel from '@/components/panels/OverviewPanel';
import TracesPanel   from '@/components/panels/TracesPanel';
import TimelinePanel from '@/components/panels/TimelinePanel';
import McpPanel      from '@/components/panels/McpPanel';
import LogsPanel     from '@/components/panels/LogsPanel';
import AlertsPanel   from '@/components/panels/AlertsPanel';
```

Add one line (after the `McpPanel` import):
```ts
import KpiPanel      from '@/components/panels/KpiPanel';
```

Change 2 — add the conditional render. Current main block (lines 20–27):
```tsx
      <main className="flex-1 overflow-hidden">
        {activeTab === 'overview'  && <OverviewPanel />}
        {activeTab === 'traces'    && <TracesPanel   />}
        {activeTab === 'timeline'  && <TimelinePanel />}
        {activeTab === 'mcp'       && <McpPanel      />}
        {activeTab === 'logs'      && <LogsPanel     />}
        {activeTab === 'alerts'    && <AlertsPanel   />}
      </main>
```

Add one line (after the `McpPanel` line, to match the TabBar order):
```tsx
        {activeTab === 'kpi'       && <KpiPanel      />}
```

Final `main` block should be:
```tsx
      <main className="flex-1 overflow-hidden">
        {activeTab === 'overview'  && <OverviewPanel />}
        {activeTab === 'traces'    && <TracesPanel   />}
        {activeTab === 'timeline'  && <TimelinePanel />}
        {activeTab === 'mcp'       && <McpPanel      />}
        {activeTab === 'kpi'       && <KpiPanel      />}
        {activeTab === 'logs'      && <LogsPanel     />}
        {activeTab === 'alerts'    && <AlertsPanel   />}
      </main>
```

- [ ] **Step 6.3: Type-check**

Run: `cd otel-monitor && npx tsc --noEmit`
Expected: exit 0. TypeScript verifies the `'kpi'` literal is a valid `TabId`.

- [ ] **Step 6.4: Smoke-verify in the browser**

Terminal 1:
```bash
cd otel-monitor && npm run dev
```

Open http://localhost:3000 in a browser. Verify:
1. The tab bar now shows "KPIs" between "MCP Tools" and "Logs".
2. Click "KPIs" — the panel renders with the top status bar ("Polling every 5s") and an error banner if `kpi_proxy.py` isn't running, OR the 3 sections with 11 cards if it is.
3. Click another tab — the panel unmounts (polling stops; confirm by watching `kpi_proxy.py` logs stop receiving requests).
4. Return to KPIs — an immediate fetch happens (not a 5s wait).

If `kpi_proxy.py` is running AND the `otel_agent_v2/` stack has received at least one request, cards should show real data (e.g. `orchestrator.active_workers` with `worker_type` labels). If cards show "no samples yet", fire a request: `curl -X POST http://localhost:8080/run -H 'Content-Type: application/json' -d '{"question":"what is 2+3?"}'` and wait ~5s for the next poll.

Stop the dev server.

- [ ] **Step 6.5: Commit**

```bash
git add otel-monitor/components/TabBar.tsx otel-monitor/app/page.tsx
git commit -m "feat(otel-monitor): wire KPIs tab into TabBar and page router"
```

---

## Summary of what this plan produces

After all 6 tasks:

1. New "KPIs" tab visible in the otel-monitor UI.
2. All 11 KPIs from `otel_agent_v2/kpi_proxy.py` rendered as snapshot cards in 3 sections (4 orchestrator, 4 langgraph, 3 mcp).
3. Live polling every 5 seconds while the tab is active; clean pause when user switches away.
4. Graceful error states: per-KPI query failures (red badge in that card) and whole-proxy unreachable (top banner).
5. 6 discrete commits, one per task, all on `main`.

What's explicitly NOT in this plan (per spec non-goals):
- No time-series sparklines.
- No store changes — KPI state is local to the panel.
- No changes to `kpi_proxy.py` or anything in `otel_agent_v2/`.
- No alerting / email hookup.
- No tests (codebase doesn't have test infrastructure; verification is via `npx tsc --noEmit` + browser smoke).

## Verification-when-done checklist

Run these from the repo root after Task 6 commits:

1. `cd otel-monitor && npx tsc --noEmit` → exit 0
2. `cd otel-monitor && npm run build` → no errors (validates Next.js will actually build the new route and page)
3. Browser check: with `kpi_proxy.py` running and one request fired through `otel_agent_v2/api.py`, KPIs tab shows non-empty cards for at least `mcp.invocations_rate`, `langgraph.step_rate`, `orchestrator.state_transitions_rate`.
4. Browser check: kill `kpi_proxy.py`, switch to KPIs tab, the error banner appears within 5s.
