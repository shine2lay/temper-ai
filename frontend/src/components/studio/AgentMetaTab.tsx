/**
 * Meta tabs for AgentPropertiesPanel:
 * Merit Tracking, Persistent Agent, Dialogue, Observability, Metadata.
 */
import type { AgentFormState, AgentFieldUpdater } from '@/hooks/useAgentEditor';
import { InlineEdit, InlineToggle } from './InlineEdit';
import { CollapsibleSection, ExpandedField, CompactArrayEditor } from './shared';
import { accent } from './agentPanelHelpers';

interface Props {
  config: AgentFormState;
  updateField: AgentFieldUpdater;
}

export function AgentMetaTab({ config, updateField }: Props) {
  return (
    <>
      {/* Merit Tracking */}
      <CollapsibleSection title="Merit Tracking" tooltip="Track agent performance and build a reputation score. Used by merit-based conflict resolution and agent selection.">
        <ExpandedField label="Enabled" tip="Track this agent's performance metrics across runs. Builds a merit score used for conflict resolution and selection.">
          <InlineToggle
            value={config.merit.enabled}
            onChange={(v) => updateField('merit', { ...config.merit, enabled: v })}
            tooltip="Enable merit tracking"
            className={accent(config, 'merit', 'enabled')}
          />
        </ExpandedField>
        {config.merit.enabled && (
          <>
            <ExpandedField label="Outcomes" labelWidth="w-20" tip="Track task outcomes (success/failure) for merit scoring.">
              <InlineToggle
                value={config.merit.track_outcomes}
                onChange={(v) => updateField('merit', { ...config.merit, track_outcomes: v })}
                tooltip="Track outcomes"
                className={accent(config, 'merit', 'track_outcomes')}
              />
            </ExpandedField>
            <ExpandedField label="Domains" tip="Domain expertise tags for this agent. Used to match agents to tasks based on domain relevance.">
              <CompactArrayEditor
                values={config.merit.domain_expertise}
                onChange={(v) => updateField('merit', { ...config.merit, domain_expertise: v })}
                placeholder="domain"
              />
            </ExpandedField>
            <ExpandedField label="Decay" tip="Enable time-based merit decay. Old performance fades, keeping the score current.">
              <InlineToggle
                value={config.merit.decay_enabled}
                onChange={(v) => updateField('merit', { ...config.merit, decay_enabled: v })}
                tooltip="Enable decay"
                className={accent(config, 'merit', 'decay_enabled')}
              />
            </ExpandedField>
            <ExpandedField label="Half-life" labelWidth="w-20" tip="Days until merit score decays to half. 90 means performance from 90 days ago has half the weight.">
              <InlineEdit
                value={config.merit.half_life_days}
                onChange={(v) => updateField('merit', { ...config.merit, half_life_days: Number(v) || 90 })}
                type="number"
                className={accent(config, 'merit', 'half_life_days')}
                min={1}
              />
              <span className="text-[9px] text-temper-text-dim ml-1">days</span>
            </ExpandedField>
          </>
        )}
      </CollapsibleSection>

      {/* Persistent Agent */}
      <CollapsibleSection title="Persistent Agent" tooltip="Make this agent persistent across workflows. Persistent agents maintain state, memory, and can be triggered by events.">
        <ExpandedField label="Persistent" tip="Register this agent as persistent. It gets a fixed namespace, survives workflow restarts, and can be triggered by events.">
          <InlineToggle
            value={config.persistent.persistent}
            onChange={(v) => updateField('persistent', { ...config.persistent, persistent: v })}
            tooltip="Enable persistence"
            className={accent(config, 'persistent', 'persistent')}
          />
        </ExpandedField>
        {config.persistent.persistent && (
          <ExpandedField label="Agent ID" tip="Unique identifier for the persistent agent. Auto-assigned on registration. Read-only.">
            <InlineEdit
              value={config.persistent.agent_id}
              onChange={() => {}}
              readOnly
              emptyLabel="auto-assigned"
            />
          </ExpandedField>
        )}
      </CollapsibleSection>

      {/* Dialogue */}
      <CollapsibleSection title="Dialogue" tooltip="Controls how this agent participates in multi-agent dialogue/debate within a stage.">
        <ExpandedField label="Aware" tip="Agent is dialogue-aware — it can see and respond to other agents' messages in collaboration rounds.">
          <InlineToggle
            value={config.dialogue.dialogue_aware}
            onChange={(v) => updateField('dialogue', { ...config.dialogue, dialogue_aware: v })}
            tooltip="Dialogue aware"
            className={accent(config, 'dialogue', 'dialogue_aware')}
          />
        </ExpandedField>
        <ExpandedField label="Max ctx" tip="Maximum characters of dialogue context to include in each turn. Prevents prompt bloat in long debates.">
          <InlineEdit
            value={config.dialogue.max_dialogue_context_chars}
            onChange={(v) => updateField('dialogue', { ...config.dialogue, max_dialogue_context_chars: Number(v) || 16384 })}
            type="number"
            className={accent(config, 'dialogue', 'max_dialogue_context_chars')}
            min={0}
          />
        </ExpandedField>
      </CollapsibleSection>

      {/* Observability */}
      <CollapsibleSection title="Observability" tooltip="Control what this agent logs and traces. Affects debug output, dashboard visibility, and storage usage.">
        <ExpandedField label="Inputs" tip="Log agent input prompts to the trace.">
          <InlineToggle
            value={config.observability.log_inputs}
            onChange={(v) => updateField('observability', { ...config.observability, log_inputs: v })}
            tooltip="Log inputs"
            className={accent(config, 'observability', 'log_inputs')}
          />
        </ExpandedField>
        <ExpandedField label="Outputs" tip="Log agent outputs to the trace.">
          <InlineToggle
            value={config.observability.log_outputs}
            onChange={(v) => updateField('observability', { ...config.observability, log_outputs: v })}
            tooltip="Log outputs"
            className={accent(config, 'observability', 'log_outputs')}
          />
        </ExpandedField>
        <ExpandedField label="Reasoning" labelWidth="w-20" tip="Log reasoning/planning steps to the trace.">
          <InlineToggle
            value={config.observability.log_reasoning}
            onChange={(v) => updateField('observability', { ...config.observability, log_reasoning: v })}
            tooltip="Log reasoning"
            className={accent(config, 'observability', 'log_reasoning')}
          />
        </ExpandedField>
        <ExpandedField label="Latency" tip="Track and report agent response latency.">
          <InlineToggle
            value={config.observability.track_latency}
            onChange={(v) => updateField('observability', { ...config.observability, track_latency: v })}
            tooltip="Track latency"
            className={accent(config, 'observability', 'track_latency')}
          />
        </ExpandedField>
        <ExpandedField label="Tokens" tip="Track and report token usage (input + output).">
          <InlineToggle
            value={config.observability.track_token_usage}
            onChange={(v) => updateField('observability', { ...config.observability, track_token_usage: v })}
            tooltip="Track tokens"
            className={accent(config, 'observability', 'track_token_usage')}
          />
        </ExpandedField>
        <ExpandedField label="Full LLM" labelWidth="w-20" tip="Log full raw LLM responses. Useful for debugging but significantly increases storage.">
          <InlineToggle
            value={config.observability.log_full_llm_responses}
            onChange={(v) => updateField('observability', { ...config.observability, log_full_llm_responses: v })}
            tooltip="Full LLM responses"
            className={accent(config, 'observability', 'log_full_llm_responses')}
          />
        </ExpandedField>
      </CollapsibleSection>

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
