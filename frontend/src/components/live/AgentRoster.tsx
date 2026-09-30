/**
 * The run's agents, grouped by stage, on the left of the live panel.
 *
 * While the run is going, a stage whose agents have all ended folds itself
 * away, so the list keeps showing what is happening now rather than what
 * already happened. Once the run is over there is no "now" left to make room
 * for, so every stage starts open and the whole run reads back.
 */
import { memo, useMemo, useState } from 'react';
import { ChevronRight } from 'lucide-react';
import { cn, formatCost, formatDuration } from '@/lib/utils';
import { statusWord, type RosterAgent, type RosterGroup } from '@/lib/agentRoster';

interface AgentRosterProps {
  groups: RosterGroup[];
  selectedId: string | null;
  onSelect: (agentId: string) => void;
  /** Ticks every second so a running agent's time keeps counting. */
  now: number;
  /**
   * The agents the run page's find bar is pointing at, or null when it is
   * pointing at nothing. As on the graph, the rest is dimmed rather than
   * dropped: the run keeps its shape and its counts.
   */
  lit?: Set<string> | null;
}

export function AgentRoster({ groups, selectedId, onSelect, now, lit = null }: AgentRosterProps) {
  const [opened, setOpened] = useState<Record<string, boolean>>({});

  // The group holding the shown agent is always open, whatever its state.
  const selectedGroup = useMemo(
    () => groups.find((g) => g.agents.some((a) => a.id === selectedId))?.key ?? null,
    [groups, selectedId],
  );

  // Nothing busy anywhere means the run is over.
  const anyBusy = groups.some((g) => !g.finished);

  if (groups.length === 0) {
    return (
      <div className="p-3 text-xs text-temper-text-dim">
        No agents yet.
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto py-1" data-testid="live-agent-roster">
      {groups.map((group) => {
        // A stage holding a match opens itself: dimming a folded-away group
        // would hide the very row the search just found.
        const hasMatch = !lit || group.agents.some((a) => lit.has(a.id));
        const open = opened[group.key]
          ?? (!group.finished || !anyBusy || group.key === selectedGroup
            || (!!lit && hasMatch));
        return (
          <div
            key={group.key}
            className={cn('mb-0.5 transition-opacity', !hasMatch && 'opacity-30')}
            data-dimmed={!hasMatch || undefined}
          >
            <button
              type="button"
              onClick={() => setOpened((o) => ({ ...o, [group.key]: !open }))}
              data-testid="live-group-header"
              aria-expanded={open}
              className="flex w-full items-center gap-1 px-2 py-1 text-left text-[11px] font-medium text-temper-text-muted hover:text-temper-text"
            >
              <ChevronRight className={cn('size-3 shrink-0 transition-transform', open && 'rotate-90')} />
              <span className="truncate">{group.name}</span>
              <span className="ml-auto shrink-0 font-mono text-[10px] opacity-60">
                {group.agents.length}
              </span>
            </button>
            {open && group.agents.map((agent) => (
              <AgentRow
                key={agent.id}
                agent={agent}
                selected={agent.id === selectedId}
                onSelect={onSelect}
                now={now}
                dimmed={!!lit && !lit.has(agent.id)}
              />
            ))}
          </div>
        );
      })}
    </div>
  );
}

interface AgentRowProps {
  agent: RosterAgent;
  selected: boolean;
  onSelect: (agentId: string) => void;
  now: number;
  dimmed?: boolean;
}

const AgentRow = memo(function AgentRow({ agent, selected, onSelect, now, dimmed = false }: AgentRowProps) {
  const seconds = agent.busy && agent.startTime
    ? Math.max(0, (now - Date.parse(agent.startTime)) / 1000)
    : agent.durationSeconds ?? null;

  return (
    <button
      type="button"
      onClick={() => onSelect(agent.id)}
      data-testid="live-agent-row"
      aria-current={selected ? 'true' : undefined}
      data-dimmed={dimmed || undefined}
      className={cn(
        'flex w-full flex-col gap-0.5 border-l-2 px-2 py-1 text-left transition-[colors,opacity]',
        selected
          ? 'border-temper-accent bg-temper-surface/70'
          : 'border-transparent hover:bg-temper-surface/40',
        dimmed && 'opacity-25',
      )}
    >
      <div className="flex items-center gap-1.5">
        <span
          className={cn(
            'size-1.5 shrink-0 rounded-full',
            agent.status === 'running' ? 'animate-pulse bg-temper-accent' : STATUS_DOT[agent.status] ?? 'bg-temper-text-dim',
          )}
        />
        <span className="truncate text-xs text-temper-text">{agent.name}</span>
        {agent.roundLabel && (
          <span className="shrink-0 rounded bg-temper-surface px-1 text-[9px] text-temper-text-dim">
            {agent.roundLabel}
          </span>
        )}
      </div>
      <div className="flex items-center gap-1.5 pl-3">
        <span
          className={cn(
            'truncate text-[10px]',
            agent.status === 'failed' ? 'text-red-400' : 'text-temper-text-dim',
          )}
          title={agent.step}
        >
          {agent.step || statusWord(agent.status)}
        </span>
        <span className="ml-auto shrink-0 font-mono text-[9px] tabular-nums text-temper-text-dim">
          {seconds != null ? formatDuration(seconds) : ''}
          {agent.costUsd > 0 ? ` · ${formatCost(agent.costUsd)}` : ''}
        </span>
      </div>
    </button>
  );
});

const STATUS_DOT: Record<string, string> = {
  completed: 'bg-emerald-500',
  failed: 'bg-red-500',
  cancelled: 'bg-amber-500',
  skipped: 'bg-temper-text-dim',
  pending: 'bg-temper-text-dim',
  queued: 'bg-temper-text-dim',
};




