import { useMemo } from 'react';
import { useExecutionStore } from '@/store/executionStore';
import { formatTokens, formatCost, formatDuration } from '@/lib/utils';

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

  return (
    <div className="flex items-center gap-6 bg-maf-panel/50 px-4 py-2 border-b border-maf-border shrink-0">
      {stats.map((s) => (
        <div key={s.label} className="flex items-center gap-1.5 text-xs">
          <span className="text-maf-text-muted">{s.label}</span>
          <span className="font-mono font-medium text-maf-text">
            {s.value}
            {s.suffix && <span className="text-red-400">{s.suffix}</span>}
          </span>
        </div>
      ))}
      {stageCosts.length > 0 && (() => {
        const maxCost = Math.max(...stageCosts.map(s => s.cost), 0.001);
        return (
          <div className="flex items-center gap-2 ml-2 border-l border-maf-border/30 pl-3">
            <span className="text-[10px] text-maf-text-dim shrink-0">Cost/stage:</span>
            <div className="flex items-end gap-1 h-4">
              {stageCosts.slice(0, 5).map(s => (
                <div key={s.name} className="flex flex-col items-center" title={`${s.name}: ${formatCost(s.cost)}`}>
                  <div className="w-3 bg-maf-accent/60 rounded-t-sm" style={{ height: Math.max((s.cost / maxCost) * 16, 2) }} />
                </div>
              ))}
            </div>
          </div>
        );
      })()}
    </div>
  );
}
