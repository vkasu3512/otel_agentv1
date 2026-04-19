'use client';
import clsx from 'clsx';
import { useTelemetry } from '@/lib/store';

export type TabId = 'overview' | 'traces' | 'timeline' | 'mcp' | 'logs' | 'alerts';

const TABS: { id: TabId; label: string }[] = [
  { id: 'overview',  label: 'Overview'  },
  { id: 'traces',    label: 'Traces'    },
  { id: 'timeline',  label: 'Timeline'  },
  { id: 'mcp',       label: 'MCP Tools' },
  { id: 'logs',      label: 'Logs'      },
  { id: 'alerts',    label: 'Alerts'    },
];

interface Props {
  active: TabId;
  onChange: (id: TabId) => void;
}

export default function TabBar({ active, onChange }: Props) {
  const { state } = useTelemetry();
  const alertCount = state.alerts.length;

  return (
    <nav className="flex items-end gap-0 px-5 bg-bg-secondary border-b border-bg-border flex-shrink-0">
      {TABS.map(tab => (
        <button
          key={tab.id}
          onClick={() => onChange(tab.id)}
          className={clsx(
            'relative flex items-center gap-1.5 px-4 py-2.5 text-xs font-mono transition-all duration-150 border-b-2 -mb-px whitespace-nowrap',
            active === tab.id
              ? 'text-accent-blue border-accent-blue'
              : 'text-text-muted border-transparent hover:text-text-secondary hover:border-bg-border-mid',
          )}
        >
          {tab.label}
          {tab.id === 'alerts' && alertCount > 0 && (
            <span className="inline-flex items-center justify-center w-4 h-4 rounded-full bg-accent-red/20 text-accent-red text-[10px] font-bold">
              {alertCount > 9 ? '9+' : alertCount}
            </span>
          )}
        </button>
      ))}
    </nav>
  );
}
