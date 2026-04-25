/**
 * Tools tab for AgentPropertiesPanel.
 */
import type { AgentFormState, AgentFieldUpdater } from '@/hooks/useAgentEditor';
import { InlineSelect } from './InlineEdit';
import { SectionHeader, ExpandedField } from './shared';
import { toolModeOptions } from './agentPanelHelpers';
import { useRegistry } from '@/hooks/useRegistry';

interface Props {
  config: AgentFormState;
  updateField: AgentFieldUpdater;
}

export function AgentToolsTab({ config, updateField }: Props) {
  const { data: registry } = useRegistry();
  const builtinTools = registry?.tools ?? [];
  const mcpServers = registry?.mcp_servers ?? [];

  return (
    <div className="px-3 py-2 border-b border-temper-border/30">
      <SectionHeader title="Tools" tooltip="Tools available to this agent. Auto: discover tools from environment. None: no tool access. Explicit: only the listed tools. MCP tools use dotted names: server.tool_name" />
      <ExpandedField label="Mode" tip="Auto-discover: agent gets all registered tools. No tools: agent cannot call any tools. Explicit: only the tools listed below.">
        <InlineSelect
          value={config.tools.mode}
          options={toolModeOptions}
          onChange={(v) => {
            const mode = v as 'auto' | 'none' | 'explicit';
            updateField('tools', { mode, entries: mode === 'explicit' ? config.tools.entries : [] });
          }}
          tooltip="Tool discovery mode"
        />
      </ExpandedField>
      {config.tools.mode === 'explicit' && (
        <div className="flex flex-col gap-2 mt-1">
          {config.tools.entries.map((entry, i) => (
            <div key={i} className="flex flex-col gap-1 p-1.5 bg-temper-surface/50 rounded border border-temper-border/50">
              <div className="flex items-center gap-1">
                <select
                  value={entry.name}
                  onChange={(e) => {
                    const entries = [...config.tools.entries];
                    entries[i] = { ...entries[i], name: e.target.value };
                    updateField('tools', { ...config.tools, entries });
                  }}
                  className="flex-1 px-2 py-1 text-xs bg-temper-surface border border-temper-border rounded text-temper-text"
                >
                  <option value="">Select tool...</option>
                  <optgroup label="Built-in Tools">
                    {builtinTools.map((t) => (
                      <option key={t} value={t}>{t}</option>
                    ))}
                  </optgroup>
                  {mcpServers.length > 0 && (
                    <optgroup label="MCP Servers">
                      {mcpServers.map((s) => (
                        <option key={s} value={s}>{s} (all tools)</option>
                      ))}
                    </optgroup>
                  )}
                </select>
                {/* Free-text input for MCP tool names like searxng.web_search */}
                {entry.name === '' || entry.name.includes('.') || mcpServers.includes(entry.name) ? (
                  <input
                    type="text"
                    value={entry.name}
                    onChange={(e) => {
                      const entries = [...config.tools.entries];
                      entries[i] = { ...entries[i], name: e.target.value };
                      updateField('tools', { ...config.tools, entries });
                    }}
                    className="flex-1 px-2 py-1 text-xs bg-temper-surface border border-temper-border rounded text-temper-text font-mono"
                    placeholder="server.tool_name"
                  />
                ) : null}
                <button
                  onClick={() => updateField('tools', {
                    ...config.tools,
                    entries: config.tools.entries.filter((_, j) => j !== i),
                  })}
                  className="text-xs text-red-600 hover:text-red-700 dark:text-red-400 dark:hover:text-red-300 px-1"
                >
                  &times;
                </button>
              </div>
              <textarea
                value={entry.config}
                onChange={(e) => {
                  const entries = [...config.tools.entries];
                  entries[i] = { ...entries[i], config: e.target.value };
                  updateField('tools', { ...config.tools, entries });
                }}
                className="px-2 py-1 text-[10px] font-mono bg-temper-surface border border-temper-border rounded text-temper-text-muted resize-y min-h-[32px]"
                placeholder='{"key": "value"}'
                rows={2}
              />
            </div>
          ))}
          <button
            onClick={() => updateField('tools', {
              ...config.tools,
              entries: [...config.tools.entries, { name: '', config: '' }],
            })}
            className="text-[9px] text-temper-accent hover:underline self-start"
          >
            + Add tool
          </button>
        </div>
      )}
    </div>
  );
}
