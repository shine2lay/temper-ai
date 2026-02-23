/**
 * Advanced tabs for AgentPropertiesPanel:
 * Error Handling, Reasoning, Context Management, Output Schema, Output Guardrails, Pre-Commands.
 */
import type { AgentFormState, AgentFieldUpdater } from '@/hooks/useAgentEditor';
import { InlineEdit, InlineSelect, InlineToggle } from './InlineEdit';
import { CollapsibleSection, ExpandedField, CompactArrayEditor, textareaClass, inputClass } from './shared';
import {
  accent,
  retryStrategyOptions,
  fallbackOptions,
  injectAsOptions,
  ctxStrategyOptions,
  tokenCounterOptions,
  enforceModeOptions,
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

      {/* Reasoning */}
      <CollapsibleSection title="Reasoning" tooltip="Enable chain-of-thought reasoning / planning. The agent generates a plan before responding, which is injected into the prompt context.">
        <ExpandedField label="Enabled" tip="Activate reasoning/planning. When on, the agent generates a plan before its main response.">
          <InlineToggle
            value={config.reasoning.enabled}
            onChange={(v) => updateField('reasoning', { ...config.reasoning, enabled: v })}
            tooltip="Enable reasoning"
            className={accent(config, 'reasoning', 'enabled')}
          />
        </ExpandedField>
        {config.reasoning.enabled && (
          <>
            <div className="mb-1.5">
              <textarea
                value={config.reasoning.planning_prompt}
                onChange={(e) => updateField('reasoning', { ...config.reasoning, planning_prompt: e.target.value })}
                className={textareaClass}
                rows={3}
                placeholder="Think step by step..."
              />
            </div>
            <ExpandedField label="Inject" tip="Where the reasoning plan is injected. System: as a system message. User: as a user message. Prefix: as output prefix.">
              <InlineSelect
                value={config.reasoning.inject_as}
                options={injectAsOptions}
                onChange={(v) => updateField('reasoning', { ...config.reasoning, inject_as: v })}
                tooltip="Inject reasoning as"
                className={accent(config, 'reasoning', 'inject_as')}
              />
            </ExpandedField>
            <ExpandedField label="Max tok" tip="Maximum tokens for the planning step.">
              <InlineEdit
                value={config.reasoning.max_planning_tokens}
                onChange={(v) => updateField('reasoning', { ...config.reasoning, max_planning_tokens: Number(v) || 1024 })}
                type="number"
                className={accent(config, 'reasoning', 'max_planning_tokens')}
                min={1}
              />
            </ExpandedField>
            <ExpandedField label="Temp" tip="Sampling temperature for the planning step. Leave empty to use the agent's main temperature.">
              <InlineEdit
                value={config.reasoning.temperature}
                onChange={(v) => updateField('reasoning', { ...config.reasoning, temperature: v != null && v !== '' ? Number(v) : null })}
                type="number"
                emptyLabel="inherit"
                min={0} max={2} step={0.1}
              />
            </ExpandedField>
          </>
        )}
      </CollapsibleSection>

      {/* Context Management */}
      <CollapsibleSection title="Context Management" tooltip="Controls how the agent manages its context window. Prevents exceeding model limits by truncating, summarizing, or using a sliding window.">
        <ExpandedField label="Enabled" tip="Activate context management. When on, the agent's context is automatically managed to stay within model limits.">
          <InlineToggle
            value={config.context_management.enabled}
            onChange={(v) => updateField('context_management', { ...config.context_management, enabled: v })}
            tooltip="Enable context management"
            className={accent(config, 'context_management', 'enabled')}
          />
        </ExpandedField>
        {config.context_management.enabled && (
          <>
            <ExpandedField label="Strategy" tip="How to handle context overflow. Truncate: cut oldest messages. Summarize: compress with LLM. Sliding window: keep N recent turns.">
              <InlineSelect
                value={config.context_management.strategy}
                options={ctxStrategyOptions}
                onChange={(v) => updateField('context_management', { ...config.context_management, strategy: v })}
                tooltip="Context strategy"
                className={accent(config, 'context_management', 'strategy')}
              />
            </ExpandedField>
            <ExpandedField label="Max tok" tip="Maximum context tokens. Leave empty to use model's default limit.">
              <InlineEdit
                value={config.context_management.max_context_tokens}
                onChange={(v) => updateField('context_management', { ...config.context_management, max_context_tokens: v != null && v !== '' ? Number(v) : null })}
                type="number"
                emptyLabel="model default"
                className={accent(config, 'context_management', 'max_context_tokens')}
                min={1}
              />
            </ExpandedField>
            <ExpandedField label="Reserved" labelWidth="w-20" tip="Tokens reserved for the output. Ensures the model has enough space to generate a full response.">
              <InlineEdit
                value={config.context_management.reserved_output_tokens}
                onChange={(v) => updateField('context_management', { ...config.context_management, reserved_output_tokens: Number(v) || 2048 })}
                type="number"
                className={accent(config, 'context_management', 'reserved_output_tokens')}
                min={1}
              />
            </ExpandedField>
            <ExpandedField label="Counter" tip="Token counting method. Approximate: fast estimate. Tiktoken: exact OpenAI tokenizer count.">
              <InlineSelect
                value={config.context_management.token_counter}
                options={tokenCounterOptions}
                onChange={(v) => updateField('context_management', { ...config.context_management, token_counter: v })}
                tooltip="Token counter"
                className={accent(config, 'context_management', 'token_counter')}
              />
            </ExpandedField>
          </>
        )}
      </CollapsibleSection>

      {/* Output Schema */}
      <CollapsibleSection title="Output Schema" tooltip="Enforce structured JSON output from the agent. Defines the expected response schema and validation behavior.">
        <ExpandedField label="Schema" tip="JSON Schema for the agent's output. When non-empty, the agent's response is validated against this schema.">
          <textarea
            value={config.output_schema.json_schema}
            onChange={(e) => updateField('output_schema', { ...config.output_schema, json_schema: e.target.value })}
            className={`${textareaClass} font-mono text-[10px]`}
            rows={4}
            placeholder='{"type": "object", "properties": {...}}'
          />
        </ExpandedField>
        {config.output_schema.json_schema.trim() && (
          <>
            <ExpandedField label="Enforce" tip="Validation mode. Validate only: log errors but accept. Strict: reject non-conforming output. Coerce: try to fix output to match schema.">
              <InlineSelect
                value={config.output_schema.enforce_mode}
                options={enforceModeOptions}
                onChange={(v) => updateField('output_schema', { ...config.output_schema, enforce_mode: v })}
                tooltip="Schema enforcement"
                className={accent(config, 'output_schema', 'enforce_mode')}
              />
            </ExpandedField>
            <ExpandedField label="Retries" tip="Max retries when output doesn't match schema. The agent is re-prompted with the validation error.">
              <InlineEdit
                value={config.output_schema.max_retries}
                onChange={(v) => updateField('output_schema', { ...config.output_schema, max_retries: Number(v) || 0 })}
                type="number"
                className={accent(config, 'output_schema', 'max_retries')}
                min={0}
              />
            </ExpandedField>
            <ExpandedField label="Strict" tip="Use strict JSON mode (provider-dependent). When on, the model is forced to produce valid JSON.">
              <InlineToggle
                value={config.output_schema.strict}
                onChange={(v) => updateField('output_schema', { ...config.output_schema, strict: v })}
                tooltip="Strict JSON mode"
                className={accent(config, 'output_schema', 'strict')}
              />
            </ExpandedField>
          </>
        )}
      </CollapsibleSection>

      {/* Output Guardrails */}
      <CollapsibleSection title="Output Guardrails" tooltip="Post-processing checks on agent output. Validates safety, quality, and compliance after the LLM responds.">
        <ExpandedField label="Enabled" tip="Activate output guardrails. When on, the agent's output is validated by the checks listed below.">
          <InlineToggle
            value={config.output_guardrails.enabled}
            onChange={(v) => updateField('output_guardrails', { ...config.output_guardrails, enabled: v })}
            tooltip="Enable guardrails"
            className={accent(config, 'output_guardrails', 'enabled')}
          />
        </ExpandedField>
        {config.output_guardrails.enabled && (
          <>
            <ExpandedField label="Checks" tip="List of guardrail check names to run on the output (e.g. no_pii, no_profanity, schema_valid).">
              <CompactArrayEditor
                values={config.output_guardrails.checks}
                onChange={(v) => updateField('output_guardrails', { ...config.output_guardrails, checks: v })}
                placeholder="check name"
              />
            </ExpandedField>
            <ExpandedField label="Retries" tip="Max retries when a guardrail check fails. The agent is re-prompted with the failure feedback.">
              <InlineEdit
                value={config.output_guardrails.max_retries}
                onChange={(v) => updateField('output_guardrails', { ...config.output_guardrails, max_retries: Number(v) || 0 })}
                type="number"
                className={accent(config, 'output_guardrails', 'max_retries')}
                min={0}
              />
            </ExpandedField>
            <ExpandedField label="Feedback" labelWidth="w-20" tip="Inject guardrail failure feedback into the retry prompt. Helps the agent understand what went wrong.">
              <InlineToggle
                value={config.output_guardrails.inject_feedback}
                onChange={(v) => updateField('output_guardrails', { ...config.output_guardrails, inject_feedback: v })}
                tooltip="Inject failure feedback"
                className={accent(config, 'output_guardrails', 'inject_feedback')}
              />
            </ExpandedField>
          </>
        )}
      </CollapsibleSection>

      {/* Pre-Commands */}
      <CollapsibleSection title="Pre-Commands" tooltip="Shell commands executed before the agent runs. Useful for environment setup, data preparation, or health checks.">
        <div className="flex flex-col gap-2">
          {config.pre_commands.map((pc, i) => (
            <div key={i} className="flex flex-col gap-1 p-1.5 bg-temper-surface/50 rounded border border-temper-border/50">
              <div className="flex items-center gap-1">
                <input
                  type="text"
                  value={pc.name}
                  onChange={(e) => {
                    const cmds = [...config.pre_commands];
                    cmds[i] = { ...cmds[i], name: e.target.value };
                    updateField('pre_commands', cmds);
                  }}
                  className="flex-1 px-2 py-1 text-xs bg-temper-surface border border-temper-border rounded text-temper-text"
                  placeholder="Command name"
                />
                <input
                  type="number"
                  value={pc.timeout_seconds}
                  onChange={(e) => {
                    const cmds = [...config.pre_commands];
                    cmds[i] = { ...cmds[i], timeout_seconds: Number(e.target.value) || 30 };
                    updateField('pre_commands', cmds);
                  }}
                  className="w-16 px-2 py-1 text-xs bg-temper-surface border border-temper-border rounded text-temper-text"
                  min={1}
                  title="Timeout (seconds)"
                />
                <button
                  onClick={() => updateField('pre_commands', config.pre_commands.filter((_, j) => j !== i))}
                  className="text-xs text-red-400 hover:text-red-300 px-1"
                >
                  &times;
                </button>
              </div>
              <input
                type="text"
                value={pc.command}
                onChange={(e) => {
                  const cmds = [...config.pre_commands];
                  cmds[i] = { ...cmds[i], command: e.target.value };
                  updateField('pre_commands', cmds);
                }}
                className={`${inputClass} font-mono text-[10px]`}
                placeholder="bash command..."
              />
            </div>
          ))}
          <button
            onClick={() => updateField('pre_commands', [...config.pre_commands, { name: '', command: '', timeout_seconds: 30 }])}
            className="text-[9px] text-temper-accent hover:underline self-start"
          >
            + Add command
          </button>
        </div>
      </CollapsibleSection>
    </>
  );
}
