import { useMemo } from 'react';
import { cn, formatTimestamp } from '@/lib/utils';
import { JsonViewer } from '@/components/shared/JsonViewer';
import type { CollaborationEvent, AgentExecution } from '@/types';

interface CollaborationTimelineProps {
  events: CollaborationEvent[];
  agents: AgentExecution[];
  strategy?: string;
}

/** Color pool for agent labels in timeline. */
const AGENT_COLORS = [
  'text-blue-400',
  'text-purple-400',
  'text-teal-400',
  'text-orange-400',
  'text-pink-400',
  'text-cyan-400',
];

const EVENT_ICONS: Record<string, string> = {
  debate_round: '\uD83D\uDDE3',
  vote: '\u2705',
  consensus: '\uD83E\uDD1D',
  feedback: '\uD83D\uDCAC',
  delegation: '\u27A1',
  aggregation: '\uD83D\uDCCA',
};

/**
 * Vertical interaction timeline for collaboration events.
 * For debate strategies, groups events by round for a round-by-round view.
 * Replaces the old SVG arrow visualization.
 */
export function CollaborationTimeline({ events, agents, strategy }: CollaborationTimelineProps) {
  const agentColorMap = useMemo(() => {
    const map = new Map<string, string>();
    agents.forEach((a, i) => {
      const name = a.agent_name ?? a.name ?? a.id;
      map.set(name, AGENT_COLORS[i % AGENT_COLORS.length]);
    });
    return map;
  }, [agents]);

  // Group events by round for debate strategy
  const isDebate = strategy === 'debate';
  const groupedRounds = useMemo(() => {
    if (!isDebate) return null;

    const rounds = new Map<number, CollaborationEvent[]>();
    let currentRound = 1;
    for (const evt of events) {
      const round = (evt.data?.round as number) ?? currentRound;
      if (!rounds.has(round)) rounds.set(round, []);
      rounds.get(round)!.push(evt);
      if (evt.event_type === 'debate_round' || evt.event_type === 'round_end') {
        currentRound = round + 1;
      }
    }
    return rounds;
  }, [events, isDebate]);

  if (events.length === 0) {
    return (
      <div className="text-xs text-maf-text-muted px-2 py-3">
        No collaboration events recorded.
      </div>
    );
  }

  // Debate round-by-round view
  if (isDebate && groupedRounds && groupedRounds.size > 0) {
    return (
      <div className="flex flex-col gap-3">
        <span className="text-xs font-medium text-maf-text-muted px-1">
          Debate Rounds ({groupedRounds.size})
        </span>
        {Array.from(groupedRounds.entries()).map(([round, roundEvents]) => (
          <div key={round} className="rounded-lg border border-maf-border/40 bg-maf-panel/30 overflow-hidden">
            <div className="px-3 py-1.5 bg-maf-surface/50 border-b border-maf-border/30">
              <span className="text-xs font-medium text-maf-text">Round {round}</span>
              <span className="text-[10px] text-maf-text-dim ml-2">
                {roundEvents.length} event{roundEvents.length !== 1 ? 's' : ''}
              </span>
            </div>
            <div className="p-2">
              <TimelineEventList
                events={roundEvents}
                agentColorMap={agentColorMap}
              />
            </div>
          </div>
        ))}
      </div>
    );
  }

  // Standard chronological timeline
  return (
    <div className="flex flex-col gap-1">
      <span className="text-xs font-medium text-maf-text-muted px-1">
        Collaboration Events ({events.length})
      </span>
      <TimelineEventList events={events} agentColorMap={agentColorMap} />
    </div>
  );
}

/** Renders a list of timeline events with vertical connector line. */
function TimelineEventList({
  events,
  agentColorMap,
}: {
  events: CollaborationEvent[];
  agentColorMap: Map<string, string>;
}) {
  return (
    <div className="relative ml-2">
      {/* Vertical line */}
      {events.length > 1 && (
        <div className="absolute left-[7px] top-2 bottom-2 w-px bg-maf-border/50" />
      )}

      {events.map((evt, i) => {
        const icon = EVENT_ICONS[evt.event_type] ?? '\u25CF';
        const fromColor = evt.from_agent ? agentColorMap.get(evt.from_agent) : undefined;
        const toColor = evt.to_agent ? agentColorMap.get(evt.to_agent) : undefined;

        return (
          <div key={`${evt.event_type}-${evt.timestamp ?? i}`} className="flex gap-3 relative mb-1.5 last:mb-0">
            {/* Dot with event icon */}
            <div className="w-4 h-4 rounded-full bg-maf-accent/20 border-2 border-maf-accent/60 shrink-0 mt-0.5 z-10 flex items-center justify-center text-[8px]">
              {icon !== '\u25CF' ? icon : ''}
            </div>

            {/* Content */}
            <div className="flex-1 rounded-md bg-maf-surface/50 px-2.5 py-1.5 text-xs min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="font-medium text-maf-accent">
                  {evt.event_type.replace(/_/g, ' ')}
                </span>

                {evt.from_agent && (
                  <span className={cn('text-[10px]', fromColor ?? 'text-maf-text-muted')}>
                    from {evt.from_agent}
                  </span>
                )}
                {evt.to_agent && (
                  <>
                    <span className="text-maf-text-dim">&rarr;</span>
                    <span className={cn('text-[10px]', toColor ?? 'text-maf-text-muted')}>
                      {evt.to_agent}
                    </span>
                  </>
                )}
                {evt.agents_involved && evt.agents_involved.length > 0 && !evt.from_agent && (
                  <span className="text-[10px] text-maf-text-muted">
                    ({evt.agents_involved.join(', ')})
                  </span>
                )}
              </div>

              {evt.timestamp && (
                <span className="text-[10px] text-maf-text-dim block mt-0.5">
                  {formatTimestamp(evt.timestamp)}
                </span>
              )}

              {evt.data && Object.keys(evt.data).length > 0 && (
                <div className="mt-1.5">
                  <JsonViewer data={evt.data} />
                </div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
