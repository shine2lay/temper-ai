import { useEffect, useMemo, useRef, useState } from 'react';
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
import { LLMCallsTable } from '@/components/layout/LLMCallsTable';
import { ExecutionDAG } from '@/components/dag/ExecutionDAG';
import { LiveStreamBar } from '@/components/dag/LiveStreamBar';
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
  const stages = useExecutionStore((s) => s.stages);
  const eventLog = useExecutionStore((s) => s.eventLog);
  const llmCalls = useExecutionStore((s) => s.llmCalls);
  const prevStatus = useRef(workflow?.status);
  const [activeTab, setActiveTab] = useState('dag');
  const [showShortcutHelp, setShowShortcutHelp] = useState(false);

  // Reset to DAG tab when navigating to a different workflow
  useEffect(() => {
    setActiveTab('dag');
  }, [workflowId]);

  const filteredEventCount = useMemo(
    () => eventLog.filter((e) => e.event_type !== 'llm_stream_batch').length,
    [eventLog],
  );

  useWorkflowWebSocket(workflowId);
  useInitialData(workflowId);
  useKeyboardShortcuts({ onSwitchTab: setActiveTab, onShowHelp: () => setShowShortcutHelp(prev => !prev) });

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
          stageCount={stages.size}
          eventCount={filteredEventCount}
          llmCallCount={llmCalls.size}
          dagContent={
            <ErrorBoundary>
              <div className="relative w-full h-full">
                <ExecutionDAG />
                <LiveStreamBar />
              </div>
            </ErrorBoundary>
          }
          timelineContent={<ErrorBoundary><TimelineChart /></ErrorBoundary>}
          eventLogContent={<ErrorBoundary><EventLogPanel /></ErrorBoundary>}
          llmCallsContent={<ErrorBoundary><LLMCallsTable /></ErrorBoundary>}
        />
        <DetailSheet />
        <StageDetailOverlay />
        {showShortcutHelp && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={() => setShowShortcutHelp(false)}>
            <div className="bg-temper-panel border border-temper-border rounded-lg p-6 shadow-xl max-w-sm" onClick={e => e.stopPropagation()}>
              <h2 className="text-lg font-semibold text-temper-text mb-4">Keyboard Shortcuts</h2>
              <div className="space-y-2 text-sm text-temper-text-muted">
                <div className="flex justify-between"><span>Close panel</span><kbd className="px-2 py-0.5 bg-temper-surface rounded text-xs">Esc</kbd></div>
                <div className="flex justify-between"><span>DAG view</span><kbd className="px-2 py-0.5 bg-temper-surface rounded text-xs">1</kbd></div>
                <div className="flex justify-between"><span>Timeline view</span><kbd className="px-2 py-0.5 bg-temper-surface rounded text-xs">2</kbd></div>
                <div className="flex justify-between"><span>Event log</span><kbd className="px-2 py-0.5 bg-temper-surface rounded text-xs">3</kbd></div>
                <div className="flex justify-between"><span>LLM calls</span><kbd className="px-2 py-0.5 bg-temper-surface rounded text-xs">4</kbd></div>
                <div className="flex justify-between"><span>This help</span><kbd className="px-2 py-0.5 bg-temper-surface rounded text-xs">?</kbd></div>
              </div>
            </div>
          </div>
        )}
      </div>
    </ReactFlowProvider>
  );
}
