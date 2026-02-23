import { useState, useEffect, useCallback } from 'react';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';

const TAB_STORAGE_KEY = 'temper-active-tab';

interface ViewTabsProps {
  dagContent: React.ReactNode;
  timelineContent: React.ReactNode;
  eventLogContent: React.ReactNode;
  llmCallsContent: React.ReactNode;
  activeTab?: string;
  onTabChange?: (tab: string) => void;
  stageCount?: number;
  eventCount?: number;
  llmCallCount?: number;
}

function CountBadge({ count }: { count?: number }) {
  if (count == null || count === 0) return null;
  return <span className="ml-1 text-[9px] font-mono opacity-60 tabular-nums">{count}</span>;
}

export function ViewTabs({
  dagContent,
  timelineContent,
  eventLogContent,
  llmCallsContent,
  activeTab: controlledTab,
  onTabChange,
  stageCount,
  eventCount,
  llmCallCount,
}: ViewTabsProps) {
  const [internalTab, setInternalTab] = useState(() => {
    return localStorage.getItem(TAB_STORAGE_KEY) ?? 'dag';
  });

  const activeTab = controlledTab ?? internalTab;

  const handleChange = useCallback(
    (tab: string) => {
      setInternalTab(tab);
      onTabChange?.(tab);
    },
    [onTabChange],
  );

  useEffect(() => {
    localStorage.setItem(TAB_STORAGE_KEY, activeTab);
  }, [activeTab]);

  return (
    <Tabs value={activeTab} onValueChange={handleChange} className="flex-1 flex flex-col min-h-0">
      <TabsList className="mx-4 mt-2">
        <TabsTrigger value="dag">
          DAG <CountBadge count={stageCount} /> <span className="ml-1 text-[10px] opacity-50 hidden sm:inline">1</span>
        </TabsTrigger>
        <TabsTrigger value="timeline">
          Timeline <span className="ml-1 text-[10px] opacity-50 hidden sm:inline">2</span>
        </TabsTrigger>
        <TabsTrigger value="eventlog">
          Event Log <CountBadge count={eventCount} /> <span className="ml-1 text-[10px] opacity-50 hidden sm:inline">3</span>
        </TabsTrigger>
        <TabsTrigger value="llmcalls">
          LLM Calls <CountBadge count={llmCallCount} /> <span className="ml-1 text-[10px] opacity-50 hidden sm:inline">4</span>
        </TabsTrigger>
      </TabsList>

      <TabsContent value="dag" className="flex-1 min-h-0">
        {dagContent}
      </TabsContent>

      <TabsContent value="timeline" className="flex-1 min-h-0">
        {timelineContent}
      </TabsContent>

      <TabsContent value="eventlog" className="flex-1 min-h-0">
        {eventLogContent}
      </TabsContent>

      <TabsContent value="llmcalls" className="flex-1 min-h-0">
        {llmCallsContent}
      </TabsContent>
    </Tabs>
  );
}
