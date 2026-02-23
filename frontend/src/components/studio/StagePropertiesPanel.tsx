/**
 * Stage-level property panel for the Studio editor.
 * Shown in the right panel when a stage is selected.
 * Uses inline-edit pattern with per-field tooltips and non-default accent highlighting.
 *
 * Two modes:
 * - Referenced (stage_ref exists): most config fields are read-only from the config file.
 * - Inline (no stage_ref): all fields fully editable.
 *
 * 4 always-open sections + 8 collapsed advanced sections.
 */
import { useDesignStore, defaultDesignStage, type DesignStage, type AgentMode, type CollaborationStrategy } from '@/store/designStore';
import { useStudioConfigs, useStudioConfig } from '@/hooks/useStudioAPI';
import { InlineEdit, InlineSelect, InlineToggle } from './InlineEdit';
import {
  SectionHeader,
  CollapsibleSection,
  ExpandedField,
  CompactArrayEditor,
  CompactKeyValueEditor,
} from './shared';

/* ---------- Constants ---------- */

const STAGE_DEFAULTS = defaultDesignStage();

const agentModeOptions = [
  { value: 'sequential', label: 'sequential' },
  { value: 'parallel', label: 'parallel' },
  { value: 'adaptive', label: 'adaptive' },
];

const collaborationOptions = [
  { value: 'independent', label: 'independent' },
  { value: 'leader', label: 'leader' },
  { value: 'consensus', label: 'consensus' },
  { value: 'debate', label: 'debate' },
  { value: 'round_robin', label: 'round_robin' },
];

const safetyModeOptions = [
  { value: 'execute', label: 'execute' },
  { value: 'monitor', label: 'monitor' },
  { value: 'audit', label: 'audit' },
];

const agentFailureOptions = [
  { value: 'continue_with_remaining', label: 'continue_with_remaining' },
  { value: 'halt', label: 'halt' },
  { value: 'retry', label: 'retry' },
  { value: 'skip', label: 'skip' },
];

const gateFailureOptions = [
  { value: 'retry_stage', label: 'retry_stage' },
  { value: 'halt', label: 'halt' },
  { value: 'skip', label: 'skip' },
  { value: 'continue', label: 'continue' },
];

const convergenceMethodOptions = [
  { value: 'exact_hash', label: 'exact_hash' },
  { value: 'cosine_similarity', label: 'cosine_similarity' },
  { value: 'levenshtein', label: 'levenshtein' },
];

/* ---------- Non-default detection ---------- */

type StageKey = keyof DesignStage;
const DEF = STAGE_DEFAULTS as unknown as Record<string, unknown>;

function accentIf(stage: DesignStage, key: StageKey): string {
  if (!(key in DEF)) return '';
  const val = stage[key];
  const def = DEF[key as string];
  if (Array.isArray(val) && Array.isArray(def)) {
    return val.length !== def.length || val.some((v: unknown, i: number) => v !== (def as unknown[])[i]) ? 'text-temper-accent' : '';
  }
  if (typeof val === 'object' && val !== null && typeof def === 'object' && def !== null) {
    return JSON.stringify(val) !== JSON.stringify(def) ? 'text-temper-accent' : '';
  }
  return val !== def ? 'text-temper-accent' : '';
}

/* ---------- Agents section for stages with stage_ref ---------- */

function RefAgentsSection({ stageRef }: { stageRef: string }) {
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
  stage,
  onUpdate,
}: {
  stage: DesignStage;
  onUpdate: (partial: Partial<Omit<DesignStage, 'name'>>) => void;
}) {
  const { data: agentConfigs } = useStudioConfigs('agents');
  const selectAgent = useDesignStore((s) => s.selectAgent);

  const available = agentConfigs?.configs
    ?.map((c) => c.name)
    .filter((n) => !stage.agents.includes(n))
    .sort() ?? [];

  return (
    <div className="flex flex-col gap-2">
      {/* Agent list */}
      <div className="flex flex-col gap-1">
        {stage.agents.map((agent) => (
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
              onClick={() => onUpdate({ agents: stage.agents.filter((a) => a !== agent) })}
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
              onUpdate({ agents: [...stage.agents, e.target.value] });
            }}
            className="text-xs bg-temper-surface border border-temper-border rounded text-temper-text-muted px-2 py-1"
          >
            <option value="">+ Add agent...</option>
            {available.map((n) => (
              <option key={n} value={n}>{n}</option>
            ))}
          </select>
        )}
        {stage.agents.length === 0 && available.length === 0 && (
          <p className="text-[10px] text-temper-text-dim">No agent configs found</p>
        )}
      </div>

      {/* Execution mode & collaboration */}
      {stage.agents.length > 1 && (
        <>
          <ExpandedField label="Mode" tip="How agents execute within this stage. Sequential: one after another. Parallel: all at once. Adaptive: system decides based on agent count and dependencies.">
            <InlineSelect
              value={stage.agent_mode}
              options={agentModeOptions}
              onChange={(v) => onUpdate({ agent_mode: v as AgentMode })}
              tooltip="Agent execution mode"
              className={accentIf(stage, 'agent_mode')}
            />
          </ExpandedField>
          <ExpandedField label="Strategy" tip="How agents collaborate. Independent: no coordination. Leader: one agent synthesizes others. Consensus: agents agree on output. Debate: agents argue to refine. Round Robin: take turns.">
            <InlineSelect
              value={stage.collaboration_strategy}
              options={collaborationOptions}
              onChange={(v) => onUpdate({ collaboration_strategy: v as CollaborationStrategy })}
              tooltip="Collaboration strategy"
              className={accentIf(stage, 'collaboration_strategy')}
            />
          </ExpandedField>
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
  const resolvedStageInfo = useDesignStore((s) => s.resolvedStageInfo);

  const { data: stageConfigs } = useStudioConfigs('stages');

  const stage = stages.find((s) => s.name === selectedStageName);
  if (!stage || !selectedStageName) return null;

  const otherStageNames = stages
    .filter((s) => s.name !== selectedStageName)
    .map((s) => s.name);

  const hasStageRef = !!stage.stage_ref;
  const ro = hasStageRef; // read-only for config fields when referenced

  // Resolved inputs from stage config (not overridden at workflow level)
  const resolved = resolvedStageInfo[selectedStageName];
  const resolvedInputs = resolved?.inputs
    ? Object.entries(resolved.inputs).filter(([key]) => !(key in stage.inputs))
    : [];

  const onUpdate = (partial: Partial<Omit<DesignStage, 'name'>>) =>
    updateStage(stage.name, partial);

  return (
    <div className="flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-temper-border">
        <h3 className="text-xs font-semibold text-temper-text">
          Stage Properties
          {hasStageRef && (
            <span className="ml-1.5 text-[9px] text-temper-text-dim font-normal">(referenced)</span>
          )}
        </h3>
        <button
          onClick={() => selectStage(null)}
          className="text-xs text-temper-text-muted hover:text-temper-text"
          aria-label="Close stage properties"
        >
          &times;
        </button>
      </div>

      <div className="overflow-y-auto max-h-[calc(100vh-8rem)]">
        {/* ====== ALWAYS-OPEN SECTIONS ====== */}

        {/* General */}
        <div className="px-3 py-2 border-b border-temper-border/30">
          <SectionHeader title="General" tooltip="Stage identity and config source." />
          <ExpandedField label="Name" tip="Unique stage identifier. Used in depends_on references and DAG visualization.">
            <InlineEdit
              value={stage.name}
              onChange={(v) => {
                const newName = String(v ?? '').replace(/[^a-zA-Z0-9_-]/g, '');
                if (newName && newName !== stage.name) {
                  renameStage(stage.name, newName);
                }
              }}
              placeholder="stage_name"
              className="w-full"
            />
          </ExpandedField>
          <ExpandedField label="Desc" tip="Human-readable summary of what this stage does. Shown in DAG tooltips and dashboard.">
            <InlineEdit
              value={stage.description}
              onChange={(v) => onUpdate({ description: String(v ?? '') })}
              type="textarea"
              placeholder="What does this stage do?"
              emptyLabel="no description"
              className={`w-full ${accentIf(stage, 'description')}`}
              readOnly={ro}
            />
          </ExpandedField>
          <ExpandedField label="Version" tip="Semver string for tracking stage config changes.">
            <InlineEdit
              value={stage.version}
              onChange={(v) => onUpdate({ version: String(v ?? '1.0') })}
              placeholder="1.0"
              className={accentIf(stage, 'version')}
              readOnly={ro}
            />
          </ExpandedField>
          <ExpandedField label="Config" tip="Stage config file to reference. When set, most fields are read from the YAML file. Set to 'None (inline)' for full manual control.">
            <InlineSelect
              value={stage.stage_ref ?? ''}
              options={[
                { value: '', label: 'inline' },
                ...(stageConfigs?.configs?.map((cfg) => ({
                  value: `configs/stages/${cfg.name}.yaml`,
                  label: cfg.name,
                })) ?? []),
              ]}
              onChange={(v) => onUpdate({ stage_ref: v || null })}
              tooltip="Stage config source"
            />
          </ExpandedField>
        </div>

        {/* Agents */}
        <div className="px-3 py-2 border-b border-temper-border/30">
          <SectionHeader
            title="Agents"
            tooltip="AI agents assigned to this stage. In inline mode you can add/remove agents and configure execution mode. In referenced mode, agents are defined in the stage config file."
          />
          {hasStageRef ? (
            <RefAgentsSection stageRef={stage.stage_ref!} />
          ) : (
            <InlineAgentsSection stage={stage} onUpdate={onUpdate} />
          )}
        </div>

        {/* Dependencies */}
        <div className="px-3 py-2 border-b border-temper-border/30">
          <SectionHeader title="Dependencies" tooltip="DAG edges that control execution order. Depends On: stages that must complete first. Loops Back To: create retry/iteration loops. Condition: skip this stage unless truthy." />
          <ExpandedField label="Depends" tip="Stages that must complete before this one runs. Creates directed edges in the DAG. Multiple dependencies = all must finish (AND logic).">
            <div className="flex flex-wrap items-center gap-1">
              {stage.depends_on.map((dep) => (
                <span
                  key={dep}
                  className="inline-flex items-center gap-0.5 px-1.5 py-0.5 text-[10px] bg-temper-surface border border-temper-border/50 rounded text-temper-text"
                >
                  {dep}
                  <button
                    onClick={() => onUpdate({ depends_on: stage.depends_on.filter((d) => d !== dep) })}
                    className="text-[10px] text-red-400 hover:text-red-300"
                  >
                    &times;
                  </button>
                </span>
              ))}
              {otherStageNames.filter((n) => !stage.depends_on.includes(n)).length > 0 && (
                <select
                  value=""
                  onChange={(e) => {
                    if (!e.target.value) return;
                    onUpdate({ depends_on: [...stage.depends_on, e.target.value] });
                  }}
                  className="text-[9px] bg-temper-surface border border-temper-border rounded text-temper-text-muted px-1 py-0.5"
                >
                  <option value="">+ Add</option>
                  {otherStageNames
                    .filter((n) => !stage.depends_on.includes(n))
                    .map((n) => <option key={n} value={n}>{n}</option>)}
                </select>
              )}
            </div>
          </ExpandedField>
          <ExpandedField label="Loop to" tip="Create a retry/iteration loop back to an earlier stage. The loop runs until max_loops is reached or a convergence condition is met.">
            <InlineSelect
              value={stage.loops_back_to ?? ''}
              options={[
                { value: '', label: 'none' },
                ...otherStageNames.map((n) => ({ value: n, label: n })),
              ]}
              onChange={(v) => onUpdate({ loops_back_to: v || null })}
              tooltip="Loop back target"
            />
          </ExpandedField>
          {stage.loops_back_to && (
            <ExpandedField label="Max loops" tip="Maximum iterations before breaking the loop. Leave empty for unlimited (controlled by convergence).">
              <InlineEdit
                value={stage.max_loops}
                onChange={(v) => onUpdate({ max_loops: v != null && v !== '' ? Number(v) : null })}
                type="number"
                emptyLabel="unlimited"
                min={1}
              />
            </ExpandedField>
          )}
          <ExpandedField label="Condition" tip="Jinja2 expression evaluated at runtime. Stage is skipped if falsy. Use {{ variable }} syntax. Example: {{ needs_review }}">
            <InlineEdit
              value={stage.condition}
              onChange={(v) => onUpdate({ condition: v != null && String(v) !== '' ? String(v) : null })}
              emptyLabel="always run"
              placeholder="{{ condition }}"
              className={accentIf(stage, 'condition')}
            />
          </ExpandedField>
        </div>

        {/* Input Wiring */}
        <div className="px-3 py-2 border-b border-temper-border/30">
          <SectionHeader title="Input Wiring" tooltip="Map data from other stages or workflow inputs into this stage. Resolved inputs from the stage config are shown read-only. Override or add additional inputs below." />
          {/* Resolved inputs from config (read-only) */}
          {resolvedInputs.length > 0 && (
            <div className="mb-2">
              {resolvedInputs.map(([key, val]) => (
                <div key={`cfg-${key}`} className="flex items-center gap-1 mb-1 opacity-60">
                  <span className="w-24 text-[10px] text-temper-text px-1.5 py-0.5 bg-temper-surface/50 border border-temper-border/50 rounded truncate">
                    {key}
                  </span>
                  <span className="text-[8px] text-temper-text-dim">&larr;</span>
                  <span className="flex-1 text-[10px] text-temper-text-muted truncate">
                    {val.source}
                  </span>
                  <span className="text-[8px] px-1 py-px rounded bg-temper-surface text-temper-text-dim shrink-0">
                    cfg
                  </span>
                </div>
              ))}
            </div>
          )}
          {/* Editable overrides */}
          <CompactKeyValueEditor
            entries={Object.fromEntries(
              Object.entries(stage.inputs).map(([k, v]) => [k, v.source])
            )}
            onChange={(entries) => {
              const inputs: Record<string, { source: string }> = {};
              for (const [k, v] of Object.entries(entries)) {
                inputs[k] = { source: v };
              }
              onUpdate({ inputs });
            }}
            keyPlaceholder="input"
            valuePlaceholder="stage.output_key"
          />
        </div>

        {/* ====== COLLAPSED ADVANCED SECTIONS ====== */}

        {/* Execution */}
        <CollapsibleSection title="Execution" tooltip="Stage-level execution settings. Timeout controls how long the stage can run before being killed.">
          <ExpandedField label="Timeout" tip="Maximum time in seconds this stage can run. The stage is killed after this duration. Set high for stages with many agents or long-running tools.">
            <InlineEdit
              value={stage.timeout_seconds}
              onChange={(v) => onUpdate({ timeout_seconds: Number(v) || STAGE_DEFAULTS.timeout_seconds })}
              type="number"
              className={accentIf(stage, 'timeout_seconds')}
              readOnly={ro}
              min={0}
            />
            <span className="text-[9px] text-temper-text-dim ml-1">s</span>
          </ExpandedField>
        </CollapsibleSection>

        {/* Collaboration Details */}
        <CollapsibleSection title="Collaboration Details" tooltip="Fine-tune how agents collaborate within this stage. These settings only apply when a collaboration strategy other than 'independent' is selected.">
          <ExpandedField label="Max rounds" tip="Maximum collaboration rounds before forcing a result. Each round lets agents exchange messages and refine their outputs.">
            <InlineEdit
              value={stage.collaboration_max_rounds}
              onChange={(v) => onUpdate({ collaboration_max_rounds: Number(v) || STAGE_DEFAULTS.collaboration_max_rounds })}
              type="number"
              className={accentIf(stage, 'collaboration_max_rounds')}
              readOnly={ro}
              min={1}
            />
          </ExpandedField>
          <ExpandedField label="Conv. thr" labelWidth="w-20" tip="Convergence threshold (0-1). Collaboration stops early when agents' outputs are this similar. Higher = stricter convergence requirements.">
            <InlineEdit
              value={stage.collaboration_convergence_threshold}
              onChange={(v) => onUpdate({ collaboration_convergence_threshold: Number(v) || STAGE_DEFAULTS.collaboration_convergence_threshold })}
              type="number"
              className={accentIf(stage, 'collaboration_convergence_threshold')}
              readOnly={ro}
              min={0}
              max={1}
              step={0.05}
            />
          </ExpandedField>
          <ExpandedField label="Dialogue" tip="Enable dialogue mode — agents see and respond to each other's outputs in real-time rather than working independently per round.">
            <InlineToggle
              value={stage.collaboration_dialogue_mode}
              onChange={(v) => onUpdate({ collaboration_dialogue_mode: v })}
              tooltip="Enable dialogue mode"
              className={accentIf(stage, 'collaboration_dialogue_mode')}
            />
          </ExpandedField>
          <ExpandedField label="Roles" tip="Assign named roles to agents (e.g. leader: agent_a, critic: agent_b). Roles influence how the collaboration strategy distributes work.">
            <CompactKeyValueEditor
              entries={stage.collaboration_roles}
              onChange={(v) => onUpdate({ collaboration_roles: v })}
              keyPlaceholder="role"
              valuePlaceholder="agent_name"
              readOnlyKeys={ro}
            />
          </ExpandedField>
          <ExpandedField label="Budget/rnd" labelWidth="w-20" tip="Maximum LLM cost per collaboration round in USD. Prevents runaway costs in long debates.">
            <InlineEdit
              value={stage.collaboration_round_budget_usd}
              onChange={(v) => onUpdate({ collaboration_round_budget_usd: v != null && v !== '' ? Number(v) : null })}
              type="number"
              emptyLabel="no limit"
              className={accentIf(stage, 'collaboration_round_budget_usd')}
              readOnly={ro}
              min={0}
              step={0.01}
            />
          </ExpandedField>
          <ExpandedField label="Dlg rounds" labelWidth="w-20" tip="Max dialogue rounds (within a single collaboration round). Controls how many back-and-forth exchanges agents can have.">
            <InlineEdit
              value={stage.collaboration_max_dialogue_rounds}
              onChange={(v) => onUpdate({ collaboration_max_dialogue_rounds: Number(v) || STAGE_DEFAULTS.collaboration_max_dialogue_rounds })}
              type="number"
              className={accentIf(stage, 'collaboration_max_dialogue_rounds')}
              readOnly={ro}
              min={1}
            />
          </ExpandedField>
          <ExpandedField label="Ctx window" labelWidth="w-20" tip="How many previous collaboration rounds are included in each agent's context. Lower values reduce prompt size but agents lose historical context.">
            <InlineEdit
              value={stage.collaboration_context_window_rounds}
              onChange={(v) => onUpdate({ collaboration_context_window_rounds: Number(v) || STAGE_DEFAULTS.collaboration_context_window_rounds })}
              type="number"
              className={accentIf(stage, 'collaboration_context_window_rounds')}
              readOnly={ro}
              min={0}
            />
          </ExpandedField>
        </CollapsibleSection>

        {/* Conflict Resolution */}
        <CollapsibleSection title="Conflict Resolution" tooltip="How to resolve conflicting outputs when multiple agents produce different results. Strategy determines the resolution algorithm, metrics determine what to optimize.">
          <ExpandedField label="Strategy" tip="Algorithm for resolving conflicts. Leave empty for default. Options: confidence_weighted, voting, llm_judge, merit_based.">
            <InlineEdit
              value={stage.conflict_strategy}
              onChange={(v) => onUpdate({ conflict_strategy: String(v ?? '') })}
              emptyLabel="default"
              className={accentIf(stage, 'conflict_strategy')}
              readOnly={ro}
            />
          </ExpandedField>
          <ExpandedField label="Metrics" tip="Which metrics to use for conflict resolution scoring. Agents are ranked by these metrics. Common: confidence, quality, relevance.">
            <CompactArrayEditor
              values={stage.conflict_metrics}
              onChange={(v) => onUpdate({ conflict_metrics: v })}
              placeholder="metric"
            />
          </ExpandedField>
          <ExpandedField label="Weights" tip="Relative weights for each metric (0-1). Higher weight = more influence on the final resolution. Unweighted metrics default to equal importance.">
            <CompactKeyValueEditor
              entries={stage.conflict_metric_weights}
              onChange={(v) => onUpdate({ conflict_metric_weights: v })}
              keyPlaceholder="metric"
              valuePlaceholder="weight"
              readOnlyKeys={ro}
            />
          </ExpandedField>
          <ExpandedField label="Auto thr" labelWidth="w-20" tip="Auto-resolve threshold (0-1). When the top-scoring agent exceeds this threshold, its output is accepted without further review.">
            <InlineEdit
              value={stage.conflict_auto_resolve_threshold}
              onChange={(v) => onUpdate({ conflict_auto_resolve_threshold: Number(v) || STAGE_DEFAULTS.conflict_auto_resolve_threshold })}
              type="number"
              className={accentIf(stage, 'conflict_auto_resolve_threshold')}
              readOnly={ro}
              min={0}
              max={1}
              step={0.05}
            />
          </ExpandedField>
          <ExpandedField label="Esc. thr" labelWidth="w-20" tip="Escalation threshold (0-1). When all agents score below this, the conflict is escalated to a human reviewer or fallback policy.">
            <InlineEdit
              value={stage.conflict_escalation_threshold}
              onChange={(v) => onUpdate({ conflict_escalation_threshold: Number(v) || STAGE_DEFAULTS.conflict_escalation_threshold })}
              type="number"
              className={accentIf(stage, 'conflict_escalation_threshold')}
              readOnly={ro}
              min={0}
              max={1}
              step={0.05}
            />
          </ExpandedField>
        </CollapsibleSection>

        {/* Safety */}
        <CollapsibleSection title="Safety" tooltip="Stage-level safety controls. Override the workflow-level safety mode for this specific stage.">
          <ExpandedField label="Mode" tip="Safety mode for this stage. Execute: run actions for real. Monitor: log but block side-effects. Audit: require human approval for each action.">
            <InlineSelect
              value={stage.safety_mode}
              options={safetyModeOptions}
              onChange={(v) => onUpdate({ safety_mode: v })}
              tooltip="Stage safety mode"
              className={accentIf(stage, 'safety_mode')}
            />
          </ExpandedField>
          <ExpandedField label="Dry-run" tip="Run a dry-run pass before the actual execution. Tool calls are simulated first, and only executed if the dry-run succeeds.">
            <InlineToggle
              value={stage.safety_dry_run_first}
              onChange={(v) => onUpdate({ safety_dry_run_first: v })}
              tooltip="Dry-run before execution"
              className={accentIf(stage, 'safety_dry_run_first')}
            />
          </ExpandedField>
          <ExpandedField label="Approval" tip="Require human approval before this stage executes. Pauses the workflow and waits for sign-off via dashboard or CLI.">
            <InlineToggle
              value={stage.safety_require_approval}
              onChange={(v) => onUpdate({ safety_require_approval: v })}
              tooltip="Require human approval"
              className={accentIf(stage, 'safety_require_approval')}
            />
          </ExpandedField>
        </CollapsibleSection>

        {/* Error Handling */}
        <CollapsibleSection title="Error Handling" tooltip="What happens when individual agents fail within this stage. Controls retry behavior and minimum success requirements.">
          <ExpandedField label="On fail" tip="What to do when an agent fails. Continue: use remaining agents' outputs. Halt: stop the stage immediately. Retry: re-run the failed agent. Skip: ignore the failed agent entirely.">
            <InlineSelect
              value={stage.error_on_agent_failure}
              options={agentFailureOptions}
              onChange={(v) => onUpdate({ error_on_agent_failure: v })}
              tooltip="Agent failure behavior"
              className={accentIf(stage, 'error_on_agent_failure')}
            />
          </ExpandedField>
          <ExpandedField label="Min ok" tip="Minimum number of agents that must succeed for the stage to be considered successful. If fewer succeed, the stage fails.">
            <InlineEdit
              value={stage.error_min_successful_agents}
              onChange={(v) => onUpdate({ error_min_successful_agents: Number(v) || STAGE_DEFAULTS.error_min_successful_agents })}
              type="number"
              className={accentIf(stage, 'error_min_successful_agents')}
              readOnly={ro}
              min={0}
            />
          </ExpandedField>
          <ExpandedField label="Retry" tip="Automatically retry failed agents. When on, failed agents are re-run up to Max Retries times before the failure policy takes effect.">
            <InlineToggle
              value={stage.error_retry_failed_agents}
              onChange={(v) => onUpdate({ error_retry_failed_agents: v })}
              tooltip="Retry failed agents"
              className={accentIf(stage, 'error_retry_failed_agents')}
            />
          </ExpandedField>
          <ExpandedField label="Max retries" labelWidth="w-20" tip="Maximum times to retry a failed agent. Each retry re-runs the agent with the same inputs. Set to 0 to disable per-agent retries.">
            <InlineEdit
              value={stage.error_max_agent_retries}
              onChange={(v) => onUpdate({ error_max_agent_retries: Number(v) || 0 })}
              type="number"
              className={accentIf(stage, 'error_max_agent_retries')}
              readOnly={ro}
              min={0}
            />
          </ExpandedField>
        </CollapsibleSection>

        {/* Quality Gates */}
        <CollapsibleSection title="Quality Gates" tooltip="Automated quality checks on stage outputs. When enabled, the engine validates that outputs meet minimum confidence, findings count, and citation requirements.">
          <ExpandedField label="Enabled" tip="Activate quality gate checks. When on, stage outputs are validated against the thresholds below before being accepted.">
            <InlineToggle
              value={stage.quality_gates_enabled}
              onChange={(v) => onUpdate({ quality_gates_enabled: v })}
              tooltip="Enable quality gates"
              className={accentIf(stage, 'quality_gates_enabled')}
            />
          </ExpandedField>
          {stage.quality_gates_enabled && (
            <>
              <ExpandedField label="Min conf" labelWidth="w-20" tip="Minimum confidence score (0-1) required for stage output to pass. Agents report confidence in their structured output.">
                <InlineEdit
                  value={stage.quality_gates_min_confidence}
                  onChange={(v) => onUpdate({ quality_gates_min_confidence: Number(v) || STAGE_DEFAULTS.quality_gates_min_confidence })}
                  type="number"
                  className={accentIf(stage, 'quality_gates_min_confidence')}
                  readOnly={ro}
                  min={0}
                  max={1}
                  step={0.05}
                />
              </ExpandedField>
              <ExpandedField label="Min finds" labelWidth="w-20" tip="Minimum number of findings/items in the output. Useful for analysis stages where you expect a certain level of detail.">
                <InlineEdit
                  value={stage.quality_gates_min_findings}
                  onChange={(v) => onUpdate({ quality_gates_min_findings: Number(v) || STAGE_DEFAULTS.quality_gates_min_findings })}
                  type="number"
                  className={accentIf(stage, 'quality_gates_min_findings')}
                  readOnly={ro}
                  min={0}
                />
              </ExpandedField>
              <ExpandedField label="Citations" labelWidth="w-20" tip="Require agents to include citations/references in their output. Helps ensure claims are grounded in evidence.">
                <InlineToggle
                  value={stage.quality_gates_require_citations}
                  onChange={(v) => onUpdate({ quality_gates_require_citations: v })}
                  tooltip="Require citations"
                  className={accentIf(stage, 'quality_gates_require_citations')}
                />
              </ExpandedField>
              <ExpandedField label="On fail" tip="What happens when quality gates aren't met. Retry: re-run the stage. Halt: stop the workflow. Skip: mark as failed and continue. Continue: accept anyway.">
                <InlineSelect
                  value={stage.quality_gates_on_failure}
                  options={gateFailureOptions}
                  onChange={(v) => onUpdate({ quality_gates_on_failure: v })}
                  tooltip="Gate failure action"
                  className={accentIf(stage, 'quality_gates_on_failure')}
                />
              </ExpandedField>
              <ExpandedField label="Max retries" labelWidth="w-20" tip="Maximum times to retry when quality gates fail. After this, the on-failure action takes effect.">
                <InlineEdit
                  value={stage.quality_gates_max_retries}
                  onChange={(v) => onUpdate({ quality_gates_max_retries: Number(v) || 0 })}
                  type="number"
                  className={accentIf(stage, 'quality_gates_max_retries')}
                  readOnly={ro}
                  min={0}
                />
              </ExpandedField>
            </>
          )}
        </CollapsibleSection>

        {/* Convergence */}
        <CollapsibleSection title="Convergence" tooltip="Stop iterating when outputs stabilize. Used with loop-back edges to detect when further iterations won't improve results.">
          <ExpandedField label="Enabled" tip="Activate convergence detection for this stage. When on, the engine compares outputs between iterations and stops if they're sufficiently similar.">
            <InlineToggle
              value={stage.convergence_enabled}
              onChange={(v) => onUpdate({ convergence_enabled: v })}
              tooltip="Enable convergence detection"
              className={accentIf(stage, 'convergence_enabled')}
            />
          </ExpandedField>
          {stage.convergence_enabled && (
            <>
              <ExpandedField label="Max iters" labelWidth="w-20" tip="Maximum iterations before forcing convergence. Acts as a safety net to prevent infinite loops.">
                <InlineEdit
                  value={stage.convergence_max_iterations}
                  onChange={(v) => onUpdate({ convergence_max_iterations: Number(v) || STAGE_DEFAULTS.convergence_max_iterations })}
                  type="number"
                  className={accentIf(stage, 'convergence_max_iterations')}
                  readOnly={ro}
                  min={1}
                />
              </ExpandedField>
              <ExpandedField label="Sim. thr" labelWidth="w-20" tip="Similarity threshold (0-1). Outputs are considered converged when similarity exceeds this value. Higher = stricter.">
                <InlineEdit
                  value={stage.convergence_similarity_threshold}
                  onChange={(v) => onUpdate({ convergence_similarity_threshold: Number(v) || STAGE_DEFAULTS.convergence_similarity_threshold })}
                  type="number"
                  className={accentIf(stage, 'convergence_similarity_threshold')}
                  readOnly={ro}
                  min={0}
                  max={1}
                  step={0.01}
                />
              </ExpandedField>
              <ExpandedField label="Method" tip="Algorithm for comparing outputs between iterations. exact_hash: byte-identical check. cosine_similarity: semantic comparison. levenshtein: text distance.">
                <InlineSelect
                  value={stage.convergence_method}
                  options={convergenceMethodOptions}
                  onChange={(v) => onUpdate({ convergence_method: v })}
                  tooltip="Convergence comparison method"
                  className={accentIf(stage, 'convergence_method')}
                />
              </ExpandedField>
            </>
          )}
        </CollapsibleSection>

        {/* Outputs */}
        <CollapsibleSection title="Outputs" tooltip="Named output definitions for this stage. These are the values that downstream stages can reference in their input wiring.">
          <CompactKeyValueEditor
            entries={stage.outputs}
            onChange={(v) => onUpdate({ outputs: v })}
            keyPlaceholder="name"
            valuePlaceholder="type"
            readOnlyKeys={ro}
          />
        </CollapsibleSection>
      </div>
    </div>
  );
}
