/**
 * Edge component that renders a path stitched from live React Flow
 * endpoints + ELK-computed intermediate bends.
 *
 * Why this hybrid: React Flow's source/target positions account for
 * the actually-rendered DOM size and handle offset (which can differ
 * from ELK's logical width by tens of pixels due to node padding,
 * border boxes, etc.). If we used ELK's endpoint values directly the
 * arrows wouldn't anchor to the rendered handles.
 *
 * Strategy:
 *   - Live endpoints (sourceX/Y, targetX/Y) are the source of truth
 *     for where the arrow head + tail must sit.
 *   - The middle bend points come from ELK's `data.points` cache. We
 *     drop the first and last cache points (those were ELK's view of
 *     the endpoints, which we're overriding) and bridge the live
 *     endpoints to the first/last *bend* with axis-aligned segments
 *     so the path stays orthogonal.
 *   - For leader-strategy fan-in edges, `data.fanIn` carries lane
 *     index + total + entry Y. Lane X is computed from live endpoints
 *     so every lane stays inside the actual rendered gap, regardless
 *     of how ELK's logical coords differ from React Flow's measured
 *     handle positions.
 */
import { type FC } from 'react';
import { BaseEdge, getSmoothStepPath, type EdgeProps } from '@xyflow/react';

const CORNER_RADIUS = 8;

type Point = { x: number; y: number };
type FanIn = { laneIndex: number; totalLanes: number; entryY: number };

function pathFromPoints(points: Point[], radius: number): string {
  if (points.length === 0) return '';
  if (points.length === 1) return `M ${points[0].x} ${points[0].y}`;
  if (points.length === 2) return `M ${points[0].x} ${points[0].y} L ${points[1].x} ${points[1].y}`;

  const segments: string[] = [`M ${points[0].x} ${points[0].y}`];
  for (let i = 1; i < points.length - 1; i++) {
    const prev = points[i - 1];
    const cur = points[i];
    const next = points[i + 1];
    const dxP = prev.x - cur.x, dyP = prev.y - cur.y;
    const lenP = Math.hypot(dxP, dyP) || 1;
    const dxN = next.x - cur.x, dyN = next.y - cur.y;
    const lenN = Math.hypot(dxN, dyN) || 1;
    const r = Math.min(radius, lenP / 2, lenN / 2);
    segments.push(`L ${cur.x + (dxP / lenP) * r} ${cur.y + (dyP / lenP) * r}`);
    segments.push(`Q ${cur.x} ${cur.y} ${cur.x + (dxN / lenN) * r} ${cur.y + (dyN / lenN) * r}`);
  }
  const last = points[points.length - 1];
  segments.push(`L ${last.x} ${last.y}`);
  return segments.join(' ');
}

/**
 * Stitch live endpoints to cached middle bends, keeping the path
 * orthogonal (every segment is purely horizontal or purely vertical).
 */
function stitchPath(
  liveSrc: Point,
  liveTgt: Point,
  middleBends: Point[],
): Point[] {
  if (middleBends.length === 0) return [liveSrc, liveTgt];

  const out: Point[] = [liveSrc];

  const firstBend = middleBends[0];
  if (Math.abs(liveSrc.y - firstBend.y) > 0.5 && Math.abs(liveSrc.x - firstBend.x) > 0.5) {
    out.push({ x: firstBend.x, y: liveSrc.y });
  }

  for (const b of middleBends) out.push(b);

  const lastBend = middleBends[middleBends.length - 1];
  if (Math.abs(liveTgt.y - lastBend.y) > 0.5 && Math.abs(liveTgt.x - lastBend.x) > 0.5) {
    out.push({ x: lastBend.x, y: liveTgt.y });
  }
  out.push(liveTgt);
  return out;
}

/**
 * Build the fan-in route for a leader-strategy edge.
 *   liveSrc → (laneX, liveSrc.y) → (laneX, entryY) → (laneX2?, entryY) → liveTgt
 * laneX is computed from live endpoints so every lane stays inside the
 * rendered gap.
 */
function fanInPoints(liveSrc: Point, liveTgt: Point, fanIn: FanIn): Point[] {
  const { laneIndex, totalLanes, entryY } = fanIn;
  const gap = liveTgt.x - liveSrc.x;
  if (gap <= 0) return [liveSrc, liveTgt];
  // Spread lanes across the middle ~60% of the live gap, leaving 20%
  // breathing room on each side. This guarantees lanes stay strictly
  // between liveSrc.x and liveTgt.x — no backward arrows.
  const laneStart = liveSrc.x + gap * 0.2;
  const laneEnd = liveSrc.x + gap * 0.8;
  const laneX = totalLanes <= 1
    ? (liveSrc.x + liveTgt.x) / 2
    : laneStart + (laneIndex * (laneEnd - laneStart)) / (totalLanes - 1);

  return [
    liveSrc,
    { x: laneX, y: liveSrc.y },
    { x: laneX, y: entryY },
    liveTgt,
  ];
}

export const RoutedEdge: FC<EdgeProps> = ({
  id,
  data,
  markerEnd,
  style,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
}) => {
  const liveSrc = { x: sourceX, y: sourceY };
  const liveTgt = { x: targetX, y: targetY };

  const fanIn = data?.fanIn as FanIn | undefined;

  let pathPoints: Point[];
  if (fanIn) {
    pathPoints = fanInPoints(liveSrc, liveTgt, fanIn);
  } else {
    const cached = (data?.points as Point[] | undefined) ?? [];
    const middleBends = cached.length >= 2 ? cached.slice(1, -1) : cached;
    pathPoints = stitchPath(liveSrc, liveTgt, middleBends);
  }

  const path =
    pathPoints.length <= 2
      ? getSmoothStepPath({
          sourceX, sourceY, targetX, targetY,
          sourcePosition, targetPosition,
          borderRadius: CORNER_RADIUS,
        })[0]
      : pathFromPoints(pathPoints, CORNER_RADIUS);

  return <BaseEdge id={id} path={path} markerEnd={markerEnd} style={style} />;
};
