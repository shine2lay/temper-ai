import { useRef } from 'react';
import type { CollaborationEvent, AgentExecution } from '@/types';

interface CollaborationSectionProps {
  events: CollaborationEvent[];
  agents: AgentExecution[];
}

interface ArrowLine {
  fromIdx: number;
  toIdx: number;
  label: string;
  eventType: string;
}

const CARD_WIDTH = 140;
const CARD_GAP = 60;
const ARROW_AREA_HEIGHT = 48;

/**
 * Collaboration arrows drawn between agent cards.
 * Shows events as labeled SVG arrows connecting agents,
 * similar to how the main DAG shows stage dependency arrows.
 */
export function CollaborationSection({ events, agents }: CollaborationSectionProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  if (events.length === 0 || agents.length === 0) return null;

  // Build name→index map for agents
  const agentNameToIdx = new Map<string, number>();
  agents.forEach((a, i) => {
    const name = a.agent_name ?? a.name ?? a.id;
    agentNameToIdx.set(name, i);
    agentNameToIdx.set(a.id, i);
  });

  // Convert events to arrows
  const arrows: ArrowLine[] = [];
  for (const evt of events) {
    if (evt.from_agent && evt.to_agent) {
      const fromIdx = agentNameToIdx.get(evt.from_agent);
      const toIdx = agentNameToIdx.get(evt.to_agent);
      if (fromIdx != null && toIdx != null && fromIdx !== toIdx) {
        arrows.push({
          fromIdx,
          toIdx,
          label: evt.event_type,
          eventType: evt.event_type,
        });
      }
    }
  }

  // Deduplicate arrows (same from→to): show count
  const arrowKey = (a: ArrowLine) => `${a.fromIdx}-${a.toIdx}-${a.eventType}`;
  const arrowCounts = new Map<string, { arrow: ArrowLine; count: number }>();
  for (const arrow of arrows) {
    const key = arrowKey(arrow);
    const entry = arrowCounts.get(key);
    if (entry) {
      entry.count++;
    } else {
      arrowCounts.set(key, { arrow, count: 1 });
    }
  }
  const uniqueArrows = Array.from(arrowCounts.values());

  const totalWidth = agents.length * CARD_WIDTH + (agents.length - 1) * CARD_GAP;
  const agentCenterX = (idx: number) => idx * (CARD_WIDTH + CARD_GAP) + CARD_WIDTH / 2;

  return (
    <div ref={containerRef} className="mt-1">
      {/* SVG arrow layer */}
      {uniqueArrows.length > 0 && (
        <svg
          width={totalWidth}
          height={ARROW_AREA_HEIGHT}
          className="block mx-auto overflow-visible"
        >
          <defs>
            <marker
              id="collab-arrowhead"
              markerWidth="8"
              markerHeight="6"
              refX="7"
              refY="3"
              orient="auto"
            >
              <polygon
                points="0 0, 8 3, 0 6"
                fill="var(--color-maf-accent, #60a5fa)"
              />
            </marker>
          </defs>
          {uniqueArrows.map(({ arrow, count }, i) => {
            const x1 = agentCenterX(arrow.fromIdx);
            const x2 = agentCenterX(arrow.toIdx);
            const midX = (x1 + x2) / 2;
            // Curve upward for left→right, downward for right→left
            const curveY = arrow.fromIdx < arrow.toIdx ? 8 : ARROW_AREA_HEIGHT - 8;
            const controlY = arrow.fromIdx < arrow.toIdx ? -12 : ARROW_AREA_HEIGHT + 12;
            const labelY = arrow.fromIdx < arrow.toIdx ? curveY - 6 : curveY + 14;
            const label = count > 1 ? `${arrow.label} x${count}` : arrow.label;

            return (
              <g key={`${arrowKey(arrow)}-${i}`}>
                <path
                  d={`M ${x1} ${curveY} Q ${midX} ${controlY} ${x2} ${curveY}`}
                  fill="none"
                  stroke="var(--color-maf-accent, #60a5fa)"
                  strokeWidth="1.5"
                  markerEnd="url(#collab-arrowhead)"
                  opacity="0.7"
                />
                <text
                  x={midX}
                  y={labelY}
                  textAnchor="middle"
                  fill="var(--color-maf-text-muted, #8a8fa0)"
                  fontSize="9"
                  fontFamily="monospace"
                >
                  {label}
                </text>
              </g>
            );
          })}
        </svg>
      )}
    </div>
  );
}
