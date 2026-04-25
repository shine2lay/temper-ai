/**
 * Edge component that renders a path from ELK-supplied waypoints.
 *
 * The path normally uses ELK's pre-computed orthogonal route. When a
 * user drags a node, React Flow updates the source/target endpoint
 * positions but the cached waypoints are now stale — so we detect the
 * drift and fall back to a smoothstep recomputed from live endpoints.
 * The arrow always anchors to the actual current node position; the
 * worst case during drag is a less-pretty path until ELK re-runs.
 */
import { type FC } from 'react';
import { BaseEdge, getSmoothStepPath, type EdgeProps } from '@xyflow/react';

const CORNER_RADIUS = 8;
/** Endpoint match tolerance — if the live endpoint is more than this
 *  many pixels from the cached endpoint, treat the cache as stale. */
const STALE_THRESHOLD = 6;

type Point = { x: number; y: number };

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

function close(a: Point, b: Point): boolean {
  return Math.abs(a.x - b.x) < STALE_THRESHOLD && Math.abs(a.y - b.y) < STALE_THRESHOLD;
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
  const cached = (data?.points as Point[] | undefined) ?? [];
  const liveSrc = { x: sourceX, y: sourceY };
  const liveTgt = { x: targetX, y: targetY };

  // Use cached path only if both endpoints still match where ELK
  // routed them. Otherwise the user has dragged a node — fall back to
  // a smoothstep computed from current handle positions so the arrow
  // stays anchored.
  const usable =
    cached.length >= 2 &&
    close(cached[0], liveSrc) &&
    close(cached[cached.length - 1], liveTgt);

  const path = usable
    ? pathFromPoints(cached, CORNER_RADIUS)
    : getSmoothStepPath({
        sourceX, sourceY, targetX, targetY,
        sourcePosition, targetPosition,
        borderRadius: CORNER_RADIUS,
      })[0];

  return <BaseEdge id={id} path={path} markerEnd={markerEnd} style={style} />;
};
