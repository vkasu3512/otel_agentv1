'use client';

import { useEffect, useState } from 'react';

interface Trace {
  traceID: string;
  rootServiceName: string;
  rootTraceName: string;
  startTimeUnixNano: string;
  durationMs: number;
  batches: any[];
}

export default function GrafanaPage() {
  const [traces, setTraces] = useState<Trace[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedTrace, setSelectedTrace] = useState<Trace | null>(null);

  useEffect(() => {
    const fetchTraces = async () => {
      try {
        const res = await fetch('/api/traces');
        const data = await res.json();
        setTraces(data.traces || []);
      } catch (error) {
        console.error('Failed to fetch traces:', error);
      } finally {
        setLoading(false);
      }
    };

    fetchTraces();
    const interval = setInterval(fetchTraces, 5000);
    return () => clearInterval(interval);
  }, []);

  const totalSpans = traces.reduce((sum, t) => {
    const spanCount = t.batches?.reduce((s, b) => {
      return s + (b.scopeSpans?.[0]?.spans?.length || 0);
    }, 0) || 0;
    return sum + spanCount;
  }, 0);

  const avgDuration = traces.length > 0
    ? (traces.reduce((sum, t) => sum + t.durationMs, 0) / traces.length).toFixed(2)
    : 0;

  return (
    <div className="min-h-screen bg-gray-900 text-white p-8">
      {/* Header - Grafana Style */}
      <div className="mb-8">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold text-orange-500">Grafana</h1>
            <p className="text-gray-400 text-sm">Traces Dashboard (Prometheus Backend)</p>
          </div>
          <div className="text-right">
            <p className="text-sm text-gray-400">Last updated: {new Date().toLocaleTimeString()}</p>
          </div>
        </div>
      </div>

      {/* Stats Dashboard */}
      <div className="grid grid-cols-4 gap-4 mb-8">
        <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
          <p className="text-gray-400 text-sm mb-2">Total Traces</p>
          <p className="text-4xl font-bold text-green-400">{traces.length}</p>
        </div>
        <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
          <p className="text-gray-400 text-sm mb-2">Total Spans</p>
          <p className="text-4xl font-bold text-blue-400">{totalSpans}</p>
        </div>
        <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
          <p className="text-gray-400 text-sm mb-2">Avg Duration</p>
          <p className="text-4xl font-bold text-purple-400">{avgDuration}ms</p>
        </div>
        <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
          <p className="text-gray-400 text-sm mb-2">Status</p>
          <p className="text-4xl font-bold text-orange-400">✓</p>
        </div>
      </div>

      {/* Main Content */}
      <div className="grid grid-cols-3 gap-8">
        {/* Traces List */}
        <div className="col-span-2">
          <div className="bg-gray-800 rounded-lg border border-gray-700 overflow-hidden">
            <div className="bg-gray-900 px-6 py-4 border-b border-gray-700">
              <h2 className="text-lg font-semibold">Recent Traces</h2>
            </div>
            <div className="divide-y divide-gray-700 max-h-96 overflow-y-auto">
              {loading ? (
                <div className="p-6 text-center text-gray-400">Loading traces...</div>
              ) : traces.length === 0 ? (
                <div className="p-6 text-center text-gray-400">No traces found</div>
              ) : (
                traces.map((trace) => (
                  <div
                    key={trace.traceID}
                    className="p-4 hover:bg-gray-700 cursor-pointer transition-colors"
                    onClick={() => setSelectedTrace(trace)}
                  >
                    <div className="flex justify-between items-start">
                      <div className="flex-1">
                        <p className="font-mono text-sm text-green-400 truncate">
                          {trace.traceID.substring(0, 40)}...
                        </p>
                        <p className="text-sm text-gray-300">{trace.rootTraceName}</p>
                      </div>
                      <div className="text-right">
                        <p className="font-bold text-blue-400">{trace.durationMs.toFixed(2)}ms</p>
                        <p className="text-xs text-gray-500">{trace.rootServiceName}</p>
                      </div>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>

        {/* Trace Details */}
        <div className="bg-gray-800 rounded-lg border border-gray-700 overflow-hidden">
          <div className="bg-gray-900 px-6 py-4 border-b border-gray-700">
            <h2 className="text-lg font-semibold">Trace Details</h2>
          </div>
          <div className="p-6 max-h-96 overflow-y-auto">
            {selectedTrace ? (
              <div className="space-y-4 text-sm">
                <div>
                  <p className="text-gray-400 mb-1">Trace ID</p>
                  <p className="font-mono text-green-400 truncate text-xs">
                    {selectedTrace.traceID}
                  </p>
                </div>
                <div>
                  <p className="text-gray-400 mb-1">Service</p>
                  <p className="text-gray-200">{selectedTrace.rootServiceName}</p>
                </div>
                <div>
                  <p className="text-gray-400 mb-1">Operation</p>
                  <p className="text-gray-200">{selectedTrace.rootTraceName}</p>
                </div>
                <div>
                  <p className="text-gray-400 mb-1">Duration</p>
                  <p className="text-gray-200">{selectedTrace.durationMs.toFixed(2)}ms</p>
                </div>
                <div>
                  <p className="text-gray-400 mb-1">Spans</p>
                  <p className="text-gray-200">
                    {selectedTrace.batches?.reduce((sum, b) => {
                      return sum + (b.scopeSpans?.[0]?.spans?.length || 0);
                    }, 0) || 0}
                  </p>
                </div>
              </div>
            ) : (
              <p className="text-gray-400 text-center py-8">Select a trace to view details</p>
            )}
          </div>
        </div>
      </div>

      {/* Footer */}
      <div className="mt-8 text-center text-gray-500 text-sm border-t border-gray-700 pt-4">
        <p>Data source: Prometheus | Refresh: Every 5s</p>
      </div>
    </div>
  );
}
