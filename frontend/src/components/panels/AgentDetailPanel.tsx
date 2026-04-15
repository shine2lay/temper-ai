import { useMemo } from 'react';
import { useExecutionStore } from '@/store/executionStore';
import { StatusBadge } from '@/components/shared/StatusBadge';
import { CollapsibleSection } from '@/components/shared/Collapsible';
import { JsonViewer } from '@/components/shared/JsonViewer';
import { MetricCell } from '@/components/shared/MetricCell';
import { MarkdownDisplay } from '@/components/shared/MarkdownDisplay';
import { CopyButton } from '@/components/shared/CopyButton';
import { ErrorDisplay } from '@/components/shared/ErrorDisplay';
import { SmartContent } from '@/components/shared/SmartContent';
import { ThinkingContent } from '@/components/shared/ThinkingContent';
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
  cn,
} from '@/lib/utils';
import { deriveTokenBreakdown } from '@/components/dag/constants';
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
  const { prompt: promptTokens, completion: completionTokens } = deriveTokenBreakdown(ag);
  const totalDisplay = (ag.total_tokens ?? 0) > 0 ? ag.total_tokens : (promptTokens + completionTokens);
  const totalTokens = Math.max(totalDisplay ?? 0, 1);
  const promptPct = (promptTokens / totalTokens) * 100;
  const completionPct = (completionTokens / totalTokens) * 100;

  // Derive cost from llm_calls when top-level is 0
  const cost = ag.estimated_cost_usd > 0
    ? ag.estimated_cost_usd
    : (ag.llm_calls ?? []).reduce((sum: number, c: { estimated_cost_usd?: number }) => sum + (c.estimated_cost_usd ?? 0), 0);


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

  // Find sibling iterations: stages with the same name that have an agent with the same agent_name
  const iterations = useMemo(() => {
    const parentStage = resolvedStageId ? stages.get(resolvedStageId) : null;
    if (!parentStage) return [];
    const stageName = parentStage.name ?? parentStage.stage_name;
    if (!stageName) return [];
    const agentName = ag.agent_name ?? ag.name;

    const siblings: { agentId: string; stageId: string; status: string; index: number }[] = [];
    let idx = 0;
    for (const [stageId, stage] of stages) {
      const sName = stage.name ?? stage.stage_name;
      if (sName !== stageName) continue;
      const matchingAgent = (stage.agents ?? []).find(
        (a) => (a.agent_name ?? a.name) === agentName,
      ) ?? (stage.agent && (stage.agent.agent_name ?? stage.agent.name) === agentName ? stage.agent : null);
      if (matchingAgent) {
        siblings.push({ agentId: matchingAgent.id, stageId, status: matchingAgent.status, index: idx });
        idx++;
      }
    }
    // Sort by start_time
    siblings.sort((a, b) => {
      const sa = stages.get(a.stageId)?.start_time ?? '';
      const sb = stages.get(b.stageId)?.start_time ?? '';
      return sa < sb ? -1 : sa > sb ? 1 : 0;
    });
    return siblings;
  }, [ag, agentId, resolvedStageId, stages]);

  const hasMultipleRuns = iterations.length > 1;

  const STATUS_DOT: Record<string, string> = {
    completed: 'bg-emerald-400',
    running: 'bg-temper-accent animate-pulse',
    failed: 'bg-red-400',
    pending: 'bg-gray-500',
  };

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

      {/* Iteration timeline strip */}
      {hasMultipleRuns && (
        <div className="flex items-center gap-1 p-2 bg-temper-surface/50 rounded-lg border border-temper-border/30">
          <span className="text-[10px] text-temper-text-dim mr-1 shrink-0">Runs:</span>
          {iterations.map((it, i) => (
            <button
              key={it.agentId}
              onClick={() => select('agent', it.agentId)}
              className={cn(
                'flex items-center gap-1.5 px-2 py-1 rounded text-[10px] transition-colors',
                it.agentId === agentId
                  ? 'bg-temper-accent/20 text-temper-accent ring-1 ring-temper-accent/40'
                  : 'text-temper-text-muted hover:text-temper-text hover:bg-temper-surface',
              )}
            >
              <span className={cn('w-2 h-2 rounded-full shrink-0', STATUS_DOT[it.status] ?? STATUS_DOT.pending)} />
              <span>#{i + 1}</span>
            </button>
          ))}
        </div>
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
        <MetricCell label="Prompt Tokens" value={formatTokens(promptTokens)} compact />
        <MetricCell label="Completion Tokens" value={formatTokens(completionTokens)} compact />
        <MetricCell label="Total Tokens" value={formatTokens(totalDisplay)} compact />
        <MetricCell label="Cost" value={formatCost(cost)} compact />
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
              Prompt {formatTokens(promptTokens)}
            </span>
            <span className="flex items-center gap-1">
              <span className="inline-block size-2 rounded-full bg-temper-token-completion" />
              Completion {formatTokens(completionTokens)}
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

      {/* System Prompt — the most important context for understanding agent behavior */}
      {config?.system_prompt && (
        <CollapsibleSection title="System Prompt" defaultOpen>
          <SmartContent content={config.system_prompt} maxHeight={200} className="mt-1" />
        </CollapsibleSection>
      )}

      {/* Task Template — what the agent was actually told to do */}
      {config?.task_template && (
        <CollapsibleSection title="Task Template" defaultOpen>
          <SmartContent content={config.task_template} maxHeight={200} className="mt-1" />
        </CollapsibleSection>
      )}

      {/* Collapsible sections */}
      <CollapsibleSection title="Input Data">
        <JsonViewer data={ag.input_data} />
      </CollapsibleSection>

      <CollapsibleSection title="Output">
        {ag.output && (
          ag.output.includes('<think>') ? (
            <ThinkingContent
              content={ag.output}
              className="mt-1 max-h-[400px] overflow-auto"
              renderContent={(text, key) => <SmartContent key={key} content={text} maxHeight={400} />}
            />
          ) : (
            <SmartContent content={ag.output} maxHeight={400} className="mt-1" />
          )
        )}
        {ag.output_data && Object.keys(ag.output_data).length > 0 && (
          <div className={ag.output ? 'mt-3 pt-3 border-t border-temper-border/30' : ''}>
            <span className="text-[10px] text-temper-text-muted uppercase tracking-wide block mb-1">Structured Output</span>
            <SmartContent content={JSON.stringify(ag.output_data, null, 2)} maxHeight={400} />
          </div>
        )}
        {!ag.output && (!ag.output_data || Object.keys(ag.output_data).length === 0) && (
          <span className="text-xs text-temper-text-dim">No output</span>
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
          {ag.llm_calls.map((llm, idx) => {
            const hasToolCalls = llm.tool_calls && llm.tool_calls.length > 0;
            const hasThinking = !!llm.thinking;
            return (
              <Button
                key={llm.id}
                variant="ghost"
                size="sm"
                className="justify-between text-left h-auto py-1.5"
                onClick={() => select('llmCall', llm.id)}
              >
                <span className="flex items-center gap-2 text-temper-text min-w-0">
                  <span className="text-[10px] text-temper-text-dim shrink-0 w-4">#{idx + 1}</span>
                  <span className="truncate text-xs">{llm.model ?? 'llm'}</span>
                  {hasToolCalls && (
                    <span className="text-[9px] px-1 py-px rounded bg-amber-500/15 text-amber-400 shrink-0">
                      {llm.tool_calls!.length} tool{llm.tool_calls!.length > 1 ? 's' : ''}
                    </span>
                  )}
                  {hasThinking && (
                    <span className="text-[9px] px-1 py-px rounded bg-violet-500/15 text-violet-400 shrink-0">
                      thinking
                    </span>
                  )}
                  <span className="text-[10px] text-temper-text-dim shrink-0 font-mono">
                    {formatTokens(llm.total_tokens)} tok
                  </span>
                  {(llm.estimated_cost_usd ?? 0) > 0 && (
                    <span className="text-[10px] text-emerald-400 shrink-0 font-mono">
                      {formatCost(llm.estimated_cost_usd)}
                    </span>
                  )}
                  {llm.duration_seconds != null && (
                    <span className="text-[10px] text-temper-text-dim shrink-0">
                      {formatDuration(llm.duration_seconds)}
                    </span>
                  )}
                </span>
                <StatusBadge status={llm.status} />
              </Button>
            );
          })}
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
              className="justify-between text-left h-auto py-1.5"
              onClick={() => select('toolCall', tool.id)}
            >
              <span className="flex items-center gap-2 text-temper-text min-w-0">
                <span className="text-xs font-medium text-amber-400">{tool.tool_name}</span>
                {tool.duration_seconds != null && (
                  <span className="text-[10px] text-temper-text-dim shrink-0">
                    {formatDuration(tool.duration_seconds)}
                  </span>
                )}
                {tool.input_data && (
                  <span className="text-[10px] text-temper-text-dim truncate max-w-[150px]">
                    {JSON.stringify(tool.input_data).slice(0, 50)}
                  </span>
                )}
              </span>
              <StatusBadge status={tool.status} />
            </Button>
          ))}
        </div>
      )}
    </div>
  );
}
