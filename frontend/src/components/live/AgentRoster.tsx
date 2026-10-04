/**
 * The run's agents, grouped by stage, on the left of the live panel.
 *
 * While the run is going, a stage whose agents have all ended folds itself
 * away, so the list keeps showing what is happening now rather than what
 * already happened. Once the run is over there is no "now" left to make room
 * for, so every stage starts open and the whole run reads back.
 */
import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
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
  /**
   * An agent picked somewhere else on the page: open the stage it sits in,
   * folded or not, and scroll the list to it. The count goes up on every
   * pick, so picking the same agent twice still brings it into view.
   */
  reveal?: { id: string; nonce: number } | null;
}

export function AgentRoster({
  groups, selectedId, onSelect, now, lit = null, reveal = null,
}: AgentRosterProps) {
  // Stages the reader folded or opened by hand, each with the pick it was
  // done at: a later pick in that stage undoes a fold, so an agent chosen
  // elsewhere is never hidden behind a stage the reader once closed.
  const [opened, setOpened] = useState<Record<string, { open: boolean; at: number }>>({});
  const rows = useRef(new Map<string, HTMLButtonElement>());
  const scrolledTo = useRef(reveal);

  const keepRow = useCallback((id: string, el: HTMLButtonElement | null) => {
    if (el) rows.current.set(id, el);
    else rows.current.delete(id);
  }, []);

  // A fresh pick brings its row into view. Only a fresh one: a run streaming
  // away must never drag the list back to the agent you last chose.
  useEffect(() => {
    if (!reveal || reveal === scrolledTo.current) return;
    scrolledTo.current = reveal;
    rows.current.get(reveal.id)?.scrollIntoView?.({ block: 'nearest' });
  }, [reveal]);

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
    // No padding at the top: a strip of it above a stuck header would show
    // the rows sliding past, which is exactly what sticking is meant to stop.
    <div className="h-full overflow-y-auto pb-1" data-testid="live-agent-roster">
      {groups.map((group) => {
        // A stage holding a match opens itself: dimming a folded-away group
        // would hide the very row the search just found.
        const hasMatch = !lit || group.agents.some((a) => lit.has(a.id));
        const byHand = opened[group.key];
        // A fold made before the newest pick in this stage is spent.
        const pickedHere = !!reveal && group.agents.some((a) => a.id === reveal.id);
        const stale = !!byHand && pickedHere && byHand.at < reveal.nonce;
        const open = (byHand && !stale ? byHand.open : undefined)
          ?? (!group.finished || !anyBusy || group.key === selectedGroup
            || (!!lit && hasMatch));
        const working = group.agents.filter((a) => a.busy).length;
        return (
          <div
            key={group.key}
            className={cn('mb-1.5 transition-opacity', !hasMatch && 'opacity-30')}
            data-dimmed={!hasMatch || undefined}
          >
            {/* The header stays put while its own agents scroll past, so a
                long stage never leaves you wondering whose list this is. */}
            <button
              type="button"
              onClick={() => setOpened((o) => ({
                ...o,
                [group.key]: { open: !open, at: reveal?.nonce ?? 0 },
              }))}
              data-testid="live-group-header"
              aria-expanded={open}
              className="sticky top-0 z-10 flex w-full items-center gap-1 border-y border-temper-border bg-temper-surface px-2 py-1 text-left text-[11px] font-semibold uppercase tracking-wide text-temper-text-muted hover:text-temper-text"
            >
              <ChevronRight className={cn('size-3 shrink-0 transition-transform', open && 'rotate-90')} />
              <span className="truncate normal-case">{group.name}</span>
              <span className="ml-auto flex shrink-0 items-center gap-1">
                {working > 0 && (
                  <span
                    data-testid="live-group-working"
                    title={`${working} still working`}
                    className="flex items-center gap-0.5 font-mono text-[9px] text-temper-accent"
                  >
                    <span className="size-1.5 animate-pulse rounded-full bg-temper-accent" />
                    {working}
                  </span>
                )}
                <span
                  title={`${group.agents.length} agent${group.agents.length === 1 ? '' : 's'}`}
                  className="rounded bg-temper-bg px-1 font-mono text-[10px] text-temper-text-dim"
                >
                  {group.agents.length}
                </span>
              </span>
            </button>
            {/* A line down the side of a stage's agents: the list reads as
                groups of agents, not as one long run of rows. */}
            {open && (
              <div className="ml-2 border-l border-temper-border/60">
                {group.agents.map((agent) => (
                  <AgentRow
                    key={agent.id}
                    agent={agent}
                    selected={agent.id === selectedId}
                    onSelect={onSelect}
                    now={now}
                    dimmed={!!lit && !lit.has(agent.id)}
                    keepRow={keepRow}
                  />
                ))}
              </div>
            )}
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
  /** Hands the row's element up, so a picked agent can be scrolled to. */
  keepRow?: (agentId: string, el: HTMLButtonElement | null) => void;
}

const AgentRow = memo(function AgentRow({
  agent, selected, onSelect, now, dimmed = false, keepRow,
}: AgentRowProps) {
  const seconds = agent.busy && agent.startTime
    ? Math.max(0, (now - Date.parse(agent.startTime)) / 1000)
    : agent.durationSeconds ?? null;

  const attach = useCallback(
    (el: HTMLButtonElement | null) => keepRow?.(agent.id, el),
    [keepRow, agent.id],
  );

  return (
    <button
      type="button"
      ref={attach}
      onClick={() => onSelect(agent.id)}
      data-testid="live-agent-row"
      data-agent-id={agent.id}
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




