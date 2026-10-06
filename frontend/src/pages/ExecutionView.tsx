import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { AlertCircle } from 'lucide-react';
import { ReactFlowProvider } from '@xyflow/react';
import { toast } from 'sonner';
import { useWorkflowWebSocket } from '@/hooks/useWorkflowWebSocket';
import { useInitialData } from '@/hooks/useInitialData';
import { useAgentLookup } from '@/hooks/useAgentLookup';
import { useKeyboardShortcuts } from '@/hooks/useKeyboardShortcuts';
import { useExecutionStore } from '@/store/executionStore';
import { isGoing } from '@/lib/runStatus';
import { WorkflowHeader } from '@/components/layout/WorkflowHeader';
import { WorkflowSummaryBar } from '@/components/layout/WorkflowSummaryBar';
import { GateModal } from '@/components/layout/GateModal';
import { ViewTabs } from '@/components/layout/ViewTabs';
import { EventLogPanel } from '@/components/layout/EventLogPanel';
import { LLMCallsTable } from '@/components/layout/LLMCallsTable';
import { ExecutionDAG } from '@/components/dag/ExecutionDAG';
import { LivePanel } from '@/components/live/LivePanel';
import { TimelineChart } from '@/components/timeline/TimelineChart';
import { BigView } from '@/components/bigview/BigView';
import { CheckpointPanel } from '@/components/layout/CheckpointPanel';
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
  const { error: loadError } = useInitialData(workflowId);
  useAgentLookup(workflowId);
  useKeyboardShortcuts({ onSwitchTab: setActiveTab, onShowHelp: () => setShowShortcutHelp(prev => !prev) });

  useEffect(() => {
    const was = prevStatus.current;
    const now = workflow?.status;
    if (was && was !== now && (isGoing(was) || was === 'queued')) {
      if (now === 'completed') toast.success('Workflow completed successfully');
      else if (now === 'failed') toast.error('Workflow failed');
      else if (now === 'cancelled') toast.info('Workflow cancelled');
    }
    prevStatus.current = now;
  }, [workflow?.status]);

  // Per-route document title (it used to read "Execution View" everywhere).
  useEffect(() => {
    document.title = workflow
      ? `Temper AI — ${workflow.workflow_name}`
      : 'Temper AI — Workflow';
    return () => {
      document.title = 'Temper AI';
    };
  }, [workflow?.workflow_name, workflow]);

  // A run that cannot be loaded (bad link, deleted history, API down) used to
  // sit on the loading skeleton forever, with the reason only in the console.
  if (!workflow && loadError) {
    return (
      <div className="flex flex-col h-full bg-temper-bg items-center justify-center gap-3 p-6 text-center">
        <AlertCircle className="size-8 text-temper-failed" aria-hidden />
        <h1 className="text-lg font-semibold text-temper-text">Run not found</h1>
        <p className="text-sm text-temper-text-muted max-w-md">
          No run with id <code className="font-mono text-xs">{workflowId}</code>.
          It may have been removed, or the link may be wrong.
        </p>
        <p className="text-xs text-temper-text-dim">{loadError.message}</p>
        <Link
          to="/"
          className="mt-1 px-3 py-1.5 rounded-md text-xs font-medium bg-temper-surface border border-temper-border text-temper-text hover:bg-temper-surface/80"
        >
          Back to workflows
        </Link>
      </div>
    );
  }

  if (!workflow) {
    return <LoadingSkeleton />;
  }

  return (
    <ReactFlowProvider>
      {/* One box per part of the run view. A run that is still growing can
          hand any one of them something it cannot draw; when that happens the
          part says so and the rest of the page carries on, instead of the
          whole page going white in the middle of the run. */}
      <div className="flex flex-col h-full bg-temper-bg">
        <ErrorBoundary label="The run's title bar" resetKey={workflowId}>
          <WorkflowHeader />
        </ErrorBoundary>
        <ErrorBoundary label="The run's totals" resetKey={workflowId}>
          <WorkflowSummaryBar />
        </ErrorBoundary>

        <ViewTabs
          activeTab={activeTab}
          onTabChange={setActiveTab}
          stageCount={stages.size}
          eventCount={filteredEventCount}
          llmCallCount={llmCalls.size}
          dagContent={
            <div className="relative w-full h-full">
              {/* The picture and the live panel break separately: a bad
                  agent in the panel must not take the graph with it. */}
              <ErrorBoundary label="The run's picture" resetKey={workflowId}>
                <ExecutionDAG />
              </ErrorBoundary>
              <ErrorBoundary label="The live panel" resetKey={workflowId}>
                <LivePanel />
              </ErrorBoundary>
            </div>
          }
          timelineContent={<ErrorBoundary label="The timeline" resetKey={workflowId}><TimelineChart /></ErrorBoundary>}
          eventLogContent={<ErrorBoundary label="The event log" resetKey={workflowId}><EventLogPanel /></ErrorBoundary>}
          llmCallsContent={<ErrorBoundary label="The model calls" resetKey={workflowId}><LLMCallsTable /></ErrorBoundary>}
          checkpointContent={<ErrorBoundary label="The checkpoints" resetKey={workflowId}><CheckpointPanel onSwitchTab={setActiveTab} /></ErrorBoundary>}
        />
        <ErrorBoundary label="The full-screen view" resetKey={workflowId}>
          <BigView />
        </ErrorBoundary>
        <ErrorBoundary label="The gate" resetKey={workflowId}>
          <GateModal executionId={workflowId} />
        </ErrorBoundary>
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
                <div className="flex justify-between"><span>Checkpoints</span><kbd className="px-2 py-0.5 bg-temper-surface rounded text-xs">5</kbd></div>
                <div className="flex justify-between"><span>This help</span><kbd className="px-2 py-0.5 bg-temper-surface rounded text-xs">?</kbd></div>
              </div>
            </div>
          </div>
        )}
      </div>
    </ReactFlowProvider>
  );
}
