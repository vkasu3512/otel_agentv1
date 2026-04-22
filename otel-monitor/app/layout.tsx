import type { Metadata } from 'next';
import './globals.css';
import { TelemetryProvider } from '@/lib/store';
import { AlertProvider } from './AlertProvider';

export const metadata: Metadata = {
  title: 'OTel LLM Agent Monitor',
  description: 'OpenTelemetry-based observability dashboard for LLM agents with MCP tools',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="scanline grid-bg">
        <TelemetryProvider>
          <AlertProvider>
            {children}
          </AlertProvider>
        </TelemetryProvider>
      </body>
    </html>
  );
}
