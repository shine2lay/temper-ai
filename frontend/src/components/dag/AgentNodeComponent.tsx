import { memo, useState } from 'react';
import { Handle, Position } from '@xyflow/react';
import type { NodeProps } from '@xyflow/react';
import { AgentCardContent } from './AgentCardContent';
import type { AgentNodeData } from '@/hooks/useDagElements';
import { cn } from '@/lib/utils';

/**
 * React Flow node for an agent-type node (standalone, not inside a stage).
 * Wraps AgentCardContent with ReactFlow handles for edge connections.
 * Shows an iteration picker when the node has multiple runs (loop/retry).
 */
export const AgentNodeComponent = memo(function AgentNodeComponent({ data }: NodeProps) {
  const { agent, stage, stageColor, isDelegate, delegatedBy, iterations } = data as AgentNodeData;
  const [iterIndex, setIterIndex] = useState(iterations ? iterations.length - 1 : 0);

  // No agent (skipped/empty stages): return null
  if (!agent) {
    const name = stage?.name ?? 'skipped';
    const borderColor = stageColor ?? '#6b7280';
    return (
      <div className="w-[200px]">
        <Handle type="target" position={Position.Left} id="left"
          className="!w-2 !h-2 !bg-temper-border !border-temper-bg" />
        <Handle type="source" position={Position.Right} id="right"
          className="!w-2 !h-2 !bg-temper-border !border-temper-bg" />
        <div
          className="rounded-lg px-3 py-2 border-2 border-dashed opacity-50"
          style={{ borderColor }}
        >
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full" style={{ backgroundColor: borderColor }} />
            <span className="text-xs font-medium text-temper-text-dim">{name}</span>
            <span className="text-[9px] px-1 py-px rounded bg-temper-surface text-temper-text-dim">skipped</span>
          </div>
        </div>
      </div>
    );
  }

  // Resolve which agent/stage to display based on selected iteration
  const displayAgent = iterations ? (iterations[iterIndex]?.agent ?? agent) : agent;
  const displayStage = iterations ? (iterations[iterIndex]?.stage ?? stage) : stage;
  const hasIterations = iterations && iterations.length > 1;

  return (
    <div className={`min-w-[250px] max-w-[350px] w-[280px] ${isDelegate ? 'relative' : ''}`}>
      {/* Handles for edges */}
      <Handle type="target" position={Position.Left} id="left"
        className="!w-2 !h-2 !bg-temper-border !border-temper-bg" />
      <Handle type="source" position={Position.Right} id="right"
        className="!w-2 !h-2 !bg-temper-border !border-temper-bg" />
      <Handle type="source" position={Position.Bottom} id="bottom"
        className="!w-0 !h-0 !bg-transparent !border-none" />
      <Handle type="target" position={Position.Bottom} id="bottom-target"
        className="!w-0 !h-0 !bg-transparent !border-none !left-[70%]" />

      {/* Delegate badge */}
      {isDelegate && (
        <div className="absolute -top-3 left-2 z-10 flex items-center gap-1">
          <span className="text-[9px] px-1.5 py-0.5 rounded-sm bg-violet-500/20 text-violet-400 border border-violet-500/30 font-medium">
            sub-agent
          </span>
          {delegatedBy && (
            <span className="text-[9px] text-temper-text-dim">
              via {delegatedBy}
            </span>
          )}
        </div>
      )}

      <AgentCardContent
        agent={displayAgent}
        borderColor={stageColor}
        borderStyle={isDelegate ? 'dashed' : undefined}
      />

      {/* Iteration picker */}
      {hasIterations && (
        <div className="flex items-center justify-between px-2 py-1 bg-temper-surface/80 border-t border-temper-border/30 rounded-b-lg text-[10px]">
          <button
            onClick={(e) => { e.stopPropagation(); setIterIndex(Math.max(0, iterIndex - 1)); }}
            disabled={iterIndex === 0}
            className={cn(
              'px-1.5 py-0.5 rounded transition-colors',
              iterIndex === 0
                ? 'text-temper-text-dim/30 cursor-default'
                : 'text-temper-text-muted hover:text-temper-text hover:bg-temper-surface',
            )}
          >
            &#x25C0;
          </button>
          <span className="text-temper-text-muted">
            Run {iterIndex + 1} / {iterations.length}
          </span>
          <button
            onClick={(e) => { e.stopPropagation(); setIterIndex(Math.min(iterations.length - 1, iterIndex + 1)); }}
            disabled={iterIndex === iterations.length - 1}
            className={cn(
              'px-1.5 py-0.5 rounded transition-colors',
              iterIndex === iterations.length - 1
                ? 'text-temper-text-dim/30 cursor-default'
                : 'text-temper-text-muted hover:text-temper-text hover:bg-temper-surface',
            )}
          >
            &#x25B6;
          </button>
        </div>
      )}
    </div>
  );
});
