/**
 * Undo/redo history management for the design store.
 * Maintains two stacks: past (undo) and future (redo).
 * Each entry is a snapshot of the mutable design state.
 */
import type { WorkflowMeta, DesignStage } from './designTypes';

const MAX_HISTORY = 50;

/** The subset of DesignState that is tracked for undo/redo. */
export interface DesignSnapshot {
  meta: WorkflowMeta;
  stages: DesignStage[];
  nodePositions: Record<string, { x: number; y: number }>;
}

export interface HistoryState {
  past: DesignSnapshot[];
  future: DesignSnapshot[];
}

export function createHistoryState(): HistoryState {
  return { past: [], future: [] };
}

/** Deep-clone the tracked portion of the store state. */
export function snapshotState(
  meta: WorkflowMeta,
  stages: DesignStage[],
  nodePositions: Record<string, { x: number; y: number }>,
): DesignSnapshot {
  return JSON.parse(JSON.stringify({ meta, stages, nodePositions }));
}

/**
 * Push a snapshot onto the past stack before a mutation.
 * Clears the future (redo) stack because new mutations invalidate redo history.
 */
export function pushSnapshot(
  history: HistoryState,
  snapshot: DesignSnapshot,
): HistoryState {
  const past = [...history.past, snapshot];
  if (past.length > MAX_HISTORY) {
    past.shift();
  }
  return { past, future: [] };
}

/** Pop the most recent snapshot from past, returning it and updated stacks. */
export function popUndo(
  history: HistoryState,
  current: DesignSnapshot,
): { snapshot: DesignSnapshot; history: HistoryState } | null {
  if (history.past.length === 0) return null;
  const past = [...history.past];
  const snapshot = past.pop()!;
  const future = [current, ...history.future];
  return { snapshot, history: { past, future } };
}

/** Pop the most recent snapshot from future, returning it and updated stacks. */
export function popRedo(
  history: HistoryState,
  current: DesignSnapshot,
): { snapshot: DesignSnapshot; history: HistoryState } | null {
  if (history.future.length === 0) return null;
  const future = [...history.future];
  const snapshot = future.shift()!;
  const past = [...history.past, current];
  return { snapshot, history: { past, future } };
}
