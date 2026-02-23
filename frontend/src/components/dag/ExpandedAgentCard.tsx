import { useMemo, useState } from 'react';
import { useExecutionStore } from '@/store/executionStore';
import { STATUS_COLORS, confidenceBadgeClass } from './constants';
import { cn, formatDuration, formatTokens, formatCost } from '@/lib/utils';
import { CollapsibleSection } from '@/components/shared/Collapsible';
import { JsonViewer } from '@/components/shared/JsonViewer';
import { OutputDisplay } from '@/components/shared/OutputDisplay';

interface ExpandedAgentCardProps {
  agentId: string;
}

/**
 * Expanded agent card shown inside expanded stage nodes.
 * Displays full agent I/O data, reasoning, and metrics.
 */
export function ExpandedAgentCard({ agentId }: ExpandedAgentCardProps) {
  const agent = useExecutionStore((s) => s.agents.get(agentId));
  const streaming = useExecutionStore((s) => s.streamingContent.get(agentId));
  const select = useExecutionStore((s) => s.select);
  const toolCalls = useExecutionStore((s) => s.toolCalls);

  const [reasonExpanded, setReasonExpanded] = useState(false);

  const hasApprovalRequired = useMemo(() => {
    for (const [, tc] of toolCalls) {
      if (tc.agent_execution_id === agentId && tc.approval_required) return true;
    }
    return false;
  }, [toolCalls, agentId]);

  if (!agent) return null;

  const borderColor = STATUS_COLORS[agent.status] ?? STATUS_COLORS.pending;
  const model = agent.agent_config_snapshot?.agent?.model;
  const totalTokens = agent.total_tokens ?? 0;
  const promptTokens = agent.prompt_tokens ?? 0;
  const completionTokens = agent.completion_tokens ?? 0;
  const promptPct = totalTokens > 0 ? (promptTokens / totalTokens) * 100 : 0;
  const completionPct =
    totalTokens > 0 ? (completionTokens / totalTokens) * 100 : 0;
  const isStreaming = streaming && !streaming.done;
  const hasOutputData = agent.output_data != null && Object.keys(agent.output_data).length > 0;
  const hasInputData = agent.input_data != null && Object.keys(agent.input_data).length > 0;

  return (
    <div
      className="bg-temper-panel rounded px-3 py-2 cursor-pointer hover:bg-temper-panel-light transition-colors focus:outline-none focus:ring-2 focus:ring-temper-accent/50 focus:ring-offset-1 focus:ring-offset-temper-panel"
      style={{ borderLeft: `4px solid ${borderColor}` }}
      onClick={(e) => {
        e.stopPropagation();
        select('agent', agentId);
      }}
    >
      {/* Name + badges */}
      <div className="flex items-center gap-2 mb-1">
        <span className="text-sm font-medium text-temper-text truncate">
          {agent.agent_name ?? agent.name ?? agentId}
        </span>
        {model && (
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-temper-surface text-temper-text-muted shrink-0">
            {model}
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
      <div className="flex items-center gap-3 text-[10px] text-temper-text-muted mb-1">
        <span>{formatDuration(agent.duration_seconds)}</span>
        <span>{formatTokens(totalTokens)} tok</span>
        {agent.estimated_cost_usd > 0 && (
          <span className="text-emerald-400">{formatCost(agent.estimated_cost_usd)}</span>
        )}
        {agent.total_llm_calls > 0 && <span>{agent.total_llm_calls} llm</span>}
        {agent.total_tool_calls > 0 && <span>{agent.total_tool_calls} tool</span>}
      </div>

      {/* Error message for failed agents */}
      {agent.status === 'failed' && agent.error_message && (
        <div className="mb-1 px-2 py-0.5 rounded text-[10px] bg-red-950/50 text-red-400 truncate">
          {agent.error_message}
        </div>
      )}

      {/* Input Data */}
      {hasInputData && (
        <CollapsibleSection title="Input Data">
          <div className="max-h-72 overflow-y-auto">
            <JsonViewer data={agent.input_data} />
          </div>
        </CollapsibleSection>
      )}

      {/* Output Data */}
      {hasOutputData && (
        <CollapsibleSection title="Output Data" defaultOpen>
          <OutputDisplay data={agent.output_data!} />
        </CollapsibleSection>
      )}

      {/* Reasoning */}
      {agent.reasoning && (
        <CollapsibleSection title="Reasoning">
          <div
            className={cn(
              'overflow-y-auto text-xs text-temper-text-dim font-mono whitespace-pre-wrap p-2 rounded bg-temper-surface',
              !reasonExpanded && 'max-h-32',
            )}
          >
            {agent.reasoning}
          </div>
          {agent.reasoning.length > 300 && (
            <button
              className="text-[10px] text-temper-text-muted hover:text-temper-text mt-1"
              onClick={(e) => { e.stopPropagation(); setReasonExpanded(!reasonExpanded); }}
            >
              {reasonExpanded ? 'Show less' : 'Show more'}
            </button>
          )}
        </CollapsibleSection>
      )}
    </div>
  );
}
