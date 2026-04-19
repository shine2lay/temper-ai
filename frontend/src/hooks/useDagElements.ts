import { useMemo } from 'react';
import { useExecutionStore } from '@/store/executionStore';
import { selectStageGroups, selectDagInfo } from '@/store/selectors';
import { computeStagePositions } from '@/lib/dagLayout';
import { STAGE_PALETTE, EDGE_COLORS } from '@/lib/constants';
import type { Node, Edge, MarkerType } from '@xyflow/react';
import type { StageExecution, AgentExecution } from '@/types';
import type { DagInfo } from '@/store/selectors';
import type { StagePosition } from '@/lib/dagLayout';

/** Agents and metrics for a single iteration of a stage. */
export interface IterationData {
  stage: StageExecution;
  agents: AgentExecution[];
  totalTokens: number;
  totalCost: number;
  durationSeconds: number;
}

/** Data for a stage-type node (composite, has multiple agents). */
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
  // Dispatch metadata — if set, this stage was materialized at runtime
  // by a dispatcher. Rendered prominently so it's obvious.
  dispatchedBy?: string;
  dispatchedChildren?: string[];
  removedChildren?: string[];
}

/** Data for an agent-type node (leaf, single agent). */
export interface AgentNodeData extends Record<string, unknown> {
  agent: AgentExecution | null;
  stage: StageExecution;
  stageColor: string;
  totalTokens: number;
  totalCost: number;
  durationSeconds: number;
  isDelegate?: boolean;
  delegatedBy?: string;
  // Dispatch metadata — whose dispatch added this node, or which children
  // this node dispatched.
  dispatchedBy?: string;
  dispatchedChildren?: string[];
  removedChildren?: string[];
  /** All iterations for this node (when loop/retry produces multiple runs). */
  iterations?: { agent: AgentExecution | null; stage: StageExecution }[];
}

/**
 * Transforms store state into React Flow nodes and edges.
 *
 * Renders differently based on node type:
 * - type='agent': renders as AgentNodeComponent (compact card)
 * - type='stage': renders as StageNode (container with agents inside)
 */
export function useDagElements(): { nodes: Node[]; edges: Edge[] } {
  const workflow = useExecutionStore((s) => s.workflow);
  const stages = useExecutionStore((s) => s.stages);
  const agents = useExecutionStore((s) => s.agents);
  const expandedStages = useExecutionStore((s) => s.expandedStages);

  return useMemo(() => {
    if (!workflow) return { nodes: [], edges: [] };

    const stageGroups = selectStageGroups(stages);
    const dagInfo = selectDagInfo();
    const positions = computeStagePositions(stageGroups, dagInfo, expandedStages);

    const nodes: Node[] = [];
    const edges: Edge[] = [];

    let colorIndex = 0;
    const stageNames = Array.from(stageGroups.keys());
    const renderedStages = new Set<string>(); // Track which stages actually render

    // Pre-pass: group delegate nodes by their parent (delegate_source)
    const delegatesByParent = new Map<string, string[]>();
    for (const [stageName, executions] of stageGroups) {
      const latest = executions[executions.length - 1];
      if (latest.type === 'delegate') {
        const parent = latest.delegate_source;
        if (parent) {
          const list = delegatesByParent.get(parent) ?? [];
          list.push(stageName);
          delegatesByParent.set(parent, list);
        }
      }
    }
    // Set of delegate stage names (to skip when rendering top-level)
    const delegateStageNames = new Set(
      Array.from(delegatesByParent.values()).flat(),
    );

    for (const [stageName, executions] of stageGroups) {
      const latest = executions[executions.length - 1];
      const pos = positions.get(stageName);
      if (!pos) continue;

      const stageColor = STAGE_PALETTE[colorIndex % STAGE_PALETTE.length];
      colorIndex++;

      // Determine if this is an agent-type or stage-type node
      const nodeType = latest.type ?? 'agent';
      const isDelegate = nodeType === 'delegate';
      const nodeAgents = latest.agents ?? [];
      const isSkipped = latest.status === 'skipped' && nodeAgents.length === 0;

      // Skipped stages: don't render
      if (isSkipped) {
        colorIndex++;
        continue;
      }

      // Delegate nodes are rendered inside their parent — skip top-level
      if (delegateStageNames.has(stageName)) {
        renderedStages.add(stageName); // still mark as rendered for edge routing
        continue;
      }

      renderedStages.add(stageName);

      // Check if this agent has delegate children
      const delegateNames = delegatesByParent.get(stageName);

      if ((nodeType === 'agent' || isDelegate) && !delegateNames) {
        // Simple agent node: render as compact agent card
        const agent = nodeAgents.length > 0
          ? (agents.get(nodeAgents[0].id) ?? nodeAgents[0])
          : null;

        const totalTokens = agent?.total_tokens ?? 0;
        const totalCost = agent?.estimated_cost_usd ?? 0;
        const durationSeconds = latest.duration_seconds ?? 0;

        // Build iterations for multi-run nodes (loops/retries)
        const iters = executions.length > 1
          ? executions.map((exec) => {
              const execAgents = exec.agents ?? [];
              const execAgent = execAgents.length > 0
                ? (agents.get(execAgents[0].id) ?? execAgents[0])
                : null;
              return { agent: execAgent, stage: exec };
            })
          : undefined;

        const data: AgentNodeData = {
          agent,
          stage: latest,
          stageColor,
          totalTokens,
          totalCost,
          durationSeconds,
          isDelegate,
          delegatedBy: isDelegate ? latest.delegated_by : undefined,
          dispatchedBy: latest.dispatched_by,
          dispatchedChildren: latest.dispatched_children,
          removedChildren: latest.removed_children,
          iterations: iters,
        };

        nodes.push({
          id: stageName,
          type: 'agentNode',
          position: { x: pos.x, y: pos.y },
          data,
        });
      } else if (nodeType === 'agent' && delegateNames) {
        // Agent with delegates: render as a group container
        // Parent agent card at top, delegate cards below
        const parentAgent = nodeAgents.length > 0
          ? (agents.get(nodeAgents[0].id) ?? nodeAgents[0])
          : null;

        const cardH = 200;
        const hdrH = 75;
        const pad = 28;
        const gap = 20;

        // Collect delegate agents
        const delegateAgents: { name: string; agent: AgentExecution | null; stage: StageExecution }[] = [];
        for (const dName of delegateNames) {
          const dExecs = stageGroups.get(dName);
          if (!dExecs) continue;
          const dLatest = dExecs[dExecs.length - 1];
          const dAgents = dLatest.agents ?? [];
          const dAgent = dAgents.length > 0
            ? (agents.get(dAgents[0].id) ?? dAgents[0])
            : null;
          delegateAgents.push({ name: dName, agent: dAgent, stage: dLatest });
        }

        // Calculate totals
        let totalTokens = parentAgent?.total_tokens ?? 0;
        let totalCost = parentAgent?.estimated_cost_usd ?? 0;
        for (const d of delegateAgents) {
          totalTokens += d.agent?.total_tokens ?? 0;
          totalCost += d.agent?.estimated_cost_usd ?? 0;
        }
        const durationSeconds = latest.duration_seconds ?? 0;

        // Horizontal layout: parent on left, delegates stacked vertically on right
        const delegatesH = delegateAgents.length * cardH + (delegateAgents.length - 1) * gap;
        const contentH = Math.max(cardH, delegatesH);
        const maxCardW = 350; // AgentNodeComponent max-w-[350px]
        const containerW = pad * 3 + maxCardW * 2 + gap;
        const containerH = hdrH + pad + contentH + pad;

        const iterations: IterationData[] = [{
          stage: latest,
          agents: nodeAgents,
          totalTokens,
          totalCost,
          durationSeconds,
        }];

        const data: StageNodeData = {
          stage: latest,
          iterations,
          iterationCount: 1,
          stageColor,
          strategy: 'delegate',
          totalTokens,
          totalCost,
          durationSeconds,
          dagInfo,
          expanded: true,
          delegateCount: delegateAgents.length,
          dispatchedBy: latest.dispatched_by,
          dispatchedChildren: latest.dispatched_children,
          removedChildren: latest.removed_children,
        };

        nodes.push({
          id: stageName,
          type: 'stageGroup',
          position: { x: pos.x, y: pos.y },
          data,
          style: {
            width: Math.max(containerW, 350),
            height: Math.max(containerH, 200),
          },
        });

        // Parent agent card on the left, aligned to top of content area
        const parentY = hdrH + pad;
        if (parentAgent) {
          nodes.push({
            id: `${stageName}__${parentAgent.agent_name ?? parentAgent.id}`,
            type: 'agentNode',
            position: { x: pad, y: parentY },
            parentId: stageName,
            extent: 'parent' as const,
            data: {
              agent: parentAgent,
              stage: latest,
              stageColor,
              totalTokens: parentAgent.total_tokens ?? 0,
              totalCost: parentAgent.estimated_cost_usd ?? 0,
              durationSeconds: parentAgent.duration_seconds ?? 0,
            } as AgentNodeData,
          });
        }

        // Delegate agent cards stacked vertically on the right
        const delegateColor = '#8b5cf6'; // violet
        const delegateX = pad + maxCardW + gap;
        delegateAgents.forEach((d, i) => {
          const childY = hdrH + pad + i * (cardH + gap);
          // Clean up display name: strip "delegate:" prefix and trailing "_N"
          const displayName = d.name
            .replace(/^delegate:/, '')
            .replace(/_\d+$/, '');

          nodes.push({
            id: d.name,
            type: 'agentNode',
            position: { x: delegateX, y: childY },
            parentId: stageName,
            extent: 'parent' as const,
            data: {
              agent: d.agent,
              stage: { ...d.stage, name: displayName },
              stageColor: delegateColor,
              totalTokens: d.agent?.total_tokens ?? 0,
              totalCost: d.agent?.estimated_cost_usd ?? 0,
              durationSeconds: d.agent?.duration_seconds ?? 0,
              isDelegate: true,
              delegatedBy: parentAgent?.agent_name,
            } as AgentNodeData,
          });

          // Edge from parent agent → delegate (horizontal arrow)
          if (parentAgent) {
            edges.push({
              id: `delegate-${stageName}-${d.name}`,
              source: `${stageName}__${parentAgent.agent_name ?? parentAgent.id}`,
              target: d.name,
              sourceHandle: 'right',
              targetHandle: 'left',
              type: 'default',
              markerEnd: {
                type: 'arrowclosed' as MarkerType,
                color: delegateColor,
                width: 12,
                height: 12,
              },
              style: { stroke: delegateColor, strokeWidth: 1.5, strokeDasharray: '6 3' },
            });
          }
        });
      } else {
        // Stage node: render as group container with child agent nodes inside
        const nodeAgents = (latest.agents ?? []).map(
          (a) => agents.get(a.id) ?? a,
        );

        let totalTokens = 0;
        let totalCost = 0;
        for (const a of nodeAgents) {
          totalTokens += a.total_tokens ?? 0;
          totalCost += a.estimated_cost_usd ?? 0;
        }
        const durationSeconds = latest.duration_seconds ?? 0;
        const strategy = latest.strategy;

        // Layout constants
        const cardW = 280;
        const cardH = 200;
        const hdrH = 75;
        const pad = 28;
        const gap = 30;

        const iterations: IterationData[] = [{
          stage: latest,
          agents: nodeAgents,
          totalTokens,
          totalCost,
          durationSeconds,
        }];

        const data: StageNodeData = {
          stage: latest,
          iterations,
          iterationCount: executions.length,
          stageColor,
          strategy,
          totalTokens,
          totalCost,
          durationSeconds,
          dagInfo,
          expanded: true,
          dispatchedBy: latest.dispatched_by,
          dispatchedChildren: latest.dispatched_children,
          removedChildren: latest.removed_children,
        };

        // Identify leader agent (if leader strategy)
        const isLeader = strategy === 'leader';
        const isSequential = strategy === 'sequential';
        const leaderAgent = isLeader
          ? nodeAgents.find((a) => a.role === 'leader') ?? nodeAgents[nodeAgents.length - 1]
          : null;
        const workerAgents = isLeader
          ? nodeAgents.filter((a) => a !== leaderAgent)
          : nodeAgents;

        // Calculate container size based on strategy
        let containerW: number;
        let containerH: number;

        if (isSequential) {
          // Horizontal chain
          containerW = pad * 2 + nodeAgents.length * cardW + (nodeAgents.length - 1) * gap;
          containerH = hdrH + pad + cardH + pad;
        } else if (isLeader) {
          // Workers stacked vertically on left, leader on right
          const workersH = workerAgents.length * cardH + (workerAgents.length - 1) * gap;
          containerW = pad * 3 + cardW * 2 + gap;
          containerH = hdrH + pad + Math.max(workersH, cardH) + pad;
        } else {
          // Parallel: vertical stack
          containerW = pad * 2 + cardW;
          containerH = hdrH + pad + nodeAgents.length * cardH + (nodeAgents.length - 1) * gap + pad;
        }

        // Parent group node
        nodes.push({
          id: stageName,
          type: 'stageGroup',
          position: { x: pos.x, y: pos.y },
          data,
          style: {
            width: Math.max(containerW, 350),
            height: Math.max(containerH, 200),
          },
        });

        // Position child nodes based on strategy
        if (isLeader && leaderAgent) {
          // Workers: vertical stack on left
          workerAgents.forEach((agent, i) => {
            nodes.push({
              id: `${stageName}__${agent.agent_name ?? agent.id}`,
              type: 'agentNode',
              position: { x: pad, y: hdrH + pad + i * (cardH + gap) },
              parentId: stageName,
              extent: 'parent' as const,
              data: {
                agent, stage: latest, stageColor,
                totalTokens: agent.total_tokens ?? 0,
                totalCost: agent.estimated_cost_usd ?? 0,
                durationSeconds: agent.duration_seconds ?? 0,
              } as AgentNodeData,
            });
          });

          // Leader: positioned to the right, vertically centered
          const workersH = workerAgents.length * cardH + (workerAgents.length - 1) * gap;
          const leaderY = hdrH + pad + Math.max(0, (workersH - cardH) / 2);
          nodes.push({
            id: `${stageName}__${leaderAgent.agent_name ?? leaderAgent.id}`,
            type: 'agentNode',
            position: { x: pad + cardW + gap, y: leaderY },
            parentId: stageName,
            extent: 'parent' as const,
            data: {
              agent: leaderAgent, stage: latest, stageColor,
              totalTokens: leaderAgent.total_tokens ?? 0,
              totalCost: leaderAgent.estimated_cost_usd ?? 0,
              durationSeconds: leaderAgent.duration_seconds ?? 0,
            } as AgentNodeData,
          });

          // Edges: each worker → leader
          for (const worker of workerAgents) {
            edges.push({
              id: `inner-${stageName}-${worker.agent_name ?? worker.id}-to-leader`,
              source: `${stageName}__${worker.agent_name ?? worker.id}`,
              target: `${stageName}__${leaderAgent.agent_name ?? leaderAgent.id}`,
              sourceHandle: 'right',
              targetHandle: 'left',
              type: 'default',
              markerEnd: {
                type: 'arrowclosed' as MarkerType,
                color: stageColor,
                width: 14,
                height: 14,
              },
              style: { stroke: stageColor, strokeWidth: 2 },
              animated: latest.status === 'running',
            });
          }
        } else {
          // Sequential or Parallel: position agents
          nodeAgents.forEach((agent, i) => {
            const childX = isSequential ? pad + i * (cardW + gap) : pad;
            const childY = isSequential ? hdrH + pad : hdrH + pad + i * (cardH + gap);

            nodes.push({
              id: `${stageName}__${agent.agent_name ?? agent.id}`,
              type: 'agentNode',
              position: { x: childX, y: childY },
              parentId: stageName,
              extent: 'parent' as const,
              data: {
                agent, stage: latest, stageColor,
                totalTokens: agent.total_tokens ?? 0,
                totalCost: agent.estimated_cost_usd ?? 0,
                durationSeconds: agent.duration_seconds ?? 0,
              } as AgentNodeData,
            });
          });

          // Sequential edges (horizontal arrows)
          if (isSequential && nodeAgents.length > 1) {
            for (let i = 0; i < nodeAgents.length - 1; i++) {
              const src = nodeAgents[i];
              const tgt = nodeAgents[i + 1];
              edges.push({
                id: `inner-${stageName}-${i}`,
                source: `${stageName}__${src.agent_name ?? src.id}`,
                target: `${stageName}__${tgt.agent_name ?? tgt.id}`,
                sourceHandle: 'right',
                targetHandle: 'left',
                type: 'default',
                markerEnd: {
                  type: 'arrowclosed' as MarkerType,
                  color: stageColor,
                  width: 14,
                  height: 14,
                },
                style: { stroke: stageColor, strokeWidth: 2 },
                animated: latest.status === 'running',
              });
            }
          }
          // No inner edges for parallel
        }
      }
    }

    // Arrowhead marker for dependency edges
    const depMarker = {
      type: 'arrowclosed' as MarkerType,
      color: EDGE_COLORS.dataFlow,
      width: 16,
      height: 16,
    };

    // Build edges with smart handle selection based on node positions
    if (dagInfo.hasDeps) {
      for (const [target, deps] of dagInfo.depMap) {
        if (!renderedStages.has(target)) continue; // Skip edges to non-rendered stages
        // Skip edges to/from delegate nodes (they're rendered inside parent containers)
        if (delegateStageNames.has(target)) continue;
        for (const source of deps) {
          if (!renderedStages.has(source)) continue; // Skip edges from non-rendered stages
          if (delegateStageNames.has(source)) continue;
          const sourceStage = stageGroups.get(source);
          const sourceStatus = sourceStage
            ? sourceStage[sourceStage.length - 1].status
            : undefined;

          const srcPos = positions.get(source);
          const tgtPos = positions.get(target);
          const handles = _pickHandles(srcPos, tgtPos);

          edges.push({
            id: `dep-${source}-${target}`,
            source,
            target,
            sourceHandle: handles.sourceHandle,
            targetHandle: handles.targetHandle,
            type: 'default',
            markerEnd: depMarker,
            style: { stroke: EDGE_COLORS.dataFlow, strokeWidth: 2 },
            animated: sourceStatus === 'running',
          });
        }
      }

      for (const [source, target] of dagInfo.loopsBackTo) {
        const sourceExecs = stageGroups.get(source);
        const targetExecs = stageGroups.get(target);
        const iterCount = targetExecs ? targetExecs.length : 0;
        const maxLoops = dagInfo.maxLoops.get(source);
        const sourceStatus = sourceExecs
          ? sourceExecs[sourceExecs.length - 1].status
          : undefined;
        const isActive = sourceStatus === 'failed' || sourceStatus === 'running';

        const iterLabel = maxLoops
          ? `${iterCount}/${maxLoops}`
          : `x${iterCount}`;
        const label = iterCount > 1
          ? `retry ${iterLabel}`
          : maxLoops
            ? `on fail (max ${maxLoops})`
            : 'on fail';

        edges.push({
          id: `loop-${source}-${target}`,
          source,
          target,
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
    } else {
      // Fallback: sequential edges in stage order
      for (let i = 0; i < stageNames.length - 1; i++) {
        const source = stageNames[i];
        const target = stageNames[i + 1];
        const sourceStage = stageGroups.get(source);
        const sourceStatus = sourceStage
          ? sourceStage[sourceStage.length - 1].status
          : undefined;

        edges.push({
          id: `seq-${source}-${target}`,
          source,
          target,
          sourceHandle: 'right',
          targetHandle: 'left',
          type: 'default',
          markerEnd: depMarker,
          style: { stroke: EDGE_COLORS.dataFlow, strokeWidth: 2 },
          animated: sourceStatus === 'running',
        });
      }
    }

    return { nodes, edges };
  }, [workflow, stages, agents, expandedStages]);
}

/**
 * Pick source/target handles based on relative node positions.
 * - Same column (small x delta): use bottom→top
 * - Target to the right: use right→left (default L→R flow)
 * - Target to the left: use left→right (backflow)
 */
function _pickHandles(
  srcPos: StagePosition | undefined,
  tgtPos: StagePosition | undefined,
): { sourceHandle: string; targetHandle: string } {
  if (!srcPos || !tgtPos) {
    return { sourceHandle: 'right', targetHandle: 'left' };
  }

  const dx = tgtPos.x - srcPos.x;
  const dy = tgtPos.y - srcPos.y;

  // If target is roughly in the same column (small horizontal gap),
  // route vertically to avoid crossing
  if (Math.abs(dx) < 80) {
    return dy > 0
      ? { sourceHandle: 'bottom', targetHandle: 'left' }
      : { sourceHandle: 'right', targetHandle: 'bottom' };
  }

  // Normal left-to-right flow
  if (dx > 0) {
    return { sourceHandle: 'right', targetHandle: 'left' };
  }

  // Backflow (target is to the left)
  return { sourceHandle: 'left', targetHandle: 'right' };
}
