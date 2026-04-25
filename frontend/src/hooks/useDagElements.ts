/**
 * Builds React Flow nodes and edges from store state, using ELK
 * (Eclipse Layout Kernel via elkjs) for actual layout + edge routing.
 *
 * Pipeline:
 *   1. Synchronous data extraction from the store: top-level latest
 *      executions, iteration grouping, delegate map, color palette.
 *   2. Async ELK layout — feeds the NodeExecution tree to lib/elkLayout
 *      and waits for positions + edge waypoints. Stale layout stays
 *      visible while a new pass is computing.
 *   3. Map ELK output → React Flow nodes/edges with the original
 *      NodeData payloads (StageNodeData / AgentNodeData) attached so
 *      the existing custom node components keep working unchanged.
 *   4. Hover-to-reveal: edges restyled in a cheap synchronous pass that
 *      doesn't disturb node identity (no layout jitter on hover).
 *
 * What we no longer do:
 *   - BFS-based positioning (ELK does it)
 *   - Per-strategy column/row math (synthesized as edges, ELK lays
 *     them out the same as any directed graph)
 *   - Lane edge offsets (ELK's ORTHOGONAL routing handles this)
 *   - Container-port retargeting for cross-container edges (ELK's
 *     compound graph support routes them through container handles
 *     natively)
 */

import { useEffect, useMemo, useState } from 'react';
import type { Edge, MarkerType, Node } from '@xyflow/react';

import { useExecutionStore } from '@/store/executionStore';
import { selectDagInfo, selectStageGroups } from '@/store/selectors';
import type { DagInfo } from '@/store/selectors';
import {
  layoutWithElk,
  type ElkLayoutResult,
  type ElkPositionedNode,
} from '@/lib/elkLayout';
import { EDGE_COLORS, LAYOUT, STAGE_PALETTE } from '@/lib/constants';
import type { AgentExecution, NodeExecution, StageExecution } from '@/types';

// ---------------------------------------------------------------------------
// Public types — kept stable so the existing node components don't change.
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
// Internal context built from store (cheap, synchronous).
// ---------------------------------------------------------------------------

interface DataCtx {
  topLevelLatest: NodeExecution[];
  executionsByName: Map<string, NodeExecution[]>;
  delegatesByParent: Map<string, NodeExecution[]>;
  colorByName: Map<string, string>;
  agents: Map<string, AgentExecution>;
  dagInfo: DagInfo;
  stageGroups: Map<string, StageExecution[]>;
}


// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useDagElements(): { nodes: Node[]; edges: Edge[] } {
  const workflow = useExecutionStore((s) => s.workflow);
  const stages = useExecutionStore((s) => s.stages);
  const agents = useExecutionStore((s) => s.agents);
  const hoveredNodeId = useExecutionStore((s) => s.hoveredNodeId);

  // Sync data extraction.
  const dataCtx = useMemo<DataCtx | null>(() => {
    if (!workflow) return null;
    const stageGroups = selectStageGroups(stages);
    const dagInfo = selectDagInfo();

    const topLevelLatest: NodeExecution[] = [];
    const executionsByName = new Map<string, NodeExecution[]>();
    for (const [name, execs] of stageGroups) {
      const latest = execs[execs.length - 1];
      if (latest.type === 'delegate') continue;
      topLevelLatest.push(latest);
      executionsByName.set(name, execs);
    }

    const delegatesByParent = new Map<string, NodeExecution[]>();
    for (const [, execs] of stageGroups) {
      const latest = execs[execs.length - 1];
      if (latest.type === 'delegate' && latest.delegate_source) {
        const list = delegatesByParent.get(latest.delegate_source) ?? [];
        list.push(latest);
        delegatesByParent.set(latest.delegate_source, list);
      }
    }

    const colorByName = new Map<string, string>();
    topLevelLatest.forEach((n, i) => {
      colorByName.set(n.name ?? n.id, STAGE_PALETTE[i % STAGE_PALETTE.length]);
    });

    return {
      topLevelLatest,
      executionsByName,
      delegatesByParent,
      colorByName,
      agents,
      dagInfo,
      stageGroups,
    };
  }, [workflow, stages, agents]);

  // Async ELK layout. Stale layout stays visible until new one resolves.
  const [layout, setLayout] = useState<ElkLayoutResult | null>(null);
  useEffect(() => {
    if (!dataCtx) {
      setLayout(null);
      return;
    }
    let cancelled = false;
    layoutWithElk(dataCtx.topLevelLatest)
      .then((result) => {
        if (!cancelled) setLayout(result);
      })
      .catch((err) => {
        // ELK can throw on weird inputs (cycles ELK can't handle, etc).
        // Log so we surface the issue, but don't blank the view —
        // keep the prior layout up.
        console.error('[useDagElements] ELK layout failed:', err);
      });
    return () => {
      cancelled = true;
    };
  }, [dataCtx]);

  // Map ELK output → React Flow nodes/edges.
  const structural = useMemo<{ nodes: Node[]; edges: Edge[] }>(() => {
    if (!layout || !dataCtx) return { nodes: [], edges: [] };
    return buildReactFlow(layout, dataCtx);
  }, [layout, dataCtx]);

  // Hover restyle — cheap, doesn't disturb node identity.
  return useMemo(
    () => ({
      nodes: structural.nodes,
      edges: applyHoverOpacity(structural.nodes, structural.edges, hoveredNodeId),
    }),
    [structural, hoveredNodeId],
  );
}


// ---------------------------------------------------------------------------
// Build React Flow nodes + edges from ELK result + data context.
// ---------------------------------------------------------------------------

function buildReactFlow(
  layout: ElkLayoutResult,
  ctx: DataCtx,
): { nodes: Node[]; edges: Edge[] } {
  const rfNodes: Node[] = [];
  const rfEdges: Edge[] = [];

  for (const elkNode of layout.nodes) {
    rfNodes.push(toReactFlowNode(elkNode, ctx));
  }

  for (const e of layout.edges) {
    rfEdges.push(toReactFlowEdge(e, ctx));
  }

  // Workflow-level affordances: loop-back arrows + dispatch indicators.
  appendWorkflowLevelEdges(rfEdges, ctx, layout);

  return { nodes: rfNodes, edges: rfEdges };
}

function toReactFlowNode(elkNode: ElkPositionedNode, ctx: DataCtx): Node {
  const { node, parentId, x, y, width, height } = elkNode;
  const stageColor = ctx.colorByName.get(node.name ?? node.id)
    ?? (parentId ? ctx.colorByName.get(findTopLevelName(parentId, ctx) ?? '') : undefined)
    ?? STAGE_PALETTE[0];

  const isLeafAgent = node.type === 'agent' || node.type === 'delegate';

  if (isLeafAgent) {
    const data = buildAgentData(node, stageColor, ctx);
    return {
      id: node.id,
      type: 'agentNode',
      position: { x, y },
      ...(parentId ? { parentId, extent: 'parent' as const } : {}),
      data,
    };
  }

  // Stage container.
  const data = buildStageData(node, stageColor, ctx);
  return {
    id: node.id,
    type: 'stageGroup',
    position: { x, y },
    style: { width, height },
    ...(parentId ? { parentId, extent: 'parent' as const } : {}),
    data,
  };
}

function buildAgentData(
  node: NodeExecution,
  stageColor: string,
  ctx: DataCtx,
): AgentNodeData {
  const agentList = node.agents ?? (node.agent ? [node.agent] : []);
  const liveAgent = agentList.length > 0
    ? (ctx.agents.get(agentList[0].id) ?? agentList[0])
    : null;

  const execs = ctx.executionsByName.get(node.name ?? node.id) ?? [];
  const iters = execs.length > 1
    ? execs.map((exec) => {
        const ea = exec.agents ?? (exec.agent ? [exec.agent] : []);
        const a = ea.length > 0 ? (ctx.agents.get(ea[0].id) ?? ea[0]) : null;
        return { agent: a, stage: exec };
      })
    : undefined;

  return {
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
}

function buildStageData(
  node: NodeExecution,
  stageColor: string,
  ctx: DataCtx,
): StageNodeData {
  const allAgents = collectAgents(node, ctx.agents);
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
  return {
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
}

function collectAgents(node: NodeExecution, agentMap: Map<string, AgentExecution>): AgentExecution[] {
  const out: AgentExecution[] = [];
  const list = node.agents ?? (node.agent ? [node.agent] : []);
  for (const a of list) out.push(agentMap.get(a.id) ?? a);
  for (const child of node.child_nodes ?? []) out.push(...collectAgents(child, agentMap));
  return out;
}

/** Walk to find which top-level node contains `id`, for color inheritance. */
function findTopLevelName(_id: string, _ctx: DataCtx): string | null {
  // ELK already gives us parent ids; finding the topmost ancestor would
  // require building a parent chain. For now, color leaves with palette[0]
  // when they're nested — tweak later if needed for visual clarity.
  return null;
}

function toReactFlowEdge(
  e: { id: string; source: string; target: string; points: { x: number; y: number }[] },
  _ctx: DataCtx,
): Edge {
  return {
    id: e.id,
    source: e.source,
    target: e.target,
    type: 'routed',
    data: { points: e.points },
    markerEnd: {
      type: 'arrowclosed' as MarkerType,
      color: EDGE_COLORS.dataFlow,
      width: 14,
      height: 14,
    },
    style: { stroke: EDGE_COLORS.dataFlow, strokeWidth: 2 },
  };
}

function appendWorkflowLevelEdges(
  edges: Edge[],
  ctx: DataCtx,
  _layout: ElkLayoutResult,
): void {
  // Loop-back arrows. These don't go through ELK — we draw them as a
  // separate overlay above the laid-out graph.
  const renderedNames = new Set(ctx.topLevelLatest.map((n) => n.name ?? n.id));
  for (const [source, target] of ctx.dagInfo.loopsBackTo) {
    if (!renderedNames.has(source) || !renderedNames.has(target)) continue;
    const sourceExecs = ctx.stageGroups.get(source);
    const targetExecs = ctx.stageGroups.get(target);
    const sourceId = sourceExecs?.[sourceExecs.length - 1]?.id;
    const targetId = targetExecs?.[targetExecs.length - 1]?.id;
    if (!sourceId || !targetId) continue;

    const iterCount = targetExecs?.length ?? 0;
    const maxLoops = ctx.dagInfo.maxLoops.get(source);
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

  // Dispatch indicators. We rely on ELK-routed inner edges to express
  // the actual flow ("ticket_dispatcher → pipeline_t1"), but want to
  // mark the relationship visually with the existing amber dispatch
  // edge component. ELK already routes the edge; we just override its
  // type + color when the target was added by a dispatcher.
  for (const e of edges) {
    if (e.type !== 'routed') continue;
    const targetNode = findNodeExecutionById(e.target, ctx);
    if (targetNode?.dispatched_by) {
      e.type = 'dispatch';
      e.style = { stroke: '#f59e0b', strokeWidth: 2, strokeDasharray: '8 4' };
      e.markerEnd = {
        type: 'arrowclosed' as MarkerType,
        color: '#f59e0b',
        width: 14,
        height: 14,
      };
    }
  }
}

function findNodeExecutionById(id: string, ctx: DataCtx): NodeExecution | null {
  // Walk top-level + nested children for a match.
  const stack = [...ctx.topLevelLatest];
  while (stack.length) {
    const n = stack.pop()!;
    if (n.id === id) return n;
    if (n.child_nodes) for (const c of n.child_nodes) stack.push(c);
  }
  return null;
}


// ---------------------------------------------------------------------------
// Hover-to-reveal opacity (unchanged from before, just relocated).
// ---------------------------------------------------------------------------

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

function collectSubtree(nodes: Node[], rootId: string): Set<string> {
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

// Suppress unused-import warning for LAYOUT (kept for future tuning hooks)
void LAYOUT;
