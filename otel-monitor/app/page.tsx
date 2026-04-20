'use client';
import { useState } from 'react';
import TopBar        from '@/components/TopBar';
import TabBar, { type TabId } from '@/components/TabBar';
import OverviewPanel from '@/components/panels/OverviewPanel';
import TracesPanel   from '@/components/panels/TracesPanel';
import TimelinePanel from '@/components/panels/TimelinePanel';
import McpPanel      from '@/components/panels/McpPanel';
import KpiPanel      from '@/components/panels/KpiPanel';
import LogsPanel     from '@/components/panels/LogsPanel';
import AlertsPanel   from '@/components/panels/AlertsPanel';

export default function Home() {
  const [activeTab, setActiveTab] = useState<TabId>('overview');

  return (
    <div className="flex flex-col h-screen overflow-hidden">
      <TopBar />
      <TabBar active={activeTab} onChange={setActiveTab} />

      <main className="flex-1 overflow-hidden">
        {activeTab === 'overview'  && <OverviewPanel />}
        {activeTab === 'traces'    && <TracesPanel   />}
        {activeTab === 'timeline'  && <TimelinePanel />}
        {activeTab === 'mcp'       && <McpPanel      />}
        {activeTab === 'kpi'       && <KpiPanel      />}
        {activeTab === 'logs'      && <LogsPanel     />}
        {activeTab === 'alerts'    && <AlertsPanel   />}
      </main>
    </div>
  );
}
