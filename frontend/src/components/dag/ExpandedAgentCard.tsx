import { useMemo } from 'react';
import { useExecutionStore } from '@/store/executionStore';
import { STATUS_COLORS } from './constants';
import { cn, formatDuration, formatTokens } from '@/lib/utils';
import { CollapsibleSection } from '@/components/shared/Collapsible';
import { JsonViewer } from '@/components/shared/JsonViewer';

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
      className="bg-temper-panel rounded px-3 py-2 cursor-pointer hover:bg-temper-panel-light transition-colors"
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
          <span className={cn(
            'text-[10px] px-1.5 py-0.5 rounded shrink-0 font-mono',
            agent.confidence_score >= 0.8 ? 'bg-emerald-950/50 text-emerald-400' :
            agent.confidence_score >= 0.5 ? 'bg-amber-950/50 text-amber-400' :
            'bg-red-950/50 text-red-400'
          )}>
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
          title={`Prompt: ${promptTokens} tokens | Completion: ${completionTokens} tokens | Total: ${totalTokens}`}
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
          <div className="max-h-72 overflow-y-auto">
            <JsonViewer data={agent.output_data} />
          </div>
        </CollapsibleSection>
      )}

      {/* Reasoning */}
      {agent.reasoning && (
        <CollapsibleSection title="Reasoning">
          <div className="max-h-72 overflow-y-auto text-xs text-temper-text-dim font-mono whitespace-pre-wrap p-2 rounded bg-temper-surface">
            {agent.reasoning}
          </div>
        </CollapsibleSection>
      )}
    </div>
  );
}
