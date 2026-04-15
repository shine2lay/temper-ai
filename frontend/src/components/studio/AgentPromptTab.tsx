/**
 * Prompt tab for AgentPropertiesPanel.
 */
import type { AgentFormState, AgentFieldUpdater } from '@/hooks/useAgentEditor';
import { InlineSelect } from './InlineEdit';
import { SectionHeader, ExpandedField, CompactKeyValueEditor, textareaClass } from './shared';
import { InlineEdit } from './InlineEdit';

interface Props {
  config: AgentFormState;
  updateField: AgentFieldUpdater;
}

export function AgentPromptTab({ config, updateField }: Props) {
  return (
    <div className="px-3 py-2 border-b border-temper-border/30">
      <SectionHeader title="Prompt" tooltip="The system prompt that defines this agent's behavior. Can be inline text or a template file reference. Variables are injected via Jinja2 {{ variable }} syntax." />
      <ExpandedField label="Mode" tip="Inline: prompt text is stored directly in the config. Template: references an external .j2 or .txt file.">
        <InlineSelect
          value={config.prompt.mode}
          options={[
            { value: 'inline', label: 'inline' },
            { value: 'template', label: 'template' },
          ]}
          onChange={(v) => updateField('prompt', { ...config.prompt, mode: v as 'inline' | 'template' })}
          tooltip="Prompt source mode"
        />
      </ExpandedField>
      {config.prompt.mode === 'inline' ? (
        <>
          <ExpandedField label="System" tip="The system prompt that defines this agent's persona and behavior. This is the 'role' message sent to the LLM.">
            <textarea
              value={config.prompt.inline}
              onChange={(e) => updateField('prompt', { ...config.prompt, inline: e.target.value })}
              className={textareaClass}
              rows={4}
              placeholder="You are a helpful assistant..."
            />
          </ExpandedField>
          <ExpandedField label="Task" tip="The task template with {{ variables }} — this is the 'user' message. Use {{ task }} for the workflow input, {{ other_agents }} for upstream outputs, {{ memories }} for recalled memories.">
            <textarea
              value={config.prompt.template ?? ''}
              onChange={(e) => updateField('prompt', { ...config.prompt, template: e.target.value })}
              className={textareaClass}
              rows={4}
              placeholder="Task: {{ task }}&#10;{{ other_agents }}&#10;Output as JSON: {}"
            />
          </ExpandedField>
        </>
      ) : (
        <ExpandedField label="File" tip="Path to a Jinja2 template file (.j2 or .txt). Resolved relative to the configs directory.">
          <InlineEdit
            value={config.prompt.template}
            onChange={(v) => updateField('prompt', { ...config.prompt, template: String(v ?? '') })}
            placeholder="prompts/agent.j2"
            className="w-full"
          />
        </ExpandedField>
      )}
      <ExpandedField label="Vars" tip="Key-value pairs passed to the Jinja2 template as variables. These are available as {{ key }} in the prompt.">
        <CompactKeyValueEditor
          entries={config.prompt.variables}
          onChange={(v) => updateField('prompt', { ...config.prompt, variables: v })}
          keyPlaceholder="var"
          valuePlaceholder="value"
        />
      </ExpandedField>
    </div>
  );
}
