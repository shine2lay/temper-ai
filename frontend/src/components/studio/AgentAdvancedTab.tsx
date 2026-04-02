/**
 * Advanced tabs for AgentPropertiesPanel:
 * Error Handling.
 */
import type { AgentFormState, AgentFieldUpdater } from '@/hooks/useAgentEditor';
import { InlineEdit, InlineSelect } from './InlineEdit';
import { CollapsibleSection, ExpandedField } from './shared';
import {
  accent,
  retryStrategyOptions,
  fallbackOptions,
} from './agentPanelHelpers';

interface Props {
  config: AgentFormState;
  updateField: AgentFieldUpdater;
}

export function AgentAdvancedTab({ config, updateField }: Props) {
  return (
    <>
      {/* Error Handling */}
      <CollapsibleSection title="Error Handling" tooltip="Controls how this agent handles failures, including retry strategy, fallback behavior, and escalation.">
        <ExpandedField label="Strategy" tip="Retry strategy: ExponentialBackoff, LinearBackoff, FixedDelay, NoRetry.">
          <InlineSelect
            value={config.error_handling.retry_strategy}
            options={retryStrategyOptions}
            onChange={(v) => updateField('error_handling', { ...config.error_handling, retry_strategy: v })}
            tooltip="Retry strategy"
            className={accent(config, 'error_handling', 'retry_strategy')}
          />
        </ExpandedField>
        <ExpandedField label="Retries" tip="Maximum number of retry attempts before giving up.">
          <InlineEdit
            value={config.error_handling.max_retries}
            onChange={(v) => updateField('error_handling', { ...config.error_handling, max_retries: Number(v) || 0 })}
            type="number"
            className={accent(config, 'error_handling', 'max_retries')}
            min={0}
          />
        </ExpandedField>
        <ExpandedField label="Fallback" tip="What to do when retries are exhausted. Graceful: reduce scope. Hard fail: propagate error. Default resp: return a default.">
          <InlineSelect
            value={config.error_handling.fallback}
            options={fallbackOptions}
            onChange={(v) => updateField('error_handling', { ...config.error_handling, fallback: v })}
            tooltip="Fallback behavior"
            className={accent(config, 'error_handling', 'fallback')}
          />
        </ExpandedField>
        <ExpandedField label="Escalate" labelWidth="w-20" tip="Escalate to a human after this many failed attempts. Pauses execution and waits for human intervention.">
          <InlineEdit
            value={config.error_handling.escalate_to_human_after}
            onChange={(v) => updateField('error_handling', { ...config.error_handling, escalate_to_human_after: Number(v) || 2 })}
            type="number"
            className={accent(config, 'error_handling', 'escalate_to_human_after')}
            min={0}
          />
        </ExpandedField>
        <ExpandedField label="Init delay" labelWidth="w-20" tip="Initial retry delay in seconds. The first retry waits this long.">
          <InlineEdit
            value={config.error_handling.retry_initial_delay}
            onChange={(v) => updateField('error_handling', { ...config.error_handling, retry_initial_delay: Number(v) || 1 })}
            type="number"
            className={accent(config, 'error_handling', 'retry_initial_delay')}
            min={0}
          />
          <span className="text-[9px] text-temper-text-dim ml-1">s</span>
        </ExpandedField>
        <ExpandedField label="Max delay" labelWidth="w-20" tip="Maximum retry delay in seconds. Caps the exponential/linear growth.">
          <InlineEdit
            value={config.error_handling.retry_max_delay}
            onChange={(v) => updateField('error_handling', { ...config.error_handling, retry_max_delay: Number(v) || 30 })}
            type="number"
            className={accent(config, 'error_handling', 'retry_max_delay')}
            min={0}
          />
          <span className="text-[9px] text-temper-text-dim ml-1">s</span>
        </ExpandedField>
        <ExpandedField label="Exp base" labelWidth="w-20" tip="Base multiplier for exponential backoff (e.g. 2.0 means delay doubles each retry).">
          <InlineEdit
            value={config.error_handling.retry_exponential_base}
            onChange={(v) => updateField('error_handling', { ...config.error_handling, retry_exponential_base: Number(v) || 2.0 })}
            type="number"
            className={accent(config, 'error_handling', 'retry_exponential_base')}
            min={1} step={0.5}
          />
        </ExpandedField>
      </CollapsibleSection>

      {/* Section removed — backend does not implement this yet */}
      {/* Reasoning (enabled, planning_prompt, inject_as, max_planning_tokens, temperature) — no planning pre-pass exists */}

      {/* Section removed — backend does not implement this yet */}
      {/* Context Management (enabled, strategy, max_context_tokens, reserved_output_tokens, token_counter) — backend uses token_budget top-level, not this */}

      {/* Section removed — backend does not implement this yet */}
      {/* Output Schema (json_schema, enforce_mode, max_retries, strict) — no schema validation exists */}

      {/* Section removed — backend does not implement this yet */}
      {/* Output Guardrails (enabled, checks, max_retries, inject_feedback) — no guardrail pipeline */}

      {/* Section removed — backend does not implement this yet */}
      {/* Pre-Commands (name, command, timeout_seconds) — no command runner exists */}
    </>
  );
}
