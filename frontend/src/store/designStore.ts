/**
 * Zustand store for the Workflow Studio visual editor.
 * Holds the editable workflow configuration, stage graph, and selection state.
 */
import { create } from 'zustand';
import { immer } from 'zustand/middleware/immer';
import { defaultMeta } from './designDefaults';
import { parseWorkflowMeta, parseWorkflowStages, serializeWorkflowConfig } from './designPersistence';
import {
  snapshotState,
  pushSnapshot,
  popUndo,
  popRedo,
} from './designHistory';
import type {
  DesignState,
  ResolvedStageInfo,
  ResolvedAgentSummary,
  ValidationState,
} from './designTypes';
import type { DesignSnapshot } from './designHistory';

// Re-export types for backward compat
export type {
  AgentMode,
  CollaborationStrategy,
  DesignStage,
  WorkflowOutput,
  WorkflowMeta,
  ValidationState,
  ResolvedAgentSummary,
  ResolvedStageInfo,
  DesignState,
} from './designTypes';

export { defaultMeta, defaultDesignStage } from './designDefaults';

/** Capture the current snapshot from immer draft or plain state. */
function captureSnapshot(state: DesignState): DesignSnapshot {
  return snapshotState(state.meta, state.stages, state.nodePositions);
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
    resolvedAgentSummaries: {},

    _historyPast: [],
    _historyFuture: [],

    canUndo: false,
    canRedo: false,

    setMeta: (partial) =>
      set((state) => {
        const snap = captureSnapshot(state as unknown as DesignState);
        const result = pushSnapshot(
          { past: state._historyPast, future: state._historyFuture },
          snap,
        );
        state._historyPast = result.past;
        state._historyFuture = result.future;
        state.canUndo = result.past.length > 0;
        state.canRedo = false;
        Object.assign(state.meta, partial);
        state.isDirty = true;
      }),

    addStage: (stage) =>
      set((state) => {
        const exists = state.stages.some((s) => s.name === stage.name);
        if (exists) return;
        const snap = captureSnapshot(state as unknown as DesignState);
        const result = pushSnapshot(
          { past: state._historyPast, future: state._historyFuture },
          snap,
        );
        state._historyPast = result.past;
        state._historyFuture = result.future;
        state.canUndo = result.past.length > 0;
        state.canRedo = false;
        state.stages.push(stage);
        state.isDirty = true;
      }),

    updateStage: (name, partial) =>
      set((state) => {
        const stage = state.stages.find((s) => s.name === name);
        if (!stage) return;
        const snap = captureSnapshot(state as unknown as DesignState);
        const result = pushSnapshot(
          { past: state._historyPast, future: state._historyFuture },
          snap,
        );
        state._historyPast = result.past;
        state._historyFuture = result.future;
        state.canUndo = result.past.length > 0;
        state.canRedo = false;
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
        const snap = captureSnapshot(state as unknown as DesignState);
        const result = pushSnapshot(
          { past: state._historyPast, future: state._historyFuture },
          snap,
        );
        state._historyPast = result.past;
        state._historyFuture = result.future;
        state.canUndo = result.past.length > 0;
        state.canRedo = false;
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
        const snap = captureSnapshot(state as unknown as DesignState);
        const result = pushSnapshot(
          { past: state._historyPast, future: state._historyFuture },
          snap,
        );
        state._historyPast = result.past;
        state._historyFuture = result.future;
        state.canUndo = result.past.length > 0;
        state.canRedo = false;
        state.stages = state.stages.filter((s) => s.name !== name);
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
        const snap = captureSnapshot(state as unknown as DesignState);
        const result = pushSnapshot(
          { past: state._historyPast, future: state._historyFuture },
          snap,
        );
        state._historyPast = result.past;
        state._historyFuture = result.future;
        state.canUndo = result.past.length > 0;
        state.canRedo = false;
        targetStage.depends_on.push(source);
        state.isDirty = true;
      }),

    removeDependency: (source, target) =>
      set((state) => {
        const targetStage = state.stages.find((s) => s.name === target);
        if (!targetStage) return;
        const snap = captureSnapshot(state as unknown as DesignState);
        const result = pushSnapshot(
          { past: state._historyPast, future: state._historyFuture },
          snap,
        );
        state._historyPast = result.past;
        state._historyFuture = result.future;
        state.canUndo = result.past.length > 0;
        state.canRedo = false;
        targetStage.depends_on = targetStage.depends_on.filter((d) => d !== source);
        state.isDirty = true;
      }),

    setLoopBack: (source, target, maxLoops) =>
      set((state) => {
        const stage = state.stages.find((s) => s.name === source);
        if (!stage) return;
        const snap = captureSnapshot(state as unknown as DesignState);
        const result = pushSnapshot(
          { past: state._historyPast, future: state._historyFuture },
          snap,
        );
        state._historyPast = result.past;
        state._historyFuture = result.future;
        state.canUndo = result.past.length > 0;
        state.canRedo = false;
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

    setValidation: (validation: ValidationState) =>
      set((state) => {
        state.validation = validation;
      }),

    setResolvedStageInfo: (stageName: string, info: ResolvedStageInfo) =>
      set((state) => {
        state.resolvedStageInfo[stageName] = info;
      }),

    setResolvedAgentSummary: (name: string, summary: ResolvedAgentSummary) =>
      set((state) => {
        state.resolvedAgentSummaries[name] = summary;
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
        state.resolvedAgentSummaries = {};
        state.meta = parseWorkflowMeta(name, config);
        state.stages = parseWorkflowStages(config);
        // Clear history on load — fresh baseline
        state._historyPast = [];
        state._historyFuture = [];
        state.canUndo = false;
        state.canRedo = false;
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
        state.resolvedAgentSummaries = {};
        state._historyPast = [];
        state._historyFuture = [];
        state.canUndo = false;
        state.canRedo = false;
      }),

    toWorkflowConfig: () => {
      const { meta, stages } = get();
      return serializeWorkflowConfig(meta, stages);
    },

    undo: () =>
      set((state) => {
        const current = captureSnapshot(state as unknown as DesignState);
        const result = popUndo(
          { past: state._historyPast, future: state._historyFuture },
          current,
        );
        if (!result) return;
        state.meta = result.snapshot.meta;
        state.stages = result.snapshot.stages;
        state.nodePositions = result.snapshot.nodePositions;
        state._historyPast = result.history.past;
        state._historyFuture = result.history.future;
        state.canUndo = result.history.past.length > 0;
        state.canRedo = result.history.future.length > 0;
        state.isDirty = true;
      }),

    redo: () =>
      set((state) => {
        const current = captureSnapshot(state as unknown as DesignState);
        const result = popRedo(
          { past: state._historyPast, future: state._historyFuture },
          current,
        );
        if (!result) return;
        state.meta = result.snapshot.meta;
        state.stages = result.snapshot.stages;
        state.nodePositions = result.snapshot.nodePositions;
        state._historyPast = result.history.past;
        state._historyFuture = result.history.future;
        state.canUndo = result.history.past.length > 0;
        state.canRedo = result.history.future.length > 0;
        state.isDirty = true;
      }),
  })),
);
