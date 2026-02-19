import { useEffect, useRef, useState } from 'react';
import { useParams } from 'react-router-dom';
import { ReactFlowProvider } from '@xyflow/react';
import { toast } from 'sonner';
import { useWorkflowWebSocket } from '@/hooks/useWorkflowWebSocket';
import { useInitialData } from '@/hooks/useInitialData';
import { useKeyboardShortcuts } from '@/hooks/useKeyboardShortcuts';
import { useExecutionStore } from '@/store/executionStore';
import { WorkflowHeader } from '@/components/layout/WorkflowHeader';
import { WorkflowSummaryBar } from '@/components/layout/WorkflowSummaryBar';
import { ViewTabs } from '@/components/layout/ViewTabs';
import { EventLogPanel } from '@/components/layout/EventLogPanel';
import { ExecutionDAG } from '@/components/dag/ExecutionDAG';
import { TimelineChart } from '@/components/timeline/TimelineChart';
import { DetailSheet } from '@/components/panels/DetailSheet';
import { StageDetailOverlay } from '@/components/stage-detail';
import { ErrorBoundary } from '@/components/shared/ErrorBoundary';

function LoadingSkeleton() {
  return (
    <div className="flex flex-col h-full bg-temper-bg">
      <div className="bg-temper-panel px-4 py-3 border-b border-temper-border shrink-0">
        <div className="skeleton h-6 w-48" />
      </div>
      <div className="flex items-center gap-6 bg-temper-panel/50 px-4 py-2 border-b border-temper-border shrink-0">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="skeleton h-4 w-20" />
        ))}
      </div>
      <div className="flex-1 flex items-center justify-center">
        <div className="flex flex-col items-center gap-3">
          <div className="skeleton h-8 w-8 rounded-full" />
          <span className="text-sm text-temper-text-muted">Loading workflow...</span>
        </div>
      </div>
    </div>
  );
}

export function ExecutionView() {
  const { workflowId } = useParams<{ workflowId: string }>();
  const workflow = useExecutionStore((s) => s.workflow);
  const prevStatus = useRef(workflow?.status);
  const [activeTab, setActiveTab] = useState(() => {
    return localStorage.getItem('temper-active-tab') ?? 'dag';
  });

  useWorkflowWebSocket(workflowId);
  useInitialData(workflowId);
  useKeyboardShortcuts({ onSwitchTab: setActiveTab });

  useEffect(() => {
    if (prevStatus.current === 'running' && workflow?.status === 'completed') {
      toast.success('Workflow completed successfully');
    } else if (prevStatus.current === 'running' && workflow?.status === 'failed') {
      toast.error('Workflow failed');
    }
    prevStatus.current = workflow?.status;
  }, [workflow?.status]);

  if (!workflow) {
    return <LoadingSkeleton />;
  }

  return (
    <ReactFlowProvider>
      <div className="flex flex-col h-full bg-temper-bg">
        <WorkflowHeader />
        <WorkflowSummaryBar />

        <ViewTabs
          activeTab={activeTab}
          onTabChange={setActiveTab}
          dagContent={<ErrorBoundary><ExecutionDAG /></ErrorBoundary>}
          timelineContent={<ErrorBoundary><TimelineChart /></ErrorBoundary>}
          eventLogContent={<ErrorBoundary><EventLogPanel /></ErrorBoundary>}
        />
        <DetailSheet />
        <StageDetailOverlay />
      </div>
    </ReactFlowProvider>
  );
}
