/**
 * Meta tabs for AgentPropertiesPanel:
 * Metadata.
 */
import type { AgentFormState, AgentFieldUpdater } from '@/hooks/useAgentEditor';
import { InlineEdit } from './InlineEdit';
import { CollapsibleSection, ExpandedField, CompactArrayEditor } from './shared';

interface Props {
  config: AgentFormState;
  updateField: AgentFieldUpdater;
}

export function AgentMetaTab({ config, updateField }: Props) {
  return (
    <>
      {/* Section removed — backend does not implement this yet */}
      {/* Merit Tracking (enabled, track_outcomes, domain_expertise, decay_enabled, half_life_days) — no merit system */}

      {/* Section removed — backend does not implement this yet */}
      {/* Persistent Agent (persistent, agent_id) — no persistent agent registry */}

      {/* Section removed — backend does not implement this yet */}
      {/* Dialogue (dialogue_aware, max_dialogue_context_chars) — strategy context always injected regardless */}

      {/* Section removed — backend does not implement this yet */}
      {/* Observability (log_inputs, log_outputs, log_reasoning, track_latency, track_token_usage, log_full_llm_responses) — everything is always logged regardless of these toggles */}

      {/* Metadata */}
      <CollapsibleSection title="Metadata" tooltip="Organizational metadata for this agent. Tags for filtering, ownership info, and documentation links.">
        <ExpandedField label="Tags" tip="Free-form labels for filtering and organizing agents.">
          <CompactArrayEditor
            values={config.metadata.tags}
            onChange={(v) => updateField('metadata', { ...config.metadata, tags: v })}
            placeholder="tag"
          />
        </ExpandedField>
        <ExpandedField label="Owner" tip="Person or team responsible for this agent.">
          <InlineEdit
            value={config.metadata.owner}
            onChange={(v) => updateField('metadata', { ...config.metadata, owner: String(v ?? '') })}
            emptyLabel="none"
          />
        </ExpandedField>
        {config.metadata.created && (
          <ExpandedField label="Created" tip="When this agent config was first created.">
            <InlineEdit value={config.metadata.created} onChange={() => {}} readOnly />
          </ExpandedField>
        )}
        {config.metadata.last_modified && (
          <ExpandedField label="Modified" tip="When this agent config was last modified.">
            <InlineEdit value={config.metadata.last_modified} onChange={() => {}} readOnly />
          </ExpandedField>
        )}
        <ExpandedField label="Docs" tip="URL to documentation for this agent.">
          <InlineEdit
            value={config.metadata.documentation_url}
            onChange={(v) => updateField('metadata', { ...config.metadata, documentation_url: String(v ?? '') })}
            emptyLabel="none"
            placeholder="https://..."
            className="w-full"
          />
        </ExpandedField>
      </CollapsibleSection>
    </>
  );
}
