import { memo, useState } from 'react';
import { useExecutionStore } from '@/store/executionStore';
import { STATUS_COLORS, deriveTokenBreakdown } from './constants';
import { cn, formatDuration, formatTokens, formatCost } from '@/lib/utils';
import type { AgentExecution } from '@/types';

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
  const output = isStreaming ? streaming.content : agent.output ?? '';
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
          {model && (
            <span className="text-[8px] px-1 py-px rounded bg-temper-surface text-temper-text-dim font-mono"
                  title={provider ? `${provider}/${model}` : model}>
              {provider ? `${provider}` : ''}{provider && model ? '/' : ''}{model}
            </span>
          )}
        </span>
      </div>

      {/* Dense metrics + config row */}
      <div className="flex items-center gap-1.5 px-2.5 py-1 text-[10px] text-temper-text-muted flex-wrap">
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
      </div>

      {/* Token breakdown bar */}
      {totalTokens > 0 && promptTokens > 0 && (
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


/** Parse input data into source tags and a preview string. */
function InputSection({ data, expanded }: { data: Record<string, unknown>; expanded: boolean }) {
  // Extract source info from input keys
  const sources: string[] = [];
  const otherAgents = data.other_agents;
  const prevOutput = data.previous_output;
  const task = data.task;

  if (otherAgents && typeof otherAgents === 'string') {
    // Extract source names from "[source_name]:" markers
    const matches = otherAgents.match(/\[([^\]]+)\]:/g);
    if (matches) {
      for (const m of matches) sources.push(m.slice(1, -2));
    }
  }
  if (prevOutput != null) sources.push('prev agent');
  if (task && sources.length === 0) sources.push('workflow input');

  // Build preview: task first line, then a hint about other_agents
  let preview = '';
  if (task && typeof task === 'string') {
    preview = task.length > 80 ? task.slice(0, 80) + '...' : task;
  }

  if (expanded) {
    try {
      preview = JSON.stringify(data, null, 2).slice(0, 2000);
    } catch {
      preview = String(data);
    }
  }

  return (
    <div className="flex flex-col gap-0.5">
      {/* Source tags */}
      <div className="flex items-center gap-1 flex-wrap">
        <span className="text-[9px] font-semibold text-temper-text-muted">IN</span>
        {sources.map((s) => (
          <span key={s} className="text-[8px] px-1 py-px rounded bg-blue-500/10 text-blue-400 font-mono">
            ← {s}
          </span>
        ))}
      </div>
      {/* Preview */}
      {preview && (
        <pre className={cn(
          'text-[9px] text-temper-text-dim whitespace-pre-wrap break-words font-mono leading-tight',
          expanded ? 'max-h-[160px] overflow-y-auto' : 'max-h-[20px] overflow-hidden',
        )}>
          {preview}
        </pre>
      )}
    </div>
  );
}

/** Output section with type signal and preview. */
function OutputSection({ output, error, expanded }: { output: string; error?: string | null; expanded: boolean }) {
  // Detect output type
  const trimmed = output.trim();
  const isJson = trimmed.startsWith('{') || trimmed.startsWith('[');
  const isCode = trimmed.startsWith('```') || trimmed.startsWith('import ') || trimmed.startsWith('def ') || trimmed.startsWith('function ');
  const typeLabel = isJson ? 'json' : isCode ? 'code' : 'text';
  const sizeLabel = output.length > 1000
    ? `${(output.length / 1000).toFixed(1)}K`
    : `${output.length}`;

  // First meaningful line for preview
  const firstLine = trimmed.split('\n').find((l) => l.trim().length > 0) ?? '';
  const preview = firstLine.length > 100 ? firstLine.slice(0, 100) + '...' : firstLine;

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
      {/* Type + size signal */}
      <div className="flex items-center gap-1">
        <span className="text-[9px] font-semibold text-temper-text-muted">OUT</span>
        <span className={cn(
          'text-[8px] px-1 py-px rounded font-mono',
          isJson ? 'bg-emerald-500/10 text-emerald-400' :
          isCode ? 'bg-violet-500/10 text-violet-400' :
          'bg-temper-surface text-temper-text-dim',
        )}>
          {typeLabel}
        </span>
        <span className="text-[8px] text-temper-text-dim font-mono">{sizeLabel} chars</span>
      </div>
      {/* Preview */}
      <pre className={cn(
        'text-[9px] text-temper-text-dim whitespace-pre-wrap break-words font-mono leading-tight',
        expanded ? 'max-h-[200px] overflow-y-auto' : 'max-h-[20px] overflow-hidden',
      )}>
        {expanded ? output.slice(0, 2000) : preview}
      </pre>
    </div>
  );
}
