import { memo, useState, useMemo } from 'react';
import { useExecutionStore } from '@/store/executionStore';
import { STATUS_COLORS, deriveTokenBreakdown } from './constants';
import { cn, formatDuration, formatTokens, formatCost } from '@/lib/utils';
import { SmartContent } from '@/components/shared/SmartContent';
import type { AgentExecution } from '@/types';

/**
 * Build a map of stage name → primary agent name for single-agent stages.
 * Used to show agent names in source tags instead of confusing stage names.
 */
function useStageToAgentMap(): Map<string, string> {
  const stages = useExecutionStore((s) => s.stages);
  return useMemo(() => {
    const map = new Map<string, string>();
    for (const [, stage] of stages) {
      const agents = stage.agents ?? [];
      if (agents.length === 1 && agents[0]) {
        const agentName = agents[0].agent_name ?? agents[0].name ?? '';
        if (agentName && stage.name && stage.name !== agentName) {
          map.set(stage.name, agentName);
        }
      }
    }
    return map;
  }, [stages]);
}

interface AgentCardContentProps {
  agent: AgentExecution;
  /** Border color (from stage palette). */
  borderColor?: string;
  /** Whether this is inside a stage container (slightly different styling). */
  nested?: boolean;
}

/**
 * Shared agent card content — used by both AgentNodeComponent (standalone)
 * and StageNode (nested inside stage container). Ensures visual consistency.
 *
 * Shows: status dot, agent name, metrics, output preview.
 */
export const AgentCardContent = memo(function AgentCardContent({
  agent,
  borderColor,
  nested = false,
}: AgentCardContentProps) {
  const select = useExecutionStore((s) => s.select);
  const streaming = useExecutionStore((s) => s.streamingContent.get(agent.id));
  const [outputExpanded, setOutputExpanded] = useState(false);
  const [inputExpanded, setInputExpanded] = useState(false);

  const statusColor = STATUS_COLORS[agent.status] ?? STATUS_COLORS.pending;
  const isStreaming = streaming && !streaming.done;
  const textOutput = isStreaming ? streaming.content : agent.output ?? '';
  // Derive structured output from text if API doesn't provide it
  const derivedOutputData = useMemo(() => {
    if (agent.output_data && Object.keys(agent.output_data).length > 0) return agent.output_data;
    if (!textOutput) return null;
    try {
      const parsed = JSON.parse(textOutput.trim());
      return typeof parsed === 'object' && parsed !== null ? parsed : null;
    } catch { return null; }
  }, [agent.output_data, textOutput]);
  const hasOutputData = derivedOutputData != null;
  const output = textOutput || (hasOutputData ? JSON.stringify(derivedOutputData, null, 2) : '');
  const hasOutput = output.length > 0;
  const agentName = agent.agent_name ?? agent.name ?? 'agent';

  const totalTokens = agent.total_tokens ?? 0;
  const cost = agent.estimated_cost_usd ?? 0;
  const duration = agent.duration_seconds ?? 0;
  const { prompt: promptTokens, completion: completionTokens } = deriveTokenBreakdown(agent);
  const configSnapshot = agent.agent_config_snapshot?.agent;
  const model = configSnapshot?.model;
  const provider = configSnapshot?.provider;

  const tools = configSnapshot?.tools as string[] | undefined;
  const hasMem = configSnapshot?.memory && (configSnapshot.memory as Record<string, boolean>)?.enabled;
  const llmCalls = agent.total_llm_calls ?? 0;
  const toolCalls = agent.total_tool_calls ?? 0;
  const showCost = cost > 0;

  const isFailed = agent.status === 'failed';
  const isRunning = agent.status === 'running';
  // Detect script agents: check config snapshot type, or infer when no LLM activity at all
  const isScript = configSnapshot?.type === 'script'
    || (!model && !provider && totalTokens === 0 && llmCalls === 0 && duration > 0 && !isRunning);

  return (
    <div
      className={cn(
        'rounded-lg transition-all cursor-pointer',
        nested
          ? 'border border-temper-border/40 hover:border-temper-border'
          : 'border-2 shadow-sm hover:shadow-md',
        isRunning && 'dag-node-running',
        isFailed ? 'bg-red-500/5' : 'bg-temper-panel',
      )}
      style={!nested ? {
        borderColor: isFailed ? '#ef4444' : borderColor,
        ...(isRunning && borderColor ? { '--glow-color': borderColor } as React.CSSProperties : {}),
      } : undefined}
      onClick={() => select('agent', agent.id)}
    >
      {/* Header: status dot + name + model badge */}
      <div className={cn(
        'flex items-center gap-1.5 px-2.5 py-1.5 border-b border-temper-border/20',
        isFailed && 'bg-red-500/8 rounded-t-md',
      )}>
        <span
          className="w-2 h-2 rounded-full shrink-0"
          style={{ backgroundColor: statusColor }}
        />
        <span className={cn('text-[13px] font-semibold truncate', isFailed ? 'text-red-400' : 'text-temper-text')}>
          {agentName}
        </span>
        {isFailed && (
          <span className="text-[9px] px-1 py-px rounded bg-red-500/15 text-red-400 font-medium shrink-0">FAILED</span>
        )}
        {isStreaming && (
          <span className="text-[9px] px-1 py-px rounded bg-blue-500/15 text-blue-400 font-medium shrink-0 animate-pulse">streaming</span>
        )}
        <span className="ml-auto flex items-center gap-1 shrink-0">
          {isScript ? (
            <span className="text-[8px] px-1 py-px rounded bg-amber-500/15 text-amber-400 font-medium">script</span>
          ) : model ? (
            <span className="text-[8px] px-1 py-px rounded bg-temper-surface text-temper-text-dim font-mono"
                  title={provider ? `${provider}/${model}` : model}>
              {provider ? `${provider}` : ''}{provider && model ? '/' : ''}{model}
            </span>
          ) : null}
        </span>
      </div>

      {/* Dense metrics + config row — different for script vs LLM agents */}
      <div className="flex items-center gap-1.5 px-2.5 py-1 text-[10px] text-temper-text-muted flex-wrap">
        {isScript ? (
          <>
            {/* Script agent: duration + exit status, no tokens */}
            <span className="font-mono font-medium text-temper-text">{formatDuration(duration)}</span>
            {isFailed && agent.error_message && (
              <>
                <span className="text-temper-border/40">|</span>
                <span className="text-red-400 truncate max-w-[150px]">{agent.error_message.slice(0, 60)}</span>
              </>
            )}
            {!isFailed && (
              <>
                <span className="text-temper-border/40">|</span>
                <span className="text-emerald-400">exit 0</span>
              </>
            )}
            {configSnapshot?.timeout_seconds && (
              <>
                <span className="text-temper-border/40">|</span>
                <span>timeout {configSnapshot.timeout_seconds}s</span>
              </>
            )}
          </>
        ) : (
          <>
            {/* LLM agent: tokens + cost + llm/tool calls */}
            {promptTokens > 0 && (
              <span className="font-mono" style={{ color: 'var(--color-temper-token-prompt)' }}>{formatTokens(promptTokens)}p</span>
            )}
            {completionTokens > 0 && (
              <span className="font-mono" style={{ color: 'var(--color-temper-token-completion)' }}>{formatTokens(completionTokens)}c</span>
            )}
            <span className="font-mono font-medium text-temper-text">{formatTokens(totalTokens)}<span className="text-temper-text-dim"> tok</span></span>
            <span className="text-temper-border/40">|</span>
            <span>{formatDuration(duration)}</span>
            {showCost && (
              <>
                <span className="text-temper-border/40">|</span>
                <span className="text-emerald-400">{formatCost(cost)}</span>
              </>
            )}
            {llmCalls > 0 && (
              <>
                <span className="text-temper-border/40">|</span>
                <span>{llmCalls} llm</span>
              </>
            )}
            {toolCalls > 0 && (
              <>
                <span className="text-temper-border/40">|</span>
                <span className="text-amber-400">{toolCalls} tools</span>
              </>
            )}
            {tools && tools.length > 0 && (
              <>
                <span className="text-temper-border/40">|</span>
                {tools.map((t) => (
                  <span key={t} className="px-1 py-px rounded bg-amber-500/10 text-amber-400 text-[8px] font-mono">{t}</span>
                ))}
              </>
            )}
            {hasMem && <span title="Memory enabled" className="text-[9px]">🧠</span>}
          </>
        )}
      </div>

      {/* Token breakdown bar — LLM agents only */}
      {!isScript && totalTokens > 0 && promptTokens > 0 && (
        <div className="px-2.5 pb-1">
          <div
            className="h-1 w-full rounded-full bg-temper-surface overflow-hidden flex"
            title={`Prompt: ${formatTokens(promptTokens)} | Completion: ${formatTokens(completionTokens)}`}
          >
            <div className="h-full bg-temper-token-prompt" style={{ width: `${(promptTokens / totalTokens) * 100}%` }} />
            <div className="h-full bg-temper-token-completion" style={{ width: `${(completionTokens / totalTokens) * 100}%` }} />
          </div>
        </div>
      )}

      {/* Input: source tags + preview */}
      {agent.input_data && Object.keys(agent.input_data).length > 0 && (
        <div
          className="px-2.5 py-1 border-t border-temper-border/20 cursor-pointer"
          onClick={(e) => { e.stopPropagation(); setInputExpanded(!inputExpanded); }}
        >
          <InputSection data={agent.input_data} expanded={inputExpanded} />
        </div>
      )}

      {/* Output: type signal + preview */}
      {(hasOutput || isFailed) && (
        <div
          className="px-2.5 py-1 border-t border-temper-border/20 cursor-pointer"
          onClick={(e) => { e.stopPropagation(); setOutputExpanded(!outputExpanded); }}
        >
          <OutputSection output={output} error={agent.error_message} expanded={outputExpanded} />
        </div>
      )}
    </div>
  );
});


/** Parse upstream sources from other_agents string into name→preview pairs. */
function parseSourcePreviews(otherAgents: string): Array<{ name: string; preview: string }> {
  const results: Array<{ name: string; preview: string }> = [];
  // Split on [name]: markers
  const regex = /\[([^\]]+)\]:\s*/g;
  const markers: Array<{ name: string; start: number }> = [];
  let match;
  while ((match = regex.exec(otherAgents)) !== null) {
    markers.push({ name: match[1], start: match.index + match[0].length });
  }
  for (let i = 0; i < markers.length; i++) {
    const end = i + 1 < markers.length ? markers[i + 1].start - markers[i + 1].name.length - 3 : otherAgents.length;
    const content = otherAgents.slice(markers[i].start, end).trim();
    // Smart preview: detect JSON keys or first meaningful line
    let preview = '';
    const trimmed = content.trim();
    if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
      try {
        const parsed = JSON.parse(trimmed);
        if (typeof parsed === 'object' && parsed !== null && !Array.isArray(parsed)) {
          preview = `{${Object.keys(parsed).join(', ')}}`;
        } else if (Array.isArray(parsed)) {
          preview = `[${parsed.length} items]`;
        }
      } catch { /* not valid JSON, use text preview */ }
    }
    if (!preview) {
      const firstLine = trimmed.split('\n').find(l => l.trim().length > 2 && l.trim() !== '{') ?? '';
      preview = firstLine.slice(0, 60);
      if (firstLine.length > 60) preview += '...';
    }
    results.push({ name: markers[i].name, preview });
  }
  return results;
}

/** Input section — show per-source previews so you can see what each upstream produced. */
function InputSection({ data, expanded }: { data: Record<string, unknown>; expanded: boolean }) {
  const stageToAgent = useStageToAgentMap();
  const otherAgents = data.other_agents;
  const prevOutput = data.previous_output;
  const task = data.task;

  // Parse per-source previews from other_agents
  const sourcePreviews = otherAgents && typeof otherAgents === 'string'
    ? parseSourcePreviews(otherAgents)
    : [];
  const hasPrev = prevOutput != null;

  // Detect non-standard input keys as sources (when no other_agents string)
  const knownKeys = new Set(['task', 'other_agents', 'previous_output', 'workspace_path']);
  const extraSources = sourcePreviews.length === 0 && !hasPrev
    ? Object.keys(data).filter(k => !knownKeys.has(k))
    : [];
  const isWorkflowOnly = sourcePreviews.length === 0 && !hasPrev && extraSources.length === 0 && task;

  return (
    <div className="flex flex-col gap-0.5">
      {/* Source tags with previews */}
      <div className="flex items-start gap-1 flex-wrap">
        <span className="text-[9px] font-semibold text-temper-text-muted shrink-0 mt-0.5">
          {expanded ? '\u25BE' : '\u25B8'} IN
        </span>
        {isWorkflowOnly && (
          <span className="text-[8px] px-1.5 py-0.5 rounded bg-blue-500/15 text-blue-400 font-medium">
            ← workflow input
          </span>
        )}
        {sourcePreviews.map((s) => {
          // Resolve stage name to agent name for single-agent stages
          const agentName = stageToAgent.get(s.name);
          const displayName = agentName ?? s.name;
          return (
          <span key={s.name} className="inline-flex flex-col gap-px max-w-full">
            <span className="text-[8px] px-1.5 py-0.5 rounded-t bg-blue-500/15 text-blue-400 font-medium">
              ← {displayName}
            </span>
            {s.preview && (
              <span className="text-[8px] px-1.5 py-0.5 rounded-b bg-temper-surface/50 text-temper-text-dim font-mono truncate">
                {s.preview}
              </span>
            )}
          </span>
        );
        })}
        {hasPrev && (
          <span className="text-[8px] px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-400 font-medium">
            ← prev agent
          </span>
        )}
        {extraSources.map((key) => {
          const agentName = stageToAgent.get(key.replace(/_output$/, ''));
          return (
            <span key={key} className="text-[8px] px-1.5 py-0.5 rounded bg-blue-500/15 text-blue-400 font-medium">
              ← {agentName ?? key}
            </span>
          );
        })}
      </div>
      {/* Expanded: smart formatted view */}
      {expanded && (
        <div className="mt-0.5">
          <SmartContent content={(() => { try { return JSON.stringify(data, null, 2); } catch { return String(data); } })()} maxHeight={160} compact />
        </div>
      )}
    </div>
  );
}

/** Output section — smart preview based on output type. */
function OutputSection({ output, error, expanded }: { output: string; error?: string | null; expanded: boolean }) {
  const [copied, setCopied] = useState(false);

  function handleCopy(e: React.MouseEvent) {
    e.stopPropagation();
    navigator.clipboard.writeText(output).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  }
  const trimmed = output.trim();
  const isJson = trimmed.startsWith('{') || trimmed.startsWith('[');
  const isCode = trimmed.startsWith('```') || trimmed.startsWith('import ') || trimmed.startsWith('def ') || trimmed.startsWith('function ');
  const typeLabel = isJson ? 'json' : isCode ? 'code' : 'text';
  const sizeLabel = output.length > 1000
    ? `${(output.length / 1000).toFixed(1)}K`
    : `${output.length}`;

  // Smart preview: for JSON show top-level keys, for text/code show first meaningful line
  let preview = '';
  if (!expanded) {
    if (isJson) {
      try {
        const parsed = JSON.parse(trimmed);
        if (typeof parsed === 'object' && parsed !== null && !Array.isArray(parsed)) {
          const keys = Object.keys(parsed);
          preview = `{${keys.join(', ')}}`;
        } else if (Array.isArray(parsed)) {
          preview = `[${parsed.length} items]`;
        } else {
          preview = trimmed.slice(0, 100);
        }
      } catch {
        preview = trimmed.slice(0, 100);
      }
    } else {
      // For text/code, find first non-empty line that isn't just a bracket or backticks
      const lines = trimmed.split('\n');
      const meaningful = lines.find((l) => {
        const t = l.trim();
        return t.length > 2 && t !== '```' && t !== '{' && t !== '[';
      }) ?? lines[0] ?? '';
      preview = meaningful.length > 100 ? meaningful.slice(0, 100) + '...' : meaningful;
    }
  }

  if (error && !output) {
    return (
      <div className="flex items-center gap-1">
        <span className="text-[9px] font-semibold text-red-400">ERR</span>
        <span className="text-[9px] text-red-400/80 truncate">{error.slice(0, 80)}</span>
      </div>
    );
  }

  if (!output) return null;

  return (
    <div className="flex flex-col gap-0.5">
      {/* Type badge + key summary or preview */}
      <div className="flex items-center gap-1 min-w-0">
        <span className="text-[9px] font-semibold text-temper-text-muted shrink-0">{expanded ? '\u25BE' : '\u25B8'} OUT</span>
        <span className={cn(
          'text-[8px] px-1 py-px rounded font-mono shrink-0',
          isJson ? 'bg-emerald-500/15 text-emerald-400' :
          isCode ? 'bg-violet-500/15 text-violet-400' :
          'bg-temper-surface text-temper-text-dim',
        )}>
          {typeLabel}
        </span>
        <span className="text-[8px] text-temper-text-dim font-mono shrink-0">{sizeLabel}</span>
        {!expanded && preview && (
          <span className="text-[9px] text-temper-text-dim truncate font-mono">{preview}</span>
        )}
        {!expanded && (
          <button
            className="ml-auto w-5 h-5 flex items-center justify-center rounded text-[10px] text-temper-text-dim hover:text-temper-text hover:bg-temper-surface shrink-0 transition-colors"
            title="Copy output"
            onClick={handleCopy}
          >
            {copied ? '\u2713' : '\u2398'}
          </button>
        )}
      </div>
      {/* Expanded: smart formatted view */}
      {expanded && (
        <div className="mt-0.5">
          <SmartContent content={output.slice(0, 5000)} maxHeight={200} compact />
        </div>
      )}
    </div>
  );
}
