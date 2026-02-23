import { useMemo } from 'react';
import { useExecutionStore } from '@/store/executionStore';
import { selectStageGroups } from '@/store/selectors';
import { STATUS_COLORS } from '@/lib/constants';
import { ensureUTC } from '@/lib/utils';

export interface TimelineRow {
  id: string;
  /** The actual store entity ID (for selection), distinct from display row.id */
  entityId: string;
  label: string;
  level: 'workflow' | 'stage' | 'agent';
  status: string;
  startTime: number | null;
  endTime: number | null;
  parentId: string | null;
  hasChildren: boolean;
  color: string;
}

function toEpoch(ts: string | null | undefined): number | null {
  if (!ts) return null;
  return new Date(ensureUTC(ts)).getTime();
}

/**
 * Transforms Zustand store state into a flat array of timeline rows
 * for the hierarchical Gantt chart.
 */
export function useTimelineData(): {
  rows: TimelineRow[];
  timeRange: [number, number];
} {
  const workflow = useExecutionStore((s) => s.workflow);
  const stages = useExecutionStore((s) => s.stages);
  const agents = useExecutionStore((s) => s.agents);

  // Status fingerprint: only recalculate when status/timing changes,
  // not when token counts or output content updates
  const statusFingerprint = useMemo(() => {
    let fp = workflow?.status ?? '';
    for (const [id, stage] of stages) {
      fp += `|s:${id}:${stage.status}:${stage.start_time}:${stage.end_time}`;
    }
    for (const [id, agent] of agents) {
      fp += `|a:${id}:${agent.status}:${agent.start_time}:${agent.end_time}`;
    }
    return fp;
  }, [workflow, stages, agents]);

  return useMemo(() => {
    if (!workflow) return { rows: [], timeRange: [0, 0] };

    const rows: TimelineRow[] = [];
    const wfStart = toEpoch(workflow.start_time);
    const wfEnd = toEpoch(workflow.end_time);

    // Workflow row
    rows.push({
      id: workflow.id,
      entityId: workflow.id,
      label: workflow.workflow_name,
      level: 'workflow',
      status: workflow.status,
      startTime: wfStart,
      endTime: wfEnd,
      parentId: null,
      hasChildren: stages.size > 0,
      color: STATUS_COLORS[workflow.status] ?? STATUS_COLORS.pending,
    });

    // Stage and agent rows
    const stageGroups = selectStageGroups(stages);
    for (const [stageName, executions] of stageGroups) {
      const latest = executions[executions.length - 1];
      // Use earliest start and latest end across all iterations
      const stageStart = toEpoch(executions[0].start_time);
      const stageEnd = toEpoch(latest.end_time);

      // Count total agents across all iterations to determine hasChildren
      const totalAgentCount = executions.reduce(
        (sum, exec) => sum + (exec.agents?.length ?? 0),
        0,
      );

      rows.push({
        id: `stage-${stageName}`,
        entityId: latest.id,
        label: stageName,
        level: 'stage',
        status: latest.status,
        startTime: stageStart,
        endTime: stageEnd,
        parentId: workflow.id,
        hasChildren: totalAgentCount > 0,
        color: STATUS_COLORS[latest.status] ?? STATUS_COLORS.pending,
      });

      // Agent rows — track iteration index for labels
      const CIRCLED_NUMS = ['①', '②', '③', '④', '⑤', '⑥', '⑦', '⑧', '⑨', '⑩'];
      let iterIdx = 0;
      for (const exec of executions) {
        iterIdx++;
        for (const a of exec.agents ?? []) {
          const agent = agents.get(a.id);
          if (!agent) continue;
          const baseName = agent.agent_name ?? agent.name ?? a.id;
          const label =
            executions.length > 1
              ? `${CIRCLED_NUMS[iterIdx - 1] ?? `(${iterIdx})`} ${baseName}`
              : baseName;
          rows.push({
            id: a.id,
            entityId: a.id,
            label,
            level: 'agent',
            status: agent.status,
            startTime: toEpoch(agent.start_time),
            endTime: toEpoch(agent.end_time),
            parentId: `stage-${stageName}`,
            hasChildren: false,
            color: STATUS_COLORS[agent.status] ?? STATUS_COLORS.pending,
          });
        }
      }
    }

    // Compute time range
    let minTime = Infinity;
    let maxTime = -Infinity;
    const now = Date.now();
    for (const row of rows) {
      if (row.startTime !== null && row.startTime < minTime) {
        minTime = row.startTime;
      }
      if (row.endTime !== null && row.endTime > maxTime) {
        maxTime = row.endTime;
      }
    }
    if (minTime === Infinity) minTime = now;
    if (maxTime === -Infinity) maxTime = now;

    // If workflow is running, extend to now
    const isRunning = workflow.status === 'running';
    if (isRunning && now > maxTime) {
      maxTime = now;
    }

    // Ensure a minimum time span to avoid division-by-zero
    const MIN_RANGE_MS = 1000;
    if (maxTime - minTime < MIN_RANGE_MS) {
      maxTime = minTime + MIN_RANGE_MS;
    }

    return { rows, timeRange: [minTime, maxTime] as [number, number] };
  }, [statusFingerprint]); // eslint-disable-line react-hooks/exhaustive-deps
}
