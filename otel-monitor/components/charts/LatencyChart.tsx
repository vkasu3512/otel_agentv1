'use client';
import { useEffect, useRef } from 'react';
import {
  Chart, BarController, BarElement,
  CategoryScale, LinearScale, Tooltip,
} from 'chart.js';
import { useTelemetry } from '@/lib/store';

Chart.register(BarController, BarElement, CategoryScale, LinearScale, Tooltip);

export default function LatencyChart() {
  const { state } = useTelemetry();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const chartRef  = useRef<Chart | null>(null);

  useEffect(() => {
    if (!canvasRef.current) return;
    chartRef.current = new Chart(canvasRef.current, {
      type: 'bar',
      data: {
        labels: [],
        datasets: [{
          label: 'Latency (ms)',
          data: [],
          backgroundColor: 'rgba(79,156,249,0.45)',
          borderColor: '#4f9cf9',
          borderWidth: 1,
          borderRadius: 2,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: '#1a1e28',
            borderColor: 'rgba(255,255,255,0.1)',
            borderWidth: 1,
            titleColor: '#7c8599',
            bodyColor: '#e2e8f0',
            callbacks: { label: ctx => ` ${ctx.raw}ms` },
          },
        },
        scales: {
          x: {
            ticks: { display: false },
            grid: { color: 'rgba(255,255,255,0.04)' },
            border: { color: 'rgba(255,255,255,0.06)' },
          },
          y: {
            ticks: { color: '#555d70', font: { family: 'JetBrains Mono', size: 10 } },
            grid: { color: 'rgba(255,255,255,0.04)' },
            border: { color: 'rgba(255,255,255,0.06)' },
          },
        },
      },
    });
    return () => { chartRef.current?.destroy(); };
  }, []);

  useEffect(() => {
    const c = chartRef.current;
    if (!c) return;
    const lats = state.kpi.latencies;
    c.data.labels   = lats.map((_, i) => i);
    c.data.datasets[0].data = [...lats];
    // Color bars by threshold
    c.data.datasets[0].backgroundColor = lats.map(v =>
      v > 5000 ? 'rgba(248,113,113,0.55)' :
      v > 3000 ? 'rgba(251,191,36,0.55)'  :
                 'rgba(79,156,249,0.45)',
    ) as string[];
    c.update('none');
  }, [state.kpi.latencies]);

  return (
    <div className="relative h-28">
      <canvas ref={canvasRef} />
    </div>
  );
}
