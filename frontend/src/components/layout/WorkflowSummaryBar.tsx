import { useMemo } from 'react';
import { useExecutionStore } from '@/store/executionStore';
import { selectStageGroups } from '@/store/selectors';
import { formatTokens, formatCost, formatDuration } from '@/lib/utils';

import { STATUS_COLORS } from '@/lib/constants';

function pipelineColor(status: string): string {
  return STATUS_COLORS[status] ?? STATUS_COLORS.pending;
}

/**
 * Horizontal stats bar showing aggregate workflow metrics.
 * Placed between WorkflowHeader and ViewTabs.
 */
export function WorkflowSummaryBar() {
  const workflow = useExecutionStore((s) => s.workflow);
  const stages = useExecutionStore((s) => s.stages);
  const agents = useExecutionStore((s) => s.agents);

  const counts = useMemo(() => {
    let completedStages = 0;
    let totalStages = 0;
    let failedStages = 0;
    for (const [, stage] of stages) {
      totalStages++;
      if (stage.status === 'completed') completedStages++;
      if (stage.status === 'failed') failedStages++;
    }
    let completedAgents = 0;
    let totalAgents = 0;
    let failedAgents = 0;
    for (const [, agent] of agents) {
      totalAgents++;
      if (agent.status === 'completed') completedAgents++;
      if (agent.status === 'failed') failedAgents++;
    }
    return { completedStages, totalStages, failedStages, completedAgents, totalAgents, failedAgents };
  }, [stages, agents]);

  const stageCosts = useMemo(() => {
    const costs: Array<{ name: string; cost: number }> = [];
    for (const [, stage] of stages) {
      let cost = 0;
      for (const agent of stage.agents ?? []) {
        cost += agent.estimated_cost_usd ?? 0;
      }
      if (cost > 0) {
        costs.push({ name: stage.stage_name ?? stage.name ?? stage.id, cost });
      }
    }
    return costs.sort((a, b) => b.cost - a.cost);
  }, [stages]);

  const pipeline = useMemo(() => {
    const stageGroups = selectStageGroups(stages);
    const result: Array<{ name: string; status: string }> = [];
    for (const [name, executions] of stageGroups) {
      const latest = executions[executions.length - 1];
      result.push({ name, status: latest.status });
    }
    return result;
  }, [stages]);

  const slowestStage = useMemo(() => {
    return pipeline.reduce<{ name: string; dur: number }>(
      (max, s) => {
        const dur = stages.get(s.name)?.duration_seconds ?? 0;
        return dur > max.dur ? { name: s.name, dur } : max;
      },
      { name: '', dur: 0 },
    );
  }, [pipeline, stages]);

  if (!workflow) return null;

  const stagesFailed = counts.failedStages > 0 ? ` (${counts.failedStages} failed)` : '';
  const agentsFailed = counts.failedAgents > 0 ? ` (${counts.failedAgents} failed)` : '';

  const stats = [
    {
      label: 'Stages',
      value: `${counts.completedStages}/${counts.totalStages}`,
      suffix: stagesFailed,
      hasFailed: counts.failedStages > 0,
    },
    {
      label: 'Agents',
      value: `${counts.completedAgents}/${counts.totalAgents}`,
      suffix: agentsFailed,
      hasFailed: counts.failedAgents > 0,
    },
    { label: 'Duration', value: formatDuration(workflow.duration_seconds), suffix: '', hasFailed: false },
    { label: 'Tokens', value: formatTokens(workflow.total_tokens), suffix: '', hasFailed: false },
    { label: 'Cost', value: formatCost(workflow.total_cost_usd), suffix: '', hasFailed: false },
    { label: 'LLM Calls', value: String(workflow.total_llm_calls ?? 0), suffix: '', hasFailed: false },
    { label: 'Tool Calls', value: String(workflow.total_tool_calls ?? 0), suffix: '', hasFailed: false },
  ];

  const Stat = ({ label, value, suffix }: { label: string; value: string; suffix?: string }) => (
    <div className="flex items-center gap-1.5 text-xs">
      <span className="text-temper-text-muted">{label}</span>
      <span className="font-mono font-medium text-temper-text">
        {value}
        {suffix && <span className="text-red-400">{suffix}</span>}
      </span>
    </div>
  );

  return (
    <div className="flex items-center gap-3 flex-wrap bg-temper-panel/50 px-4 py-2 border-b border-temper-border shrink-0">
      {/* Progress */}
      <div className="flex items-center gap-3">
        {stats.slice(0, 2).map((s) => <Stat key={s.label} {...s} />)}
      </div>
      <div className="w-px h-4 bg-temper-border/40" />
      {/* Performance */}
      <div className="flex items-center gap-3">
        {stats.slice(2, 6).map((s) => <Stat key={s.label} {...s} />)}
      </div>
      <div className="w-px h-4 bg-temper-border/40" />
      {/* Cost + tool calls */}
      <div className="flex items-center gap-3">
        {stats.slice(6).map((s) => <Stat key={s.label} {...s} />)}
      </div>
      {stageCosts.length > 0 && (() => {
        const maxCost = Math.max(...stageCosts.map(s => s.cost), 0.001);
        return (
          <div className="flex items-center gap-2 ml-2 border-l border-temper-border/30 pl-3">
            <span className="text-[10px] text-temper-text-dim shrink-0">Cost/stage:</span>
            <div className="flex items-end gap-1 h-4">
              {stageCosts.slice(0, 5).map(s => (
                <div key={s.name} className="flex flex-col items-center" title={`${s.name}: ${formatCost(s.cost)}`}>
                  <div className="w-4 bg-temper-accent/60 rounded-t-sm" style={{ height: Math.max((s.cost / maxCost) * 20, 4) }} />
                </div>
              ))}
            </div>
          </div>
        );
      })()}
      {pipeline.length > 0 && (
        <div className="flex items-center gap-0.5 ml-2 border-l border-temper-border/30 pl-3" title="Stage pipeline">
          {pipeline.map((s, i) => {
            const isSlowest = slowestStage.dur > 0 && s.name === slowestStage.name;
            const stageDur = stages.get(s.name)?.duration_seconds;
            const dotTitle = isSlowest
              ? `${s.name}: ${s.status} — bottleneck (${formatDuration(stageDur)})`
              : `${s.name}: ${s.status}${stageDur != null ? ` (${formatDuration(stageDur)})` : ''}`;
            return (
              <div key={s.name} className="flex items-center">
                {i > 0 && <div className="w-2 h-px bg-temper-border/40" />}
                <div
                  className={
                    isSlowest
                      ? 'rounded-full shrink-0 ring-2 ring-yellow-400/70 ring-offset-1 ring-offset-temper-panel'
                      : 'rounded-full shrink-0'
                  }
                  style={{
                    backgroundColor: pipelineColor(s.status),
                    width: isSlowest ? 8 : 6,
                    height: isSlowest ? 8 : 6,
                  }}
                  title={dotTitle}
                />
                {isSlowest && (
                  <span className="ml-1 text-[9px] font-medium text-yellow-400/80 leading-none">
                    slow
                  </span>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
