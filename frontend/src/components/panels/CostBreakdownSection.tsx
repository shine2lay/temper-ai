import { useMemo } from 'react';
import { useExecutionStore } from '@/store/executionStore';
import { formatCost, formatTokens } from '@/lib/utils';

interface BarSegment {
  label: string;
  value: number;
  color: string;
}

interface BarData {
  label: string;
  total: number;
  segments: BarSegment[];
}

const AGENT_COLORS = [
  '#42a5f5', '#66bb6a', '#ab47bc', '#ffa726', '#ef5350',
  '#26c6da', '#d4e157', '#8d6e63', '#78909c', '#ec407a',
];

function HorizontalBar({ data, maxValue }: { data: BarData; maxValue: number }) {
  if (maxValue === 0) return null;
  const pct = (data.total / maxValue) * 100;

  return (
    <div className="flex items-center gap-2 py-1">
      <span className="text-xs text-temper-text truncate w-28 shrink-0" title={data.label}>
        {data.label}
      </span>
      <div className="flex-1 h-4 bg-temper-surface rounded-sm overflow-hidden flex">
        {data.segments.map((seg) => {
          const segPct = maxValue > 0 ? (seg.value / maxValue) * 100 : 0;
          if (segPct < 0.1) return null;
          return (
            <div
              key={seg.label}
              className="h-full transition-all"
              style={{ width: `${segPct}%`, backgroundColor: seg.color }}
              title={`${seg.label}: ${formatCost(seg.value)}`}
            />
          );
        })}
        {/* Pad remaining space */}
        {pct < 100 && <div className="h-full flex-1" />}
      </div>
      <span className="text-xs text-emerald-400 font-mono w-16 text-right shrink-0">
        {formatCost(data.total)}
      </span>
    </div>
  );
}

function TokenBar({ label, prompt, completion, maxTokens }: { label: string; prompt: number; completion: number; maxTokens: number }) {
  if (maxTokens === 0) return null;
  const total = prompt + completion;
  const promptPct = (prompt / maxTokens) * 100;
  const compPct = (completion / maxTokens) * 100;

  return (
    <div className="flex items-center gap-2 py-1">
      <span className="text-xs text-temper-text truncate w-28 shrink-0 font-mono" title={label}>
        {label}
      </span>
      <div className="flex-1 h-4 bg-temper-surface rounded-sm overflow-hidden flex">
        <div
          className="h-full bg-blue-500/70"
          style={{ width: `${promptPct}%` }}
          title={`Prompt: ${formatTokens(prompt)}`}
        />
        <div
          className="h-full bg-purple-500/70"
          style={{ width: `${compPct}%` }}
          title={`Completion: ${formatTokens(completion)}`}
        />
      </div>
      <span className="text-xs text-temper-text-muted font-mono w-16 text-right shrink-0">
        {formatTokens(total)}
      </span>
    </div>
  );
}

export function CostBreakdownSection() {
  const stages = useExecutionStore((s) => s.stages);
  const agents = useExecutionStore((s) => s.agents);
  const llmCalls = useExecutionStore((s) => s.llmCalls);

  // Cost by Stage (segmented by agent)
  const costByStage = useMemo((): BarData[] => {
    const result: BarData[] = [];
    let colorIdx = 0;

    for (const [, stage] of stages) {
      const segments: BarSegment[] = [];
      let stageTotal = 0;

      for (const agentRef of stage.agents ?? []) {
        const agent = agents.get(agentRef.id);
        const cost = agent?.estimated_cost_usd ?? 0;
        if (cost > 0) {
          segments.push({
            label: agent?.agent_name ?? agent?.name ?? agentRef.id,
            value: cost,
            color: AGENT_COLORS[colorIdx % AGENT_COLORS.length],
          });
          stageTotal += cost;
        }
        colorIdx++;
      }

      if (stageTotal > 0) {
        result.push({
          label: stage.stage_name ?? stage.name ?? stage.id,
          total: stageTotal,
          segments,
        });
      }
    }

    return result.sort((a, b) => b.total - a.total);
  }, [stages, agents]);

  // Tokens by Model
  const tokensByModel = useMemo(() => {
    const modelMap = new Map<string, { prompt: number; completion: number }>();
    for (const [, call] of llmCalls) {
      const model = call.model ?? 'unknown';
      const existing = modelMap.get(model) ?? { prompt: 0, completion: 0 };
      existing.prompt += call.prompt_tokens ?? 0;
      existing.completion += call.completion_tokens ?? 0;
      modelMap.set(model, existing);
    }
    return Array.from(modelMap.entries())
      .map(([model, data]) => ({ model, ...data, total: data.prompt + data.completion }))
      .sort((a, b) => b.total - a.total);
  }, [llmCalls]);

  // Top 5 Agents by Cost
  const topAgents = useMemo(() => {
    const result: { name: string; cost: number }[] = [];
    for (const [, agent] of agents) {
      const cost = agent.estimated_cost_usd ?? 0;
      if (cost > 0) {
        result.push({
          name: agent.agent_name ?? agent.name ?? agent.id,
          cost,
        });
      }
    }
    return result.sort((a, b) => b.cost - a.cost).slice(0, 5);
  }, [agents]);

  // No data — return null
  const hasCostData = costByStage.length > 0 || tokensByModel.length > 0 || topAgents.length > 0;
  if (!hasCostData) return null;

  const maxStageCost = costByStage.length > 0 ? Math.max(...costByStage.map((d) => d.total)) : 0;
  const maxModelTokens = tokensByModel.length > 0 ? Math.max(...tokensByModel.map((d) => d.total)) : 0;
  const maxAgentCost = topAgents.length > 0 ? Math.max(...topAgents.map((d) => d.cost)) : 0;

  return (
    <div className="flex flex-col gap-4">
      {/* Cost by Stage */}
      {costByStage.length > 0 && (
        <div>
          <span className="text-xs font-medium text-temper-text-muted mb-1 block">Cost by Stage</span>
          {costByStage.map((data) => (
            <HorizontalBar key={data.label} data={data} maxValue={maxStageCost} />
          ))}
          {costByStage.length > 0 && costByStage[0].segments.length > 1 && (
            <div className="flex flex-wrap gap-2 mt-1">
              {costByStage.flatMap(d => d.segments).filter((s, i, arr) => arr.findIndex(x => x.label === s.label) === i).map(seg => (
                <span key={seg.label} className="flex items-center gap-1 text-[10px] text-temper-text-dim">
                  <span className="w-2 h-2 rounded-sm shrink-0" style={{ backgroundColor: seg.color }} />
                  {seg.label}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Tokens by Model */}
      {tokensByModel.length > 0 && (
        <div>
          <span className="text-xs font-medium text-temper-text-muted mb-1 block">Tokens by Model</span>
          <div className="flex items-center gap-3 mb-1 text-[10px] text-temper-text-dim">
            <span className="flex items-center gap-1">
              <span className="w-2 h-2 rounded-sm bg-blue-500/70" /> Prompt
            </span>
            <span className="flex items-center gap-1">
              <span className="w-2 h-2 rounded-sm bg-purple-500/70" /> Completion
            </span>
          </div>
          {tokensByModel.map((data) => (
            <TokenBar
              key={data.model}
              label={data.model}
              prompt={data.prompt}
              completion={data.completion}
              maxTokens={maxModelTokens}
            />
          ))}
        </div>
      )}

      {/* Top 5 Agents by Cost */}
      {topAgents.length > 0 && (
        <div>
          <span className="text-xs font-medium text-temper-text-muted mb-1 block">Top Agents by Cost</span>
          {topAgents.map((agent) => (
            <div key={agent.name} className="flex items-center gap-2 py-1">
              <span className="text-xs text-temper-text truncate w-28 shrink-0" title={agent.name}>
                {agent.name}
              </span>
              <div className="flex-1 h-4 bg-temper-surface rounded-sm overflow-hidden">
                <div
                  className="h-full bg-emerald-500/50 transition-all"
                  style={{ width: `${maxAgentCost > 0 ? (agent.cost / maxAgentCost) * 100 : 0}%` }}
                />
              </div>
              <span className="text-xs text-emerald-400 font-mono w-16 text-right shrink-0">
                {formatCost(agent.cost)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
