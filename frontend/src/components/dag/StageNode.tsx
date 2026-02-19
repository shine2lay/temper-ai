import { useState } from 'react';
import { Handle, Position } from '@xyflow/react';
import type { NodeProps } from '@xyflow/react';
import { useExecutionStore } from '@/store/executionStore';
import { STATUS_COLORS, STATUS_BG_COLORS } from './constants';
import { formatDuration, formatTokens, formatCost } from '@/lib/utils';
import { AgentCard } from './AgentCard';
import type { StageNodeData } from '@/hooks/useDagElements';

const STRATEGY_DESCRIPTIONS: Record<string, string> = {
  debate: 'Agents debate and refine answers collaboratively',
  sequential: 'Agents execute one after another in order',
  parallel: 'Agents execute simultaneously',
  voting: 'Agents vote on the best answer',
  custom: 'Custom collaboration strategy',
};

/**
 * Custom React Flow node for a stage.
 * Shows one iteration at a time with prev/next navigation when
 * the stage has been executed multiple times (loop-back).
 */
export function StageNode({ data }: NodeProps) {
  const {
    stage,
    iterations,
    iterationCount,
    stageColor,
    strategy,
    totalTokens,
    totalCost,
  } = data as StageNodeData;

  const select = useExecutionStore((s) => s.select);
  const openStageDetail = useExecutionStore((s) => s.openStageDetail);
  const [collapsed, setCollapsed] = useState(false);
  // Default to latest iteration
  const [iterIndex, setIterIndex] = useState(iterationCount - 1);

  // Clamp index if iterations changed
  const safeIndex = Math.min(iterIndex, iterationCount - 1);
  const currentIter = iterations[safeIndex];
  const currentAgents = currentIter?.agents ?? [];
  const currentStage = currentIter?.stage ?? stage;

  const stageName = stage.stage_name ?? stage.name ?? stage.id;
  const borderColor = STATUS_COLORS[currentStage.status] ?? STATUS_COLORS.pending;
  const bgColor = STATUS_BG_COLORS[currentStage.status] ?? STATUS_BG_COLORS.pending;
  const statusDotColor = STATUS_COLORS[currentStage.status] ?? STATUS_COLORS.pending;
  const hasCollaboration = (currentStage.collaboration_events ?? []).length > 0;
  const failedCount = currentStage.num_agents_failed ?? 0;

  return (
    <div
      className="rounded-lg cursor-pointer"
      style={{
        border: `2px solid ${borderColor}`,
        backgroundColor: bgColor,
        minWidth: '260px',
      }}
      role="button"
      tabIndex={0}
      aria-label={`Stage: ${stageName}, status: ${currentStage.status}`}
      onClick={() => select('stage', currentStage.id)}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          select('stage', currentStage.id);
        }
      }}
    >
      {/* Target handle (left) */}
      <Handle
        type="target"
        position={Position.Left}
        id="left"
        className="!bg-maf-border !w-2 !h-2"
      />

      {/* Header */}
      <div className="px-3 py-2 flex items-center gap-2">
        {/* Status dot */}
        <span
          className="w-2.5 h-2.5 rounded-full shrink-0"
          style={{ backgroundColor: statusDotColor }}
        />

        {/* Stage name */}
        <span
          className="text-sm font-bold truncate"
          style={{ color: stageColor }}
        >
          {stageName}
        </span>

        {/* Strategy badge */}
        {strategy && (
          <span
            className="text-[10px] px-1.5 py-0.5 rounded bg-maf-surface text-maf-text-muted shrink-0"
            title={STRATEGY_DESCRIPTIONS[strategy] ?? strategy}
          >
            {strategy}
          </span>
        )}

        {/* Expand into overlay button */}
        <button
          onClick={(e) => {
            e.stopPropagation();
            openStageDetail(currentStage.id);
          }}
          className="text-[10px] px-1.5 py-0.5 rounded bg-maf-surface text-maf-text-muted hover:text-maf-accent hover:bg-maf-accent/10 shrink-0 transition-colors"
          aria-label="Open stage detail view"
          title="Open detailed view"
        >
          &#x2197;
        </button>

        {/* Agent hide toggle */}
        {currentAgents.length > 1 && (
          <button
            onClick={(e) => {
              e.stopPropagation();
              setCollapsed(!collapsed);
            }}
            className="text-[10px] px-1.5 py-0.5 rounded bg-maf-surface text-maf-text-muted hover:text-maf-text shrink-0 ml-auto"
            aria-expanded={!collapsed}
            aria-label={collapsed ? `Show ${currentAgents.length} agents` : 'Hide agents'}
          >
            {collapsed ? `Show ${currentAgents.length}` : 'Hide'}
          </button>
        )}
      </div>

      {/* Iteration picker (only when multiple iterations exist) */}
      {iterationCount > 1 && (
        <div className="px-3 pb-1 flex items-center gap-1.5">
          <button
            onClick={(e) => {
              e.stopPropagation();
              setIterIndex(Math.max(0, safeIndex - 1));
            }}
            disabled={safeIndex === 0}
            className="text-[10px] w-4 h-4 flex items-center justify-center rounded bg-maf-surface text-maf-text-muted hover:text-maf-text disabled:opacity-30 disabled:cursor-default transition-colors"
            aria-label="Previous iteration"
          >
            &#x25C0;
          </button>
          <div className="flex items-center gap-1">
            {iterations.map((iter, i) => {
              const dotColor = STATUS_COLORS[iter.stage.status] ?? STATUS_COLORS.pending;
              return (
                <button
                  key={iter.stage.id}
                  onClick={(e) => {
                    e.stopPropagation();
                    setIterIndex(i);
                  }}
                  className="flex items-center justify-center transition-all"
                  title={`Run ${i + 1}: ${iter.stage.status}`}
                  aria-label={`Iteration ${i + 1}`}
                  aria-pressed={i === safeIndex}
                >
                  <span
                    className="rounded-full shrink-0 transition-all"
                    style={{
                      backgroundColor: dotColor,
                      width: i === safeIndex ? 8 : 6,
                      height: i === safeIndex ? 8 : 6,
                      outline: i === safeIndex ? '2px solid rgba(255,255,255,0.3)' : 'none',
                      outlineOffset: '1px',
                    }}
                  />
                </button>
              );
            })}
          </div>
          <button
            onClick={(e) => {
              e.stopPropagation();
              setIterIndex(Math.min(iterationCount - 1, safeIndex + 1));
            }}
            disabled={safeIndex === iterationCount - 1}
            className="text-[10px] w-4 h-4 flex items-center justify-center rounded bg-maf-surface text-maf-text-muted hover:text-maf-text disabled:opacity-30 disabled:cursor-default transition-colors"
            aria-label="Next iteration"
          >
            &#x25B6;
          </button>
          <span className="text-[10px] text-maf-text-dim ml-1">
            run {safeIndex + 1}/{iterationCount}
          </span>
        </div>
      )}

      {/* Metrics row — show current iteration metrics */}
      <div className="px-3 pb-1 flex items-center gap-3 text-[10px] text-maf-text-muted">
        <span>{currentAgents.length} agent{currentAgents.length !== 1 ? 's' : ''}</span>
        <span>{formatTokens(currentIter?.totalTokens ?? 0)} tok</span>
        <span>{formatCost(currentIter?.totalCost ?? 0)}</span>
        <span>{formatDuration(currentIter?.durationSeconds ?? 0)}</span>
        {hasCollaboration && (
          <span className="text-maf-accent" title="Has collaboration events">
            &#x21C4;
          </span>
        )}
        {failedCount > 0 && (
          <span className="text-red-400">
            {failedCount} failed
          </span>
        )}
        {/* Show aggregate totals when multi-iteration */}
        {iterationCount > 1 && (
          <span className="text-maf-text-dim" title="Total across all iterations">
            ({formatTokens(totalTokens)} / {formatCost(totalCost)} total)
          </span>
        )}
      </div>

      {/* Mini agent status dots (always visible — quick glance) */}
      {currentAgents.length > 0 && (
        <div className="px-3 pb-1.5 flex items-center gap-1 flex-wrap">
          {currentAgents.map((agent) => {
            const dotColor = STATUS_COLORS[agent.status] ?? STATUS_COLORS.pending;
            const name = agent.agent_name ?? agent.name ?? agent.id;
            return (
              <span
                key={agent.id}
                className="w-2 h-2 rounded-full shrink-0"
                style={{ backgroundColor: dotColor }}
                title={`${name}: ${agent.status}`}
              />
            );
          })}
        </div>
      )}

      {/* Compact: vertical agent stack */}
      {!collapsed && (
        <div className="px-2 pb-2 flex flex-col gap-2">
          {currentAgents.map((agent) => (
            <AgentCard key={agent.id} agentId={agent.id} />
          ))}
        </div>
      )}
      {collapsed && (
        <div className="px-2 pb-2 text-[10px] text-maf-text-muted">
          {currentAgents.length} agents
        </div>
      )}

      {/* Error message for failed stages */}
      {currentStage.status === 'failed' && currentStage.error_message && (
        <div className="mx-2 mb-2 px-2 py-1 rounded text-xs bg-red-950/50 text-red-400 border border-red-900/50 truncate">
          {currentStage.error_message}
        </div>
      )}

      {/* Source handle (right — forward flow) */}
      <Handle
        type="source"
        position={Position.Right}
        id="right"
        className="!bg-maf-border !w-2 !h-2"
      />
      {/* Loop source handle (bottom — loop-back out) */}
      <Handle
        type="source"
        position={Position.Bottom}
        id="bottom"
        className="!bg-maf-border !w-2 !h-2"
      />
      {/* Loop target handle (top — loop-back in) */}
      <Handle
        type="target"
        position={Position.Top}
        id="top"
        className="!bg-maf-border !w-2 !h-2"
      />
    </div>
  );
}
