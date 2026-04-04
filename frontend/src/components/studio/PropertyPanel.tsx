/**
 * Right panel router: shows agent or stage properties based on selection.
 * Workflow settings live on the canvas overlay.
 */
import { useDesignStore } from '@/store/designStore';
import { StagePropertiesPanel } from './StagePropertiesPanel';
import { AgentPropertiesPanel } from './AgentPropertiesPanel';

export function PropertyPanel() {
  const selectedAgentName = useDesignStore((s) => s.selectedAgentName);
  const selectedStageName = useDesignStore((s) => s.selectedStageName);

  // No auto-selection for single-agent stages — stage panel shows first
  // so users can access dependencies. Click the agent to edit agent props.

  return (
    <div className="h-full overflow-y-auto border-l border-temper-border bg-temper-bg transition-opacity duration-150">
      {selectedAgentName ? (
        <AgentPropertiesPanel />
      ) : selectedStageName ? (
        <StagePropertiesPanel />
      ) : (
        <EmptyStatePanel />
      )}
    </div>
  );
}

function EmptyStatePanel() {
  const stageCount = useDesignStore((s) => s.stages.length);

  return (
    <div className="flex flex-col items-center justify-center h-full px-4 text-center">
      <div className="w-10 h-10 rounded-full bg-temper-surface flex items-center justify-center mb-3">
        <span className="text-lg text-temper-text-dim">{'\u2190'}</span>
      </div>
      <p className="text-xs text-temper-text-muted">
        {stageCount > 0
          ? 'Click a stage or agent on the canvas to edit its properties'
          : 'Add stages to the canvas to get started'}
      </p>
      <p className="text-[10px] text-temper-text-dim mt-2">
        Edit workflow settings on the canvas overlay
      </p>
    </div>
  );
}
