/**
 * Zustand store for the Workflow Studio visual editor.
 * Holds the editable workflow configuration, stage graph, and selection state.
 */
import { create } from 'zustand';
import { immer } from 'zustand/middleware/immer';

export type AgentMode = 'sequential' | 'parallel' | 'adaptive';
export type CollaborationStrategy = 'independent' | 'leader' | 'consensus' | 'debate' | 'round_robin';

export interface DesignStage {
  name: string;
  stage_ref: string | null;
  depends_on: string[];
  loops_back_to: string | null;
  max_loops: number | null;
  condition: string | null;
  inputs: Record<string, { source: string }>;
  /** Agent names — only used for inline stages (no stage_ref). */
  agents: string[];
  agent_mode: AgentMode;
  collaboration_strategy: CollaborationStrategy;
}

export interface WorkflowOutput {
  name: string;
  description: string;
  source: string;
}

export interface WorkflowMeta {
  name: string;
  description: string;
  timeout_seconds: number;
  max_cost_usd: number | null;
  on_stage_failure: 'halt' | 'continue' | 'skip';
  global_safety_mode: 'execute' | 'monitor' | 'audit';
  required_inputs: string[];
  optional_inputs: string[];
  outputs: WorkflowOutput[];
}

export interface ValidationState {
  status: 'idle' | 'validating' | 'valid' | 'invalid';
  errors: string[];
}

/** Resolved agent info from stage configs (fetched at load time). */
export interface ResolvedStageInfo {
  agents: string[];
  agentMode: string;
  collaborationStrategy: string;
}

export interface DesignState {
  configName: string | null;
  isDirty: boolean;
  meta: WorkflowMeta;
  stages: DesignStage[];
  selectedStageName: string | null;
  selectedAgentName: string | null;
  nodePositions: Record<string, { x: number; y: number }>;
  validation: ValidationState;
  /** Agent info resolved from stage_ref configs. Keyed by stage name. */
  resolvedStageInfo: Record<string, ResolvedStageInfo>;

  setMeta: (partial: Partial<WorkflowMeta>) => void;
  addStage: (stage: DesignStage) => void;
  updateStage: (name: string, partial: Partial<Omit<DesignStage, 'name'>>) => void;
  renameStage: (oldName: string, newName: string) => void;
  removeStage: (name: string) => void;
  addDependency: (source: string, target: string) => void;
  removeDependency: (source: string, target: string) => void;
  setLoopBack: (source: string, target: string | null, maxLoops?: number | null) => void;
  selectStage: (name: string | null) => void;
  selectAgent: (name: string | null) => void;
  setNodePosition: (name: string, x: number, y: number) => void;
  setValidation: (validation: ValidationState) => void;
  setResolvedStageInfo: (stageName: string, info: ResolvedStageInfo) => void;
  markSaved: (name: string) => void;
  loadFromConfig: (name: string, config: Record<string, unknown>) => void;
  reset: () => void;
  toWorkflowConfig: () => Record<string, unknown>;
}

const DEFAULT_TIMEOUT = 600;

/** Normalize outputs from YAML — handles both string[] and object[] formats. */
function normalizeOutputs(raw: unknown): WorkflowOutput[] {
  if (!Array.isArray(raw)) return [];
  return raw.map((item) => {
    if (typeof item === 'string') {
      return { name: item, description: '', source: '' };
    }
    if (typeof item === 'object' && item !== null) {
      const obj = item as Record<string, unknown>;
      return {
        name: (obj.name as string) ?? '',
        description: (obj.description as string) ?? '',
        source: (obj.source as string) ?? '',
      };
    }
    return { name: String(item), description: '', source: '' };
  });
}

function defaultMeta(): WorkflowMeta {
  return {
    name: '',
    description: '',
    timeout_seconds: DEFAULT_TIMEOUT,
    max_cost_usd: null,
    on_stage_failure: 'halt',
    global_safety_mode: 'execute',
    required_inputs: [],
    optional_inputs: [],
    outputs: [],
  };
}

export const useDesignStore = create<DesignState>()(
  immer((set, get) => ({
    configName: null,
    isDirty: false,
    meta: defaultMeta(),
    stages: [],
    selectedStageName: null,
    selectedAgentName: null,
    nodePositions: {},
    validation: { status: 'idle', errors: [] },
    resolvedStageInfo: {},

    setMeta: (partial) =>
      set((state) => {
        Object.assign(state.meta, partial);
        state.isDirty = true;
      }),

    addStage: (stage) =>
      set((state) => {
        const exists = state.stages.some((s) => s.name === stage.name);
        if (exists) return;
        state.stages.push(stage);
        state.isDirty = true;
      }),

    updateStage: (name, partial) =>
      set((state) => {
        const stage = state.stages.find((s) => s.name === name);
        if (!stage) return;
        Object.assign(stage, partial);
        state.isDirty = true;
      }),

    renameStage: (oldName, newName) =>
      set((state) => {
        if (oldName === newName) return;
        const exists = state.stages.some((s) => s.name === newName);
        if (exists) return;
        const stage = state.stages.find((s) => s.name === oldName);
        if (!stage) return;
        stage.name = newName;
        // Update references in other stages
        for (const s of state.stages) {
          s.depends_on = s.depends_on.map((d) => (d === oldName ? newName : d));
          if (s.loops_back_to === oldName) s.loops_back_to = newName;
        }
        // Update node positions
        if (state.nodePositions[oldName]) {
          state.nodePositions[newName] = state.nodePositions[oldName];
          delete state.nodePositions[oldName];
        }
        if (state.selectedStageName === oldName) {
          state.selectedStageName = newName;
        }
        state.isDirty = true;
      }),

    removeStage: (name) =>
      set((state) => {
        state.stages = state.stages.filter((s) => s.name !== name);
        // Clean up references
        for (const s of state.stages) {
          s.depends_on = s.depends_on.filter((d) => d !== name);
          if (s.loops_back_to === name) s.loops_back_to = null;
        }
        delete state.nodePositions[name];
        if (state.selectedStageName === name) {
          state.selectedStageName = null;
        }
        state.isDirty = true;
      }),

    addDependency: (source, target) =>
      set((state) => {
        const targetStage = state.stages.find((s) => s.name === target);
        if (!targetStage) return;
        if (targetStage.depends_on.includes(source)) return;
        targetStage.depends_on.push(source);
        state.isDirty = true;
      }),

    removeDependency: (source, target) =>
      set((state) => {
        const targetStage = state.stages.find((s) => s.name === target);
        if (!targetStage) return;
        targetStage.depends_on = targetStage.depends_on.filter((d) => d !== source);
        state.isDirty = true;
      }),

    setLoopBack: (source, target, maxLoops) =>
      set((state) => {
        const stage = state.stages.find((s) => s.name === source);
        if (!stage) return;
        stage.loops_back_to = target;
        if (maxLoops !== undefined) stage.max_loops = maxLoops;
        state.isDirty = true;
      }),

    selectStage: (name) =>
      set((state) => {
        state.selectedStageName = name;
        state.selectedAgentName = null;
      }),

    selectAgent: (name) =>
      set((state) => {
        state.selectedAgentName = name;
      }),

    setNodePosition: (name, x, y) =>
      set((state) => {
        state.nodePositions[name] = { x, y };
      }),

    setValidation: (validation) =>
      set((state) => {
        state.validation = validation;
      }),

    setResolvedStageInfo: (stageName, info) =>
      set((state) => {
        state.resolvedStageInfo[stageName] = info;
      }),

    markSaved: (name) =>
      set((state) => {
        state.configName = name;
        state.isDirty = false;
      }),

    loadFromConfig: (name, config) =>
      set((state) => {
        state.configName = name;
        state.isDirty = false;
        state.selectedStageName = null;
        state.selectedAgentName = null;
        state.nodePositions = {};
        state.validation = { status: 'idle', errors: [] };
        state.resolvedStageInfo = {};

        // Parse the workflow config
        const wf = (config as { workflow?: Record<string, unknown> }).workflow ?? config;
        const inner = wf as Record<string, unknown>;

        state.meta = {
          name: (inner.name as string) ?? name,
          description: (inner.description as string) ?? '',
          timeout_seconds: (inner.timeout_seconds as number) ?? DEFAULT_TIMEOUT,
          max_cost_usd: (inner.max_cost_usd as number | null) ?? null,
          on_stage_failure: (inner.on_stage_failure as WorkflowMeta['on_stage_failure']) ?? 'halt',
          global_safety_mode: (inner.global_safety_mode as WorkflowMeta['global_safety_mode']) ?? 'execute',
          required_inputs: (inner.required_inputs as string[]) ?? [],
          optional_inputs: (inner.optional_inputs as string[]) ?? [],
          outputs: normalizeOutputs(inner.outputs),
        };

        const rawStages = (inner.stages as Array<Record<string, unknown>>) ?? [];
        state.stages = rawStages.map((rs) => {
          const exec = rs.execution as Record<string, unknown> | undefined;
          const collab = rs.collaboration as Record<string, unknown> | undefined;
          return {
            name: (rs.name as string) ?? '',
            stage_ref: (rs.stage_ref as string | null) ?? (rs.stage as string | null) ?? null,
            depends_on: (rs.depends_on as string[]) ?? [],
            loops_back_to: (rs.loops_back_to as string | null) ?? null,
            max_loops: (rs.max_loops as number | null) ?? null,
            condition: (rs.condition as string | null) ?? null,
            inputs: (rs.inputs as Record<string, { source: string }>) ?? {},
            agents: (rs.agents as string[]) ?? [],
            agent_mode: (exec?.agent_mode as AgentMode) ?? 'sequential',
            collaboration_strategy: (collab?.strategy as CollaborationStrategy) ?? 'independent',
          };
        });
      }),

    reset: () =>
      set((state) => {
        state.configName = null;
        state.isDirty = false;
        state.meta = defaultMeta();
        state.stages = [];
        state.selectedStageName = null;
        state.selectedAgentName = null;
        state.nodePositions = {};
        state.validation = { status: 'idle', errors: [] };
        state.resolvedStageInfo = {};
      }),

    toWorkflowConfig: () => {
      const { meta, stages } = get();
      const stageConfigs = stages.map((s) => {
        const entry: Record<string, unknown> = { name: s.name };
        if (s.stage_ref) entry.stage_ref = s.stage_ref;
        if (s.depends_on.length > 0) entry.depends_on = s.depends_on;
        if (s.loops_back_to) entry.loops_back_to = s.loops_back_to;
        if (s.max_loops != null) entry.max_loops = s.max_loops;
        if (s.condition) entry.condition = s.condition;
        if (Object.keys(s.inputs).length > 0) entry.inputs = s.inputs;
        // Inline agent config (only when no stage_ref)
        if (!s.stage_ref && s.agents.length > 0) {
          entry.agents = s.agents;
          if (s.agent_mode !== 'sequential') {
            entry.execution = { agent_mode: s.agent_mode };
          }
          if (s.collaboration_strategy !== 'independent') {
            entry.collaboration = { strategy: s.collaboration_strategy };
          }
        }
        return entry;
      });

      const config: Record<string, unknown> = {
        name: meta.name,
        stages: stageConfigs,
      };

      if (meta.description) config.description = meta.description;
      if (meta.timeout_seconds !== DEFAULT_TIMEOUT) config.timeout_seconds = meta.timeout_seconds;
      if (meta.max_cost_usd != null) config.max_cost_usd = meta.max_cost_usd;
      if (meta.on_stage_failure !== 'halt') config.on_stage_failure = meta.on_stage_failure;
      if (meta.global_safety_mode !== 'execute') config.global_safety_mode = meta.global_safety_mode;
      if (meta.required_inputs.length > 0) config.required_inputs = meta.required_inputs;
      if (meta.optional_inputs.length > 0) config.optional_inputs = meta.optional_inputs;
      if (meta.outputs.length > 0) {
        config.outputs = meta.outputs.map((o) => {
          const entry: Record<string, string> = { name: o.name };
          if (o.description) entry.description = o.description;
          if (o.source) entry.source = o.source;
          return entry;
        });
      }

      return { workflow: config };
    },
  })),
);
