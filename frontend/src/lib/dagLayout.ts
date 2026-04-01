/**
 * DAG layout engine — ported from flowchart.js.
 * Computes node positions for a left-to-right stage DAG.
 */
import type { StageExecution } from '@/types';
import type { DagInfo } from '@/store/selectors';
import { LAYOUT } from './constants';

export interface StagePosition {
  x: number;
  y: number;
  width: number;
  height: number;
}

/**
 * Compute {stageName -> position} from stage groups and DAG topology.
 * X = column from depth (longest path from root), Y = centered within depth group.
 *
 * If `measuredSizes` is provided, uses actual DOM measurements for spacing.
 * Otherwise falls back to estimates.
 */
export function computeStagePositions(
  stageGroups: Map<string, StageExecution[]>,
  dagInfo: DagInfo,
  expandedStages?: Set<string>,
  measuredSizes?: Map<string, { width: number; height: number }>,
): Map<string, StagePosition> {
  const positions = new Map<string, StagePosition>();

  /** Get width for a stage — measured if available, else estimated. */
  function getWidth(name: string): number {
    const m = measuredSizes?.get(name);
    if (m) return m.width;
    const isExpanded = expandedStages?.has(name) ?? false;
    if (!isExpanded) return LAYOUT.AGENT_WIDTH + 2 * LAYOUT.STAGE_PAD_X;
    const execs = stageGroups.get(name);
    const agentCount = execs
      ? Math.max((execs[execs.length - 1].agents ?? []).length, 1)
      : 1;
    return estimateExpandedWidth(agentCount);
  }

  /** Get height for a stage — measured if available, else estimated. */
  function getHeight(name: string): number {
    const m = measuredSizes?.get(name);
    if (m) return m.height;
    const isExpanded = expandedStages?.has(name) ?? false;
    const execs = stageGroups.get(name);
    const latest = execs ? execs[execs.length - 1] : undefined;
    if (!latest) return LAYOUT.STAGE_PAD_Y + LAYOUT.STAGE_HEADER_HEIGHT + LAYOUT.STAGE_METRICS_HEIGHT + LAYOUT.AGENT_HEIGHT;
    return estimateStageHeight(latest, isExpanded);
  }

  if (!dagInfo.hasDeps) {
    // Fallback: sequential left-to-right
    let xCursor = 0;
    for (const [name] of stageGroups) {
      const w = getWidth(name);
      const h = getHeight(name);
      positions.set(name, { x: xCursor, y: 0, width: w, height: h });
      xCursor += w + LAYOUT.STAGE_GAP_X;
    }
    return positions;
  }

  const depths = computeDepthsFromDepMap(dagInfo.depMap);

  // Group stage names by depth
  const depthGroups = new Map<number, string[]>();
  for (const [name] of stageGroups) {
    const depth = depths.get(name) ?? 0;
    const group = depthGroups.get(depth);
    if (group) {
      group.push(name);
    } else {
      depthGroups.set(depth, [name]);
    }
  }

  // Compute per-column X offsets using max node width in each column
  const maxDepth = Math.max(...Array.from(depthGroups.keys()), 0);
  const colXOffsets = new Map<number, number>();
  let xCursor = 0;
  for (let d = 0; d <= maxDepth; d++) {
    colXOffsets.set(d, xCursor);
    const names = depthGroups.get(d) ?? [];
    const maxW = names.reduce((acc, n) => Math.max(acc, getWidth(n)), 0);
    xCursor += (maxW || LAYOUT.AGENT_WIDTH + 2 * LAYOUT.STAGE_PAD_X) + LAYOUT.STAGE_GAP_X;
  }

  // Assign X from depth, Y centered within each depth group
  for (const [depth, names] of depthGroups) {
    const x = colXOffsets.get(depth) ?? 0;
    const heights = names.map((name) => getHeight(name));
    const widths = names.map((name) => getWidth(name));
    const totalH =
      heights.reduce((a, b) => a + b, 0) +
      (names.length - 1) * LAYOUT.STAGE_GAP_Y;
    let yCursor = -totalH / 2;
    for (let i = 0; i < names.length; i++) {
      positions.set(names[i], {
        x,
        y: yCursor,
        width: widths[i],
        height: heights[i],
      });
      yCursor += heights[i] + LAYOUT.STAGE_GAP_Y;
    }
  }

  return positions;
}

/**
 * Compute longest-path depths from a dependency map.
 * Roots (no deps) get depth 0; each other stage = max(pred depths) + 1.
 */
export function computeDepthsFromDepMap(
  depMap: Map<string, string[]>,
): Map<string, number> {
  const depths = new Map<string, number>();
  for (const [name, deps] of depMap) {
    if (deps.length === 0) depths.set(name, 0);
  }
  let changed = true;
  while (changed) {
    changed = false;
    for (const [name, deps] of depMap) {
      if (deps.length === 0) continue;
      if (!deps.every((d) => depths.has(d))) continue;
      const newDepth = Math.max(...deps.map((d) => depths.get(d)!)) + 1;
      if (depths.get(name) !== newDepth) {
        depths.set(name, newDepth);
        changed = true;
      }
    }
  }
  return depths;
}

/** Estimate expanded width based on agent count (agents in a horizontal row). */
function estimateExpandedWidth(agentCount: number): number {
  // Each agent card: min-w-[220px] + gap-3 (12px) ≈ 232px per agent + container padding
  const AGENT_SLOT = 232;  // scanner: skip-magic
  const MIN_EXPANDED = 480; // scanner: skip-magic
  return Math.max(agentCount * AGENT_SLOT + 2 * LAYOUT.STAGE_PAD_X, MIN_EXPANDED);
}

/** Estimate total height of a stage node for vertical spacing. */
export function estimateStageHeight(
  stage: StageExecution,
  expanded = false,
): number {
  if (expanded) {
    // Expanded: header + metrics + stage I/O + collab arrows + single agent row
    const collabHeight =
      false  // collaboration_events not available in v1
        ? LAYOUT.EXPANDED_COLLAB_HEIGHT
        : 0;
    return (
      LAYOUT.STAGE_PAD_Y +
      LAYOUT.STAGE_HEADER_HEIGHT +
      LAYOUT.STAGE_METRICS_HEIGHT +
      LAYOUT.EXPANDED_STAGE_IO_HEIGHT +
      collabHeight +
      LAYOUT.EXPANDED_AGENT_HEIGHT +
      LAYOUT.AGENT_GAP_Y
    );
  }
  // Compact: agents stacked vertically
  const agentCount = Math.max((stage.agents ?? []).length, 1);
  return (
    LAYOUT.STAGE_PAD_Y +
    LAYOUT.STAGE_HEADER_HEIGHT +
    LAYOUT.STAGE_METRICS_HEIGHT +
    agentCount * (LAYOUT.AGENT_HEIGHT + LAYOUT.AGENT_GAP_Y)
  );
}
