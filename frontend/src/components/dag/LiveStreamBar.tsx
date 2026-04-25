import { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import { useExecutionStore } from '@/store/executionStore';
import { cn } from '@/lib/utils';
import type { ToolActivity } from '@/types';

/**
 * Parse content into segments of plain text, thinking blocks, and tool call blocks.
 * Handles <think>...</think> tags and 🔧 tool call markers.
 */
function parseStreamContent(content: string): Array<{ type: 'text' | 'thinking' | 'tool_call'; content: string }> {
  const segments: Array<{ type: 'text' | 'thinking' | 'tool_call'; content: string }> = [];
  let i = 0;
  let current = '';
  let inThink = false;

  while (i < content.length) {
    // Check for <think> open tag
    if (!inThink && content.startsWith('<think>', i)) {
      if (current) { segments.push({ type: 'text', content: current }); current = ''; }
      inThink = true;
      i += 7; // skip "<think>"
      continue;
    }
    // Check for </think> close tag
    if (inThink && content.startsWith('</think>', i)) {
      if (current) { segments.push({ type: 'thinking', content: current }); current = ''; }
      inThink = false;
      i += 8; // skip "</think>"
      continue;
    }
    // Check for 🔧 tool call line (at start of line)
    if (!inThink && content.startsWith('\n🔧', i)) {
      if (current) { segments.push({ type: 'text', content: current }); current = ''; }
      // Collect until next newline
      const lineEnd = content.indexOf('\n', i + 1);
      const line = lineEnd === -1 ? content.slice(i) : content.slice(i, lineEnd);
      segments.push({ type: 'tool_call', content: line.trim() });
      i = lineEnd === -1 ? content.length : lineEnd;
      continue;
    }
    current += content[i];
    i++;
  }

  // Flush remaining — if still inside <think>, it's an unclosed thinking block (streaming)
  if (current) {
    segments.push({ type: inThink ? 'thinking' : 'text', content: current });
  }

  if (segments.length === 0 && content) {
    segments.push({ type: 'text', content });
  }

  return segments;
}

export function LiveStreamBar() {
  const streamingContent = useExecutionStore((s) => s.streamingContent);
  const agents = useExecutionStore((s) => s.agents);
  const select = useExecutionStore((s) => s.select);

  const [expanded, setExpanded] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  const [activeAgentId, setActiveAgentId] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const prevLengthsRef = useRef(new Map<string, number>());

  // Active streaming agents — done if entry.done OR agent status is terminal.
  // Finished entries are NOT shown in the live bar (the user can read the
  // completed trace from the agent detail panel instead).
  const streamingAgents = useMemo(() => {
    const result: { id: string; name: string; content: string; activeToolCall: string; toolActivity: ToolActivity[] }[] = [];
    for (const [agentId, entry] of streamingContent) {
      const agent = agents.get(agentId);
      const agentDone = entry.done
        || agent?.status === 'completed'
        || agent?.status === 'failed';
      if (agentDone) continue;
      const name = agent?.agent_name ?? agent?.name ?? agentId;
      result.push({ id: agentId, name, content: entry.content, activeToolCall: entry.activeToolCall ?? '', toolActivity: entry.toolActivity ?? [] });
    }
    return result;
  }, [streamingContent, agents]);

  const isStreaming = streamingAgents.length > 0;

  // Track which agents have new content since last viewed (for notification dots)
  const updatedAgents = useMemo(() => {
    const updated = new Set<string>();
    for (const sa of streamingAgents) {
      const prevLen = prevLengthsRef.current.get(sa.id) ?? 0;
      if (sa.content.length > prevLen && sa.id !== activeAgentId) {
        updated.add(sa.id);
      }
    }
    // Update previous lengths for active agent only (so dots stay on inactive tabs)
    if (activeAgentId) {
      const active = streamingAgents.find((sa) => sa.id === activeAgentId);
      if (active) {
        prevLengthsRef.current.set(activeAgentId, active.content.length);
      }
    }
    return updated;
  }, [streamingAgents, activeAgentId]);

  // Reset dismissed state when streaming stops
  useEffect(() => {
    if (!isStreaming) setDismissed(false);
  }, [isStreaming]);

  // Auto-select first agent only — never auto-switch after that
  useEffect(() => {
    if (streamingAgents.length > 0 && !activeAgentId) {
      setActiveAgentId(streamingAgents[0].id);
    }
    // Clear if active agent is no longer streaming
    if (activeAgentId && !streamingAgents.some((sa) => sa.id === activeAgentId)) {
      setActiveAgentId(streamingAgents.length > 0 ? streamingAgents[0].id : null);
    }
  }, [streamingAgents, activeAgentId]);

  // Auto-scroll only when content changes (not every render)
  const activeStream = streamingAgents.find((sa) => sa.id === activeAgentId);
  const activeContent = activeStream?.content ?? '';
  const activeToolCallContent = activeStream?.activeToolCall ?? '';
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [activeContent, activeToolCallContent]);

  const handleOpenDetail = useCallback(() => {
    if (activeAgentId) select('agent', activeAgentId);
  }, [activeAgentId, select]);

  if (!isStreaming || dismissed) return null;

  const displayContent = activeStream?.content ?? '';
  const segments = parseStreamContent(expanded ? displayContent : displayContent.split('\n').slice(-6).join('\n'));

  return (
    <div className="absolute bottom-0 left-0 right-0 z-20 bg-temper-panel/95 backdrop-blur-sm border-t border-temper-border shadow-lg">
      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-1.5 border-b border-temper-border/30">
        {/* Pulsing dot */}
        <span className="w-2 h-2 rounded-full bg-temper-accent animate-pulse shrink-0" />
        <span className="text-xs font-medium text-temper-text">Live Output</span>

        {/* Agent tabs */}
        {streamingAgents.length > 1 && (
          <div className="flex items-center gap-1 ml-2">
            {streamingAgents.map((sa) => (
              <button
                key={sa.id}
                onClick={() => { setActiveAgentId(sa.id); prevLengthsRef.current.set(sa.id, sa.content.length); }}
                className={cn(
                  'text-[10px] px-1.5 py-0.5 rounded transition-colors relative',
                  sa.id === activeAgentId
                    ? 'bg-temper-accent/20 text-temper-accent'
                    : 'text-temper-text-muted hover:text-temper-text',
                )}
              >
                {sa.name}
                {updatedAgents.has(sa.id) && (
                  <span className="absolute -top-0.5 -right-0.5 w-1.5 h-1.5 rounded-full bg-temper-accent animate-pulse" />
                )}
              </button>
            ))}
          </div>
        )}

        <div className="ml-auto flex items-center gap-1">
          <button
            onClick={handleOpenDetail}
            className="text-[10px] px-1.5 py-0.5 rounded text-temper-accent hover:bg-temper-accent/10 transition-colors"
          >
            Open Detail
          </button>
          <button
            onClick={() => setExpanded(!expanded)}
            className="text-[10px] px-1.5 py-0.5 rounded text-temper-text-muted hover:text-temper-text transition-colors"
          >
            {expanded ? 'Collapse' : 'Expand'}
          </button>
          <button
            onClick={() => setDismissed(true)}
            className="text-[10px] px-1.5 py-0.5 rounded text-temper-text-muted hover:text-red-400 transition-colors"
            title="Dismiss"
          >
            &#x2715;
          </button>
        </div>
      </div>

      {/* Content */}
      <div
        ref={scrollRef}
        className={cn(
          'px-3 py-2 text-xs font-mono overflow-auto select-text',
          expanded ? 'max-h-56' : 'max-h-20',
        )}
      >
        <ToolActivityIndicator activities={activeStream?.toolActivity ?? []} />
        {segments.map((seg, i) => {
          if (seg.type === 'thinking') {
            return (
              <div key={i} className="my-1 px-2 py-1 rounded bg-violet-500/10 border-l-2 border-violet-500/40">
                <span className="text-[9px] text-violet-400 font-medium block mb-0.5">thinking</span>
                <span className="text-violet-300/70 whitespace-pre-wrap">{seg.content}</span>
              </div>
            );
          }
          if (seg.type === 'tool_call') {
            return (
              <div key={i} className="my-0.5 text-amber-400 whitespace-pre-wrap">
                {seg.content}
              </div>
            );
          }
          return <span key={i} className="text-temper-text whitespace-pre-wrap">{seg.content}</span>;
        })}
        {/* Active tool call being streamed — shown separately with distinct styling */}
        {activeToolCallContent && (
          <div className="mt-1 px-2 py-1.5 rounded bg-amber-500/10 border-l-2 border-amber-500/40">
            <span className="text-[9px] text-amber-400 font-medium block mb-0.5">tool call</span>
            <span className="text-amber-300/90 whitespace-pre-wrap break-all">{activeToolCallContent}</span>
            <span className="animate-pulse text-amber-400">&#x2588;</span>
          </div>
        )}
        {!activeToolCallContent && <span className="animate-pulse text-temper-accent">&#x2588;</span>}
      </div>
    </div>
  );
}

function ToolActivityIndicator({ activities }: { activities: ToolActivity[] }) {
  if (!activities.length) return null;
  const running = activities.filter((t) => t.status === 'running');
  const completed = activities.filter((t) => t.status !== 'running');
  return (
    <div className="flex flex-col gap-1 mb-1">
      {completed.length > 0 && (
        <span className="text-[10px] text-temper-text-dim">
          {completed.length} tool{completed.length !== 1 ? 's' : ''} completed
        </span>
      )}
      {running.map((t, i) => (
        <div key={i} className="text-[10px]">
          <span className="flex items-center gap-1 text-temper-accent">
            <span className="w-1.5 h-1.5 rounded-full bg-temper-accent animate-pulse shrink-0" />
            <span className="font-medium">{t.toolName}</span>
          </span>
          {t.args && Object.keys(t.args).length > 0 && (
            <pre className="pl-3 mt-0.5 text-temper-text-dim font-mono whitespace-pre-wrap break-all">
              {Object.entries(t.args).map(([k, v]) => {
                const val = typeof v === 'string' ? v : JSON.stringify(v, null, 2);
                return `${k}: ${val}`;
              }).join('\n')}
            </pre>
          )}
        </div>
      ))}
    </div>
  );
}
