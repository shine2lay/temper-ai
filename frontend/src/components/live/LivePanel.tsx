/**
 * The live panel at the bottom of a run: the run's agents on the left, the
 * chosen agent's story on the right.
 *
 * It follows whichever agent is working unless you pick one yourself; the
 * Follow button hands it back. Drag its top edge to make it as tall as the
 * page or fold it to a bar — it remembers what you chose.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { ChevronUp, Crosshair, PanelBottomClose } from 'lucide-react';
import { useExecutionStore } from '@/store/executionStore';
import { fullStory } from '@/lib/agentStory';
import { buildRoster, busyCount, newestBusyAgent, statusWord } from '@/lib/agentRoster';
import { litRosterIds } from '@/lib/runSearch';
import { cn, formatDuration } from '@/lib/utils';
import { AgentRoster } from './AgentRoster';
import { useSecondTicker } from '@/hooks/useSecondTicker';
import { AgentStoryView } from './AgentStoryView';
import { BAR_HEIGHT, useLivePanelSize } from './useLivePanelSize';

export function LivePanel() {
  const stages = useExecutionStore((s) => s.stages);
  const agents = useExecutionStore((s) => s.agents);
  const stories = useExecutionStore((s) => s.stories);
  const runStatus = useExecutionStore((s) => s.workflow?.status);
  const select = useExecutionStore((s) => s.select);
  // The run page's find bar reaches in here too: one word narrows the graph
  // and this list together, so the two never tell different stories.
  const findQuery = useExecutionStore((s) => s.findQuery);
  const findStatus = useExecutionStore((s) => s.findStatus);

  const { share, folded, dragging, setFolded, onHandlePointerDown, panelRef } = useLivePanelSize();
  const [pickedId, setPickedId] = useState<string | null>(null);

  const groups = useMemo(() => buildRoster(stages, agents, stories), [stages, agents, stories]);
  const lit = useMemo(
    () => litRosterIds(groups, findQuery, findStatus),
    [groups, findQuery, findStatus],
  );
  const following = pickedId === null;
  const followed = useMemo(() => newestBusyAgent(groups), [groups]);
  const working = useMemo(() => busyCount(groups), [groups]);

  // The agent shown: the one being followed, the one picked, or — on a run
  // that is over — the last agent of the list, so the panel is never blank.
  const lastAgentId = useMemo(() => {
    const last = groups[groups.length - 1]?.agents;
    return last && last.length > 0 ? last[last.length - 1].id : null;
  }, [groups]);
  const shownId = (following ? followed ?? lastAgentId : pickedId) ?? null;

  const agent = shownId ? agents.get(shownId) : undefined;
  const story = shownId ? stories.get(shownId) : undefined;
  const items = useMemo(() => fullStory(agent, story), [agent, story]);

  const anyBusy = working > 0;
  const now = useSecondTicker(anyBusy);

  // An agent the page has no calls for yet (it only knows of it from the
  // index): ask for the run again so its story can be read back.
  const shownRow = useMemo(() => {
    const group = groups.find((g) => g.agents.some((a) => a.id === shownId));
    const row = group?.agents.find((a) => a.id === shownId);
    return group && row ? { row, group } : null;
  }, [groups, shownId]);

  const nowLine = useMemo(() => {
    if (!shownRow) return null;
    const { row, group } = shownRow;
    const seconds = row.busy && row.startTime
      ? Math.max(0, (now - Date.parse(row.startTime)) / 1000)
      : row.durationSeconds ?? null;
    const parts = [`${group.name} · ${row.name}`];
    // An agent that has stopped says how it ended, so the line never reads
    // as if a finished agent were still at work.
    const step = row.busy ? row.step : row.step || statusWord(row.status);
    if (step) parts.push(step);
    if (seconds != null) parts.push(formatDuration(seconds));
    const others = working - (row.busy ? 1 : 0);
    const tail = others > 0 ? ` (+${others} more working)` : '';
    return `${parts.join(' · ')}${tail}`;
  }, [shownRow, now, working]);

  // Following means following: when the busiest agent changes, go with it.
  const prevFollowed = useRef(followed);
  useEffect(() => {
    prevFollowed.current = followed;
  }, [followed]);

  const height = folded ? BAR_HEIGHT : `${Math.round(share * 100)}%`;

  return (
    <div
      ref={panelRef}
      data-testid="live-panel"
      style={{ height: typeof height === 'number' ? `${height}px` : height }}
      className={cn(
        // Solid: at full height the graph behind it must not show through.
        'absolute inset-x-0 bottom-0 z-10 flex flex-col border-t border-temper-border bg-temper-bg',
        dragging && 'select-none',
      )}
    >
      <div
        onPointerDown={onHandlePointerDown}
        data-testid="live-panel-handle"
        role="separator"
        aria-orientation="horizontal"
        aria-label="Resize the live panel"
        className="group absolute -top-1 inset-x-0 h-2 cursor-row-resize"
      >
        <div className="mx-auto mt-0.5 h-1 w-16 rounded-full bg-temper-border group-hover:bg-temper-accent/60" />
      </div>

      <div className="flex h-[34px] shrink-0 items-center gap-2 px-2">
        <button
          type="button"
          onClick={() => setFolded(!folded)}
          aria-label={folded ? 'Open the live panel' : 'Fold the live panel'}
          className="shrink-0 rounded p-0.5 text-temper-text-muted hover:text-temper-text"
        >
          {folded ? <ChevronUp className="size-4" /> : <PanelBottomClose className="size-4" />}
        </button>
        <span className="shrink-0 text-[10px] font-medium uppercase tracking-wide text-temper-text-dim">
          Now
        </span>
        <span className="truncate text-xs text-temper-text" data-testid="live-now-line">
          {nowLine ?? (runStatus === 'running' ? 'Waiting for the first agent…' : 'Nothing running')}
        </span>
        <div className="ml-auto flex shrink-0 items-center gap-1">
          {!following && (
            <button
              type="button"
              onClick={() => setPickedId(null)}
              data-testid="live-follow-button"
              className="flex items-center gap-1 rounded border border-temper-border px-1.5 py-0.5 text-[10px] text-temper-text-muted hover:text-temper-text"
            >
              <Crosshair className="size-3" />
              Follow
            </button>
          )}
          {shownId && (
            <button
              type="button"
              onClick={() => select('agent', shownId)}
              data-testid="live-details-button"
              className="rounded border border-temper-border px-1.5 py-0.5 text-[10px] text-temper-text-muted hover:text-temper-text"
            >
              Details
            </button>
          )}
        </div>
      </div>

      {!folded && (
        <div className="flex min-h-0 flex-1 border-t border-temper-border">
          <div className="w-56 shrink-0 border-r border-temper-border">
            <AgentRoster
              groups={groups}
              selectedId={shownId}
              onSelect={(id) => setPickedId(id)}
              now={now}
              lit={lit}
            />
          </div>
          <div className="min-w-0 flex-1">
            {/* Keyed by agent: a different agent starts its own view, with
                its own window on a long story. */}
            <AgentStoryView
              key={shownId ?? 'none'}
              items={items}
              live={!!shownRow?.row.busy}
            />
          </div>
        </div>
      )}
    </div>
  );
}
