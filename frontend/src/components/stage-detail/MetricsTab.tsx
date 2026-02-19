import { useMemo } from 'react';
import { formatDuration, formatTokens, formatCost } from '@/lib/utils';
import { STATUS_COLORS } from '@/lib/constants';
import type { AgentExecution } from '@/types';

interface MetricsTabProps {
  agents: AgentExecution[];
  stageDurationSeconds: number | null;
}

interface AgentMetric {
  agent: AgentExecution;
  name: string;
  promptTokens: number;
  completionTokens: number;
  totalTokens: number;
  cost: number;
  duration: number;
  llmCalls: number;
  toolCalls: number;
}

/**
 * Per-agent metrics breakdown with visual bars.
 * Shows token distribution, cost, latency, and call counts.
 * Stage-level rollup at top.
 */
export function MetricsTab({ agents, stageDurationSeconds }: MetricsTabProps) {
  const { metrics, totals, maxTokens, maxDuration } = useMemo(() => {
    const agentMetrics: AgentMetric[] = agents.map((a) => ({
      agent: a,
      name: a.agent_name ?? a.name ?? a.id,
      promptTokens: a.prompt_tokens ?? 0,
      completionTokens: a.completion_tokens ?? 0,
      totalTokens: a.total_tokens ?? 0,
      cost: a.estimated_cost_usd ?? 0,
      duration: a.duration_seconds ?? 0,
      llmCalls: a.total_llm_calls ?? 0,
      toolCalls: a.total_tool_calls ?? 0,
    }));

    const totalTokens = agentMetrics.reduce((s, m) => s + m.totalTokens, 0);
    const totalCost = agentMetrics.reduce((s, m) => s + m.cost, 0);
    const totalLlm = agentMetrics.reduce((s, m) => s + m.llmCalls, 0);
    const totalTool = agentMetrics.reduce((s, m) => s + m.toolCalls, 0);
    const totalPrompt = agentMetrics.reduce((s, m) => s + m.promptTokens, 0);
    const totalCompletion = agentMetrics.reduce((s, m) => s + m.completionTokens, 0);

    const maxTok = Math.max(1, ...agentMetrics.map((m) => m.totalTokens));
    const maxDur = Math.max(1, ...agentMetrics.map((m) => m.duration));

    return {
      metrics: agentMetrics,
      totals: { totalTokens, totalCost, totalLlm, totalTool, totalPrompt, totalCompletion },
      maxTokens: maxTok,
      maxDuration: maxDur,
    };
  }, [agents]);

  return (
    <div className="flex flex-col gap-4">
      {/* Stage rollup summary */}
      <div className="grid grid-cols-3 gap-3">
        <SummaryCard label="Total Tokens" value={formatTokens(totals.totalTokens)} subValue={`${formatTokens(totals.totalPrompt)} prompt / ${formatTokens(totals.totalCompletion)} completion`} />
        <SummaryCard label="Total Cost" value={formatCost(totals.totalCost)} subValue={`${totals.totalLlm} LLM calls`} />
        <SummaryCard label="Duration" value={formatDuration(stageDurationSeconds)} subValue={`${totals.totalTool} tool calls`} />
      </div>

      {/* Stage-level token split bar */}
      {totals.totalTokens > 0 && (
        <div className="flex flex-col gap-1">
          <span className="text-xs text-temper-text-muted">Token Split (Stage Total)</span>
          <div className="h-3 w-full rounded-full bg-temper-surface overflow-hidden flex">
            <div
              className="h-full bg-temper-token-prompt transition-all"
              style={{ width: `${(totals.totalPrompt / totals.totalTokens) * 100}%` }}
              title={`Prompt: ${totals.totalPrompt}`}
            />
            <div
              className="h-full bg-temper-token-completion transition-all"
              style={{ width: `${(totals.totalCompletion / totals.totalTokens) * 100}%` }}
              title={`Completion: ${totals.totalCompletion}`}
            />
          </div>
          <div className="flex gap-4 text-[10px] text-temper-text-dim">
            <span className="flex items-center gap-1">
              <span className="inline-block w-2 h-2 rounded-sm bg-temper-token-prompt" />
              Prompt ({((totals.totalPrompt / totals.totalTokens) * 100).toFixed(0)}%)
            </span>
            <span className="flex items-center gap-1">
              <span className="inline-block w-2 h-2 rounded-sm bg-temper-token-completion" />
              Completion ({((totals.totalCompletion / totals.totalTokens) * 100).toFixed(0)}%)
            </span>
          </div>
        </div>
      )}

      {/* Per-agent breakdown */}
      <div className="flex flex-col gap-1">
        <span className="text-xs font-medium text-temper-text-muted">Per-Agent Breakdown</span>

        {/* Table header */}
        <div className="grid grid-cols-[1fr_120px_80px_80px_60px_60px] gap-2 px-3 py-1 text-[10px] text-temper-text-dim border-b border-temper-border/30">
          <span>Agent</span>
          <span>Tokens</span>
          <span>Duration</span>
          <span>Cost</span>
          <span className="text-center">LLM</span>
          <span className="text-center">Tool</span>
        </div>

        {/* Agent rows */}
        {metrics.map((m) => {
          const statusColor = STATUS_COLORS[m.agent.status] ?? STATUS_COLORS.pending;
          const tokenPct = (m.totalTokens / maxTokens) * 100;
          const durationPct = (m.duration / maxDuration) * 100;
          const promptPct = m.totalTokens > 0 ? (m.promptTokens / m.totalTokens) * 100 : 0;

          return (
            <div
              key={m.agent.id}
              className="grid grid-cols-[1fr_120px_80px_80px_60px_60px] gap-2 px-3 py-2 items-center hover:bg-temper-surface/30 rounded transition-colors"
            >
              {/* Agent name + status */}
              <div className="flex items-center gap-2 min-w-0">
                <span
                  className="w-2 h-2 rounded-full shrink-0"
                  style={{ backgroundColor: statusColor }}
                />
                <span className="text-xs text-temper-text truncate">{m.name}</span>
              </div>

              {/* Token bar */}
              <div className="flex flex-col gap-0.5">
                <div className="h-2 w-full rounded-full bg-temper-surface overflow-hidden flex">
                  <div
                    className="h-full bg-temper-token-prompt"
                    style={{ width: `${(tokenPct * promptPct) / 100}%` }}
                  />
                  <div
                    className="h-full bg-temper-token-completion"
                    style={{ width: `${(tokenPct * (100 - promptPct)) / 100}%` }}
                  />
                </div>
                <span className="text-[10px] text-temper-text-dim">{formatTokens(m.totalTokens)}</span>
              </div>

              {/* Duration bar */}
              <div className="flex flex-col gap-0.5">
                <div className="h-2 w-full rounded-full bg-temper-surface overflow-hidden">
                  <div
                    className="h-full rounded-full transition-all"
                    style={{
                      width: `${durationPct}%`,
                      backgroundColor: statusColor,
                      opacity: 0.7,
                    }}
                  />
                </div>
                <span className="text-[10px] text-temper-text-dim">{formatDuration(m.duration)}</span>
              </div>

              {/* Cost */}
              <span className="text-xs text-temper-text">{formatCost(m.cost)}</span>

              {/* LLM calls */}
              <span className="text-xs text-temper-text text-center">{m.llmCalls}</span>

              {/* Tool calls */}
              <span className="text-xs text-temper-text text-center">{m.toolCalls}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function SummaryCard({
  label,
  value,
  subValue,
}: {
  label: string;
  value: string;
  subValue?: string;
}) {
  return (
    <div className="flex flex-col rounded-lg bg-temper-panel/60 border border-temper-border/30 p-3">
      <span className="text-[10px] text-temper-text-dim">{label}</span>
      <span className="text-lg font-semibold text-temper-text">{value}</span>
      {subValue && <span className="text-[10px] text-temper-text-dim mt-0.5">{subValue}</span>}
    </div>
  );
}
