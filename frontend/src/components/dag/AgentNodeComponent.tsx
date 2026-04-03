import { memo } from 'react';
import { Handle, Position } from '@xyflow/react';
import type { NodeProps } from '@xyflow/react';
import { AgentCardContent } from './AgentCardContent';
import type { AgentNodeData } from '@/hooks/useDagElements';

/**
 * React Flow node for an agent-type node (standalone, not inside a stage).
 * Wraps AgentCardContent with ReactFlow handles for edge connections.
 */
export const AgentNodeComponent = memo(function AgentNodeComponent({ data }: NodeProps) {
  const { agent, stage, stageColor, isDelegate, delegatedBy } = data as AgentNodeData;

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
            <span className="text-[8px] px-1 py-px rounded bg-temper-surface text-temper-text-dim">skipped</span>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className={`min-w-[250px] max-w-[350px] w-[280px] ${isDelegate ? 'relative' : ''}`}>
      {/* Handles for edges */}
      <Handle type="target" position={Position.Left} id="left"
        className="!w-2 !h-2 !bg-temper-border !border-temper-bg" />
      <Handle type="source" position={Position.Right} id="right"
        className="!w-2 !h-2 !bg-temper-border !border-temper-bg" />
      {/* Bottom handles only rendered when needed — hidden by default to reduce visual noise */}
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
            <span className="text-[8px] text-temper-text-dim">
              via {delegatedBy}
            </span>
          )}
        </div>
      )}

      <AgentCardContent
        agent={agent}
        borderColor={stageColor}
        borderStyle={isDelegate ? 'dashed' : undefined}
      />
    </div>
  );
});
