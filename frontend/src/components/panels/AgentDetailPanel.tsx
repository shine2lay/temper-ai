import { useMemo } from 'react';
import { useExecutionStore } from '@/store/executionStore';
import { StatusBadge } from '@/components/shared/StatusBadge';
import { CollapsibleSection } from '@/components/shared/Collapsible';
import { JsonViewer } from '@/components/shared/JsonViewer';
import { MetricCell } from '@/components/shared/MetricCell';
import { MarkdownDisplay } from '@/components/shared/MarkdownDisplay';
import { CopyButton } from '@/components/shared/CopyButton';
import { ErrorDisplay } from '@/components/shared/ErrorDisplay';
import { EmptyState } from '@/components/shared/EmptyState';
import { StreamingPanel } from '@/components/panels/StreamingPanel';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Separator } from '@/components/ui/separator';
import {
  formatDuration,
  formatTimestamp,
  formatTokens,
  formatCost,
} from '@/lib/utils';
// Agent data comes from the Zustand store (updated via WebSocket + snapshot polling)

interface AgentDetailPanelProps {
  agentId: string;
}

export function AgentDetailPanel({ agentId }: AgentDetailPanelProps) {
  const ag = useExecutionStore((s) => s.agents.get(agentId));
  const select = useExecutionStore((s) => s.select);
  const stages = useExecutionStore((s) => s.stages);
  const isRunning = ag?.status === 'running';

  if (!ag) {
    return <EmptyState title="Agent not found" />;
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
        {config?.type && config.type !== 'standard' && (
          <Badge variant="secondary" className="text-xs">
            {config.type}
          </Badge>
        )}
        {ag.role && (
          <Badge variant="secondary" className="text-xs">
            {ag.role}
          </Badge>
        )}
      </div>

      {/* Metrics grid — short values */}
      <div className="grid grid-cols-3 gap-2">
        <MetricCell label="Prompt Tokens" value={formatTokens(ag.prompt_tokens)} compact />
        <MetricCell label="Completion Tokens" value={formatTokens(ag.completion_tokens)} compact />
        <MetricCell label="Total Tokens" value={formatTokens(ag.total_tokens)} compact />
        <MetricCell label="Cost" value={formatCost(ag.estimated_cost_usd)} compact />
        <MetricCell label="Duration" value={formatDuration(ag.duration_seconds)} compact />
        <MetricCell label="LLM Calls" value={String(ag.total_llm_calls)} compact />
        <MetricCell label="Tool Calls" value={String(ag.total_tool_calls)} compact />
        {ag.confidence_score != null && (
          <MetricCell label="Confidence" value={`${(ag.confidence_score * 100).toFixed(1)}%`} compact />
        )}
      </div>

      {/* Metrics grid — timestamps */}
      <div className="grid grid-cols-2 gap-2">
        <MetricCell label="Start Time" value={formatTimestamp(ag.start_time)} compact />
        <MetricCell label="End Time" value={formatTimestamp(ag.end_time)} compact />
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
      {ag.error_message && <ErrorDisplay error={ag.error_message} />}

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

      {(config?.inputs || config?.outputs) && (
        <CollapsibleSection title="Declared I/O">
          {config?.inputs && (
            <div className="mb-2">
              <span className="text-[10px] font-medium text-temper-text-muted uppercase tracking-wide block mb-1">Inputs</span>
              <div className="rounded-md border border-temper-border bg-temper-panel overflow-hidden">
                <table className="w-full text-xs">
                  <tbody>
                    {Object.entries(config.inputs).map(([name, decl]) => (
                      <tr key={name} className="border-b border-temper-border/30 last:border-b-0">
                        <td className="px-3 py-1 text-temper-text font-medium">{name}</td>
                        <td className="px-3 py-1 text-temper-text-muted font-mono">{(decl as Record<string, unknown>)?.type as string}</td>
                        <td className="px-3 py-1 text-temper-text-dim">{(decl as Record<string, unknown>)?.required ? 'required' : 'optional'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
          {config?.outputs && (
            <div>
              <span className="text-[10px] font-medium text-temper-text-muted uppercase tracking-wide block mb-1">Outputs</span>
              <div className="rounded-md border border-temper-border bg-temper-panel overflow-hidden">
                <table className="w-full text-xs">
                  <tbody>
                    {Object.entries(config.outputs).map(([name, decl]) => (
                      <tr key={name} className="border-b border-temper-border/30 last:border-b-0">
                        <td className="px-3 py-1 text-temper-text font-medium">{name}</td>
                        <td className="px-3 py-1 text-temper-text-muted font-mono">{(decl as Record<string, unknown>)?.type as string}</td>
                        <td className="px-3 py-1 text-temper-text-dim">{((decl as Record<string, unknown>)?.description ?? '') as string}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
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
