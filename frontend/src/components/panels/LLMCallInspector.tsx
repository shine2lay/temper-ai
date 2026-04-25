import { useExecutionStore } from '@/store/executionStore';
import { SmartContent } from '@/components/shared/SmartContent';
import { ThinkingContent } from '@/components/shared/ThinkingContent';
import { StatusBadge } from '@/components/shared/StatusBadge';
import { CollapsibleSection } from '@/components/shared/Collapsible';
import { MetricCell } from '@/components/shared/MetricCell';
import { MarkdownDisplay } from '@/components/shared/MarkdownDisplay';
import { CopyButton } from '@/components/shared/CopyButton';
import { Separator } from '@/components/ui/separator';
import { formatTimestamp, formatTokens, formatCost, formatBytes, formatDuration, categorizeError } from '@/lib/utils';

interface LLMCallInspectorProps {
  llmCallId: string;
}

function PromptDisplay({ prompt }: { prompt: unknown }) {
  if (prompt == null) {
    return <p className="text-xs text-temper-text-dim">No prompt data</p>;
  }

  if (Array.isArray(prompt)) {
    return (
      <div className="mt-1 flex flex-col gap-2">
        {prompt.map((msg, i) => {
          const role =
            typeof msg === 'object' && msg !== null
              ? (msg as Record<string, unknown>).role
              : undefined;
          const content =
            typeof msg === 'object' && msg !== null
              ? (msg as Record<string, unknown>).content
              : String(msg);
          const toolCalls = typeof msg === 'object' && msg !== null
            ? (msg as Record<string, unknown>).tool_calls as Array<Record<string, unknown>> | undefined
            : undefined;
          // Guard against null/undefined content (tool-call assistant messages have no text)
          const contentStr = content == null
            ? (toolCalls ? `[Tool calls: ${toolCalls.map(tc => (tc as Record<string, unknown>).function ? ((tc as Record<string, unknown>).function as Record<string, unknown>).name : tc.name).join(', ')}]` : '')
            : (typeof content === 'string' ? content : (JSON.stringify(content, null, 2) ?? ''));
          return (
            <div key={i} className="rounded-md overflow-hidden">
              {role != null && (
                <div className="px-2 py-1 bg-temper-accent/10 text-xs font-medium text-temper-accent">
                  {String(role)}
                  {toolCalls && <span className="ml-2 text-amber-400 font-normal">{toolCalls.length} tool call{toolCalls.length !== 1 ? 's' : ''}</span>}
                </div>
              )}
              {contentStr && (
                contentStr.includes('<think>') ? (
                  <ThinkingContent
                    content={contentStr}
                    renderContent={(text, key) => <SmartContent key={key} content={text} maxHeight={300} />}
                  />
                ) : (
                  <SmartContent content={contentStr} maxHeight={300} />
                )
              )}
              {toolCalls && (
                <div className="px-2 py-1.5 bg-amber-500/5 border-t border-temper-border/20">
                  {toolCalls.map((tc, j) => {
                    const fn = (tc as Record<string, unknown>).function as Record<string, unknown> | undefined;
                    const name = fn?.name ?? tc.name ?? 'unknown';
                    const args = fn?.arguments ?? tc.arguments;
                    return (
                      <div key={j} className="text-[10px] font-mono text-amber-400 mb-0.5">
                        {String(name)}({typeof args === 'string' ? args.slice(0, 80) : JSON.stringify(args)?.slice(0, 80)})
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
      </div>
    );
  }

  const str = typeof prompt === 'string' ? prompt : JSON.stringify(prompt, null, 2);
  return <SmartContent content={str} maxHeight={300} className="mt-1" />;
}

function promptToString(prompt: unknown): string {
  if (prompt == null) return '';
  if (typeof prompt === 'string') return prompt;
  return JSON.stringify(prompt, null, 2);
}

function TokenBar({
  promptTokens,
  completionTokens,
  totalTokens,
}: {
  promptTokens: number;
  completionTokens: number;
  totalTokens: number;
}) {
  const total = Math.max(totalTokens, 1);
  const promptPct = (promptTokens / total) * 100;
  const completionPct = (completionTokens / total) * 100;

  return (
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
  );
}

export function LLMCallInspector({ llmCallId }: LLMCallInspectorProps) {
  const llmCall = useExecutionStore((s) => s.llmCalls.get(llmCallId));
  const select = useExecutionStore((s) => s.select);
  const agents = useExecutionStore((s) => s.agents);
  const stages = useExecutionStore((s) => s.stages);

  if (!llmCall) {
    return (
      <div className="p-4 text-sm text-temper-text-muted">
        LLM call not found.
      </div>
    );
  }

  const parentAgent = llmCall.agent_execution_id ? agents.get(llmCall.agent_execution_id) : undefined;
  const parentStageId = parentAgent?.stage_execution_id ?? parentAgent?.stage_id;
  const parentStage = parentStageId ? stages.get(parentStageId) : undefined;

  // Derive latency from timestamps when not directly available
  let derivedDuration = llmCall.duration_seconds;
  if (derivedDuration == null && llmCall.start_time && llmCall.end_time) {
    derivedDuration = (new Date(llmCall.end_time).getTime() - new Date(llmCall.start_time).getTime()) / 1000;
  } else if (derivedDuration == null && llmCall.latency_ms != null) {
    derivedDuration = llmCall.latency_ms / 1000;
  }
  const latencyDisplay = llmCall.latency_ms != null
    ? `${llmCall.latency_ms}ms`
    : derivedDuration != null
      ? formatDuration(derivedDuration)
      : '-';

  return (
    <div className="flex flex-col gap-4 p-4">
      {/* Breadcrumb */}
      <div className="flex items-center gap-1 text-xs flex-wrap">
        {parentStage && (
          <>
            <button
              onClick={() => select('stage', parentStageId!)}
              className="text-temper-accent hover:underline"
            >
              {parentStage.stage_name ?? parentStage.name ?? parentStageId}
            </button>
            <span className="text-temper-text-dim">&gt;</span>
          </>
        )}
        {llmCall.agent_execution_id && (
          <>
            <button
              onClick={() => select('agent', llmCall.agent_execution_id!)}
              className="text-temper-accent hover:underline"
            >
              {parentAgent?.agent_name ?? parentAgent?.name ?? llmCall.agent_execution_id}
            </button>
            <span className="text-temper-text-dim">&gt;</span>
          </>
        )}
        <span className="text-temper-text-muted">
          {llmCall.provider && llmCall.model
            ? `${llmCall.provider}/${llmCall.model}`
            : llmCall.model ?? 'LLM Call'}
        </span>
      </div>

      {/* Header */}
      <div className="flex flex-wrap items-center gap-2 sticky top-0 z-10 bg-temper-bg pb-2">
        <h3 className="text-lg font-semibold text-temper-text">
          {llmCall.provider && llmCall.model
            ? `${llmCall.provider}/${llmCall.model}`
            : llmCall.model ?? 'LLM Call'}
        </h3>
        <StatusBadge status={llmCall.status} />
      </div>

      {/* Metrics */}
      <div className="grid grid-cols-2 gap-3">
        <MetricCell label="Latency" value={latencyDisplay} />
        <MetricCell
          label="Total Tokens"
          value={formatTokens(llmCall.total_tokens)}
        />
        <MetricCell
          label="Prompt Tokens"
          value={formatTokens(llmCall.prompt_tokens)}
        />
        <MetricCell
          label="Completion Tokens"
          value={formatTokens(llmCall.completion_tokens)}
        />
        <MetricCell
          label="Cost"
          value={formatCost(llmCall.estimated_cost_usd)}
        />
        {llmCall.tool_calls_made != null && (
          <MetricCell
            label="Tool Calls Made"
            value={String(llmCall.tool_calls_made)}
          />
        )}
        {llmCall.prompt != null && (
          <MetricCell label="Prompt Size" value={formatBytes(new Blob([promptToString(llmCall.prompt)]).size)} />
        )}
        <MetricCell label="Start Time" value={formatTimestamp(llmCall.start_time)} />
        <MetricCell label="End Time" value={formatTimestamp(llmCall.end_time)} />
      </div>

      {/* Token bar */}
      {llmCall.total_tokens > 0 && (
        <TokenBar
          promptTokens={llmCall.prompt_tokens}
          completionTokens={llmCall.completion_tokens}
          totalTokens={llmCall.total_tokens}
        />
      )}

      {/* Error */}
      {llmCall.status === 'failed' && llmCall.error_message && (() => {
        const { type, retryable } = categorizeError(llmCall.error_message);
        return (
          <div className="rounded-md bg-temper-bg-failed p-3 text-sm text-temper-failed">
            <div className="flex items-center gap-2 mb-1">
              <span className="text-xs font-medium px-1.5 py-0.5 rounded bg-red-100 border border-red-300 dark:bg-red-950 dark:border-red-900/50">{type}</span>
              {retryable && <span className="text-xs text-amber-600 dark:text-amber-400">Retryable</span>}
            </div>
            {llmCall.error_message}
          </div>
        );
      })()}

      <Separator />

      {/* Prompt */}
      <CollapsibleSection title="Prompt" defaultOpen>
        <PromptDisplay prompt={llmCall.prompt} />
        <CopyButton text={promptToString(llmCall.prompt)} className="mt-1" />
      </CollapsibleSection>

      {/* Thinking / Reasoning */}
      {llmCall.thinking && (
        <CollapsibleSection title="Thinking" defaultOpen={false}>
          <div className="mt-1 p-2 rounded bg-violet-500/5 border border-violet-500/20 max-h-96 overflow-auto">
            <MarkdownDisplay content={llmCall.thinking} className="text-violet-300/80" />
          </div>
          <CopyButton text={llmCall.thinking} className="mt-1" />
        </CollapsibleSection>
      )}

      {/* Response */}
      <CollapsibleSection title="Response" defaultOpen>
        {llmCall.response ? (
          llmCall.response.includes('<think>') ? (
            <>
              <ThinkingContent
                content={llmCall.response}
                className="mt-1 max-h-96 overflow-auto"
                renderContent={(text, key) => <MarkdownDisplay key={key} content={text} />}
              />
              <CopyButton text={llmCall.response} className="mt-1" />
            </>
          ) : (
            <>
              <MarkdownDisplay content={llmCall.response} className="mt-1 max-h-96 overflow-auto" />
              <CopyButton text={llmCall.response} className="mt-1" />
            </>
          )
        ) : llmCall.tool_calls && llmCall.tool_calls.length > 0 ? (
          <div className="mt-1">
            <p className="text-[10px] text-temper-text-dim mb-1.5">Model issued tool calls instead of text response:</p>
            <div className="flex flex-col gap-1">
              {llmCall.tool_calls.map((tc, i) => (
                <div key={i} className="flex items-center gap-1.5 px-2 py-1 rounded bg-amber-500/10 border border-amber-500/20">
                  <span className="text-[10px] font-mono text-amber-400">{tc.name}</span>
                </div>
              ))}
            </div>
          </div>
        ) : (
          <p className="mt-1 text-xs text-temper-text-dim">No response data</p>
        )}
      </CollapsibleSection>
    </div>
  );
}
