/**
 * Right panel router: shows agent, stage, or workflow properties
 * based on current selection state.
 * Priority: agent > stage > workflow.
 */
import { useDesignStore } from '@/store/designStore';
import { WorkflowPropertiesPanel } from './WorkflowPropertiesPanel';
import { StagePropertiesPanel } from './StagePropertiesPanel';
import { AgentPropertiesPanel } from './AgentPropertiesPanel';

export function PropertyPanel() {
  const selectedAgentName = useDesignStore((s) => s.selectedAgentName);
  const selectedStageName = useDesignStore((s) => s.selectedStageName);

  return (
    <div className="h-full overflow-y-auto border-l border-temper-border bg-temper-bg">
      {selectedAgentName ? (
        <AgentPropertiesPanel />
      ) : selectedStageName ? (
        <StagePropertiesPanel />
      ) : (
        <WorkflowPropertiesPanel />
      )}
    </div>
  );
}
