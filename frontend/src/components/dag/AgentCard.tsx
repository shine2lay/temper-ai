import { memo, useState, useMemo } from 'react';
import { useExecutionStore } from '@/store/executionStore';
import { STATUS_COLORS, confidenceBadgeClass, deriveTokenBreakdown } from './constants';
import { cn, formatDuration, formatTokens, formatCost } from '@/lib/utils';

interface AgentCardProps {
  agentId: string;
}

/**
 * Agent card rendered inside a StageNode.
 * Uses fine-grained Zustand selector so it only re-renders when
 * THIS agent's data changes.
 */
export const AgentCard = memo(function AgentCard({ agentId }: AgentCardProps) {
  const agent = useExecutionStore((s) => s.agents.get(agentId));
  const streaming = useExecutionStore((s) => s.streamingContent.get(agentId));
  const select = useExecutionStore((s) => s.select);
  const toolCalls = useExecutionStore((s) => s.toolCalls);
  const [outputExpanded, setOutputExpanded] = useState(false);

  const hasApprovalRequired = useMemo(() => {
    for (const [, tc] of toolCalls) {
      if (tc.agent_execution_id === agentId && tc.approval_required) return true;
    }
    return false;
  }, [toolCalls, agentId]);

  if (!agent) return null;

  const borderColor = STATUS_COLORS[agent.status] ?? STATUS_COLORS.pending;
  const model = agent.agent_config_snapshot?.agent?.model;
  const agentType = agent.agent_config_snapshot?.agent?.type;
  const totalTokens = agent.total_tokens ?? 0;
  const { prompt: promptTokens, completion: completionTokens } = deriveTokenBreakdown(agent);
  const promptPct = totalTokens > 0 ? (promptTokens / totalTokens) * 100 : 0;
  const completionPct =
    totalTokens > 0 ? (completionTokens / totalTokens) * 100 : 0;
  const isStreaming = streaming && !streaming.done;

  return (
    <div
      className="bg-temper-panel rounded px-3 py-2 cursor-pointer hover:bg-temper-panel-light transition-colors focus:outline-none focus:ring-2 focus:ring-temper-accent/50 focus:ring-offset-1 focus:ring-offset-temper-panel"
      style={{ borderLeft: `4px solid ${borderColor}` }}
      onClick={(e) => {
        e.stopPropagation();
        select('agent', agentId);
      }}
    >
      {/* Name + model badge */}
      <div className="flex items-center gap-2 mb-1">
        <span className="text-sm font-medium text-temper-text truncate">
          {agent.agent_name ?? agent.name ?? agentId}
        </span>
        {model && (
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-temper-surface text-temper-text-muted shrink-0">
            {model}
          </span>
        )}
        {agentType && agentType !== 'standard' && (
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-temper-surface text-temper-text-muted shrink-0">
            {agentType}
          </span>
        )}
        {agent.role && (
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-temper-surface text-temper-text-muted shrink-0">
            {agent.role}
          </span>
        )}
        {agent.confidence_score != null && (
          <span className={cn('text-[10px] px-1.5 py-0.5 rounded shrink-0 font-mono', confidenceBadgeClass(agent.confidence_score))}>
            {(agent.confidence_score * 100).toFixed(0)}%
          </span>
        )}
        {hasApprovalRequired && (
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-950/50 text-amber-400 border border-amber-900/50 shrink-0" title="Has tool calls requiring approval">
            !
          </span>
        )}
        {isStreaming && (
          <span className="w-2 h-2 rounded-full bg-temper-accent animate-pulse-streaming shrink-0" />
        )}
      </div>

      {/* Token bar */}
      {totalTokens > 0 && (
        <div
          className="h-1.5 w-full rounded-full bg-temper-surface mb-1 overflow-hidden flex"
          title={`Prompt: ${formatTokens(promptTokens)} | Completion: ${formatTokens(completionTokens)} | Total: ${formatTokens(totalTokens)}`}
        >
          <div
            className="h-full bg-temper-token-prompt"
            style={{ width: `${promptPct}%` }}
          />
          <div
            className="h-full bg-temper-token-completion"
            style={{ width: `${completionPct}%` }}
          />
        </div>
      )}

      {/* Metrics */}
      <div className="flex items-center gap-3 text-[10px] text-temper-text-muted">
        <span>{formatDuration(agent.duration_seconds)}</span>
        <span title="Prompt tokens" className="text-temper-token-prompt">{formatTokens(promptTokens)}p</span>
        <span title="Completion tokens" className="text-temper-token-completion">{formatTokens(completionTokens)}c</span>
        <span>{formatTokens(totalTokens)} tok</span>
        {agent.estimated_cost_usd > 0 && (
          <span className="text-emerald-400">{formatCost(agent.estimated_cost_usd)}</span>
        )}
        {agent.total_llm_calls > 0 && <span>{agent.total_llm_calls} llm</span>}
        {agent.total_tool_calls > 0 && <span>{agent.total_tool_calls} tool</span>}
      </div>

      {/* Error message for failed agents */}
      {agent.status === 'failed' && agent.error_message && (
        <div className="mt-1 px-2 py-0.5 rounded text-[10px] bg-red-950/50 text-red-400 truncate">
          {agent.error_message}
        </div>
      )}

      {/* Output preview */}
      {agent.output && (
        <div
          className={cn('mt-1 text-[10px] text-temper-text-dim font-mono cursor-pointer', !outputExpanded && 'line-clamp-2')}
          onClick={(e) => { e.stopPropagation(); setOutputExpanded(!outputExpanded); }}
          title={outputExpanded ? 'Click to collapse' : 'Click to expand'}
        >
          {agent.output}
        </div>
      )}
    </div>
  );
});
