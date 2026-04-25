/**
 * ELK-based layout for the workflow execution DAG.
 *
 * Replaces the BFS-based `dagFragment.ts` primitive. ELK's `layered`
 * algorithm with `edgeRouting: ORTHOGONAL` handles the actual hard
 * problem we'd been working around: routing edges through inter-node
 * channels so they don't cut across unrelated nodes' bodies.
 *
 * Why ELK and not dagre: native compound-graph (nested container)
 * support and orthogonal edge routing with explicit lane channels.
 * Dagre would still cross nodes in dense fan-outs.
 *
 * Pipeline:
 *   1. Walk our NodeExecution tree, drop skipped nodes (rewire edges
 *      transitively so A → SKIP → C becomes A → C).
 *   2. Synthesize edges from layout hints (sequential = chain,
 *      parallel = clear, leader = fan-in).
 *   3. Build an ELK compound-graph spec — one ElkNode per logical
 *      node, `children` field for nested stages.
 *   4. Run ELK (async). Returns positions + edge waypoints.
 *   5. Caller maps the result into React Flow nodes/edges.
 */

import type { LayoutOptions } from 'elkjs/lib/elk-api';
import type { ElkExtendedEdge, ElkNode } from 'elkjs/lib/elk-api';
import ELK from 'elkjs/lib/elk.bundled.js';

import type { NodeExecution, AgentExecution } from '@/types';
import { LAYOUT } from './constants';

// ---------------------------------------------------------------------------
// Public types — consumed by useDagElements
// ---------------------------------------------------------------------------

/** Layout hint for a fragment — usually a stage's `strategy` field. */
export type LayoutHint =
  | 'sequential'
  | 'parallel'
  | 'leader'
  | 'depends_on'
  | undefined;

/** Per-node position + optional inner content size (for containers). */
export interface ElkPositionedNode {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
  /** Parent container id (undefined = top-level). */
  parentId?: string;
  /** Original NodeExecution — caller uses this to build node data. */
  node: NodeExecution;
  /** True for synthetic agent-pseudo nodes (ones we made up to render an
   *  agent inside its stage container). */
  isPseudoAgent: boolean;
  /** Original agent reference for pseudo-agent nodes. */
  agent?: AgentExecution;
}

/** Edge with ELK-routed waypoints. */
export interface ElkPositionedEdge {
  id: string;
  source: string;
  target: string;
  /** ELK-computed bend points (absolute coordinates). Use these for the
   *  SVG path. Always at least 2 points (source endpoint + target
   *  endpoint); typically more for orthogonal edges with bends. */
  points: { x: number; y: number }[];
  /** Optional metadata for custom edge components (dispatch, loop-back). */
  meta?: { kind?: 'depends_on' | 'sequential' | 'leader' | 'parallel' | 'inner' };
  /** Fan-in routing metadata for leader-strategy edges. RoutedEdge uses
   *  this to compute lane X / entry Y at render time using live React
   *  Flow endpoints (which can differ from ELK's logical coords by 60+
   *  pixels because RF measures the rendered handle position).
   *
   *  When set, RoutedEdge ignores `points` for X positioning. */
  fanIn?: { laneIndex: number; totalLanes: number; entryY: number };
}

export interface ElkLayoutResult {
  nodes: ElkPositionedNode[];
  edges: ElkPositionedEdge[];
  /** Overall bounding box. */
  width: number;
  height: number;
}

export interface BuildOptions {
  /** Per-node measured DOM size for container-aware layout. Without it
   *  we use estimates. */
  measuredSize?: (id: string) => { width: number; height: number } | undefined;
  /** Hide skipped nodes. Default true. */
  hideSkipped?: boolean;
}


// ---------------------------------------------------------------------------
// Sizing — same defaults as the BFS layout, used when no DOM measurement
// is available yet. Once nodes have measured.{width,height}, those win.
// ---------------------------------------------------------------------------

const LEAF_AGENT_W = LAYOUT.AGENT_WIDTH;
const LEAF_AGENT_H = LAYOUT.AGENT_HEIGHT;
const HEADER_H = LAYOUT.STAGE_HEADER_HEIGHT + LAYOUT.STAGE_METRICS_HEIGHT;
const PAD = LAYOUT.STAGE_PAD_X;


// ---------------------------------------------------------------------------
// Skipped-node filter (ported from dagFragment.ts)
// ---------------------------------------------------------------------------

interface FilteredFragment {
  liveNodes: NodeExecution[];
  /** id → list of dep ids (rewired). */
  depMap: Map<string, string[]>;
}

function rawDepMap(nodes: NodeExecution[]): Map<string, string[]> {
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

function filterSkippedAndRewire(nodes: NodeExecution[]): FilteredFragment {
  const skipped = new Set(nodes.filter((n) => n.status === 'skipped').map((n) => n.id));
  if (skipped.size === 0) return { liveNodes: nodes, depMap: rawDepMap(nodes) };

  const liveNodes = nodes.filter((n) => !skipped.has(n.id));
  const raw = rawDepMap(nodes);

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
  for (const n of liveNodes) depMap.set(n.id, rewire(raw.get(n.id) ?? []));
  return { liveNodes, depMap };
}


// ---------------------------------------------------------------------------
// Layout-hint → synthetic depMap (ported from dagFragment.ts)
// ---------------------------------------------------------------------------

function synthesizeDepMap(
  nodes: NodeExecution[],
  hint: LayoutHint,
  baseDepMap: Map<string, string[]>,
): Map<string, string[]> {
  if (!hint || hint === 'depends_on') return baseDepMap;
  if (nodes.length <= 1) return baseDepMap;

  if (hint === 'parallel') {
    const out = new Map<string, string[]>();
    for (const n of nodes) out.set(n.id, []);
    return out;
  }
  if (hint === 'sequential') {
    const out = new Map<string, string[]>();
    for (let i = 0; i < nodes.length; i++) {
      out.set(nodes[i].id, i === 0 ? [] : [nodes[i - 1].id]);
    }
    return out;
  }
  if (hint === 'leader') {
    const leader = nodes[nodes.length - 1];
    const out = new Map<string, string[]>();
    for (const n of nodes) out.set(n.id, []);
    out.set(leader.id, nodes.slice(0, -1).map((n) => n.id));
    return out;
  }
  return baseDepMap;
}


// ---------------------------------------------------------------------------
// Compound graph builder
//
// We walk the NodeExecution tree once and emit one ELK node per logical
// node. Stage containers carry their children via the `children` field
// — that's how ELK does compound (nested) graphs. Edges between siblings
// inside a container live on the container's `edges` field; edges
// between top-level siblings live on the root.
//
// Same `pseudo agent node` trick the old layout used: when a stage has
// `agents` instead of `child_nodes`, we synthesize per-agent NodeExecution
// shells so they fit through the same code path.
// ---------------------------------------------------------------------------

interface BuildContext {
  options: BuildOptions;
  /** Reverse lookup so caller can recover NodeExecution + agent metadata. */
  byId: Map<string, ElkPositionedNode>;
}

function pseudoAgentNode(
  parent: NodeExecution,
  agent: AgentExecution,
  isDelegate: boolean,
): NodeExecution {
  return {
    id: `${parent.id}__${agent.agent_name ?? agent.id}`,
    name: agent.agent_name ?? agent.id,
    type: isDelegate ? 'delegate' : 'agent',
    status: agent.status as NodeExecution['status'],
    start_time: agent.start_time,
    end_time: agent.end_time,
    duration_seconds: agent.duration_seconds,
    cost_usd: agent.estimated_cost_usd ?? 0,
    total_tokens: agent.total_tokens ?? 0,
    agent,
    depends_on: [],
  };
}

function buildElkNode(
  node: NodeExecution,
  parentId: string | undefined,
  parentHint: LayoutHint,
  ctx: BuildContext,
): ElkNode {
  // Decide what's "inside" this node — child stages or synthesized
  // per-agent pseudo nodes.
  const realChildren = node.child_nodes ?? [];
  const pseudoChildren: NodeExecution[] =
    realChildren.length > 0
      ? realChildren
      : (node.agents ?? []).map((a) =>
          pseudoAgentNode(node, a, /* isDelegate */ false),
        );

  // Filter skipped + rewire deps within this fragment.
  const { liveNodes, depMap: baseDepMap } = ctx.options.hideSkipped !== false
    ? filterSkippedAndRewire(pseudoChildren)
    : { liveNodes: pseudoChildren, depMap: rawDepMap(pseudoChildren) };

  // Synthesize edges for this fragment's strategy hint.
  const synthDepMap = synthesizeDepMap(
    liveNodes,
    node.strategy as LayoutHint,
    baseDepMap,
  );

  // Build inner ELK nodes recursively.
  const childElkNodes: ElkNode[] = liveNodes.map((child) =>
    buildElkNode(child, node.id, node.strategy as LayoutHint, ctx),
  );

  // Build inner edges (siblings inside this container).
  const innerEdges: ElkExtendedEdge[] = [];
  for (const n of liveNodes) {
    for (const dep of synthDepMap.get(n.id) ?? []) {
      innerEdges.push({
        id: `e-${dep}-${n.id}`,
        sources: [dep],
        targets: [n.id],
      });
    }
  }

  // Pick this node's size — measured if available, else estimate.
  const measured = ctx.options.measuredSize?.(node.id);
  const isLeaf = childElkNodes.length === 0;
  const width = measured?.width ?? (isLeaf ? LEAF_AGENT_W : 600);
  const height = measured?.height ?? (isLeaf ? LEAF_AGENT_H : 400);

  const elkNode: ElkNode = {
    id: node.id,
    width,
    height,
    children: childElkNodes.length > 0 ? childElkNodes : undefined,
    edges: innerEdges.length > 0 ? innerEdges : undefined,
    layoutOptions: !isLeaf ? FRAGMENT_OPTIONS : undefined,
  };

  // Stash for caller to pick up post-layout.
  ctx.byId.set(node.id, {
    id: node.id,
    x: 0,
    y: 0,
    width,
    height,
    parentId,
    node,
    isPseudoAgent: false,
  });

  // Mute the unused param warning while keeping the parent hint signature
  // available for future per-fragment overrides.
  void parentHint;
  return elkNode;
}


// ---------------------------------------------------------------------------
// Layout options — the parts of ELK that map to "freeway lanes."
// ---------------------------------------------------------------------------

// Original spacing values — bigger values trade off: more space sometimes
// helps short-distance fan-outs but pushes long-distance edges further
// from their targets, which causes new crossings. These values were the
// best balance found across the four reference runs.
const ROOT_OPTIONS: LayoutOptions = {
  'elk.algorithm': 'layered',
  'elk.direction': 'RIGHT',
  'elk.layered.edgeRouting': 'ORTHOGONAL',
  'elk.layered.spacing.nodeNodeBetweenLayers': '80',
  'elk.layered.spacing.edgeNodeBetweenLayers': '40',
  'elk.layered.spacing.edgeEdgeBetweenLayers': '20',
  'elk.spacing.nodeNode': '40',
  'elk.spacing.edgeNode': '20',
  'elk.spacing.edgeEdge': '12',
  // BK placement aligns nodes vertically when they share a fan-in/out
  // pattern (helps the leader fan-in case where the moderator should
  // sit at the vertical center of its source nodes).
  'elk.layered.nodePlacement.strategy': 'BRANDES_KOEPF',
  'elk.layered.nodePlacement.bk.fixedAlignment': 'BALANCED',
  'elk.padding': '[top=60,left=20,bottom=20,right=20]',
};

const FRAGMENT_OPTIONS: LayoutOptions = {
  'elk.algorithm': 'layered',
  'elk.direction': 'RIGHT',
  'elk.layered.edgeRouting': 'ORTHOGONAL',
  // 220 gives a wide enough channel for 5+ fan-in lanes to splay
  // between worker column and leader column without arrows looking
  // squished against the right edge of the workers.
  'elk.layered.spacing.nodeNodeBetweenLayers': '220',
  'elk.layered.spacing.edgeNodeBetweenLayers': '40',
  'elk.layered.spacing.edgeEdgeBetweenLayers': '24',
  'elk.spacing.nodeNode': '40',
  'elk.spacing.edgeNode': '30',
  // 28 ensures each fan-in lane has visible separation from its
  // neighbour. With 5 workers feeding 1 leader the previous 12px
  // packed the lanes too close to read.
  'elk.spacing.edgeEdge': '28',
  'elk.layered.nodePlacement.strategy': 'BRANDES_KOEPF',
  'elk.layered.nodePlacement.bk.fixedAlignment': 'BALANCED',
  // Bigger right padding gives the last node-column inside a stage
  // container some breathing room to its parent's right border —
  // otherwise the leader/last-column visually slams the edge.
  'elk.padding': `[top=${HEADER_H + PAD},left=${PAD},bottom=${PAD},right=${PAD * 2}]`,
};


// ---------------------------------------------------------------------------
// Public API: layout(topLevelNodes, options) → Promise<ElkLayoutResult>
// ---------------------------------------------------------------------------

const elk = new ELK();

export async function layoutWithElk(
  topLevelNodes: NodeExecution[],
  options: BuildOptions = {},
): Promise<ElkLayoutResult> {
  const ctx: BuildContext = { options, byId: new Map() };

  // Filter top-level skipped + rewire across the top level.
  const { liveNodes, depMap } = options.hideSkipped !== false
    ? filterSkippedAndRewire(topLevelNodes)
    : { liveNodes: topLevelNodes, depMap: rawDepMap(topLevelNodes) };

  const rootChildren: ElkNode[] = liveNodes.map((n) =>
    buildElkNode(n, undefined, undefined, ctx),
  );

  // Top-level edges: from the rewired depMap.
  const rootEdges: ElkExtendedEdge[] = [];
  for (const n of liveNodes) {
    for (const dep of depMap.get(n.id) ?? []) {
      rootEdges.push({
        id: `e-${dep}-${n.id}`,
        sources: [dep],
        targets: [n.id],
      });
    }
  }

  const root: ElkNode = {
    id: '__root__',
    children: rootChildren,
    edges: rootEdges,
    layoutOptions: ROOT_OPTIONS,
  };

  const laidOut = await elk.layout(root);
  const result = collectResult(laidOut, ctx);

  // Strategy-specific post-processing. ELK's general-purpose layout
  // does well most of the time, but specific strategies have an
  // expected visual that ELK doesn't quite hit (e.g. `leader` wants
  // the leader vertically centered on its workers, not aligned to one
  // worker's row). Override here.
  postProcessStrategies(result);

  return result;
}


// ---------------------------------------------------------------------------
// Strategy-specific post-processors
// ---------------------------------------------------------------------------

/** Mutates `result` in place. */
function postProcessStrategies(result: ElkLayoutResult): void {
  // Build a parent → children map and an absolute-Y map for the walk.
  const childrenByParent = new Map<string | undefined, ElkPositionedNode[]>();
  for (const n of result.nodes) {
    const list = childrenByParent.get(n.parentId) ?? [];
    list.push(n);
    childrenByParent.set(n.parentId, list);
  }
  const absPos = new Map<string, { x: number; y: number }>();
  const computeAbs = (
    n: ElkPositionedNode,
    parentAbsX: number,
    parentAbsY: number,
  ): void => {
    const ax = parentAbsX + n.x;
    const ay = parentAbsY + n.y;
    absPos.set(n.id, { x: ax, y: ay });
    for (const c of childrenByParent.get(n.id) ?? []) computeAbs(c, ax, ay);
  };
  for (const top of childrenByParent.get(undefined) ?? []) computeAbs(top, 0, 0);

  for (const container of result.nodes) {
    if (container.node.strategy !== 'leader') continue;
    const kids = childrenByParent.get(container.id) ?? [];
    if (kids.length < 2) continue;

    // ELK output may reorder children. Find the leader by matching
    // back to the original NodeExecution's last agent / child entry —
    // that's the one we treated as the leader during edge synthesis.
    const orig = container.node;
    const origKidsList: { id?: string; name?: string }[] =
      orig.child_nodes && orig.child_nodes.length > 0
        ? orig.child_nodes
        : (orig.agents ?? []).map((a) => ({
            id: `${orig.id}__${a.agent_name ?? a.id}`,
            name: a.agent_name ?? a.id,
          }));
    const leaderRef = origKidsList[origKidsList.length - 1];
    const leader = kids.find((k) => k.id === leaderRef?.id) ?? kids[kids.length - 1];
    const workers = kids.filter((k) => k !== leader);
    if (workers.length === 0) continue;

    // (1) Vertically center the leader on the workers' bounding box.
    let minTop = Infinity, maxBottom = -Infinity;
    for (const w of workers) {
      const ay = absPos.get(w.id)?.y ?? 0;
      minTop = Math.min(minTop, ay);
      maxBottom = Math.max(maxBottom, ay + w.height);
    }
    const workersCenterY = (minTop + maxBottom) / 2;
    const leaderAbs = absPos.get(leader.id) ?? { x: 0, y: 0 };
    const leaderCenterY = leaderAbs.y + leader.height / 2;
    const deltaY = workersCenterY - leaderCenterY;
    if (Math.abs(deltaY) >= 4) {
      leader.y += deltaY;
      absPos.set(leader.id, { x: leaderAbs.x, y: leaderAbs.y + deltaY });
    }

    // (2) Custom fan-in routing. ELK packs all worker→leader edges
    // through a single vertical column, which visually merges N arrows
    // into one line. Replace those routes: each edge gets its own lane
    // X in the gap and its own entry Y on the leader's left edge so the
    // fan-in reads as N distinct arrows.
    const leaderPosNew = absPos.get(leader.id)!;
    const leaderLeftX = leaderPosNew.x;
    const leaderTopY = leaderPosNew.y;
    const leaderBottomY = leaderTopY + leader.height;

    // Find the rightmost worker right-edge so all lanes start past it.
    let workerRightMax = -Infinity;
    for (const w of workers) {
      const ax = absPos.get(w.id)?.x ?? 0;
      workerRightMax = Math.max(workerRightMax, ax + w.width);
    }
    if (!isFinite(workerRightMax) || workerRightMax >= leaderLeftX) continue;
    const gap = leaderLeftX - workerRightMax;
    if (gap < 40) continue;  // not enough room to splay — leave ELK's route

    // Stable order: by source Y so visually-top worker → topmost lane.
    const incoming = result.edges
      .filter((e) => e.target === leader.id)
      .map((e) => {
        const src = absPos.get(e.source);
        const srcNode = result.nodes.find((n) => n.id === e.source);
        return {
          edge: e,
          srcCenterY: src && srcNode ? src.y + srcNode.height / 2 : 0,
          srcRight: src && srcNode ? src.x + srcNode.width : workerRightMax,
        };
      })
      .sort((a, b) => a.srcCenterY - b.srcCenterY);

    if (incoming.length < 2) continue;

    const N = incoming.length;
    // Entry Ys (vertical positions on leader's left edge): these match
    // between ELK coords and render coords, so we can compute and use
    // them directly. Lane X is left to RoutedEdge to compute at render
    // time from live src/tgt X (they don't always match ELK's logical X).
    const entryMargin = Math.min(20, leader.height * 0.15);
    const entryTop = leaderTopY + entryMargin;
    const entryBottom = leaderBottomY - entryMargin;
    const entryStep = N > 1 ? (entryBottom - entryTop) / (N - 1) : 0;

    incoming.forEach(({ edge }, i) => {
      const entryY = N === 1 ? leaderTopY + leader.height / 2 : entryTop + i * entryStep;
      edge.fanIn = { laneIndex: i, totalLanes: N, entryY };
      // Leave edge.points alone so RoutedEdge can fall back to it if
      // fanIn isn't honored for some reason.
    });
  }
}


function collectResult(root: ElkNode, ctx: BuildContext): ElkLayoutResult {
  const nodes: ElkPositionedNode[] = [];
  const edges: ElkPositionedEdge[] = [];

  // ELK gives positions relative to each node's parent. Walk the tree,
  // accumulating absolute coordinates. We emit positions in *parent-
  // relative* form (matches React Flow's `parentId` semantics) but
  // resolve absolute to compute the bounding box.
  const walk = (n: ElkNode, parentAbsX: number, parentAbsY: number, parentId?: string) => {
    if (n.id === '__root__') {
      for (const child of n.children ?? []) walk(child, 0, 0, undefined);
      for (const e of n.edges ?? []) emitEdge(e, 0, 0);
      return;
    }
    const x = n.x ?? 0;
    const y = n.y ?? 0;
    const absX = parentAbsX + x;
    const absY = parentAbsY + y;

    const meta = ctx.byId.get(n.id);
    if (meta) {
      nodes.push({
        ...meta,
        x,
        y,
        width: n.width ?? meta.width,
        height: n.height ?? meta.height,
        parentId,
      });
    }

    for (const child of n.children ?? []) walk(child, absX, absY, n.id);
    // Edges declared on a container live in the container's coordinate
    // space — points are relative to the container. Adjust to absolute.
    for (const e of n.edges ?? []) emitEdge(e, absX, absY);
  };

  const emitEdge = (e: ElkExtendedEdge, baseX: number, baseY: number) => {
    const sections = e.sections ?? [];
    if (sections.length === 0) return;
    const points: { x: number; y: number }[] = [];
    for (const s of sections) {
      points.push({ x: baseX + s.startPoint.x, y: baseY + s.startPoint.y });
      for (const bp of s.bendPoints ?? []) {
        points.push({ x: baseX + bp.x, y: baseY + bp.y });
      }
      points.push({ x: baseX + s.endPoint.x, y: baseY + s.endPoint.y });
    }
    edges.push({
      id: e.id,
      source: e.sources?.[0] ?? '',
      target: e.targets?.[0] ?? '',
      points,
    });
  };

  walk(root, 0, 0, undefined);

  let maxX = 0,
    maxY = 0;
  for (const n of nodes) {
    if (n.parentId) continue; // top-level only contributes to overall bbox
    maxX = Math.max(maxX, n.x + n.width);
    maxY = Math.max(maxY, n.y + n.height);
  }

  return { nodes, edges, width: maxX, height: maxY };
}
