/**
 * Agent-level property editor for the Studio.
 * Shown in the right panel when an agent name is selected from a stage.
 * Uses inline-edit pattern with per-field tooltips and non-default accent highlighting.
 *
 * 4 always-open sections + 13 collapsed advanced sections split across tab components.
 */
import { useDesignStore } from '@/store/designStore';
import { useAgentEditor } from '@/hooks/useAgentEditor';
import { InlineEdit, InlineSelect } from './InlineEdit';
import {
  SectionHeader,
  ExpandedField,
} from './shared';
import { useRegistry, toOptions } from '@/hooks/useRegistry';
import { AgentPromptTab } from './AgentPromptTab';
import { AgentInferenceTab } from './AgentInferenceTab';
import { AgentToolsTab } from './AgentToolsTab';
import { AgentSafetyTab } from './AgentSafetyTab';
import { AgentAdvancedTab } from './AgentAdvancedTab';
import { AgentMetaTab } from './AgentMetaTab';

export function AgentPropertiesPanel() {
  const selectedAgentName = useDesignStore((s) => s.selectedAgentName);
  const selectAgent = useDesignStore((s) => s.selectAgent);
  const { data: registry } = useRegistry();
  const typeOptions = toOptions(registry?.agent_types);
  const {
    config,
    isDirty,
    isLoading,
    error,
    updateField,
    save,
    validate,
    saveStatus,
    saveError,
    validateResult,
    validateStatus,
  } = useAgentEditor(selectedAgentName);

  if (!selectedAgentName) return null;

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-32">
        <p className="text-xs text-temper-text-muted">Loading agent...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col gap-2 p-3">
        <button
          onClick={() => selectAgent(null)}
          className="text-xs text-temper-accent hover:underline self-start"
        >
          &larr; Back to stage
        </button>
        <p className="text-xs text-red-600 dark:text-red-400">
          Failed to load agent: {(error as Error).message}
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col">
      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-temper-border">
        <button
          onClick={() => selectAgent(null)}
          className="text-xs text-temper-accent hover:underline shrink-0"
          aria-label="Back to stage"
        >
          &larr;
        </button>
        <h3 className="text-xs font-semibold text-temper-text truncate flex-1">
          {config.name || selectedAgentName}
          {isDirty && (
            <span
              className="inline-block w-1.5 h-1.5 rounded-full bg-amber-400 ml-1.5 align-middle"
              title="Unsaved changes"
            />
          )}
        </h3>
        <div className="flex items-center gap-1 shrink-0">
          <button
            onClick={() => validate()}
            disabled={validateStatus === 'pending'}
            className="px-2 py-1 text-[10px] rounded border border-temper-border text-temper-text-muted hover:bg-temper-surface disabled:opacity-50"
          >
            {validateStatus === 'pending' ? '...' : 'Validate'}
          </button>
          <button
            onClick={() => save()}
            disabled={!isDirty || saveStatus === 'pending'}
            className="px-2 py-1 text-[10px] rounded bg-temper-accent text-white hover:opacity-90 disabled:opacity-50"
          >
            {saveStatus === 'pending' ? '...' : 'Save'}
          </button>
        </div>
      </div>

      {/* Status banners */}
      {saveStatus === 'success' && (
        <div className="px-3 py-1.5 text-[10px] text-green-700 bg-green-400/10 dark:text-green-400 border-b border-temper-border/50">
          Agent saved
        </div>
      )}
      {saveError && (
        <div className="px-3 py-1.5 text-[10px] text-red-700 bg-red-400/10 dark:text-red-400 border-b border-temper-border/50">
          Save failed: {saveError.message}
        </div>
      )}
      {validateResult && !validateResult.valid && (
        <div className="px-3 py-1.5 text-[10px] text-yellow-400 bg-yellow-400/10 border-b border-temper-border/50">
          {validateResult.errors.map((e, i) => <p key={i}>{e}</p>)}
        </div>
      )}
      {validateResult?.valid && (
        <div className="px-3 py-1.5 text-[10px] text-green-400 bg-green-400/10 border-b border-temper-border/50">
          Valid
        </div>
      )}

      <div className="overflow-y-auto max-h-[calc(100vh-8rem)]">
        {/* ====== ALWAYS-OPEN SECTIONS ====== */}

        {/* General */}
        <div className="px-3 py-2 border-b border-temper-border/30">
          <SectionHeader title="General" tooltip="Agent identity. Name is read-only (set by the config file name)." />
          <ExpandedField label="Name" tip="Agent identifier — derived from the config file name. Read-only.">
            <InlineEdit value={config.name} onChange={() => {}} readOnly emptyLabel="unnamed" className="w-full" />
          </ExpandedField>
          <ExpandedField label="Desc" tip="Human-readable summary of what this agent does. Shown in stage tooltips and dashboard.">
            <InlineEdit
              value={config.description}
              onChange={(v) => updateField('description', String(v ?? ''))}
              type="textarea"
              placeholder="What does this agent do?"
              emptyLabel="no description"
              className="w-full"
            />
          </ExpandedField>
          <ExpandedField label="Version" tip="Semver string for tracking agent config changes.">
            <InlineEdit
              value={config.version}
              onChange={(v) => updateField('version', String(v ?? '1.0'))}
              placeholder="1.0"
            />
          </ExpandedField>
          <ExpandedField label="Type" tip="Agent archetype. Standard: general-purpose. Router: dispatches to other agents. Critic: reviews other agents' output. Orchestrator: manages sub-workflows.">
            <InlineSelect
              value={config.type}
              options={typeOptions}
              onChange={(v) => updateField('type', v)}
              tooltip="Agent type"
            />
          </ExpandedField>
        </div>

        {/* Prompt */}
        <AgentPromptTab config={config} updateField={updateField} />

        {/* Inference */}
        <AgentInferenceTab config={config} updateField={updateField} />

        {/* Tools */}
        <AgentToolsTab config={config} updateField={updateField} />

        {/* ====== COLLAPSED ADVANCED SECTIONS ====== */}

        {/* Safety + Memory */}
        <AgentSafetyTab config={config} updateField={updateField} />

        {/* Error Handling, Reasoning, Context, Output Schema, Output Guardrails, Pre-Commands */}
        <AgentAdvancedTab config={config} updateField={updateField} />

        {/* Merit, Persistent, Dialogue, Observability, Metadata */}
        <AgentMetaTab config={config} updateField={updateField} />
      </div>
    </div>
  );
}
