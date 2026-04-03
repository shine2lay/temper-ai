import { useState, useEffect, useCallback } from 'react';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';

const TAB_STORAGE_KEY = 'temper-active-tab';

interface ViewTabsProps {
  dagContent: React.ReactNode;
  timelineContent: React.ReactNode;
  eventLogContent: React.ReactNode;
  llmCallsContent: React.ReactNode;
  checkpointContent?: React.ReactNode;
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
  checkpointContent,
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
          DAG <CountBadge count={stageCount} />
        </TabsTrigger>
        <TabsTrigger value="timeline">
          Timeline
        </TabsTrigger>
        <TabsTrigger value="eventlog">
          Event Log <CountBadge count={eventCount} />
        </TabsTrigger>
        <TabsTrigger value="llmcalls">
          LLM Calls <CountBadge count={llmCallCount} />
        </TabsTrigger>
        {checkpointContent && (
          <TabsTrigger value="checkpoints">
            Checkpoints
          </TabsTrigger>
        )}
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

      {checkpointContent && (
        <TabsContent value="checkpoints" className="flex-1 min-h-0">
          {checkpointContent}
        </TabsContent>
      )}
    </Tabs>
  );
}
