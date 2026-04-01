/**
 * Inference tab for AgentPropertiesPanel.
 */
import type { AgentFormState, AgentFieldUpdater } from '@/hooks/useAgentEditor';
import { InlineEdit, InlineSelect } from './InlineEdit';
import { SectionHeader, ExpandedField } from './shared';
import { accent } from './agentPanelHelpers';
import { useRegistry, toOptions } from '@/hooks/useRegistry';

interface Props {
  config: AgentFormState;
  updateField: AgentFieldUpdater;
}

export function AgentInferenceTab({ config, updateField }: Props) {
  const { data: registry } = useRegistry();
  const providerOptions = toOptions(registry?.providers);

  return (
    <div className="px-3 py-2 border-b border-temper-border/30">
      <SectionHeader title="Inference" tooltip="LLM provider configuration. Controls which model is used, how it's called, and retry behavior." />
      <ExpandedField label="Provider" tip="LLM provider — populated from registered providers. Determines the API format used.">
        <InlineSelect
          value={config.inference.provider}
          options={providerOptions}
          onChange={(v) => updateField('inference', { ...config.inference, provider: String(v ?? '') })}
          className={`w-full ${accent(config, 'inference', 'provider')}`}
        />
      </ExpandedField>
      <ExpandedField label="Model" tip="Model identifier (e.g. gpt-4o, claude-sonnet-4-20250514, qwen3-next). Must be available from the configured provider.">
        <InlineEdit
          value={config.inference.model}
          onChange={(v) => updateField('inference', { ...config.inference, model: String(v ?? '') })}
          placeholder="gpt-4o"
          className={`w-full ${accent(config, 'inference', 'model')}`}
        />
      </ExpandedField>
      <ExpandedField label="Base URL" tip="Custom API endpoint URL. Only needed for self-hosted models (Ollama, vLLM) or proxies. Leave empty to use provider defaults.">
        <InlineEdit
          value={config.inference.base_url}
          onChange={(v) => updateField('inference', { ...config.inference, base_url: String(v ?? '') })}
          placeholder="http://localhost:8000"
          emptyLabel="default"
          className="w-full"
        />
      </ExpandedField>
      <ExpandedField label="API key" tip="Environment variable name for the API key (e.g. OPENAI_API_KEY). The value is read at runtime, not stored in the config.">
        <InlineEdit
          value={config.inference.api_key_ref}
          onChange={(v) => updateField('inference', { ...config.inference, api_key_ref: String(v ?? '') })}
          placeholder="OPENAI_API_KEY"
          emptyLabel="none"
          className="w-full"
        />
      </ExpandedField>
      <ExpandedField label="Temp" tip="Sampling temperature (0-2). Lower = more deterministic, higher = more creative. 0.7 is a balanced default.">
        <InlineEdit
          value={config.inference.temperature}
          onChange={(v) => updateField('inference', { ...config.inference, temperature: Number(v) || 0 })}
          type="number"
          className={accent(config, 'inference', 'temperature')}
          min={0} max={2} step={0.1}
        />
      </ExpandedField>
      <ExpandedField label="Max tok" tip="Maximum output tokens for each LLM call. Set higher for agents that produce long outputs (code, analysis).">
        <InlineEdit
          value={config.inference.max_tokens}
          onChange={(v) => updateField('inference', { ...config.inference, max_tokens: Number(v) || 1 })}
          type="number"
          className={accent(config, 'inference', 'max_tokens')}
          min={1}
        />
      </ExpandedField>
      <ExpandedField label="Top P" tip="Nucleus sampling (0-1). Controls diversity by limiting to the top P probability mass. 1 = consider all tokens.">
        <InlineEdit
          value={config.inference.top_p}
          onChange={(v) => updateField('inference', { ...config.inference, top_p: Number(v) || 0 })}
          type="number"
          className={accent(config, 'inference', 'top_p')}
          min={0} max={1} step={0.05}
        />
      </ExpandedField>
      <ExpandedField label="Timeout" tip="Maximum time in seconds to wait for an LLM response. Default 600s (10 min). Set higher for large context or slow models.">
        <InlineEdit
          value={config.inference.timeout_seconds}
          onChange={(v) => updateField('inference', { ...config.inference, timeout_seconds: Number(v) || 0 })}
          type="number"
          className={accent(config, 'inference', 'timeout_seconds')}
          min={0}
        />
        <span className="text-[9px] text-temper-text-dim ml-1">s</span>
      </ExpandedField>
      <ExpandedField label="Retries" tip="Maximum times to retry a failed LLM call (e.g. timeout, rate limit). Uses the agent's error handling retry strategy.">
        <InlineEdit
          value={config.inference.max_retries}
          onChange={(v) => updateField('inference', { ...config.inference, max_retries: Number(v) || 0 })}
          type="number"
          className={accent(config, 'inference', 'max_retries')}
          min={0}
        />
      </ExpandedField>
      <ExpandedField label="Retry dly" labelWidth="w-20" tip="Delay in seconds before the first retry attempt. Combined with the retry strategy (exponential backoff, etc.).">
        <InlineEdit
          value={config.inference.retry_delay_seconds}
          onChange={(v) => updateField('inference', { ...config.inference, retry_delay_seconds: Number(v) || 0 })}
          type="number"
          className={accent(config, 'inference', 'retry_delay_seconds')}
          min={0}
        />
        <span className="text-[9px] text-temper-text-dim ml-1">s</span>
      </ExpandedField>
    </div>
  );
}
