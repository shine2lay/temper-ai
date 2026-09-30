import { useMemo } from 'react';
import { useExecutionStore } from '@/store/executionStore';
import { useStageLookup } from '@/store/selectors';
import { StatusBadge } from '@/components/shared/StatusBadge';
import { ToolOriginBadge } from '@/components/shared/ToolOriginBadge';
import { CollapsibleSection } from '@/components/shared/Collapsible';
import { JsonViewer } from '@/components/shared/JsonViewer';
import { MetricCell } from '@/components/shared/MetricCell';
import { MarkdownDisplay } from '@/components/shared/MarkdownDisplay';
import { CopyButton } from '@/components/shared/CopyButton';
import { ErrorDisplay } from '@/components/shared/ErrorDisplay';
import { SmartContent } from '@/components/shared/SmartContent';
import { ThinkingContent } from '@/components/shared/ThinkingContent';
import { hasThinkingTags } from '@/lib/streamSegments';
import { agentDisplayName, UNNAMED_AGENT } from '@/lib/liveAgents';
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
  // Includes the nodes nested inside another node, so "Back to Stage" on an
  // agent of an inner stage opens that stage instead of an empty panel.
  const stages = useStageLookup();
  const streamEntry = useExecutionStore((s) => s.streamingContent.get(agentId));
  const isRunning = ag?.status === 'running';
  // Keep the streamed transcript visible after the agent finishes — same
  // content the live bar showed during the run, just frozen. Empties on a
  // fresh page load (chunks aren't persisted in the backend), but in-session
  // it preserves the full trace so the user can scroll back through it.
  const hasStream = !!(streamEntry && (streamEntry.content || streamEntry.thinking || (streamEntry.toolActivity?.length ?? 0) > 0));

  // Hooks before the early return below: a panel opened on an agent the
  // page had no record of yet crashed ("rendered more hooks") when the
  // record arrived.
  const stageExecutionId = ag?.stage_execution_id;
  const stageIdOfAgent = ag?.stage_id;
  const resolvedStageId = useMemo(() => {
    const direct = stageExecutionId ?? stageIdOfAgent;
    if (direct) return direct;
    for (const [stageId, stage] of Array.from(stages)) {
      if (stage.agents?.some((a) => a.id === agentId)) {
        return stageId;
      }
    }
    return undefined;
  }, [stageExecutionId, stageIdOfAgent, stages, agentId]);

  // Find sibling iterations: stages with the same name that have an agent with the same agent_name
  const iterations = useMemo(() => {
    if (!ag) return [];
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
  }, [ag, resolvedStageId, stages]);

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

  // The calls that thought, keeping each one's place in the list so the
  // section and the calls below it name the same #N.
  const thinkingCalls = (ag.llm_calls ?? [])
    .map((call, index) => ({ call, index }))
    .filter(({ call }) => !!call.thinking);

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
          {agentDisplayName(ag) ?? UNNAMED_AGENT}
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
        {(ag.round ?? 1) > 1 && (
          <Badge variant="secondary" className="text-xs">
            round {ag.round}
          </Badge>
        )}
      </div>

      {ag.summary_only && (
        <p data-testid="agent-summary-only" className="text-xs text-temper-text-muted">
          {ag.agent_name
            ? 'The page has only a summary of this agent. A new agent\'s details arrive with the next update; an earlier loop round or retried attempt keeps just this summary and what it streamed.'
            : 'The server could not say which agent this is. Its streamed output is below.'}
        </p>
      )}

      {/* Metrics grid — short values */}
      <div className="grid grid-cols-3 gap-2">
        <MetricCell label="Prompt Tokens" value={formatTokens(promptTokens)} compact />
        <MetricCell label="Completion Tokens" value={formatTokens(completionTokens)} compact />
        <MetricCell label="Total Tokens" value={formatTokens(totalDisplay)} compact />
        <MetricCell label="Cost" value={formatCost(cost)} compact />
        <MetricCell label="Duration" value={formatDuration(ag.duration_seconds)} compact />
        {/* One cell, not two: seven cells in a three-column grid left "Tool
            Calls" stranded alone on its own row. They are the same kind of
            fact, and together they make the common case a clean 2x3. */}
        <MetricCell
          label="Calls"
          value={`${ag.total_llm_calls} llm \u00b7 ${ag.total_tool_calls} tool`}
          compact
        />
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

      {/* Streamed transcript — shown while running and kept visible
          after the agent finishes so the user can read back through the
          token-by-token trace + tool calls. */}
      {hasStream && (
        <>
          <Separator />
          <div>
            <span className="mb-2 block text-sm font-medium text-temper-text-muted">
              {isRunning ? 'Live Stream' : 'Live Streamed'}
            </span>
            <StreamingPanel agentId={agentId} />
          </div>
        </>
      )}

      <Separator />

      {/* What the agent produced comes first and open: it is what someone
          opens this panel to read. The prompt and template are identical on
          every run of the agent, so they follow, collapsed — the previous
          order hid a 3,000-character answer behind a disclosure triangle
          while boilerplate filled the screen. */}
      <CollapsibleSection title="Output" defaultOpen>
        {ag.output && (
          hasThinkingTags(ag.output) ? (
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

      <CollapsibleSection title="Input Data">
        <JsonViewer data={ag.input_data} />
      </CollapsibleSection>

      {config?.system_prompt && (
        <CollapsibleSection title="System Prompt">
          <SmartContent content={config.system_prompt} maxHeight={200} className="mt-1" />
        </CollapsibleSection>
      )}

      {config?.task_template && (
        <CollapsibleSection title="Task Template">
          <SmartContent content={config.task_template} maxHeight={200} className="mt-1" />
        </CollapsibleSection>
      )}

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

      {/* Everything this agent thought, in one place.
          The badge on a call below says thinking happened; reading it meant
          opening each call in turn, which for a twenty-call agent is twenty
          round trips to find the one that went wrong. Folded by default: an
          agent that thinks is normal, and the answer stays the thing you see
          first. */}
      {thinkingCalls.length > 0 && (
        <CollapsibleSection
          title={`Thinking (${thinkingCalls.length} call${thinkingCalls.length > 1 ? 's' : ''})`}
        >
          <div className="flex flex-col gap-3" data-testid="agent-thinking">
            {thinkingCalls.map(({ call, index }) => (
              <div key={call.id} className="flex flex-col gap-1">
                <button
                  type="button"
                  className="self-start text-[10px] font-mono text-temper-text-dim hover:text-temper-text"
                  onClick={() => select('llmCall', call.id)}
                >
                  #{index + 1} {call.model ?? 'llm'} &middot; open call
                </button>
                {/* Marked as thinking wherever it is shown, and never run
                    together with the answer: what the model considered and
                    what it said are different claims. */}
                <div className="rounded bg-violet-500/10 border border-violet-500/30 p-2">
                  <MarkdownDisplay content={call.thinking!} className="text-violet-900 dark:text-violet-300/80 text-xs" />
                </div>
              </div>
            ))}
          </div>
        </CollapsibleSection>
      )}

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
                <ToolOriginBadge tool={tool} />
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
