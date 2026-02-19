import { useMemo } from 'react';
import { useExecutionStore } from '@/store/executionStore';
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from '@/components/ui/sheet';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { StatusBadge } from '@/components/shared/StatusBadge';
import { Badge } from '@/components/ui/badge';
import { ErrorBoundary } from '@/components/shared/ErrorBoundary';
import { formatDuration, formatTokens, formatCost, ensureUTC } from '@/lib/utils';
import { GanttTimeline } from './GanttTimeline';
import { AgentRow } from './AgentRow';
import { CollaborationTimeline } from './CollaborationTimeline';
import { LogsTab } from './LogsTab';
import { OutputsTab } from './OutputsTab';
import { MetricsTab } from './MetricsTab';
import type { AgentExecution } from '@/types';

const STRATEGY_LABELS: Record<string, string> = {
  debate: 'Debate',
  sequential: 'Sequential',
  parallel: 'Parallel',
  voting: 'Voting',
  custom: 'Custom',
};

/**
 * Full-width bottom sheet overlay for stage detail inspection.
 * Combines Kestra-style tabs with Gantt timeline, expandable agent rows,
 * dual-mode logs, output comparison, and per-agent metrics.
 *
 * Triggered by the expand button on StageNode (replaces inline expansion).
 */
export function StageDetailOverlay() {
  const stageDetailId = useExecutionStore((s) => s.stageDetailId);
  const closeStageDetail = useExecutionStore((s) => s.closeStageDetail);
  const stage = useExecutionStore((s) =>
    s.stageDetailId ? s.stages.get(s.stageDetailId) : undefined,
  );
  const allAgents = useExecutionStore((s) => s.agents);

  // Derive resolved + sorted agents via useMemo (not in selector — selectors
  // must return stable references to avoid useSyncExternalStore infinite loops)
  const agents = useMemo(() => {
    if (!stage?.agents) return [] as AgentExecution[];
    return stage.agents
      .map((a) => allAgents.get(a.id) ?? a)
      .sort((a, b) => {
        if (!a.start_time) return 1;
        if (!b.start_time) return -1;
        return ensureUTC(a.start_time).localeCompare(ensureUTC(b.start_time));
      });
  }, [stage, allAgents]);

  const open = !!stageDetailId && !!stage;

  const strategy = stage?.stage_config_snapshot?.stage?.collaboration?.strategy
    ?? stage?.stage_config_snapshot?.stage?.execution?.agent_mode;

  const collabEvents = stage?.collaboration_events ?? [];
  const { totalTokens, totalCost } = useMemo(() => ({
    totalTokens: agents.reduce((sum, a) => sum + (a.total_tokens ?? 0), 0),
    totalCost: agents.reduce((sum, a) => sum + (a.estimated_cost_usd ?? 0), 0),
  }), [agents]);

  return (
    <Sheet open={open} onOpenChange={(isOpen) => !isOpen && closeStageDetail()}>
      <SheetContent
        side="bottom"
        className="h-[78vh] flex flex-col rounded-t-xl overflow-hidden"
        onOpenAutoFocus={(e) => e.preventDefault()}
      >
        {stage && (
          <>
            {/* Header bar */}
            <SheetHeader className="shrink-0 pb-0">
              <div className="flex items-center gap-3 flex-wrap">
                <SheetTitle className="text-lg font-bold text-maf-text">
                  {stage.stage_name ?? stage.name ?? stageDetailId}
                </SheetTitle>
                <StatusBadge status={stage.status} />
                {strategy && (
                  <Badge variant="secondary" className="text-xs">
                    {STRATEGY_LABELS[strategy] ?? strategy}
                  </Badge>
                )}
                {stage.stage_type && (
                  <Badge variant="outline" className="text-xs">
                    {stage.stage_type}
                  </Badge>
                )}
              </div>
              <SheetDescription className="sr-only">
                Detailed view of stage {stage.stage_name}
              </SheetDescription>

              {/* Summary metrics */}
              <div className="flex items-center gap-4 mt-1 text-xs text-maf-text-muted">
                <span>{agents.length} agent{agents.length !== 1 ? 's' : ''}</span>
                <span>{formatDuration(stage.duration_seconds)}</span>
                <span>{formatTokens(totalTokens)} tokens</span>
                <span>{formatCost(totalCost)}</span>
                {(stage.num_agents_failed ?? 0) > 0 && (
                  <span className="text-red-400">
                    {stage.num_agents_failed} failed
                  </span>
                )}
              </div>
            </SheetHeader>

            {/* Tabbed content */}
            <Tabs defaultValue="overview" className="flex-1 flex flex-col min-h-0 px-4 pb-4">
              <TabsList variant="line" className="shrink-0 mb-3">
                <TabsTrigger value="overview">Overview</TabsTrigger>
                <TabsTrigger value="logs">
                  Logs
                </TabsTrigger>
                <TabsTrigger value="outputs">Outputs</TabsTrigger>
                <TabsTrigger value="metrics">Metrics</TabsTrigger>
              </TabsList>

              {/* === Overview tab === */}
              <TabsContent value="overview" className="flex-1 overflow-y-auto min-h-0">
                <ErrorBoundary>
                  <div className="flex flex-col gap-4">
                    {/* Gantt Timeline */}
                    <div className="rounded-lg border border-maf-border/30 bg-maf-panel/30 p-3">
                      <GanttTimeline
                        agents={agents}
                        stageDurationSeconds={stage.duration_seconds}
                        stageStartTime={stage.start_time}
                      />
                    </div>

                    {/* Collaboration events (if any) */}
                    {collabEvents.length > 0 && (
                      <div className="rounded-lg border border-maf-border/30 bg-maf-panel/30 p-3">
                        <CollaborationTimeline
                          events={collabEvents}
                          agents={agents}
                          strategy={strategy}
                        />
                      </div>
                    )}

                    {/* Agent rows */}
                    <div className="flex flex-col gap-2">
                      <span className="text-xs font-medium text-maf-text-muted px-1">
                        Agents ({agents.length})
                      </span>
                      {agents.map((agent) => (
                        <AgentRow key={agent.id} agentId={agent.id} />
                      ))}
                    </div>
                  </div>
                </ErrorBoundary>
              </TabsContent>

              {/* === Logs tab === */}
              <TabsContent value="logs" className="flex-1 overflow-y-auto min-h-0">
                <ErrorBoundary>
                  <LogsTab agents={agents} />
                </ErrorBoundary>
              </TabsContent>

              {/* === Outputs tab === */}
              <TabsContent value="outputs" className="flex-1 overflow-y-auto min-h-0">
                <ErrorBoundary>
                  <OutputsTab
                    agents={agents}
                    stageOutputData={stage.output_data}
                    strategy={strategy}
                  />
                </ErrorBoundary>
              </TabsContent>

              {/* === Metrics tab === */}
              <TabsContent value="metrics" className="flex-1 overflow-y-auto min-h-0">
                <ErrorBoundary>
                  <MetricsTab
                    agents={agents}
                    stageDurationSeconds={stage.duration_seconds}
                  />
                </ErrorBoundary>
              </TabsContent>
            </Tabs>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}
