'use client';
import { useAlertTicker } from '@/lib/useAlertTicker';

export function AlertProvider({ children }: { children: React.ReactNode }) {
  useAlertTicker();
  return children;
}
