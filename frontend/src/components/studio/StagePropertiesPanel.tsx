/**
 * Stage-level property form for the Studio editor.
 * Shown in the right panel when a stage is selected.
 * Organized into sections: General, Agents, Dependencies, Input Wiring.
 */
import { useDesignStore, type AgentMode, type CollaborationStrategy } from '@/store/designStore';
import { useStudioConfigs, useStudioConfig } from '@/hooks/useStudioAPI';
import { Section, Field } from './shared';

/* ---------- Agents section for stages with stage_ref ---------- */

function RefAgentsSection({ stageRef }: { stageRef: string }) {
  // Extract config name from path like "configs/stages/vcs_design.yaml"
  const configName = stageRef.replace(/^.*\//, '').replace(/\.yaml$/, '');
  const { data, isLoading } = useStudioConfig('stages', configName);
  const selectAgent = useDesignStore((s) => s.selectAgent);

  if (isLoading) {
    return <p className="text-[10px] text-temper-text-dim">Loading agents...</p>;
  }

  const stageData = (data as { stage?: Record<string, unknown> })?.stage ?? data;
  const agents = (stageData as Record<string, unknown>)?.agents as string[] | undefined;
  const execution = (stageData as Record<string, unknown>)?.execution as Record<string, unknown> | undefined;
  const collaboration = (stageData as Record<string, unknown>)?.collaboration as Record<string, unknown> | undefined;

  if (!agents || agents.length === 0) {
    return <p className="text-[10px] text-temper-text-dim">No agents in this config</p>;
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-col gap-1">
        {agents.map((agent) => (
          <button
            key={agent}
            onClick={() => selectAgent(agent)}
            className="flex items-center gap-1.5 px-2 py-1 bg-temper-surface rounded text-xs text-temper-text hover:bg-temper-surface/80 transition-colors group text-left w-full"
          >
            <span className="w-1.5 h-1.5 rounded-full bg-temper-accent shrink-0" />
            <span className="flex-1">{agent}</span>
            <span className="text-[10px] text-temper-text-dim opacity-0 group-hover:opacity-100 transition-opacity">
              Edit &rarr;
            </span>
          </button>
        ))}
      </div>
      {(execution || collaboration) && (
        <div className="flex flex-wrap gap-2 text-[10px] text-temper-text-dim">
          {typeof execution?.agent_mode === 'string' && (
            <span className="px-1.5 py-0.5 bg-temper-surface rounded">
              {execution.agent_mode}
            </span>
          )}
          {typeof collaboration?.strategy === 'string' && (
            <span className="px-1.5 py-0.5 bg-temper-surface rounded">
              {collaboration.strategy}
            </span>
          )}
        </div>
      )}
    </div>
  );
}

/* ---------- Agents section for inline stages ---------- */

function InlineAgentsSection({
  agents,
  agentMode,
  collaborationStrategy,
  onUpdateAgents,
  onUpdateMode,
  onUpdateStrategy,
}: {
  agents: string[];
  agentMode: AgentMode;
  collaborationStrategy: CollaborationStrategy;
  onUpdateAgents: (agents: string[]) => void;
  onUpdateMode: (mode: AgentMode) => void;
  onUpdateStrategy: (strategy: CollaborationStrategy) => void;
}) {
  const { data: agentConfigs } = useStudioConfigs('agents');
  const selectAgent = useDesignStore((s) => s.selectAgent);

  const available = agentConfigs?.configs
    ?.map((c) => c.name)
    .filter((n) => !agents.includes(n))
    .sort() ?? [];

  return (
    <div className="flex flex-col gap-2">
      {/* Agent list */}
      <Field label="Agents" hint="AI agents that run in this stage">
        <div className="flex flex-col gap-1">
          {agents.map((agent) => (
            <div key={agent} className="flex items-center gap-1">
              <button
                onClick={() => selectAgent(agent)}
                className="flex-1 flex items-center gap-1.5 text-xs text-temper-text px-2 py-1 bg-temper-surface rounded hover:bg-temper-surface/80 transition-colors group text-left"
              >
                <span className="w-1.5 h-1.5 rounded-full bg-temper-accent shrink-0" />
                <span className="flex-1">{agent}</span>
                <span className="text-[10px] text-temper-text-dim opacity-0 group-hover:opacity-100 transition-opacity">
                  Edit &rarr;
                </span>
              </button>
              <button
                onClick={() => onUpdateAgents(agents.filter((a) => a !== agent))}
                className="text-xs text-red-400 hover:text-red-300 px-1"
                aria-label={`Remove agent ${agent}`}
              >
                &times;
              </button>
            </div>
          ))}
          {available.length > 0 && (
            <select
              value=""
              onChange={(e) => {
                if (!e.target.value) return;
                onUpdateAgents([...agents, e.target.value]);
              }}
              className="text-xs bg-temper-surface border border-temper-border rounded text-temper-text-muted px-2 py-1"
            >
              <option value="">+ Add agent...</option>
              {available.map((n) => (
                <option key={n} value={n}>{n}</option>
              ))}
            </select>
          )}
          {agents.length === 0 && available.length === 0 && (
            <p className="text-[10px] text-temper-text-dim">No agent configs found</p>
          )}
        </div>
      </Field>

      {/* Execution mode */}
      {agents.length > 1 && (
        <>
          <Field label="Agent Mode" hint="How agents execute within this stage">
            <select
              value={agentMode}
              onChange={(e) => onUpdateMode(e.target.value as AgentMode)}
              className="w-full px-2 py-1.5 text-xs bg-temper-surface border border-temper-border rounded text-temper-text"
            >
              <option value="sequential">Sequential — one after another</option>
              <option value="parallel">Parallel — all at once</option>
              <option value="adaptive">Adaptive — system decides</option>
            </select>
          </Field>

          <Field label="Collaboration" hint="How agents work together">
            <select
              value={collaborationStrategy}
              onChange={(e) => onUpdateStrategy(e.target.value as CollaborationStrategy)}
              className="w-full px-2 py-1.5 text-xs bg-temper-surface border border-temper-border rounded text-temper-text"
            >
              <option value="independent">Independent — no coordination</option>
              <option value="leader">Leader — one agent synthesizes others</option>
              <option value="consensus">Consensus — agents agree on output</option>
              <option value="debate">Debate — agents argue to refine</option>
              <option value="round_robin">Round Robin — take turns</option>
            </select>
          </Field>
        </>
      )}
    </div>
  );
}

/* ---------- Main panel ---------- */

export function StagePropertiesPanel() {
  const selectedStageName = useDesignStore((s) => s.selectedStageName);
  const stages = useDesignStore((s) => s.stages);
  const updateStage = useDesignStore((s) => s.updateStage);
  const renameStage = useDesignStore((s) => s.renameStage);
  const selectStage = useDesignStore((s) => s.selectStage);

  const { data: stageConfigs } = useStudioConfigs('stages');

  const stage = stages.find((s) => s.name === selectedStageName);
  if (!stage || !selectedStageName) return null;

  const otherStageNames = stages
    .filter((s) => s.name !== selectedStageName)
    .map((s) => s.name);

  const hasStageRef = !!stage.stage_ref;
  const agentBadge = hasStageRef ? 'from config' : `${stage.agents.length}`;

  return (
    <div className="flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-temper-border">
        <h3 className="text-xs font-semibold text-temper-text">
          Stage Properties
        </h3>
        <button
          onClick={() => selectStage(null)}
          className="text-xs text-temper-text-muted hover:text-temper-text"
          aria-label="Close stage properties"
        >
          &times;
        </button>
      </div>

      {/* General */}
      <Section title="General" defaultOpen={true}>
        <Field label="Name">
          <input
            type="text"
            value={stage.name}
            onChange={(e) => {
              const newName = e.target.value.replace(/[^a-zA-Z0-9_-]/g, '');
              if (newName && newName !== stage.name) {
                renameStage(stage.name, newName);
              }
            }}
            onBlur={(e) => {
              const newName = e.target.value.replace(/[^a-zA-Z0-9_-]/g, '');
              if (newName && newName !== selectedStageName) {
                renameStage(selectedStageName, newName);
              }
            }}
            className="w-full px-2 py-1.5 text-sm bg-temper-surface border border-temper-border rounded text-temper-text"
            aria-label="Stage name"
          />
        </Field>
        <Field
          label="Stage Config"
          hint="Which stage definition to use"
        >
          <select
            value={stage.stage_ref ?? ''}
            onChange={(e) =>
              updateStage(stage.name, {
                stage_ref: e.target.value || null,
              })
            }
            className="w-full px-2 py-1.5 text-xs bg-temper-surface border border-temper-border rounded text-temper-text"
          >
            <option value="">None (inline)</option>
            {stageConfigs?.configs?.map((cfg) => (
              <option key={cfg.name} value={`configs/stages/${cfg.name}.yaml`}>
                {cfg.name}
              </option>
            ))}
          </select>
        </Field>
      </Section>

      {/* Agents */}
      <Section title="Agents" badge={agentBadge} defaultOpen={true}>
        {hasStageRef ? (
          <RefAgentsSection stageRef={stage.stage_ref!} />
        ) : (
          <InlineAgentsSection
            agents={stage.agents}
            agentMode={stage.agent_mode}
            collaborationStrategy={stage.collaboration_strategy}
            onUpdateAgents={(agents) => updateStage(stage.name, { agents })}
            onUpdateMode={(agent_mode) => updateStage(stage.name, { agent_mode })}
            onUpdateStrategy={(collaboration_strategy) =>
              updateStage(stage.name, { collaboration_strategy })
            }
          />
        )}
      </Section>

      {/* Dependencies */}
      <Section title="Dependencies" defaultOpen={true}>
        <Field
          label="Depends On"
          hint="Stages that must complete before this one runs"
        >
          <div className="flex flex-col gap-1">
            {stage.depends_on.map((dep) => (
              <div key={dep} className="flex items-center gap-1">
                <span className="flex-1 text-xs text-temper-text px-2 py-1 bg-temper-surface rounded">
                  {dep}
                </span>
                <button
                  onClick={() =>
                    updateStage(stage.name, {
                      depends_on: stage.depends_on.filter((d) => d !== dep),
                    })
                  }
                  className="text-xs text-red-400 hover:text-red-300 px-1"
                  aria-label={`Remove dependency on ${dep}`}
                >
                  &times;
                </button>
              </div>
            ))}
            {otherStageNames.filter((n) => !stage.depends_on.includes(n)).length > 0 && (
              <select
                value=""
                onChange={(e) => {
                  if (!e.target.value) return;
                  updateStage(stage.name, {
                    depends_on: [...stage.depends_on, e.target.value],
                  });
                  e.target.value = '';
                }}
                className="text-xs bg-temper-surface border border-temper-border rounded text-temper-text-muted px-2 py-1"
              >
                <option value="">+ Add dependency...</option>
                {otherStageNames
                  .filter((n) => !stage.depends_on.includes(n))
                  .map((n) => (
                    <option key={n} value={n}>
                      {n}
                    </option>
                  ))}
              </select>
            )}
            {stage.depends_on.length === 0 && otherStageNames.length === 0 && (
              <p className="text-[10px] text-temper-text-dim">
                Add more stages to create dependencies
              </p>
            )}
          </div>
        </Field>

        <Field
          label="Loops Back To"
          hint="Create a retry/iteration loop to an earlier stage"
        >
          <select
            value={stage.loops_back_to ?? ''}
            onChange={(e) =>
              updateStage(stage.name, {
                loops_back_to: e.target.value || null,
              })
            }
            className="w-full px-2 py-1.5 text-xs bg-temper-surface border border-temper-border rounded text-temper-text"
          >
            <option value="">None</option>
            {otherStageNames.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </Field>

        {stage.loops_back_to && (
          <Field
            label="Max Loops"
            hint="Maximum iterations before breaking the loop"
          >
            <input
              type="number"
              value={stage.max_loops ?? ''}
              onChange={(e) =>
                updateStage(stage.name, {
                  max_loops: e.target.value ? Number(e.target.value) : null,
                })
              }
              className="w-24 px-2 py-1.5 text-xs bg-temper-surface border border-temper-border rounded text-temper-text"
              placeholder="Unlimited"
              min={1}
            />
          </Field>
        )}

        <Field
          label="Condition"
          hint="Only run this stage if condition is truthy"
        >
          <input
            type="text"
            value={stage.condition ?? ''}
            onChange={(e) =>
              updateStage(stage.name, {
                condition: e.target.value || null,
              })
            }
            className="w-full px-2 py-1.5 text-xs bg-temper-surface border border-temper-border rounded text-temper-text"
            placeholder="e.g., {{ needs_review }}"
          />
        </Field>
      </Section>

      {/* Input Wiring */}
      <Section title="Input Wiring" defaultOpen={true}>
        <Field
          label="Inputs"
          hint="Map data from other stages into this stage"
        >
          <div className="flex flex-col gap-1.5">
            {Object.entries(stage.inputs).map(([key, val]) => (
              <div key={key} className="flex items-center gap-1">
                <input
                  type="text"
                  value={key}
                  readOnly
                  className="w-24 text-xs bg-temper-surface border border-temper-border rounded text-temper-text px-2 py-1"
                />
                <span className="text-xs text-temper-text-dim">&larr;</span>
                <input
                  type="text"
                  value={val.source}
                  onChange={(e) => {
                    const newInputs = { ...stage.inputs };
                    newInputs[key] = { source: e.target.value };
                    updateStage(stage.name, { inputs: newInputs });
                  }}
                  className="flex-1 text-xs bg-temper-surface border border-temper-border rounded text-temper-text px-2 py-1"
                  placeholder="stage.output_key"
                />
                <button
                  onClick={() => {
                    const newInputs = { ...stage.inputs };
                    delete newInputs[key];
                    updateStage(stage.name, { inputs: newInputs });
                  }}
                  className="text-xs text-red-400 hover:text-red-300 px-1"
                  aria-label={`Remove input ${key}`}
                >
                  &times;
                </button>
              </div>
            ))}
            <button
              onClick={() => {
                const newKey = `input_${Object.keys(stage.inputs).length}`;
                updateStage(stage.name, {
                  inputs: { ...stage.inputs, [newKey]: { source: '' } },
                });
              }}
              className="text-[10px] text-temper-accent hover:underline self-start"
            >
              + Add input
            </button>
          </div>
        </Field>
      </Section>
    </div>
  );
}
