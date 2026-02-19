import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useExecutionStore } from '@/store/executionStore';
import { StatusBadge } from '@/components/shared/StatusBadge';
import { CollapsibleSection } from '@/components/shared/Collapsible';
import { JsonViewer } from '@/components/shared/JsonViewer';
import { MetricCell } from '@/components/shared/MetricCell';
import { MarkdownDisplay } from '@/components/shared/MarkdownDisplay';
import { CopyButton } from '@/components/shared/CopyButton';
import { StreamingPanel } from '@/components/panels/StreamingPanel';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Separator } from '@/components/ui/separator';
import {
  formatDuration,
  formatTimestamp,
  formatTokens,
  formatCost,
  categorizeError,
} from '@/lib/utils';
import { AGENT_DETAIL_REFETCH_MS } from '@/lib/constants';
import type { AgentExecution } from '@/types';

interface AgentDetailPanelProps {
  agentId: string;
}

export function AgentDetailPanel({ agentId }: AgentDetailPanelProps) {
  const agent = useExecutionStore((s) => s.agents.get(agentId));
  const select = useExecutionStore((s) => s.select);
  const stages = useExecutionStore((s) => s.stages);
  const isRunning = agent?.status === 'running';

  const { data: detailAgent, isFetching, error: fetchError } = useQuery<AgentExecution>({
    queryKey: ['agent-detail', agentId],
    queryFn: async () => {
      const res = await fetch(`/api/agents/${agentId}`);
      if (!res.ok) throw new Error('Failed to fetch agent detail');
      return res.json();
    },
    refetchInterval: isRunning ? AGENT_DETAIL_REFETCH_MS : false,
    enabled: !!agentId,
  });

  const ag = detailAgent ?? agent;

  if (!ag) {
    return (
      <div className="p-4 text-sm text-temper-text-muted">Agent not found.</div>
    );
  }

  const config = ag.agent_config_snapshot?.agent;
  const totalTokens = Math.max(ag.total_tokens, 1);
  const promptPct = (ag.prompt_tokens / totalTokens) * 100;
  const completionPct = (ag.completion_tokens / totalTokens) * 100;

  const resolvedStageId = useMemo(() => {
    const direct = ag.stage_execution_id ?? ag.stage_id;
    if (direct) return direct;
    for (const [stageId, stage] of Array.from(stages)) {
      if (stage.agents?.some((a) => a.id === agentId)) {
        return stageId;
      }
    }
    return undefined;
  }, [ag.stage_execution_id, ag.stage_id, stages, agentId]);

  return (
    <div className="flex flex-col gap-4 p-4">
      {/* Breadcrumb */}
      {resolvedStageId && (
        <button
          onClick={() => select('stage', resolvedStageId)}
          className="text-xs text-temper-accent hover:underline self-start"
        >
          &larr; Back to Stage
        </button>
      )}

      {/* Header */}
      <div className="flex flex-wrap items-center gap-2 sticky top-0 z-10 bg-temper-bg pb-2">
        <h3 className="text-lg font-semibold text-temper-text">
          {ag.agent_name ?? ag.name ?? agentId}
        </h3>
        <StatusBadge status={ag.status} />
        {config?.provider && config?.model && (
          <Badge variant="secondary" className="text-xs">
            {config.provider}/{config.model}
          </Badge>
        )}
        {ag.role && (
          <Badge variant="secondary" className="text-xs">
            {ag.role}
          </Badge>
        )}
        {isFetching && (
          <div className="text-[10px] text-temper-accent animate-pulse">Refreshing...</div>
        )}
      </div>

      {/* Refetch error */}
      {fetchError && (
        <div className="text-xs text-red-400 bg-red-950/30 rounded px-2 py-1">
          Failed to refresh: {(fetchError as Error).message}
        </div>
      )}

      {/* Metrics grid */}
      <div className="grid grid-cols-2 gap-3">
        <MetricCell
          label="Prompt Tokens"
          value={formatTokens(ag.prompt_tokens)}
        />
        <MetricCell
          label="Completion Tokens"
          value={formatTokens(ag.completion_tokens)}
        />
        <MetricCell
          label="Total Tokens"
          value={formatTokens(ag.total_tokens)}
        />
        <MetricCell label="Cost" value={formatCost(ag.estimated_cost_usd)} />
        <MetricCell
          label="Duration"
          value={formatDuration(ag.duration_seconds)}
        />
        <MetricCell label="LLM Calls" value={String(ag.total_llm_calls)} />
        <MetricCell label="Tool Calls" value={String(ag.total_tool_calls)} />
        {ag.confidence_score != null && (
          <MetricCell
            label="Confidence"
            value={`${(ag.confidence_score * 100).toFixed(1)}%`}
          />
        )}
        <MetricCell label="Start Time" value={formatTimestamp(ag.start_time)} />
        <MetricCell label="End Time" value={formatTimestamp(ag.end_time)} />
      </div>

      {/* Token bar */}
      {ag.total_tokens > 0 && (
        <div className="flex flex-col gap-1">
          <span className="text-xs text-temper-text-muted">Token Distribution</span>
          <div className="flex h-3 w-full overflow-hidden rounded-full bg-temper-panel">
            <div
              className="bg-temper-token-prompt transition-all"
              style={{ width: `${promptPct}%` }}
            />
            <div
              className="bg-temper-token-completion transition-all"
              style={{ width: `${completionPct}%` }}
            />
          </div>
          <div className="flex gap-3 text-xs text-temper-text-dim">
            <span className="flex items-center gap-1">
              <span className="inline-block size-2 rounded-full bg-temper-token-prompt" />
              Prompt {formatTokens(ag.prompt_tokens)}
            </span>
            <span className="flex items-center gap-1">
              <span className="inline-block size-2 rounded-full bg-temper-token-completion" />
              Completion {formatTokens(ag.completion_tokens)}
            </span>
          </div>
        </div>
      )}

      {/* Error */}
      {ag.error_message && (() => {
        const { type, retryable } = categorizeError(ag.error_message);
        return (
          <div className="rounded-md bg-temper-bg-failed p-3 text-sm text-temper-failed">
            <div className="flex items-center gap-2 mb-1">
              <span className="text-xs font-medium px-1.5 py-0.5 rounded bg-red-950 border border-red-900/50">{type}</span>
              {retryable && <span className="text-xs text-amber-400">Retryable</span>}
            </div>
            {ag.error_message}
          </div>
        );
      })()}

      {/* Streaming panel when running */}
      {isRunning && (
        <>
          <Separator />
          <div>
            <span className="mb-2 block text-sm font-medium text-temper-text-muted">
              Live Stream
            </span>
            <StreamingPanel agentId={agentId} />
          </div>
        </>
      )}

      <Separator />

      {/* Collapsible sections */}
      <CollapsibleSection title="Input Data">
        <JsonViewer data={ag.input_data} />
      </CollapsibleSection>

      <CollapsibleSection title="Output">
        {ag.output ? (
          <>
            <MarkdownDisplay content={ag.output} className="mt-1 max-h-64 overflow-auto" />
            <CopyButton text={ag.output} className="mt-1" />
          </>
        ) : (
          <JsonViewer data={ag.output_data} />
        )}
      </CollapsibleSection>

      {ag.reasoning && (
        <CollapsibleSection title="Reasoning">
          <MarkdownDisplay content={ag.reasoning} className="mt-1 max-h-64 overflow-auto" />
          <CopyButton text={ag.reasoning} className="mt-1" />
        </CollapsibleSection>
      )}

      {config && (
        <CollapsibleSection title="Agent Config">
          <JsonViewer data={ag.agent_config_snapshot} />
        </CollapsibleSection>
      )}

      <Separator />

      {/* LLM calls list */}
      {ag.llm_calls && ag.llm_calls.length > 0 && (
        <div className="flex flex-col gap-2">
          <span className="text-sm font-medium text-temper-text-muted">
            LLM Calls
          </span>
          {ag.llm_calls.map((llm) => (
            <Button
              key={llm.id}
              variant="ghost"
              size="sm"
              className="justify-between text-left"
              onClick={() => select('llmCall', llm.id)}
            >
              <span className="flex items-center gap-2 text-temper-text">
                <span className="truncate text-xs">
                  {llm.model ?? llm.llm_call_id ?? llm.id}
                </span>
              </span>
              <StatusBadge status={llm.status} />
            </Button>
          ))}
        </div>
      )}

      {/* Tool calls list */}
      {ag.tool_calls && ag.tool_calls.length > 0 && (
        <div className="flex flex-col gap-2">
          <span className="text-sm font-medium text-temper-text-muted">
            Tool Calls
          </span>
          {ag.tool_calls.map((tool) => (
            <Button
              key={tool.id}
              variant="ghost"
              size="sm"
              className="justify-between text-left"
              onClick={() => select('toolCall', tool.id)}
            >
              <span className="text-xs text-temper-text">{tool.tool_name}</span>
              <StatusBadge status={tool.status} />
            </Button>
          ))}
        </div>
      )}
    </div>
  );
}
