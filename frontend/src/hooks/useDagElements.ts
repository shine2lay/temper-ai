/**
 * Builds React Flow nodes and edges from store state.
 *
 * Architecture: a single recursive walker (`buildFragment`) handles every
 * level of the DAG via the `computeFragmentLayout` primitive in
 * `lib/dagFragment.ts`. Stages with `child_nodes` recurse; stages with
 * leaf agents (no children) synthesize per-agent fragment nodes and recurse
 * with the strategy as a layout hint. Strategies (`sequential` / `parallel`
 * / `leader`) collapse into edge synthesis on the same primitive — there's
 * no per-strategy positioning code.
 *
 * Skipped nodes are filtered before layout, with edges rewired transitively
 * so `A → SKIP → C` becomes `A → C`. No more "gaping hole" gaps.
 *
 * Workflow-level affordances (loop-back, dispatch indicators) attach at
 * the top level after the fragment walk completes.
 */

import { useMemo } from 'react';
import type { Edge, MarkerType, Node } from '@xyflow/react';

import { useExecutionStore } from '@/store/executionStore';
import { selectDagInfo, selectStageGroups } from '@/store/selectors';
import type { DagInfo } from '@/store/selectors';
import {
  computeFragmentLayout,
  type FragmentPosition,
  type LayoutHint,
} from '@/lib/dagFragment';
import { EDGE_COLORS, LAYOUT, STAGE_PALETTE } from '@/lib/constants';
import type { AgentExecution, NodeExecution, StageExecution } from '@/types';

// ---------------------------------------------------------------------------
// Public types — kept stable so StageGroupNode / AgentNodeComponent don't
// need updates.
// ---------------------------------------------------------------------------

export interface IterationData {
  stage: StageExecution;
  agents: AgentExecution[];
  totalTokens: number;
  totalCost: number;
  durationSeconds: number;
}

export interface StageNodeData extends Record<string, unknown> {
  stage: StageExecution;
  iterations: IterationData[];
  iterationCount: number;
  stageColor: string;
  strategy?: string;
  totalTokens: number;
  totalCost: number;
  durationSeconds: number;
  dagInfo: DagInfo;
  expanded: boolean;
  delegateCount?: number;
  dispatchedBy?: string;
  dispatchedChildren?: string[];
  removedChildren?: string[];
}

export interface AgentNodeData extends Record<string, unknown> {
  agent: AgentExecution | null;
  stage: StageExecution;
  stageColor: string;
  totalTokens: number;
  totalCost: number;
  durationSeconds: number;
  isDelegate?: boolean;
  delegatedBy?: string;
  dispatchedBy?: string;
  dispatchedChildren?: string[];
  removedChildren?: string[];
  iterations?: { agent: AgentExecution | null; stage: StageExecution }[];
}


// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useDagElements(): { nodes: Node[]; edges: Edge[] } {
  const workflow = useExecutionStore((s) => s.workflow);
  const stages = useExecutionStore((s) => s.stages);
  const agents = useExecutionStore((s) => s.agents);
  const hoveredNodeId = useExecutionStore((s) => s.hoveredNodeId);

  // Structural pass: nodes + edges without hover-derived styling. Memoized
  // on data deps only, so hover changes don't re-trigger size measurement
  // / position recomputation (which caused visible layout jitter).
  const structural = useMemo<{ nodes: Node[]; edges: Edge[] }>(() => {
    if (!workflow) return { nodes: [], edges: [] };

    const stageGroups = selectStageGroups(stages);
    const dagInfo = selectDagInfo();

    // Top-level: pick the latest execution per name (iteration grouping —
    // multiple runs of the same name show up as iteration badges, not as
    // separate DAG nodes).
    const topLevelLatest: NodeExecution[] = [];
    const executionsByName = new Map<string, NodeExecution[]>();
    for (const [name, execs] of stageGroups) {
      const latest = execs[execs.length - 1];
      // Filter delegates out of top-level — they're rendered as children of
      // their delegate_source.
      if (latest.type === 'delegate') continue;
      topLevelLatest.push(latest);
      executionsByName.set(name, execs);
    }

    // Pre-pass: group delegate stages under their sources so the recursive
    // walker can treat them as if they were proper child_nodes of the parent.
    const delegatesByParent = new Map<string, NodeExecution[]>();
    for (const [, execs] of stageGroups) {
      const latest = execs[execs.length - 1];
      if (latest.type === 'delegate' && latest.delegate_source) {
        const list = delegatesByParent.get(latest.delegate_source) ?? [];
        list.push(latest);
        delegatesByParent.set(latest.delegate_source, list);
      }
    }

    // Color assignment is per top-level node, stable by index.
    const colorByName = new Map<string, string>();
    topLevelLatest.forEach((n, i) => {
      colorByName.set(n.name ?? n.id, STAGE_PALETTE[i % STAGE_PALETTE.length]);
    });

    const ctx: BuildCtx = {
      agents,
      executionsByName,
      delegatesByParent,
      colorByName,
      dagInfo,
    };

    // Dispatch-driven layout: when a top-level node was added at runtime by
    // a dispatcher (e.g. `pipeline_t4` dispatched by `ticket_dispatcher`
    // inside `sprint`), give it a synthetic dep on the dispatcher's
    // top-level ancestor (`sprint`) so BFS places it one column to the
    // right, instead of stacking all 3 in column 0. The visual edge for
    // this synthetic dep is suppressed below — only the existing amber
    // cross-level dispatch edge shows.
    const ancestorByName = buildTopLevelAncestorMap(topLevelLatest);
    const syntheticDepKeys = new Set<string>();
    const enrichedTopLevel = topLevelLatest.map((n) => {
      const dispatcher = n.dispatched_by;
      if (!dispatcher) return n;
      const ancestorName = ancestorByName.get(dispatcher);
      if (!ancestorName || ancestorName === (n.name ?? n.id)) return n;
      const existing = new Set(n.depends_on ?? []);
      if (existing.has(ancestorName)) return n;
      // Mark by id-pair so we can drop the auto-generated inner edge later.
      syntheticDepKeys.add(`${ancestorName}->${n.id}`);
      return { ...n, depends_on: [...(n.depends_on ?? []), ancestorName] };
    });

    const fragment = buildFragment(enrichedTopLevel, null, undefined, ctx);

    // Drop top-level fragment edges produced by synthetic dispatch deps —
    // the same relationship is already drawn (more accurately, leaf-to-leaf)
    // by the cross-level dispatch edge in appendWorkflowLevelEdges.
    if (syntheticDepKeys.size > 0) {
      const ancestorIdByName = new Map<string, string>();
      for (const top of enrichedTopLevel) {
        ancestorIdByName.set(top.name ?? top.id, top.id);
      }
      const dropEdgeIds = new Set<string>();
      for (const key of syntheticDepKeys) {
        const [ancestorName, targetId] = key.split('->');
        const ancestorId = ancestorIdByName.get(ancestorName);
        if (ancestorId) dropEdgeIds.add(`inner-${ancestorId}-${targetId}`);
      }
      fragment.rfEdges = fragment.rfEdges.filter((e) => !dropEdgeIds.has(e.id));
    }

    // Workflow-level edges (loop-back + dispatch). Dispatch edges in
    // particular can be cross-level: a leaf agent inside a stage container
    // (e.g. `ticket_dispatcher` inside `sprint`) can dispatch new top-level
    // sibling stages (e.g. `pipeline_t1`). For those, the source endpoint
    // is the nested agent's id, not the top-level container's id. Build a
    // recursive name → rendered id map so we can resolve dispatchers
    // wherever they live in the tree.
    const renderedNames = new Set(topLevelLatest.map((n) => n.name ?? n.id));
    const liveTopIds = new Set(fragment.liveTopLevelIds);
    const renderedNodeIds = new Set(fragment.rfNodes.map((n) => n.id));
    const nameToRenderedId = buildNameToIdMap(fragment.rfNodes);
    appendWorkflowLevelEdges(
      fragment.rfEdges,
      dagInfo,
      stageGroups,
      renderedNames,
      liveTopIds,
      renderedNodeIds,
      nameToRenderedId,
    );

    // Container-port routing: an edge that spans different parent
    // containers gets retargeted to point at the LCA's direct children
    // instead of deeply-nested endpoints. e.g. an edge from
    // ticket_dispatcher_no_qa (inside sprint) to setup_ticket (inside
    // pipeline_t1 inside sprint) becomes ticket_dispatcher_no_qa →
    // pipeline_t1. Keeps cross-container edges from crossing other
    // containers' chrome.
    fragment.rfEdges = retargetCrossContainerEdges(
      fragment.rfNodes,
      fragment.rfEdges,
    );

    return { nodes: fragment.rfNodes, edges: fragment.rfEdges };
  }, [workflow, stages, agents]);

  // Hover pass: cheap restyle of edges only. Nodes pass through
  // unchanged so their identity / measured sizes stay stable.
  return useMemo(() => ({
    nodes: structural.nodes,
    edges: applyHoverOpacity(structural.nodes, structural.edges, hoveredNodeId),
  }), [structural, hoveredNodeId]);
}

/** Apply opacity + width emphasis to edges based on hover state.
 *
 * Resting state: edges at 0.35 opacity — present but recessive.
 * On hover: connected edges snap to full opacity + thicker stroke;
 * unconnected edges dim further to 0.06.
 *
 * "Connected" is computed against the hovered node's *subtree* — hovering
 * a stage container highlights edges between any of its descendants.
 * Hovering a leaf agent highlights edges with that agent as source/target.
 */
function applyHoverOpacity(
  nodes: Node[], edges: Edge[], hoveredNodeId: string | null,
): Edge[] {
  const REST = 0.35;
  const DIM = 0.06;
  if (!hoveredNodeId) {
    return edges.map((e) => ({
      ...e,
      style: { ...(e.style || {}), opacity: REST },
    }));
  }
  // Build the set of node ids that count as "the hovered subtree": the
  // hovered node + every descendant via the parentId chain.
  const subtreeIds = collectSubtree(nodes, hoveredNodeId);
  return edges.map((e) => {
    const isConnected = subtreeIds.has(e.source) || subtreeIds.has(e.target);
    const baseStyle = e.style || {};
    const baseWidth = typeof baseStyle.strokeWidth === 'number' ? baseStyle.strokeWidth : 2;
    return {
      ...e,
      style: {
        ...baseStyle,
        opacity: isConnected ? 1 : DIM,
        strokeWidth: isConnected ? baseWidth + 1 : baseWidth,
      },
    };
  });
}

/** Walk every edge — if an endpoint is nested inside a container that
 *  the OTHER endpoint isn't part of, retarget the endpoint to the
 *  highest ancestor that's still inside the lowest-common-ancestor
 *  container. So a leaf-to-leaf cross-container edge becomes a
 *  sibling-to-sibling edge between containers (or a leaf in one + a
 *  container in the other), routed cleanly within the LCA's bounds.
 *
 *  No-ops when both endpoints share an immediate parent (intra-container
 *  edges stay leaf-to-leaf so the inside of a container reads naturally).
 */
function retargetCrossContainerEdges(nodes: Node[], edges: Edge[]): Edge[] {
  const parentOf = new Map<string, string | undefined>();
  for (const n of nodes) {
    parentOf.set(n.id, (n as { parentId?: string }).parentId);
  }
  const ancestorChain = (id: string): string[] => {
    const chain = [id];
    let cur = parentOf.get(id);
    while (cur) {
      chain.push(cur);
      cur = parentOf.get(cur);
    }
    return chain;  // [self, parent, grandparent, ..., topmost]
  };
  return edges.map((e) => {
    const src = ancestorChain(e.source);
    const tgt = ancestorChain(e.target);
    // Same immediate parent? Already a sibling edge — leave it alone.
    if (src[1] === tgt[1] && src[1] !== undefined) return e;
    if (src[1] === undefined && tgt[1] === undefined) return e;  // both top-level
    // Find lowest common ancestor (any node id in both chains).
    const srcSet = new Set(src);
    let lcaIdxInTgt = -1;
    for (let i = 0; i < tgt.length; i++) {
      if (srcSet.has(tgt[i])) { lcaIdxInTgt = i; break; }
    }
    const lca = lcaIdxInTgt >= 0 ? tgt[lcaIdxInTgt] : undefined;
    // Resolve each endpoint to "direct child of LCA" — the container
    // that's a sibling at the LCA level. If LCA is undefined (top-level),
    // promote each to its topmost ancestor.
    const promoteTo = (chain: string[]): string => {
      if (lca === undefined) return chain[chain.length - 1];
      const idx = chain.indexOf(lca);
      // chain[idx] is the LCA itself; chain[idx-1] is its direct child.
      return idx > 0 ? chain[idx - 1] : chain[0];
    };
    const newSource = promoteTo(src);
    const newTarget = promoteTo(tgt);
    if (newSource === e.source && newTarget === e.target) return e;
    // Preserve edge identity by ID — id collisions are unlikely since
    // multiple leaf-pairs that promote to the same container pair
    // would share an edge anyway (same dispatch relationship).
    return { ...e, source: newSource, target: newTarget };
  });
}

/** Return the set of node ids that are `rootId` or any descendant of
 *  `rootId` via React Flow's `parentId` field. */
function collectSubtree(nodes: Node[], rootId: string): Set<string> {
  // childrenByParent: parentId -> [child ids]
  const childrenByParent = new Map<string, string[]>();
  for (const n of nodes) {
    const pid = (n as { parentId?: string }).parentId;
    if (!pid) continue;
    const list = childrenByParent.get(pid) ?? [];
    list.push(n.id);
    childrenByParent.set(pid, list);
  }
  const out = new Set<string>([rootId]);
  const stack = [rootId];
  while (stack.length) {
    const id = stack.pop()!;
    for (const childId of childrenByParent.get(id) ?? []) {
      if (out.has(childId)) continue;
      out.add(childId);
      stack.push(childId);
    }
  }
  return out;
}


// ---------------------------------------------------------------------------
// Recursive builder
// ---------------------------------------------------------------------------

interface BuildCtx {
  agents: Map<string, AgentExecution>;
  executionsByName: Map<string, NodeExecution[]>;
  delegatesByParent: Map<string, NodeExecution[]>;
  colorByName: Map<string, string>;
  dagInfo: DagInfo;
}

interface FragmentResult {
  rfNodes: Node[];
  rfEdges: Edge[];
  width: number;
  height: number;
  /** Ids of nodes that survived the skip filter at THIS level. Caller uses
   *  this to suppress workflow-level edges that point at skipped nodes. */
  liveTopLevelIds: string[];
}

const HEADER_H = LAYOUT.STAGE_HEADER_HEIGHT + LAYOUT.STAGE_METRICS_HEIGHT;
const PAD = LAYOUT.STAGE_PAD_X;

function buildFragment(
  nodes: NodeExecution[],
  parentContainerId: string | null,
  layoutHint: LayoutHint,
  ctx: BuildCtx,
): FragmentResult {
  // First, recursively measure children of any stage in this fragment.
  // We need their inner sizes BEFORE laying out this fragment so the layout
  // primitive can size containers correctly.
  const innerCache = new Map<string, FragmentResult>();
  for (const n of nodes) {
    if (n.status === 'skipped') continue;
    const inner = computeInnerFragment(n, ctx);
    if (inner) innerCache.set(n.id, inner);
  }

  const sizeFor = (n: NodeExecution): { width: number; height: number } => {
    const inner = innerCache.get(n.id);
    if (inner) {
      return {
        width: inner.width + PAD * 2,
        height: inner.height + HEADER_H + PAD * 2,
      };
    }
    return leafSize(n);
  };

  const layout = computeFragmentLayout(nodes, { layoutHint, sizeFor });

  const rfNodes: Node[] = [];
  const rfEdges: Edge[] = [];
  const liveTopLevelIds: string[] = layout.liveNodes.map((n) => n.id);

  for (const n of layout.liveNodes) {
    const pos = layout.positions.get(n.id)!;
    const stageColor = colorOf(n, parentContainerId, ctx);
    const inner = innerCache.get(n.id);

    if (inner) {
      emitContainer(rfNodes, rfEdges, n, pos, stageColor, inner, parentContainerId, ctx);
    } else {
      emitLeafAgent(rfNodes, n, pos, stageColor, parentContainerId, ctx);
    }
  }

  // Inner edges from layout (synthetic + real depends_on).
  for (const e of layout.edges) {
    rfEdges.push(makeInnerEdge(e.source, e.target, parentContainerId, ctx));
  }

  return {
    rfNodes,
    rfEdges,
    width: layout.width,
    height: layout.height,
    liveTopLevelIds,
  };
}


// ---------------------------------------------------------------------------
// Inner-fragment computation. Decides what "inside this node" means:
//   - has child_nodes  → recurse on them
//   - has agents       → synthesize fragment nodes from agents, recurse
//   - has delegates    → synthesize fragment nodes from delegates, recurse
//   - else             → leaf, no inner
// ---------------------------------------------------------------------------

function computeInnerFragment(node: NodeExecution, ctx: BuildCtx): FragmentResult | null {
  // 1. Real nested stages.
  if (node.child_nodes && node.child_nodes.length > 0) {
    // Unwrap the "stage-ref passthrough" pattern: when a stage has exactly
    // one child stage with the same name (the inner copy that the executor
    // creates when expanding a `ref:`), render the grandchildren directly
    // in this container so we don't get two nested same-name boxes.
    const passthrough = unwrapPassthrough(node);
    if (passthrough) {
      const hint = (passthrough.strategy ?? node.strategy) as LayoutHint;
      // If the passthrough child has its own children, recurse on those;
      // otherwise treat its agents as a fragment.
      if (passthrough.child_nodes && passthrough.child_nodes.length > 0) {
        return buildFragment(passthrough.child_nodes, node.id, hint, ctx);
      }
      if ((passthrough.agents ?? []).length > 0) {
        const pseudo = (passthrough.agents ?? []).map((a) =>
          pseudoAgentNode(node, a, false),
        );
        return buildFragment(pseudo, node.id, hint, ctx);
      }
    }
    return buildFragment(node.child_nodes, node.id, node.strategy as LayoutHint, ctx);
  }

  // 2. Stage with leaf agents → synthesize fragment nodes per agent.
  if (node.type === 'stage' && (node.agents ?? []).length > 0) {
    const pseudo: NodeExecution[] = (node.agents ?? []).map((a) =>
      pseudoAgentNode(node, a, /* isDelegate */ false),
    );
    return buildFragment(pseudo, node.id, node.strategy as LayoutHint, ctx);
  }

  // 3. Agent with delegates → synthesize the parent agent + delegate agents
  //    as a leader-style fragment. This preserves the existing visual where
  //    delegates fan out from the parent.
  const delegates = ctx.delegatesByParent.get(node.name ?? node.id);
  if (node.type === 'agent' && delegates && delegates.length > 0) {
    const parentAgent = node.agent ?? (node.agents ?? [])[0];
    if (!parentAgent) return null;
    const pseudo: NodeExecution[] = [
      pseudoAgentNode(node, parentAgent, false),
      ...delegates.map((d) => {
        const dAgent = d.agent ?? (d.agents ?? [])[0] ?? null;
        return delegatePseudoNode(node, d, dAgent);
      }),
    ];
    return buildFragment(pseudo, node.id, 'leader', ctx);
  }

  return null;
}


// ---------------------------------------------------------------------------
// React Flow node emission
// ---------------------------------------------------------------------------

function emitContainer(
  rfNodes: Node[],
  rfEdges: Edge[],
  node: NodeExecution,
  pos: FragmentPosition,
  stageColor: string,
  inner: FragmentResult,
  parentContainerId: string | null,
  ctx: BuildCtx,
): void {
  const allAgents = collectAgents(node, ctx);
  const totalTokens = allAgents.reduce((acc, a) => acc + (a.total_tokens ?? 0), 0);
  const totalCost = allAgents.reduce((acc, a) => acc + (a.estimated_cost_usd ?? 0), 0);

  const execs = ctx.executionsByName.get(node.name ?? node.id) ?? [node];
  const iterations: IterationData[] = [
    {
      stage: node,
      agents: allAgents,
      totalTokens,
      totalCost,
      durationSeconds: node.duration_seconds ?? 0,
    },
  ];

  const data: StageNodeData = {
    stage: node,
    iterations,
    iterationCount: execs.length,
    stageColor,
    strategy: node.strategy,
    totalTokens,
    totalCost,
    durationSeconds: node.duration_seconds ?? 0,
    dagInfo: ctx.dagInfo,
    expanded: true,
    delegateCount: ctx.delegatesByParent.get(node.name ?? node.id)?.length,
    dispatchedBy: node.dispatched_by,
    dispatchedChildren: node.dispatched_children,
    removedChildren: node.removed_children,
  };

  rfNodes.push({
    id: node.id,
    type: 'stageGroup',
    position: { x: pos.x, y: pos.y },
    ...(parentContainerId
      ? { parentId: parentContainerId, extent: 'parent' as const }
      : {}),
    style: {
      width: pos.width,
      height: pos.height,
    },
    data,
  });

  // Inner content sits below the header, padded.
  for (const innerNode of inner.rfNodes) {
    if (innerNode.parentId !== node.id) {
      // Only direct children of this container need translation; deeper
      // descendants are positioned relative to their own container.
      rfNodes.push(innerNode);
      continue;
    }
    rfNodes.push({
      ...innerNode,
      position: {
        x: innerNode.position.x + PAD,
        y: innerNode.position.y + HEADER_H + PAD,
      },
    });
  }
  rfEdges.push(...inner.rfEdges);
}

function emitLeafAgent(
  rfNodes: Node[],
  node: NodeExecution,
  pos: FragmentPosition,
  stageColor: string,
  parentContainerId: string | null,
  ctx: BuildCtx,
): void {
  const agentList = node.agents ?? (node.agent ? [node.agent] : []);
  const liveAgent = agentList.length > 0
    ? (ctx.agents.get(agentList[0].id) ?? agentList[0])
    : null;

  const execs = ctx.executionsByName.get(node.name ?? node.id) ?? [];
  const iters = execs.length > 1
    ? execs.map((exec) => {
        const execAgents = exec.agents ?? (exec.agent ? [exec.agent] : []);
        const execAgent = execAgents.length > 0
          ? (ctx.agents.get(execAgents[0].id) ?? execAgents[0])
          : null;
        return { agent: execAgent, stage: exec };
      })
    : undefined;

  const data: AgentNodeData = {
    agent: liveAgent,
    stage: node,
    stageColor,
    totalTokens: liveAgent?.total_tokens ?? 0,
    totalCost: liveAgent?.estimated_cost_usd ?? 0,
    durationSeconds: node.duration_seconds ?? liveAgent?.duration_seconds ?? 0,
    isDelegate: node.type === 'delegate',
    delegatedBy: node.delegated_by,
    dispatchedBy: node.dispatched_by,
    dispatchedChildren: node.dispatched_children,
    removedChildren: node.removed_children,
    iterations: iters,
  };

  rfNodes.push({
    id: node.id,
    type: 'agentNode',
    position: { x: pos.x, y: pos.y },
    ...(parentContainerId
      ? { parentId: parentContainerId, extent: 'parent' as const }
      : {}),
    data,
  });
}


// ---------------------------------------------------------------------------
// Edges
// ---------------------------------------------------------------------------

function makeInnerEdge(
  sourceId: string,
  targetId: string,
  parentContainerId: string | null,
  ctx: BuildCtx,
): Edge {
  // For inner edges within a fragment we always use right→left (BFS gives
  // left-to-right flow). For top-level edges between containers we'd want
  // smart handle selection; that's handled in appendWorkflowLevelEdges.
  const color = parentContainerId
    ? colorById(parentContainerId, ctx) ?? EDGE_COLORS.dataFlow
    : EDGE_COLORS.dataFlow;

  return {
    id: `inner-${sourceId}-${targetId}`,
    source: sourceId,
    target: targetId,
    sourceHandle: 'right',
    targetHandle: 'left',
    type: 'smoothstep',
    markerEnd: {
      type: 'arrowclosed' as MarkerType,
      color,
      width: 14,
      height: 14,
    },
    style: { stroke: color, strokeWidth: 2 },
  };
}

function appendWorkflowLevelEdges(
  edges: Edge[],
  dagInfo: DagInfo,
  stageGroups: Map<string, StageExecution[]>,
  renderedNames: Set<string>,
  liveTopIds: Set<string>,
  renderedNodeIds: Set<string>,
  nameToRenderedId: Map<string, string>,
): void {
  // Loop-back arrows (workflow-level only).
  const dispatchMarker = {
    type: 'arrowclosed' as MarkerType,
    color: '#f59e0b',
    width: 16,
    height: 16,
  };
  const depMarker = {
    type: 'arrowclosed' as MarkerType,
    color: EDGE_COLORS.dataFlow,
    width: 16,
    height: 16,
  };

  // Loop-back edges (workflow-level retries).
  for (const [source, target] of dagInfo.loopsBackTo) {
    if (!renderedNames.has(source) || !renderedNames.has(target)) continue;
    const sourceExecs = stageGroups.get(source);
    const targetExecs = stageGroups.get(target);
    const sourceId = sourceExecs?.[sourceExecs.length - 1]?.id;
    const targetId = targetExecs?.[targetExecs.length - 1]?.id;
    if (!sourceId || !targetId) continue;
    if (!liveTopIds.has(sourceId) || !liveTopIds.has(targetId)) continue;

    const iterCount = targetExecs?.length ?? 0;
    const maxLoops = dagInfo.maxLoops.get(source);
    const sourceStatus = sourceExecs?.[sourceExecs.length - 1]?.status;
    const isActive = sourceStatus === 'failed' || sourceStatus === 'running';

    const iterLabel = maxLoops ? `${iterCount}/${maxLoops}` : `x${iterCount}`;
    const label = iterCount > 1
      ? `retry ${iterLabel}`
      : maxLoops ? `on fail (max ${maxLoops})` : 'on fail';

    edges.push({
      id: `loop-${source}-${target}`,
      source: sourceId,
      target: targetId,
      sourceHandle: 'bottom',
      targetHandle: 'bottom-target',
      type: 'loopBack',
      label,
      style: {
        stroke: EDGE_COLORS.loopBack,
        strokeWidth: 2.5,
        strokeDasharray: '8 4',
      },
      animated: isActive,
    });
  }

  // Dispatch edges: a dispatcher node added the target at runtime. The
  // dispatcher may be a leaf agent nested inside a stage container — e.g.
  // `ticket_dispatcher` lives inside `sprint` and dispatches new top-level
  // pipeline stages. We resolve `dispatched_by` against the recursive
  // name→id map (covering all rendered nesting levels), not just the top.
  for (const [name, execs] of stageGroups) {
    if (!renderedNames.has(name)) continue;
    const latest = execs[execs.length - 1];
    if (!latest.dispatched_by) continue;
    if (!liveTopIds.has(latest.id)) continue;
    const sourceId = nameToRenderedId.get(latest.dispatched_by);
    if (!sourceId || !renderedNodeIds.has(sourceId)) continue;
    edges.push({
      id: `dispatch-${sourceId}-${latest.id}`,
      source: sourceId,
      target: latest.id,
      sourceHandle: 'right',
      targetHandle: 'left',
      type: 'dispatch',
      markerEnd: dispatchMarker,
      animated: latest.status === 'running',
      zIndex: 1000,
    });
  }

  // Top-level dependency edges (when fragment didn't synthesize them — i.e.
  // when the workflow has explicit depends_on). The recursive builder
  // already produced inner edges for siblings within stage containers; here
  // we add edges between top-level containers.
  if (!dagInfo.hasDeps) return;
  for (const [target, deps] of dagInfo.depMap) {
    if (!renderedNames.has(target)) continue;
    const targetExecs = stageGroups.get(target);
    const targetId = targetExecs?.[targetExecs.length - 1]?.id;
    if (!targetId || !liveTopIds.has(targetId)) continue;
    for (const source of deps) {
      if (!renderedNames.has(source)) continue;
      const sourceExecs = stageGroups.get(source);
      const sourceId = sourceExecs?.[sourceExecs.length - 1]?.id;
      if (!sourceId || !liveTopIds.has(sourceId)) continue;
      // Skip if this edge is already in the inner-edges set (from a fragment
      // that included these as siblings).
      const id = `inner-${sourceId}-${targetId}`;
      if (edges.some((e) => e.id === id)) continue;
      edges.push({
        id: `dep-${sourceId}-${targetId}`,
        source: sourceId,
        target: targetId,
        sourceHandle: 'right',
        targetHandle: 'left',
        type: 'smoothstep',
        markerEnd: depMarker,
        style: { stroke: EDGE_COLORS.dataFlow, strokeWidth: 2 },
      });
    }
  }
}


// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Detect the "stage-ref" passthrough pattern: outer stage has a single
 *  child stage with the same name. The executor creates this when expanding
 *  a YAML `ref:` — visually it's a redundant wrapper. */
function unwrapPassthrough(node: NodeExecution): NodeExecution | null {
  const kids = node.child_nodes ?? [];
  if (kids.length !== 1) return null;
  const only = kids[0];
  if (only.type !== 'stage') return null;
  if ((only.name ?? only.id) !== (node.name ?? node.id)) return null;
  return only;
}

/** For every named node anywhere in the tree (top-level, nested stage,
 *  leaf agent inside a stage), return which top-level container it
 *  belongs to. Used so a top-level node dispatched by a deeply-nested
 *  agent can pick up a synthetic layout dep on that agent's outermost
 *  container — the BFS sees it and places things horizontally. */
function buildTopLevelAncestorMap(topLevel: NodeExecution[]): Map<string, string> {
  const out = new Map<string, string>();
  for (const top of topLevel) {
    const topName = top.name ?? top.id;
    const stack: NodeExecution[] = [top];
    while (stack.length) {
      const n = stack.pop()!;
      out.set(n.name ?? n.id, topName);
      for (const a of n.agents ?? []) {
        if (a.agent_name) out.set(a.agent_name, topName);
      }
      if (n.agent?.agent_name) out.set(n.agent.agent_name, topName);
      for (const c of n.child_nodes ?? []) stack.push(c);
    }
  }
  return out;
}

/** Build a `name → rendered React Flow id` map covering every node we
 *  emitted, regardless of nesting depth. Used to resolve cross-level
 *  dispatch edges where the dispatcher lives inside a container. */
function buildNameToIdMap(rfNodes: Node[]): Map<string, string> {
  const out = new Map<string, string>();
  for (const n of rfNodes) {
    const data = n.data as { stage?: { name?: string }; agent?: { agent_name?: string } } | undefined;
    const stageName = data?.stage?.name;
    if (stageName && !out.has(stageName)) out.set(stageName, n.id);
    const agentName = data?.agent?.agent_name;
    if (agentName && !out.has(agentName)) out.set(agentName, n.id);
  }
  return out;
}

function leafSize(node: NodeExecution): { width: number; height: number } {
  // Even "stage with no children" cases use leaf size since the outer loop
  // detects inner content and overrides via sizeFor.
  void node;
  return { width: LAYOUT.AGENT_WIDTH + 60, height: LAYOUT.AGENT_HEIGHT };
}

function colorOf(node: NodeExecution, parentContainerId: string | null, ctx: BuildCtx): string {
  // Top-level: per-node from palette.
  if (!parentContainerId) {
    return ctx.colorByName.get(node.name ?? node.id) ?? STAGE_PALETTE[0];
  }
  // Nested: inherit parent's color.
  return colorById(parentContainerId, ctx) ?? STAGE_PALETTE[0];
}

function colorById(id: string, ctx: BuildCtx): string | undefined {
  // Walk top-level looking for the id (slow but the map is small in practice).
  for (const [name, color] of ctx.colorByName) {
    const execs = ctx.executionsByName.get(name);
    if (execs && execs.some((e) => e.id === id)) return color;
  }
  return undefined;
}

function collectAgents(node: NodeExecution, ctx: BuildCtx): AgentExecution[] {
  const out: AgentExecution[] = [];
  const agentList = node.agents ?? (node.agent ? [node.agent] : []);
  for (const a of agentList) out.push(ctx.agents.get(a.id) ?? a);
  for (const child of node.child_nodes ?? []) out.push(...collectAgents(child, ctx));
  return out;
}

/** Build a synthetic NodeExecution for a leaf agent so it can travel
 *  through the same recursive builder as a real node. */
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

function delegatePseudoNode(
  parent: NodeExecution,
  delegateNode: NodeExecution,
  agent: AgentExecution | null,
): NodeExecution {
  // Delegate cards keep their original delegate node id so selection still
  // resolves to the right place in the store.
  return {
    id: delegateNode.id,
    name: delegateNode.name,
    type: 'delegate',
    status: delegateNode.status,
    start_time: delegateNode.start_time,
    end_time: delegateNode.end_time,
    duration_seconds: delegateNode.duration_seconds,
    cost_usd: delegateNode.cost_usd,
    total_tokens: delegateNode.total_tokens,
    agent: agent ?? undefined,
    delegated_by: parent.name ?? parent.id,
    delegate_source: parent.name ?? parent.id,
    depends_on: [],
  };
}
