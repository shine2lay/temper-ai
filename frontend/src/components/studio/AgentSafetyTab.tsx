/**
 * Safety and Memory tabs for AgentPropertiesPanel.
 */
import type { AgentFormState, AgentFieldUpdater } from '@/hooks/useAgentEditor';
import { InlineEdit, InlineToggle } from './InlineEdit';
import { CollapsibleSection, ExpandedField } from './shared';
import { accent } from './agentPanelHelpers';

interface Props {
  config: AgentFormState;
  updateField: AgentFieldUpdater;
}

export function AgentSafetyTab({ config, updateField }: Props) {
  return (
    <>
      {/* Section removed — backend does not implement this yet */}
      {/* Agent-level Safety (mode, risk_level, max_tool_calls_per_execution, max_execution_time_seconds, require_approval_for_tools, max_prompt_length, max_tool_result_size) — safety is workflow-level only */}

      {/* Section removed — backend does not implement this yet */}
      {/* Error Handling (retry_strategy, max_retries, fallback, escalate_to_human_after, retry_initial_delay, retry_max_delay, retry_exponential_base) — stored but never read by the agent */}

      <CollapsibleSection title="Memory" tooltip="Agent memory configuration. Controls episodic memory and knowledge retrieval.">
        <ExpandedField label="Enabled" tip="Activate memory for this agent. When on, the agent can store and recall information across turns and runs.">
          <InlineToggle
            value={config.memory.enabled}
            onChange={(v) => updateField('memory', { ...config.memory, enabled: v })}
            tooltip="Enable memory"
            className={accent(config, 'memory', 'enabled')}
          />
        </ExpandedField>
        {config.memory.enabled && (
          <ExpandedField label="Recall limit" labelWidth="w-24" tip="Number of memory items to retrieve. Maps to recall_limit in the backend.">
            <InlineEdit
              value={config.memory.retrieval_k}
              onChange={(v) => updateField('memory', { ...config.memory, retrieval_k: Number(v) || 10 })}
              type="number"
              className={accent(config, 'memory', 'retrieval_k')}
              min={1}
            />
          </ExpandedField>
        )}
        {/* Section removed — backend does not implement this yet */}
        {/* Removed memory fields: type, scope, provider, namespace, tenant_id, relevance_threshold, embedding_model, max_episodes, decay_factor, auto_extract_procedural, shared_namespace — stored but never read */}
      </CollapsibleSection>
    </>
  );
}
