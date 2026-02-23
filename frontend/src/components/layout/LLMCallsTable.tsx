import { useState, useMemo, useCallback } from 'react';
import { useExecutionStore } from '@/store/executionStore';
import { formatTokens, formatCost, formatDuration, formatTimestamp, cn } from '@/lib/utils';
import type { LLMCall } from '@/types';

type SortField = 'status' | 'model' | 'agent' | 'stage' | 'prompt_tokens' | 'completion_tokens' | 'total_tokens' | 'cost' | 'latency' | 'start_time';
type SortDir = 'asc' | 'desc';

const STATUS_DOT: Record<string, string> = {
  completed: 'bg-emerald-400',
  running: 'bg-temper-accent animate-pulse',
  failed: 'bg-red-400',
  pending: 'bg-gray-500',
};

interface EnrichedLLMCall extends LLMCall {
  agentName: string;
  stageName: string;
}

function SortHeader({
  label,
  field,
  sortField,
  sortDir,
  onSort,
}: {
  label: string;
  field: SortField;
  sortField: SortField;
  sortDir: SortDir;
  onSort: (f: SortField) => void;
}) {
  const active = sortField === field;
  return (
    <button
      className={cn(
        'flex items-center gap-1 text-left text-[10px] font-semibold uppercase tracking-wider',
        active ? 'text-temper-accent' : 'text-temper-text-muted hover:text-temper-text',
      )}
      onClick={() => onSort(field)}
    >
      {label}
      {active && <span>{sortDir === 'asc' ? '\u25B2' : '\u25BC'}</span>}
    </button>
  );
}

export function LLMCallsTable() {
  const llmCalls = useExecutionStore((s) => s.llmCalls);
  const agents = useExecutionStore((s) => s.agents);
  const stages = useExecutionStore((s) => s.stages);
  const select = useExecutionStore((s) => s.select);

  const [sortField, setSortField] = useState<SortField>('start_time');
  const [sortDir, setSortDir] = useState<SortDir>('desc');
  const [filterModel, setFilterModel] = useState<string>('');
  const [filterAgent, setFilterAgent] = useState<string>('');
  const [filterStatus, setFilterStatus] = useState<string>('');
  const [searchText, setSearchText] = useState('');

  const handleSort = useCallback(
    (field: SortField) => {
      if (sortField === field) {
        setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
      } else {
        setSortField(field);
        setSortDir('desc');
      }
    },
    [sortField],
  );

  // Build agent→stage lookup
  const agentStageMap = useMemo(() => {
    const map = new Map<string, string>();
    for (const [, stage] of stages) {
      for (const agent of stage.agents ?? []) {
        map.set(agent.id, stage.id);
      }
    }
    return map;
  }, [stages]);

  // Enrich LLM calls with resolved names
  const enriched = useMemo((): EnrichedLLMCall[] => {
    const result: EnrichedLLMCall[] = [];
    for (const [, call] of llmCalls) {
      const agentId = call.agent_execution_id ?? call.agent_id ?? '';
      const agent = agents.get(agentId);
      const agentName = agent?.agent_name ?? agent?.name ?? agentId;
      const stageId = agentStageMap.get(agentId) ?? '';
      const stage = stages.get(stageId);
      const stageName = stage?.stage_name ?? stage?.name ?? stageId;
      result.push({ ...call, agentName, stageName });
    }
    return result;
  }, [llmCalls, agents, stages, agentStageMap]);

  // Unique models and agents for filter dropdowns
  const uniqueModels = useMemo(() => {
    const set = new Set<string>();
    for (const c of enriched) if (c.model) set.add(c.model);
    return Array.from(set).sort();
  }, [enriched]);

  const uniqueAgents = useMemo(() => {
    const set = new Set<string>();
    for (const c of enriched) if (c.agentName) set.add(c.agentName);
    return Array.from(set).sort();
  }, [enriched]);

  // Filter + sort
  const rows = useMemo(() => {
    let filtered = enriched;

    if (filterModel) filtered = filtered.filter((c) => c.model === filterModel);
    if (filterAgent) filtered = filtered.filter((c) => c.agentName === filterAgent);
    if (filterStatus) filtered = filtered.filter((c) => c.status === filterStatus);
    if (searchText) {
      const lower = searchText.toLowerCase();
      filtered = filtered.filter(
        (c) =>
          (c.model ?? '').toLowerCase().includes(lower) ||
          c.agentName.toLowerCase().includes(lower) ||
          c.stageName.toLowerCase().includes(lower),
      );
    }

    const sorted = [...filtered].sort((a, b) => {
      let cmp = 0;
      switch (sortField) {
        case 'status': cmp = a.status.localeCompare(b.status); break;
        case 'model': cmp = (a.model ?? '').localeCompare(b.model ?? ''); break;
        case 'agent': cmp = a.agentName.localeCompare(b.agentName); break;
        case 'stage': cmp = a.stageName.localeCompare(b.stageName); break;
        case 'prompt_tokens': cmp = (a.prompt_tokens ?? 0) - (b.prompt_tokens ?? 0); break;
        case 'completion_tokens': cmp = (a.completion_tokens ?? 0) - (b.completion_tokens ?? 0); break;
        case 'total_tokens': cmp = (a.total_tokens ?? 0) - (b.total_tokens ?? 0); break;
        case 'cost': cmp = (a.estimated_cost_usd ?? 0) - (b.estimated_cost_usd ?? 0); break;
        case 'latency': cmp = (a.duration_seconds ?? 0) - (b.duration_seconds ?? 0); break;
        case 'start_time': cmp = (a.start_time ?? '').localeCompare(b.start_time ?? ''); break;
      }
      return sortDir === 'asc' ? cmp : -cmp;
    });

    return sorted;
  }, [enriched, filterModel, filterAgent, filterStatus, searchText, sortField, sortDir]);

  // Summary
  const summary = useMemo(() => {
    let totalTokens = 0;
    let totalCost = 0;
    let totalLatency = 0;
    let count = 0;
    for (const r of rows) {
      totalTokens += r.total_tokens ?? 0;
      totalCost += r.estimated_cost_usd ?? 0;
      totalLatency += r.duration_seconds ?? 0;
      count++;
    }
    return { totalTokens, totalCost, avgLatency: count > 0 ? totalLatency / count : 0, count };
  }, [rows]);

  if (llmCalls.size === 0) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center text-temper-text-muted gap-2">
        <span className="text-2xl">&#x1F4E1;</span>
        <span className="text-sm">No LLM calls yet</span>
        <span className="text-xs text-temper-text-dim">LLM calls will appear as agents execute</span>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col min-h-0">
      {/* Filter bar */}
      <div className="flex items-center gap-2 px-4 py-2 border-b border-temper-border/30 shrink-0 flex-wrap">
        <select
          value={filterModel}
          onChange={(e) => setFilterModel(e.target.value)}
          className="px-2 py-0.5 rounded text-xs bg-temper-surface border border-temper-border text-temper-text"
        >
          <option value="">All Models</option>
          {uniqueModels.map((m) => <option key={m} value={m}>{m}</option>)}
        </select>
        <select
          value={filterAgent}
          onChange={(e) => setFilterAgent(e.target.value)}
          className="px-2 py-0.5 rounded text-xs bg-temper-surface border border-temper-border text-temper-text"
        >
          <option value="">All Agents</option>
          {uniqueAgents.map((a) => <option key={a} value={a}>{a}</option>)}
        </select>
        {['completed', 'running', 'failed', 'pending'].map((s) => (
          <button
            key={s}
            onClick={() => setFilterStatus(filterStatus === s ? '' : s)}
            className={cn(
              'px-2 py-0.5 rounded text-xs transition-colors',
              filterStatus === s
                ? 'bg-temper-accent/20 text-temper-accent'
                : 'text-temper-text-muted hover:text-temper-text',
            )}
          >
            {s}
          </button>
        ))}
        <input
          type="text"
          placeholder="Search..."
          value={searchText}
          onChange={(e) => setSearchText(e.target.value)}
          className="px-2 py-0.5 rounded text-xs bg-temper-surface border border-temper-border text-temper-text placeholder:text-temper-text-dim focus:outline-none focus:ring-1 focus:ring-temper-accent w-full sm:w-36"
        />
        <span className="ml-auto text-xs text-temper-text-muted">
          {rows.length}/{enriched.length} calls
        </span>
      </div>

      {/* Table */}
      <div className="flex-1 overflow-auto min-h-0 px-4 py-2">
        <table className="w-full text-xs">
          <thead className="sticky top-0 bg-temper-bg z-10">
            <tr className="border-b border-temper-border/30">
              <th className="py-1.5 px-2 text-left"><SortHeader label="" field="status" sortField={sortField} sortDir={sortDir} onSort={handleSort} /></th>
              <th className="py-1.5 px-2 text-left"><SortHeader label="Model" field="model" sortField={sortField} sortDir={sortDir} onSort={handleSort} /></th>
              <th className="py-1.5 px-2 text-left"><SortHeader label="Agent" field="agent" sortField={sortField} sortDir={sortDir} onSort={handleSort} /></th>
              <th className="py-1.5 px-2 text-left"><SortHeader label="Stage" field="stage" sortField={sortField} sortDir={sortDir} onSort={handleSort} /></th>
              <th className="py-1.5 px-2 text-right"><SortHeader label="Prompt" field="prompt_tokens" sortField={sortField} sortDir={sortDir} onSort={handleSort} /></th>
              <th className="py-1.5 px-2 text-right"><SortHeader label="Comp" field="completion_tokens" sortField={sortField} sortDir={sortDir} onSort={handleSort} /></th>
              <th className="py-1.5 px-2 text-right"><SortHeader label="Total" field="total_tokens" sortField={sortField} sortDir={sortDir} onSort={handleSort} /></th>
              <th className="py-1.5 px-2 text-right"><SortHeader label="Cost" field="cost" sortField={sortField} sortDir={sortDir} onSort={handleSort} /></th>
              <th className="py-1.5 px-2 text-right"><SortHeader label="Latency" field="latency" sortField={sortField} sortDir={sortDir} onSort={handleSort} /></th>
              <th className="py-1.5 px-2 text-right"><SortHeader label="Time" field="start_time" sortField={sortField} sortDir={sortDir} onSort={handleSort} /></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((call) => (
              <tr
                key={call.id}
                className="border-b border-temper-border/20 hover:bg-temper-surface/50 cursor-pointer transition-colors"
                onClick={() => select('llmCall', call.id)}
              >
                <td className="py-1.5 px-2">
                  <span className={cn('w-2 h-2 rounded-full inline-block', STATUS_DOT[call.status] ?? STATUS_DOT.pending)} title={call.status} />
                </td>
                <td className="py-1.5 px-2 text-temper-text font-mono truncate max-w-[120px]" title={call.model ?? '-'}>{call.model ?? '-'}</td>
                <td className="py-1.5 px-2 text-temper-text truncate max-w-[120px]" title={call.agentName}>{call.agentName}</td>
                <td className="py-1.5 px-2 text-temper-text-muted truncate max-w-[100px]" title={call.stageName}>{call.stageName}</td>
                <td className="py-1.5 px-2 text-right text-temper-text-muted font-mono">{formatTokens(call.prompt_tokens)}</td>
                <td className="py-1.5 px-2 text-right text-temper-text-muted font-mono">{formatTokens(call.completion_tokens)}</td>
                <td className="py-1.5 px-2 text-right text-temper-text font-mono">{formatTokens(call.total_tokens)}</td>
                <td className="py-1.5 px-2 text-right text-emerald-400 font-mono">{formatCost(call.estimated_cost_usd)}</td>
                <td className="py-1.5 px-2 text-right text-temper-text-muted font-mono">{formatDuration(call.duration_seconds)}</td>
                <td className="py-1.5 px-2 text-right text-temper-text-dim font-mono">{formatTimestamp(call.start_time)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Summary row */}
      <div className="flex items-center gap-6 px-4 py-2 border-t border-temper-border/30 text-xs text-temper-text-muted shrink-0 bg-temper-panel/50">
        <span>{summary.count} calls</span>
        <span>{formatTokens(summary.totalTokens)} total tokens</span>
        <span className="text-emerald-400">{formatCost(summary.totalCost)} total cost</span>
        <span>avg {formatDuration(summary.avgLatency)} latency</span>
      </div>
    </div>
  );
}
