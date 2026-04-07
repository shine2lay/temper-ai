import { memo } from 'react';
import { Handle, Position } from '@xyflow/react';
import type { NodeProps } from '@xyflow/react';
import { useExecutionStore } from '@/store/executionStore';
import { STATUS_COLORS } from './constants';
import { cn, formatDuration, formatTokens, formatCost } from '@/lib/utils';
import type { StageNodeData } from '@/hooks/useDagElements';

const STRATEGY_LABELS: Record<string, string> = {
  parallel: '⚡ parallel',
  sequential: '→ sequential',
  leader: '👑 leader',
  delegate: '🔀 delegated',
};

/**
 * Stage group node — renders as a container in the DAG.
 * Child agent nodes are rendered by ReactFlow inside this container
 * via parentId grouping. This component only renders the header/chrome.
 */
export const StageGroupNode = memo(function StageGroupNode({ data }: NodeProps) {
  const {
    stage,
    stageColor,
    strategy,
    totalTokens,
    totalCost,
    durationSeconds,
    delegateCount,
  } = data as StageNodeData;

  const select = useExecutionStore((s) => s.select);
  const statusColor = STATUS_COLORS[stage.status] ?? STATUS_COLORS.pending;
  const stageName = stage.name ?? stage.stage_name ?? stage.id;
  const agents = stage.agents ?? [];

  const showCost = totalCost > 0;
  const agentLabel = delegateCount
    ? `${agents.length} agent + ${delegateCount} sub-agent${delegateCount > 1 ? 's' : ''}`
    : `${agents.length} agents`;
  const isRunning = stage.status === 'running';

  return (
    <div
      className={cn(
        'rounded-xl w-full h-full relative',
        !isRunning && 'border-2',
      )}
      style={{
        borderColor: isRunning ? 'transparent' : stageColor,
        backgroundColor: `color-mix(in srgb, ${stageColor} 4%, transparent)`,
      }}
      role="button"
      tabIndex={0}
      onClick={() => select('stage', stage.id)}
      onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); select('stage', stage.id); } }}
    >
      {/* Handles */}
      <Handle type="target" position={Position.Left} id="left"
        className="!w-2 !h-2 !bg-temper-border !border-temper-bg" />
      <Handle type="source" position={Position.Right} id="right"
        className="!w-2 !h-2 !bg-temper-border !border-temper-bg" />
      <Handle type="source" position={Position.Bottom} id="bottom"
        className="!w-2 !h-2 !bg-temper-border !border-temper-bg" />
      <Handle type="target" position={Position.Bottom} id="bottom-target"
        className="!w-2 !h-2 !bg-temper-border !border-temper-bg !left-[70%]" />

      {/* Animated dashed border for running stages */}
      {isRunning && (
        <svg className="absolute inset-0 w-full h-full pointer-events-none z-10" overflow="visible">
          <rect
            x="0" y="0" width="100%" height="100%"
            rx="12" ry="12"
            fill="none"
            stroke={stageColor}
            strokeWidth="2.5"
            strokeDasharray="16 8"
            className="dag-stage-running-border"
          />
        </svg>
      )}

      {/* Colored header banner */}
      <div
        className="px-3 py-1.5 flex items-center gap-2 rounded-t-[10px]"
        style={{ backgroundColor: `color-mix(in srgb, ${stageColor} 12%, transparent)` }}
      >
        <span
          className="w-2 h-2 rounded-full shrink-0"
          style={{ backgroundColor: statusColor }}
        />
        <span className="text-sm font-bold truncate" style={{ color: stageColor }}>
          {stageName}
        </span>
        {strategy && (
          <span
            className="text-[10px] px-1.5 py-0.5 rounded shrink-0 font-medium"
            style={{ backgroundColor: `color-mix(in srgb, ${stageColor} 15%, transparent)`, color: stageColor }}
          >
            {STRATEGY_LABELS[strategy] ?? strategy}
          </span>
        )}
      </div>

      {/* Metrics row */}
      <div className="px-3 py-1 flex items-center gap-2 text-[10px] text-temper-text-muted border-b border-temper-border/10">
        <span>{agentLabel}</span>
        <span className="text-temper-border/40">|</span>
        <span>{formatTokens(totalTokens)} tok</span>
        {showCost && (
          <>
            <span className="text-temper-border/40">|</span>
            <span>{formatCost(totalCost)}</span>
          </>
        )}
        <span className="text-temper-border/40">|</span>
        <span>{formatDuration(durationSeconds)}</span>
      </div>

      {/* Child nodes render here via ReactFlow's parentId grouping */}
    </div>
  );
});
