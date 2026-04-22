'use client';
import { useEffect, useRef } from 'react';
import {
  Chart, LineController, LineElement, PointElement,
  CategoryScale, LinearScale, Tooltip, Legend,
} from 'chart.js';
import { useTelemetry } from '@/lib/store';
import { REAL_MCP_TOOLS, REAL_TOOL_COLORS } from '@/lib/tempo-mapper';

Chart.register(LineController, LineElement, PointElement, CategoryScale, LinearScale, Tooltip, Legend);

export default function McpInvocationChart() {
  const { state } = useTelemetry();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const chartRef  = useRef<Chart | null>(null);

  useEffect(() => {
    if (!canvasRef.current) return;
    chartRef.current = new Chart(canvasRef.current, {
      type: 'line',
      data: {
        labels: [],
        datasets: REAL_MCP_TOOLS.map(t => ({
          label: t,
          data: [],
          borderColor: REAL_TOOL_COLORS[t],
          backgroundColor: 'transparent',
          borderWidth: 1.5,
          pointRadius: 2,
          tension: 0.35,
        })),
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        plugins: {
          legend: {
            labels: {
              color: '#7c8599',
              font: { family: 'JetBrains Mono', size: 10 },
              boxWidth: 12, boxHeight: 2, padding: 12,
            },
          },
          tooltip: {
            backgroundColor: '#1a1e28',
            borderColor: 'rgba(255,255,255,0.1)',
            borderWidth: 1,
            titleColor: '#7c8599',
            bodyColor: '#e2e8f0',
          },
        },
        scales: {
          x: { ticks: { display: false }, grid: { color: 'rgba(255,255,255,0.04)' }, border: { color: 'rgba(255,255,255,0.06)' } },
          y: { min: 0, ticks: { color: '#555d70', font: { family: 'JetBrains Mono', size: 10 } }, grid: { color: 'rgba(255,255,255,0.04)' }, border: { color: 'rgba(255,255,255,0.06)' } },
        },
      },
    });
    return () => { chartRef.current?.destroy(); };
  }, []);

  useEffect(() => {
    const c = chartRef.current;
    if (!c) return;
    const maxLen = Math.max(...REAL_MCP_TOOLS.map(t => state.kpi.mcpCalls[t]?.history.length || 0), 0);
    c.data.labels = Array.from({ length: maxLen }, (_, i) => i);
    REAL_MCP_TOOLS.forEach((t, i) => {
      c.data.datasets[i].data = [...(state.kpi.mcpCalls[t]?.history || [])];
    });
    c.update('none');
  }, [state.kpi.mcpCalls]);

  return (
    <div className="relative h-36">
      <canvas ref={canvasRef} />
    </div>
  );
}
