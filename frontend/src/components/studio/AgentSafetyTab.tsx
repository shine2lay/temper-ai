/**
 * Safety and Memory tabs for AgentPropertiesPanel.
 */
import type { AgentFormState, AgentFieldUpdater } from '@/hooks/useAgentEditor';
import { InlineEdit, InlineSelect, InlineToggle } from './InlineEdit';
import { CollapsibleSection, ExpandedField, CompactArrayEditor } from './shared';
import { accent, safetyModeOptions, riskOptions } from './agentPanelHelpers';

interface Props {
  config: AgentFormState;
  updateField: AgentFieldUpdater;
}

export function AgentSafetyTab({ config, updateField }: Props) {
  return (
    <>
      <CollapsibleSection title="Safety" tooltip="Controls what actions this agent is allowed to take. Mode, risk level, execution limits, and tool approval requirements.">
        <ExpandedField label="Mode" tip="Execute: run actions for real. Monitor: log but block. Audit: require human approval.">
          <InlineSelect
            value={config.safety.mode}
            options={safetyModeOptions}
            onChange={(v) => updateField('safety', { ...config.safety, mode: v })}
            tooltip="Safety mode"
            className={accent(config, 'safety', 'mode')}
          />
        </ExpandedField>
        <ExpandedField label="Risk" tip="Risk classification. Affects safety policy behavior and audit trail verbosity.">
          <InlineSelect
            value={config.safety.risk_level}
            options={riskOptions}
            onChange={(v) => updateField('safety', { ...config.safety, risk_level: v })}
            tooltip="Risk level"
            className={accent(config, 'safety', 'risk_level')}
          />
        </ExpandedField>
        <ExpandedField label="Max calls" labelWidth="w-20" tip="Maximum tool calls per execution cycle. Prevents runaway agents from consuming excessive resources.">
          <InlineEdit
            value={config.safety.max_tool_calls_per_execution}
            onChange={(v) => updateField('safety', { ...config.safety, max_tool_calls_per_execution: Number(v) || 0 })}
            type="number"
            className={accent(config, 'safety', 'max_tool_calls_per_execution')}
            min={0}
          />
        </ExpandedField>
        <ExpandedField label="Max time" labelWidth="w-20" tip="Maximum execution time in seconds before the agent is killed.">
          <InlineEdit
            value={config.safety.max_execution_time_seconds}
            onChange={(v) => updateField('safety', { ...config.safety, max_execution_time_seconds: Number(v) || 0 })}
            type="number"
            className={accent(config, 'safety', 'max_execution_time_seconds')}
            min={0}
          />
          <span className="text-[9px] text-temper-text-dim ml-1">s</span>
        </ExpandedField>
        <ExpandedField label="Approve" labelWidth="w-20" tip="Tools that require human approval before execution. List tool names that should pause for sign-off.">
          <CompactArrayEditor
            values={config.safety.require_approval_for_tools}
            onChange={(v) => updateField('safety', { ...config.safety, require_approval_for_tools: v })}
            placeholder="tool name"
          />
        </ExpandedField>
        <ExpandedField label="Max prompt" labelWidth="w-20" tip="Maximum prompt length in characters. Prompts exceeding this are truncated or rejected.">
          <InlineEdit
            value={config.safety.max_prompt_length}
            onChange={(v) => updateField('safety', { ...config.safety, max_prompt_length: Number(v) || 100000 })}
            type="number"
            className={accent(config, 'safety', 'max_prompt_length')}
            min={0}
          />
        </ExpandedField>
        <ExpandedField label="Max result" labelWidth="w-20" tip="Maximum tool result size in bytes. Results exceeding this are truncated.">
          <InlineEdit
            value={config.safety.max_tool_result_size}
            onChange={(v) => updateField('safety', { ...config.safety, max_tool_result_size: Number(v) || 65536 })}
            type="number"
            className={accent(config, 'safety', 'max_tool_result_size')}
            min={0}
          />
        </ExpandedField>
      </CollapsibleSection>

      <CollapsibleSection title="Memory" tooltip="Agent memory configuration. Controls episodic memory, knowledge retrieval, and cross-workflow sharing.">
        <ExpandedField label="Enabled" tip="Activate memory for this agent. When on, the agent can store and recall information across turns and runs.">
          <InlineToggle
            value={config.memory.enabled}
            onChange={(v) => updateField('memory', { ...config.memory, enabled: v })}
            tooltip="Enable memory"
            className={accent(config, 'memory', 'enabled')}
          />
        </ExpandedField>
        {config.memory.enabled && (
          <>
            <ExpandedField label="Type" tip="Memory backend type: conversation, knowledge_graph, hybrid.">
              <InlineEdit
                value={config.memory.type}
                onChange={(v) => updateField('memory', { ...config.memory, type: String(v ?? '') })}
                placeholder="conversation"
                className={accent(config, 'memory', 'type')}
              />
            </ExpandedField>
            <ExpandedField label="Scope" tip="Memory scope: agent (private), workflow (shared within workflow), global (shared across all workflows).">
              <InlineEdit
                value={config.memory.scope}
                onChange={(v) => updateField('memory', { ...config.memory, scope: String(v ?? '') })}
                placeholder="agent"
                className={accent(config, 'memory', 'scope')}
              />
            </ExpandedField>
            <ExpandedField label="Provider" tip="Storage provider: postgres, redis, sqlite.">
              <InlineEdit
                value={config.memory.provider}
                onChange={(v) => updateField('memory', { ...config.memory, provider: String(v ?? '') })}
                placeholder="postgres"
                className={accent(config, 'memory', 'provider')}
              />
            </ExpandedField>
            <ExpandedField label="NS" tip="Memory namespace for isolation. Agents in the same namespace share memories.">
              <InlineEdit
                value={config.memory.namespace}
                onChange={(v) => updateField('memory', { ...config.memory, namespace: String(v ?? '') })}
                emptyLabel="auto"
                className={accent(config, 'memory', 'namespace')}
              />
            </ExpandedField>
            <ExpandedField label="Tenant" tip="Tenant ID for multi-tenant isolation.">
              <InlineEdit
                value={config.memory.tenant_id}
                onChange={(v) => updateField('memory', { ...config.memory, tenant_id: String(v ?? '') })}
                emptyLabel="none"
                className={accent(config, 'memory', 'tenant_id')}
              />
            </ExpandedField>
            <ExpandedField label="K" tip="Number of memory items to retrieve (top-K). Higher values provide more context but increase prompt size.">
              <InlineEdit
                value={config.memory.retrieval_k}
                onChange={(v) => updateField('memory', { ...config.memory, retrieval_k: Number(v) || 10 })}
                type="number"
                className={accent(config, 'memory', 'retrieval_k')}
                min={1}
              />
            </ExpandedField>
            <ExpandedField label="Relevance" labelWidth="w-20" tip="Minimum relevance score (0-1) for retrieved memories. Lower values return more results.">
              <InlineEdit
                value={config.memory.relevance_threshold}
                onChange={(v) => updateField('memory', { ...config.memory, relevance_threshold: Number(v) || 0.8 })}
                type="number"
                className={accent(config, 'memory', 'relevance_threshold')}
                min={0} max={1} step={0.05}
              />
            </ExpandedField>
            <ExpandedField label="Embed" tip="Embedding model for semantic memory search.">
              <InlineEdit
                value={config.memory.embedding_model}
                onChange={(v) => updateField('memory', { ...config.memory, embedding_model: String(v ?? '') })}
                emptyLabel="default"
                className={accent(config, 'memory', 'embedding_model')}
              />
            </ExpandedField>
            <ExpandedField label="Max ep." labelWidth="w-20" tip="Maximum episodes to keep. Older episodes are pruned based on decay factor.">
              <InlineEdit
                value={config.memory.max_episodes}
                onChange={(v) => updateField('memory', { ...config.memory, max_episodes: Number(v) || 100 })}
                type="number"
                className={accent(config, 'memory', 'max_episodes')}
                min={1}
              />
            </ExpandedField>
            <ExpandedField label="Decay" tip="Decay factor (0-1) for memory relevance over time. 0.99 means slow decay.">
              <InlineEdit
                value={config.memory.decay_factor}
                onChange={(v) => updateField('memory', { ...config.memory, decay_factor: Number(v) || 0.99 })}
                type="number"
                className={accent(config, 'memory', 'decay_factor')}
                min={0} max={1} step={0.01}
              />
            </ExpandedField>
            <ExpandedField label="Auto proc" labelWidth="w-20" tip="Automatically extract procedural knowledge (how-to steps) from agent interactions.">
              <InlineToggle
                value={config.memory.auto_extract_procedural}
                onChange={(v) => updateField('memory', { ...config.memory, auto_extract_procedural: v })}
                tooltip="Auto-extract procedural knowledge"
                className={accent(config, 'memory', 'auto_extract_procedural')}
              />
            </ExpandedField>
            <ExpandedField label="Shared NS" labelWidth="w-20" tip="Shared namespace for cross-agent memory. Agents with the same shared namespace can read each other's memories.">
              <InlineEdit
                value={config.memory.shared_namespace}
                onChange={(v) => updateField('memory', { ...config.memory, shared_namespace: String(v ?? '') })}
                emptyLabel="none"
                className={accent(config, 'memory', 'shared_namespace')}
              />
            </ExpandedField>
          </>
        )}
      </CollapsibleSection>
    </>
  );
}
