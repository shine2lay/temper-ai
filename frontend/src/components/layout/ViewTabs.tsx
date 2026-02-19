import { useState, useEffect, useCallback } from 'react';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';

const TAB_STORAGE_KEY = 'maf-active-tab';

interface ViewTabsProps {
  dagContent: React.ReactNode;
  timelineContent: React.ReactNode;
  eventLogContent: React.ReactNode;
  activeTab?: string;
  onTabChange?: (tab: string) => void;
}

export function ViewTabs({
  dagContent,
  timelineContent,
  eventLogContent,
  activeTab: controlledTab,
  onTabChange,
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
          DAG <span className="ml-1 text-[9px] opacity-40 hidden sm:inline">1</span>
        </TabsTrigger>
        <TabsTrigger value="timeline">
          Timeline <span className="ml-1 text-[9px] opacity-40 hidden sm:inline">2</span>
        </TabsTrigger>
        <TabsTrigger value="eventlog">
          Event Log <span className="ml-1 text-[9px] opacity-40 hidden sm:inline">3</span>
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
    </Tabs>
  );
}
