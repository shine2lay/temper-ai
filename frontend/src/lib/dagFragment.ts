/**
 * Recursive DAG fragment layout primitive.
 *
 * A "fragment" is a set of sibling nodes laid out together — could be the
 * top-level workflow nodes, the children of a nested stage, or the leaf
 * agents inside a strategy-bearing stage. The primitive handles all three
 * with one BFS-based positioner.
 *
 * Strategies are layout hints that synthesize edges:
 *   - sequential : node[i] depends on node[i-1]   → N columns of 1 row
 *   - parallel   : no synthetic deps              → 1 column of N rows
 *   - leader     : leader depends on every worker → 2 columns, fan-in
 *   - depends_on : use the node's actual depends_on (default)
 *
 * Skipped nodes are filtered out before layout. Their incoming edges are
 * rewired to bypass them so flow stays connected (`A → SKIP → C` becomes
 * `A → C`). This prevents the "gaping hole" where a skipped node would
 * otherwise reserve a layout slot.
 */

import type { NodeExecution } from '@/types';
import { LAYOUT } from './constants';
import { computeDepthsFromDepMap } from './dagLayout';

/** Layout hint for a fragment — usually a stage's `strategy` field. */
export type LayoutHint = 'sequential' | 'parallel' | 'leader' | 'depends_on' | undefined;

export interface FragmentPosition {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** Synthetic edge produced by the layout (for strategy hints + actual deps). */
export interface FragmentEdge {
  source: string;
  target: string;
  /** Marks edges synthesized by `sequential`/`leader` so the renderer can
   *  style them differently from explicit `depends_on` edges if desired. */
  synthetic?: boolean;
}

export interface FragmentLayout {
  /** Position keyed by node.id (NOT name — names can repeat across iterations). */
  positions: Map<string, FragmentPosition>;
  /** Inner edges between siblings, post-skip-rewire and post-strategy-synthesis. */
  edges: FragmentEdge[];
  /** Bounding box of the fragment's content (excluding any container chrome). */
  width: number;
  height: number;
  /** The nodes that survived the skip filter — caller renders these. */
  liveNodes: NodeExecution[];
}

export interface FragmentOptions {
  layoutHint?: LayoutHint;
  /** When true, skipped nodes are removed and their edges rewired transitively.
   *  Default: true. */
  hideSkipped?: boolean;
  /** Per-node measured sizes (id → {width, height}). Falls back to estimates. */
  sizeFor?: (node: NodeExecution) => { width: number; height: number };
}


// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

export function computeFragmentLayout(
  nodes: NodeExecution[],
  options: FragmentOptions = {},
): FragmentLayout {
  const hideSkipped = options.hideSkipped !== false;

  // 1. Filter skipped nodes, rewiring their edges so flow stays connected.
  const { liveNodes, depMap } = hideSkipped
    ? filterSkippedAndRewire(nodes)
    : { liveNodes: nodes, depMap: rawDepMap(nodes) };

  if (liveNodes.length === 0) {
    return { positions: new Map(), edges: [], width: 0, height: 0, liveNodes: [] };
  }

  // 2. Apply layout hint by synthesizing edges. The hint operates on the
  //    *live* node list — strategies don't see skipped slots.
  const synthDepMap = synthesizeDepMap(liveNodes, options.layoutHint, depMap);

  // 3. BFS depths from the synthesized dep map.
  const depths = computeDepthsFromDepMap(synthDepMap);

  // 4. Group nodes by depth in their original sibling order (stable layout).
  const order = new Map(liveNodes.map((n, i) => [n.id, i]));
  const byDepth = new Map<number, NodeExecution[]>();
  for (const n of liveNodes) {
    const d = depths.get(n.id) ?? 0;
    const list = byDepth.get(d) ?? [];
    list.push(n);
    byDepth.set(d, list);
  }
  for (const list of byDepth.values()) {
    list.sort((a, b) => (order.get(a.id) ?? 0) - (order.get(b.id) ?? 0));
  }

  // 5. Per-column max width drives X cursor; per-column total height drives
  //    bounding height. Y centers each column relative to the tallest column
  //    so the fragment looks balanced.
  const sizeFor = options.sizeFor ?? defaultSize;
  const sizes = new Map<string, { width: number; height: number }>();
  for (const n of liveNodes) sizes.set(n.id, sizeFor(n));

  const maxDepth = Math.max(0, ...byDepth.keys());
  const colXOffsets: number[] = [];
  const colWidths: number[] = [];
  let xCursor = 0;
  for (let d = 0; d <= maxDepth; d++) {
    colXOffsets.push(xCursor);
    const list = byDepth.get(d) ?? [];
    const colW = list.reduce((acc, n) => Math.max(acc, sizes.get(n.id)!.width), LAYOUT.AGENT_WIDTH);
    colWidths.push(colW);
    xCursor += colW + LAYOUT.STAGE_GAP_X;
  }
  const totalWidth = Math.max(0, xCursor - LAYOUT.STAGE_GAP_X);

  let maxColumnHeight = 0;
  const colHeights: number[] = [];
  for (let d = 0; d <= maxDepth; d++) {
    const list = byDepth.get(d) ?? [];
    const h = list.reduce((acc, n) => acc + sizes.get(n.id)!.height, 0)
      + Math.max(0, list.length - 1) * LAYOUT.STAGE_GAP_Y;
    colHeights.push(h);
    maxColumnHeight = Math.max(maxColumnHeight, h);
  }

  // 6. Place each node. Origin is (0, 0) — caller adds container offset.
  const positions = new Map<string, FragmentPosition>();
  for (let d = 0; d <= maxDepth; d++) {
    const list = byDepth.get(d) ?? [];
    if (list.length === 0) continue;
    const x = colXOffsets[d];
    let y = (maxColumnHeight - colHeights[d]) / 2;
    for (const n of list) {
      const s = sizes.get(n.id)!;
      // Center each node horizontally within its column (so wider columns
      // don't make narrower nodes look left-justified).
      const colW = colWidths[d];
      positions.set(n.id, {
        x: x + (colW - s.width) / 2,
        y,
        width: s.width,
        height: s.height,
      });
      y += s.height + LAYOUT.STAGE_GAP_Y;
    }
  }

  // 7. Inner edges = synthesized depMap converted into edge list.
  const edges: FragmentEdge[] = [];
  const synthSet = strategyEdgeSet(liveNodes, options.layoutHint);
  for (const n of liveNodes) {
    for (const dep of synthDepMap.get(n.id) ?? []) {
      edges.push({
        source: dep,
        target: n.id,
        synthetic: synthSet.has(`${dep}->${n.id}`),
      });
    }
  }

  return { positions, edges, width: totalWidth, height: maxColumnHeight, liveNodes };
}


// ---------------------------------------------------------------------------
// Skip filter + transitive edge rewire
// ---------------------------------------------------------------------------

interface FilteredDepMap {
  liveNodes: NodeExecution[];
  /** id → list of dep ids (ids that point AT this node). All ids are live. */
  depMap: Map<string, string[]>;
}

function rawDepMap(nodes: NodeExecution[]): Map<string, string[]> {
  // Map by name (since depends_on uses names) but key the result by id for layout.
  const nameToId = new Map<string, string>();
  for (const n of nodes) nameToId.set(n.name ?? n.id, n.id);
  const out = new Map<string, string[]>();
  for (const n of nodes) {
    const deps: string[] = [];
    for (const depName of n.depends_on ?? []) {
      const id = nameToId.get(depName);
      if (id) deps.push(id);
    }
    out.set(n.id, deps);
  }
  return out;
}

/** Remove skipped nodes; rewire `A → SKIP → C` to `A → C`. Idempotent for
 *  chains of multiple consecutive skipped nodes. */
function filterSkippedAndRewire(nodes: NodeExecution[]): FilteredDepMap {
  const skipped = new Set(nodes.filter(n => n.status === 'skipped').map(n => n.id));
  if (skipped.size === 0) {
    return { liveNodes: nodes, depMap: rawDepMap(nodes) };
  }

  const liveNodes = nodes.filter(n => !skipped.has(n.id));
  const raw = rawDepMap(nodes);

  // For each live target, transitively expand any skipped predecessors
  // back to their non-skipped ancestors.
  const rewire = (deps: string[]): string[] => {
    const out = new Set<string>();
    const stack = [...deps];
    const seen = new Set<string>();
    while (stack.length) {
      const d = stack.pop()!;
      if (seen.has(d)) continue;
      seen.add(d);
      if (skipped.has(d)) {
        for (const grand of raw.get(d) ?? []) stack.push(grand);
      } else {
        out.add(d);
      }
    }
    return [...out];
  };

  const depMap = new Map<string, string[]>();
  for (const n of liveNodes) {
    depMap.set(n.id, rewire(raw.get(n.id) ?? []));
  }
  return { liveNodes, depMap };
}


// ---------------------------------------------------------------------------
// Layout-hint → synthetic depMap
// ---------------------------------------------------------------------------

function synthesizeDepMap(
  nodes: NodeExecution[],
  hint: LayoutHint,
  baseDepMap: Map<string, string[]>,
): Map<string, string[]> {
  if (!hint || hint === 'depends_on') return baseDepMap;
  if (nodes.length <= 1) return baseDepMap;

  if (hint === 'parallel') {
    // Strip all deps — every node sits at depth 0.
    const out = new Map<string, string[]>();
    for (const n of nodes) out.set(n.id, []);
    return out;
  }

  if (hint === 'sequential') {
    // Chain: node[i] depends on node[i-1].
    const out = new Map<string, string[]>();
    for (let i = 0; i < nodes.length; i++) {
      out.set(nodes[i].id, i === 0 ? [] : [nodes[i - 1].id]);
    }
    return out;
  }

  if (hint === 'leader') {
    // Leader (last node, by convention — matches the existing renderer's
    // pick) depends on every other node; others have no inner deps.
    const leader = nodes[nodes.length - 1];
    const out = new Map<string, string[]>();
    for (const n of nodes) out.set(n.id, []);
    out.set(leader.id, nodes.slice(0, -1).map(n => n.id));
    return out;
  }

  return baseDepMap;
}

/** Set of "src->tgt" strings the strategy hint synthesized — used by the
 *  caller to mark synthetic edges differently from real depends_on edges. */
function strategyEdgeSet(nodes: NodeExecution[], hint: LayoutHint): Set<string> {
  const out = new Set<string>();
  if (!hint || hint === 'depends_on' || nodes.length <= 1) return out;
  if (hint === 'sequential') {
    for (let i = 1; i < nodes.length; i++) {
      out.add(`${nodes[i - 1].id}->${nodes[i].id}`);
    }
  } else if (hint === 'leader') {
    const leader = nodes[nodes.length - 1];
    for (let i = 0; i < nodes.length - 1; i++) {
      out.add(`${nodes[i].id}->${leader.id}`);
    }
  }
  // parallel: no edges to mark
  return out;
}


// ---------------------------------------------------------------------------
// Default size estimator (used when caller doesn't supply sizeFor)
// ---------------------------------------------------------------------------

function defaultSize(node: NodeExecution): { width: number; height: number } {
  // Stage with children: caller is expected to pass a sizeFor that uses
  // recursive measurements. Without one, estimate based on agent count.
  const agentCount = (node.agents ?? []).length;
  if (node.child_nodes && node.child_nodes.length > 0) {
    // Rough ballpark — caller usually overrides.
    return { width: 600, height: 400 };
  }
  if (node.type === 'stage' && agentCount > 0) {
    return {
      width: LAYOUT.AGENT_WIDTH + 2 * LAYOUT.STAGE_PAD_X,
      height:
        LAYOUT.STAGE_PAD_Y +
        LAYOUT.STAGE_HEADER_HEIGHT +
        LAYOUT.STAGE_METRICS_HEIGHT +
        agentCount * (LAYOUT.AGENT_HEIGHT + LAYOUT.AGENT_GAP_Y) +
        LAYOUT.STAGE_PAD_Y,
    };
  }
  return { width: LAYOUT.AGENT_WIDTH, height: LAYOUT.AGENT_HEIGHT };
}
