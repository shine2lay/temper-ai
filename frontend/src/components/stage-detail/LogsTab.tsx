import { useState, useMemo } from 'react';
import { useExecutionStore } from '@/store/executionStore';
import { cn, formatTimestamp, ensureUTC } from '@/lib/utils';
import { JsonViewer } from '@/components/shared/JsonViewer';
import type { AgentExecution } from '@/types';

interface LogsTabProps {
  agents: AgentExecution[];
}

type ViewMode = 'by-agent' | 'chronological';
type LogLevel = 'all' | 'llm' | 'tool' | 'error';

interface LogEntry {
  key: string;
  timestamp: string;
  agentName: string;
  agentId: string;
  type: 'llm' | 'tool' | 'error' | 'output';
  title: string;
  detail?: string;
  data?: unknown;
  status: string;
  durationMs?: number;
}

const AGENT_BG_COLORS = [
  'border-l-blue-500',
  'border-l-purple-500',
  'border-l-teal-500',
  'border-l-orange-500',
  'border-l-pink-500',
  'border-l-cyan-500',
];

/**
 * Dual-mode log viewer inspired by Kestra.
 * By-agent: collapsible sections per agent (each agent's logs grouped).
 * Chronological: interleaved timeline, color-coded by agent.
 * Includes log level filter and collapsible log entries (Airflow-style).
 */
export function LogsTab({ agents }: LogsTabProps) {
  const llmCalls = useExecutionStore((s) => s.llmCalls);
  const toolCalls = useExecutionStore((s) => s.toolCalls);
  const [viewMode, setViewMode] = useState<ViewMode>('chronological');
  const [levelFilter, setLevelFilter] = useState<LogLevel>('all');
  const [searchQuery, setSearchQuery] = useState('');

  // Build agent color map
  const agentColorMap = useMemo(() => {
    const map = new Map<string, number>();
    agents.forEach((a, i) => {
      map.set(a.id, i % AGENT_BG_COLORS.length);
    });
    return map;
  }, [agents]);

  // Build log entries from LLM calls, tool calls, and agent outputs
  const allLogs = useMemo(() => {
    const entries: LogEntry[] = [];

    for (const agent of agents) {
      const agentName = agent.agent_name ?? agent.name ?? agent.id;

      // LLM calls
      for (const llm of agent.llm_calls ?? []) {
        const fullLlm = llmCalls.get(llm.id) ?? llm;
        entries.push({
          key: `${agent.id}-llm-${fullLlm.id}`,
          timestamp: fullLlm.start_time ?? '',
          agentName,
          agentId: agent.id,
          type: 'llm',
          title: `LLM Call: ${fullLlm.model ?? fullLlm.provider ?? 'unknown'}`,
          detail: fullLlm.response ? truncate(fullLlm.response, 200) : undefined,
          data: fullLlm.prompt,
          status: fullLlm.status,
          durationMs: fullLlm.latency_ms ?? (fullLlm.duration_seconds ? fullLlm.duration_seconds * 1000 : undefined),
        });
      }

      // Tool calls
      for (const tool of agent.tool_calls ?? []) {
        const fullTool = toolCalls.get(tool.id) ?? tool;
        entries.push({
          key: `${agent.id}-tool-${fullTool.id}`,
          timestamp: fullTool.start_time ?? '',
          agentName,
          agentId: agent.id,
          type: 'tool',
          title: `Tool: ${fullTool.tool_name}`,
          detail: fullTool.output_data ? truncate(JSON.stringify(fullTool.output_data), 200) : undefined,
          data: fullTool.input_params,
          status: fullTool.status,
          durationMs: fullTool.duration_seconds ? fullTool.duration_seconds * 1000 : undefined,
        });
      }

      // Agent error
      if (agent.status === 'failed' && agent.error_message) {
        entries.push({
          key: `${agent.id}-error`,
          timestamp: agent.end_time ?? agent.start_time ?? '',
          agentName,
          agentId: agent.id,
          type: 'error',
          title: `Agent Error`,
          detail: agent.error_message,
          status: 'failed',
        });
      }
    }

    // Sort chronologically (normalize timestamps for consistent comparison)
    entries.sort((a, b) => {
      if (!a.timestamp) return 1;
      if (!b.timestamp) return -1;
      return ensureUTC(a.timestamp).localeCompare(ensureUTC(b.timestamp));
    });

    return entries;
  }, [agents, llmCalls, toolCalls]);

  // Apply filters
  const filteredLogs = useMemo(() => {
    let logs = allLogs;
    if (levelFilter === 'error') {
      logs = logs.filter((l) => l.type === 'error' || l.status === 'failed');
    } else if (levelFilter !== 'all') {
      logs = logs.filter((l) => l.type === levelFilter);
    }
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      logs = logs.filter(
        (l) =>
          l.title.toLowerCase().includes(q) ||
          l.agentName.toLowerCase().includes(q) ||
          (l.detail && l.detail.toLowerCase().includes(q)),
      );
    }
    return logs;
  }, [allLogs, levelFilter, searchQuery]);

  // Group by agent for by-agent view
  const logsByAgent = useMemo(() => {
    const map = new Map<string, { agentName: string; agentId: string; logs: LogEntry[] }>();
    for (const agent of agents) {
      const name = agent.agent_name ?? agent.name ?? agent.id;
      map.set(agent.id, { agentName: name, agentId: agent.id, logs: [] });
    }
    for (const log of filteredLogs) {
      const group = map.get(log.agentId);
      if (group) group.logs.push(log);
    }
    return Array.from(map.values());
  }, [agents, filteredLogs]);

  return (
    <div className="flex flex-col gap-3">
      {/* Controls bar */}
      <div className="flex items-center gap-3 flex-wrap">
        {/* View mode toggle */}
        <div role="radiogroup" aria-label="View mode" className="flex rounded-md bg-temper-surface overflow-hidden">
          <button
            role="radio"
            aria-checked={viewMode === 'chronological'}
            className={cn(
              'px-3 py-1 text-xs transition-colors',
              viewMode === 'chronological'
                ? 'bg-temper-accent/20 text-temper-accent'
                : 'text-temper-text-muted hover:text-temper-text',
            )}
            onClick={() => setViewMode('chronological')}
          >
            Timeline
          </button>
          <button
            role="radio"
            aria-checked={viewMode === 'by-agent'}
            className={cn(
              'px-3 py-1 text-xs transition-colors',
              viewMode === 'by-agent'
                ? 'bg-temper-accent/20 text-temper-accent'
                : 'text-temper-text-muted hover:text-temper-text',
            )}
            onClick={() => setViewMode('by-agent')}
          >
            By Agent
          </button>
        </div>

        {/* Level filter */}
        <div role="radiogroup" aria-label="Log level filter" className="flex rounded-md bg-temper-surface overflow-hidden">
          {(['all', 'llm', 'tool', 'error'] as LogLevel[]).map((level) => (
            <button
              key={level}
              role="radio"
              aria-checked={levelFilter === level}
              className={cn(
                'px-2 py-1 text-[10px] transition-colors capitalize',
                levelFilter === level
                  ? 'bg-temper-accent/20 text-temper-accent'
                  : 'text-temper-text-muted hover:text-temper-text',
              )}
              onClick={() => setLevelFilter(level)}
            >
              {level}
            </button>
          ))}
        </div>

        {/* Search */}
        <input
          type="text"
          placeholder="Search logs..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="px-2 py-1 text-xs rounded-md bg-temper-surface border border-temper-border/30 text-temper-text placeholder:text-temper-text-dim flex-1 min-w-[140px] max-w-[240px] outline-none focus:border-temper-accent/50"
        />

        {/* Count */}
        <span className="text-[10px] text-temper-text-dim ml-auto">
          {filteredLogs.length} entries
        </span>
      </div>

      {/* Log content */}
      {filteredLogs.length === 0 ? (
        <div className="text-xs text-temper-text-muted py-6 text-center">
          No log entries {levelFilter !== 'all' ? `matching "${levelFilter}"` : 'recorded'}.
        </div>
      ) : viewMode === 'chronological' ? (
        <div className="flex flex-col gap-1">
          {filteredLogs.map((log) => (
            <LogEntryRow
              key={log.key}
              log={log}
              colorIndex={agentColorMap.get(log.agentId) ?? 0}
              showAgent
            />
          ))}
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          {logsByAgent.map((group) => (
            <AgentLogGroup
              key={group.agentId}
              agentName={group.agentName}
              logs={group.logs}
              colorIndex={agentColorMap.get(group.agentId) ?? 0}
            />
          ))}
        </div>
      )}
    </div>
  );
}

/** Collapsible log entry row. */
function LogEntryRow({
  log,
  colorIndex,
  showAgent,
}: {
  log: LogEntry;
  colorIndex: number;
  showAgent?: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const borderClass = AGENT_BG_COLORS[colorIndex];
  const typeColors: Record<string, string> = {
    llm: 'text-blue-400 bg-blue-950/30',
    tool: 'text-teal-400 bg-teal-950/30',
    error: 'text-red-400 bg-red-950/30',
    output: 'text-emerald-400 bg-emerald-950/30',
  };
  const typeColor = typeColors[log.type] ?? 'text-temper-text-muted';

  return (
    <div
      className={cn(
        'rounded-md bg-temper-panel/40 border-l-2 overflow-hidden',
        borderClass,
      )}
    >
      <button
        className="w-full flex items-center gap-2 px-3 py-1.5 text-left hover:bg-temper-surface/30 transition-colors"
        onClick={() => setExpanded(!expanded)}
      >
        {/* Expand chevron */}
        {!!(log.detail || log.data) && (
          <span
            className={cn(
              'text-[10px] text-temper-text-dim transition-transform shrink-0',
              expanded && 'rotate-90',
            )}
          >
            &#9654;
          </span>
        )}

        {/* Timestamp */}
        <span className="text-[10px] text-temper-text-dim shrink-0 font-mono w-[85px]">
          {log.timestamp ? formatTimestamp(log.timestamp) : '-'}
        </span>

        {/* Type badge */}
        <span className={cn('text-[10px] px-1.5 py-0.5 rounded shrink-0', typeColor)}>
          {log.type}
        </span>

        {/* Agent name */}
        {showAgent && (
          <span className="text-[10px] text-temper-text-muted shrink-0 truncate max-w-[80px]">
            {log.agentName}
          </span>
        )}

        {/* Title */}
        <span className="text-xs text-temper-text truncate flex-1 min-w-0">
          {log.title}
        </span>

        {/* Status + duration */}
        <span
          className={cn(
            'text-[10px] shrink-0',
            log.status === 'failed' ? 'text-red-400' : 'text-temper-text-dim',
          )}
        >
          {log.status === 'failed' ? '\u2717' : '\u2713'}
        </span>
        {log.durationMs != null && (
          <span className="text-[10px] text-temper-text-dim shrink-0 font-mono w-[50px] text-right">
            {log.durationMs >= 1000
              ? `${(log.durationMs / 1000).toFixed(1)}s`
              : `${Math.round(log.durationMs)}ms`}
          </span>
        )}
      </button>

      {/* Expanded detail */}
      {expanded && !!(log.detail || log.data) && (
        <div className="border-t border-temper-border/20 px-3 py-2 bg-temper-surface/20">
          {log.detail && (
            <div className="text-xs text-temper-text font-mono whitespace-pre-wrap mb-2 max-h-48 overflow-y-auto">
              {log.detail}
            </div>
          )}
          {log.data != null && (
            <div className="max-h-48 overflow-y-auto">
              <JsonViewer data={log.data} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/** Collapsible agent log group for by-agent view. */
function AgentLogGroup({
  agentName,
  logs,
  colorIndex,
}: {
  agentName: string;
  logs: LogEntry[];
  colorIndex: number;
}) {
  const [collapsed, setCollapsed] = useState(false);
  const borderClass = AGENT_BG_COLORS[colorIndex];

  return (
    <div className={cn('rounded-lg border border-temper-border/30 overflow-hidden')}>
      <button
        className={cn(
          'w-full flex items-center gap-2 px-3 py-2 text-left border-l-2',
          'bg-temper-surface/30 hover:bg-temper-surface/50 transition-colors',
          borderClass,
        )}
        onClick={() => setCollapsed(!collapsed)}
      >
        <span
          className={cn(
            'text-xs text-temper-text-muted transition-transform',
            !collapsed && 'rotate-90',
          )}
        >
          &#9654;
        </span>
        <span className="text-sm font-medium text-temper-text">{agentName}</span>
        <span className="text-[10px] text-temper-text-dim ml-auto">
          {logs.length} entries
        </span>
      </button>

      {!collapsed && (
        <div className="flex flex-col gap-0.5 p-1">
          {logs.length === 0 ? (
            <div className="text-xs text-temper-text-dim px-3 py-2">No entries</div>
          ) : (
            logs.map((log) => (
              <LogEntryRow key={log.key} log={log} colorIndex={colorIndex} />
            ))
          )}
        </div>
      )}
    </div>
  );
}

function truncate(text: string, maxLen: number): string {
  if (text.length <= maxLen) return text;
  return text.slice(0, maxLen) + '...';
}
