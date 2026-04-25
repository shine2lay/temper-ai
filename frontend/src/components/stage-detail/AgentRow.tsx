import { useState } from 'react';
import { useExecutionStore } from '@/store/executionStore';
import { STATUS_COLORS } from '@/lib/constants';
import { cn, formatDuration, formatTokens, formatCost } from '@/lib/utils';
import { JsonViewer } from '@/components/shared/JsonViewer';

interface AgentRowProps {
  agentId: string;
  defaultExpanded?: boolean;
}

/**
 * Expandable agent row for stage detail overlay.
 * Collapsed: single scannable line with key metrics.
 * Expanded: n8n-inspired 3-pane layout (Input | Output | Reasoning).
 */
export function AgentRow({ agentId, defaultExpanded = false }: AgentRowProps) {
  const agent = useExecutionStore((s) => s.agents.get(agentId));
  const streaming = useExecutionStore((s) => s.streamingContent.get(agentId));
  const select = useExecutionStore((s) => s.select);
  const [expanded, setExpanded] = useState(defaultExpanded);

  // Targeted selector — only re-renders when this agent's approval status changes
  const hasApprovalRequired = useExecutionStore((s) => {
    for (const [, tc] of s.toolCalls) {
      if (tc.agent_execution_id === agentId && tc.approval_required) return true;
    }
    return false;
  });

  if (!agent) return null;

  const borderColor = STATUS_COLORS[agent.status] ?? STATUS_COLORS.pending;
  const model = agent.agent_config_snapshot?.agent?.model;
  const regionId = `agent-detail-${agentId}`;
  const totalTokens = agent.total_tokens ?? 0;
  const isStreaming = streaming && !streaming.done;
  const hasInputData = agent.input_data != null && Object.keys(agent.input_data).length > 0;
  const hasOutputData = agent.output_data != null && Object.keys(agent.output_data).length > 0;
  const hasReasoning = !!agent.reasoning;
  const hasOutput = !!agent.output;
  const isFailed = agent.status === 'failed';

  return (
    <div
      className={cn(
        'rounded-lg border transition-all',
        isFailed ? 'border-red-300 bg-red-50 dark:border-red-900/50 dark:bg-red-950/20' : 'border-temper-border/50 bg-temper-panel/50',
        expanded && 'shadow-md',
      )}
    >
      {/* Collapsed row — always visible */}
      <button
        className={cn(
          'w-full flex items-center gap-3 px-4 py-2.5 text-left',
          'hover:bg-temper-surface/50 transition-colors rounded-lg',
        )}
        onClick={() => setExpanded(!expanded)}
        aria-expanded={expanded}
        aria-controls={regionId}
      >
        {/* Expand chevron */}
        <span
          className={cn(
            'text-xs text-temper-text-muted transition-transform shrink-0',
            expanded && 'rotate-90',
          )}
        >
          &#9654;
        </span>

        {/* Status indicator */}
        <span
          className="w-2 h-2 rounded-full shrink-0"
          style={{ backgroundColor: borderColor }}
          title={agent.status}
        />

        {/* Agent name */}
        <span className="text-sm font-medium text-temper-text truncate min-w-0">
          {agent.agent_name ?? agent.name ?? agentId}
        </span>

        {/* Badges */}
        <div className="flex items-center gap-1.5 shrink-0">
          {model && (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-temper-surface text-temper-text-muted">
              {model}
            </span>
          )}
          {agent.role && (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-temper-surface text-temper-text-muted">
              {agent.role}
            </span>
          )}
          {agent.confidence_score != null && (
            <span
              className={cn(
                'text-[10px] px-1.5 py-0.5 rounded font-mono',
                agent.confidence_score >= 0.8
                  ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-400'
                  : agent.confidence_score >= 0.5
                    ? 'bg-amber-100 text-amber-700 dark:bg-amber-950/50 dark:text-amber-400'
                    : 'bg-red-100 text-red-700 dark:bg-red-950/50 dark:text-red-400',
              )}
            >
              {(agent.confidence_score * 100).toFixed(0)}%
            </span>
          )}
          {hasApprovalRequired && (
            <span
              className="text-[10px] px-1.5 py-0.5 rounded bg-amber-100 text-amber-700 border border-amber-300 dark:bg-amber-950/50 dark:text-amber-400 dark:border-amber-900/50"
              title="Has tool calls requiring approval"
            >
              !
            </span>
          )}
          {isStreaming && (
            <span className="w-2 h-2 rounded-full bg-temper-accent animate-pulse shrink-0" />
          )}
        </div>

        {/* Metrics — right-aligned */}
        <div className="flex items-center gap-3 ml-auto text-[11px] text-temper-text-muted shrink-0">
          <span>{formatDuration(agent.duration_seconds)}</span>
          <span>{formatTokens(totalTokens)} tok</span>
          {agent.total_llm_calls > 0 && <span>{agent.total_llm_calls} llm</span>}
          {agent.total_tool_calls > 0 && <span>{agent.total_tool_calls} tool</span>}
          <span>{formatCost(agent.estimated_cost_usd)}</span>
        </div>
      </button>

      {/* Expanded content — 3-pane layout */}
      {expanded && (
        <div id={regionId} role="region" aria-label={`Details for ${agent.agent_name ?? agentId}`} className="border-t border-temper-border/30">
          {/* Error banner for failed agents */}
          {isFailed && agent.error_message && (
            <div className="mx-4 mt-3 px-3 py-2 rounded-md bg-red-50 text-sm text-red-700 border border-red-200 dark:bg-red-950/40 dark:text-red-400 dark:border-red-900/50">
              <span className="font-medium">Error: </span>
              {agent.error_message}
            </div>
          )}

          {/* Three-pane grid */}
          <div className="grid grid-cols-3 gap-3 p-4">
            {/* Pane 1: Input */}
            <div className="flex flex-col gap-1.5 min-w-0">
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-temper-text-muted">Input</span>
              </div>
              <div className="rounded-md bg-temper-surface/70 p-2 max-h-64 overflow-y-auto">
                {hasInputData ? (
                  <JsonViewer data={agent.input_data} />
                ) : (
                  <span className="text-xs text-temper-text-dim">No input data</span>
                )}
              </div>
            </div>

            {/* Pane 2: Output */}
            <div className="flex flex-col gap-1.5 min-w-0">
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-temper-text-muted">Output</span>
                <button
                  className="text-[10px] text-temper-accent hover:underline"
                  onClick={(e) => {
                    e.stopPropagation();
                    select('agent', agentId);
                  }}
                >
                  Full details
                </button>
              </div>
              <div className="rounded-md bg-temper-surface/70 p-2 max-h-64 overflow-y-auto">
                {hasOutputData ? (
                  <JsonViewer data={agent.output_data} />
                ) : hasOutput ? (
                  <div className="text-xs text-temper-text font-mono whitespace-pre-wrap">
                    {agent.output}
                  </div>
                ) : isStreaming ? (
                  <div className="text-xs text-temper-text font-mono whitespace-pre-wrap">
                    {streaming.content}
                    <span className="inline-block w-1.5 h-3.5 bg-temper-accent animate-pulse ml-0.5" />
                  </div>
                ) : (
                  <span className="text-xs text-temper-text-dim">No output yet</span>
                )}
              </div>
            </div>

            {/* Pane 3: Reasoning */}
            <div className="flex flex-col gap-1.5 min-w-0">
              <span className="text-xs font-medium text-temper-text-muted">Reasoning</span>
              <div className="rounded-md bg-temper-surface/70 p-2 max-h-64 overflow-y-auto">
                {hasReasoning ? (
                  <div className="text-xs text-temper-text-dim font-mono whitespace-pre-wrap">
                    {agent.reasoning}
                  </div>
                ) : isStreaming && streaming.thinking ? (
                  <div className="text-xs text-temper-text-dim font-mono whitespace-pre-wrap">
                    {streaming.thinking}
                    <span className="inline-block w-1.5 h-3.5 bg-temper-accent/50 animate-pulse ml-0.5" />
                  </div>
                ) : (
                  <span className="text-xs text-temper-text-dim">No reasoning captured</span>
                )}
              </div>
            </div>
          </div>

          {/* Token distribution bar */}
          {totalTokens > 0 && (
            <div className="px-4 pb-3">
              <div className="flex items-center gap-2 text-[10px] text-temper-text-dim mb-1">
                <span>Token distribution</span>
                <span className="ml-auto">
                  {agent.prompt_tokens} prompt / {agent.completion_tokens} completion
                </span>
              </div>
              <div className="h-1.5 w-full rounded-full bg-temper-surface overflow-hidden flex">
                <div
                  className="h-full bg-temper-token-prompt"
                  style={{ width: `${(agent.prompt_tokens / totalTokens) * 100}%` }}
                />
                <div
                  className="h-full bg-temper-token-completion"
                  style={{ width: `${(agent.completion_tokens / totalTokens) * 100}%` }}
                />
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
