import { useMemo } from 'react';
import { useExecutionStore } from '@/store/executionStore';
import { selectStageGroups, selectDagInfo } from '@/store/selectors';
import { computeStagePositions } from '@/lib/dagLayout';
import { STAGE_PALETTE, EDGE_COLORS } from '@/lib/constants';
import type { Node, Edge } from '@xyflow/react';
import type { StageExecution, AgentExecution } from '@/types';
import type { DagInfo } from '@/store/selectors';

/** Agents and metrics for a single iteration of a stage. */
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
}

/**
 * Transforms store state into React Flow nodes and edges.
 * Groups stages by name, computes DAG positions, and generates
 * data_flow / loop_back / sequential edges.
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

    for (const [stageName, executions] of stageGroups) {
      const latest = executions[executions.length - 1];
      const pos = positions.get(stageName);
      if (!pos) continue;

      // Build per-iteration data
      const iterations: IterationData[] = executions.map((exec) => {
        const iterAgents = (exec.agents ?? []).map(
          (a) => agents.get(a.id) ?? a,
        );
        let iterTokens = 0;
        let iterCost = 0;
        for (const a of iterAgents) {
          iterTokens += a.total_tokens ?? 0;
          iterCost += a.estimated_cost_usd ?? 0;
        }
        return {
          stage: exec,
          agents: iterAgents,
          totalTokens: iterTokens,
          totalCost: iterCost,
          durationSeconds: exec.duration_seconds ?? 0,
        };
      });

      // Aggregate totals across all iterations
      let totalTokens = 0;
      let totalCost = 0;
      let durationSeconds = 0;
      for (const iter of iterations) {
        totalTokens += iter.totalTokens;
        totalCost += iter.totalCost;
        durationSeconds += iter.durationSeconds;
      }

      // Determine strategy from config snapshot
      const strategy =
        latest.stage_config_snapshot?.stage?.collaboration?.strategy ??
        latest.stage_config_snapshot?.stage?.execution?.agent_mode;

      const stageColor =
        STAGE_PALETTE[colorIndex % STAGE_PALETTE.length];
      colorIndex++;

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
        expanded: expandedStages.has(stageName),
      };

      nodes.push({
        id: stageName,
        type: 'stage',
        position: { x: pos.x, y: pos.y },
        data,
      });
    }

    // Build edges
    if (dagInfo.hasDeps) {
      // Forward dependency edges (right → left)
      for (const [target, deps] of dagInfo.depMap) {
        for (const source of deps) {
          const sourceStage = stageGroups.get(source);
          const sourceStatus = sourceStage
            ? sourceStage[sourceStage.length - 1].status
            : undefined;

          edges.push({
            id: `dep-${source}-${target}`,
            source,
            target,
            sourceHandle: 'right',
            targetHandle: 'left',
            type: 'smoothstep',
            style: { stroke: EDGE_COLORS.dataFlow, strokeWidth: 2 },
            animated: sourceStatus === 'running',
          });
        }
      }

      // Loop-back edges (bottom → top, routed below the DAG)
      for (const [source, target] of dagInfo.loopsBackTo) {
        const sourceExecs = stageGroups.get(source);
        const targetExecs = stageGroups.get(target);
        const iterCount = targetExecs ? targetExecs.length : 0;
        const maxLoops = dagInfo.maxLoops.get(source);
        const sourceStatus = sourceExecs
          ? sourceExecs[sourceExecs.length - 1].status
          : undefined;
        const isActive = sourceStatus === 'failed' || sourceStatus === 'running';

        // Build label: "on fail → retry (2/3)"
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
          targetHandle: 'top',
          type: 'smoothstep',
          label,
          labelStyle: { fill: '#ffa726', fontSize: 11, fontWeight: 600 },
          labelBgStyle: { fill: '#1a1225', fillOpacity: 0.9 },
          labelBgPadding: [6, 3] as [number, number],
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
          type: 'smoothstep',
          style: { stroke: EDGE_COLORS.dataFlow, strokeWidth: 2 },
          animated: sourceStatus === 'running',
        });
      }
    }

    return { nodes, edges };
  }, [workflow, stages, agents, expandedStages]);
}
