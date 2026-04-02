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
  const { agent, stage, stageColor } = data as AgentNodeData;

  if (!agent) return null;

  return (
    <div className="min-w-[250px] max-w-[350px] w-[280px]">
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

      <AgentCardContent agent={agent} borderColor={stageColor} />
    </div>
  );
});
