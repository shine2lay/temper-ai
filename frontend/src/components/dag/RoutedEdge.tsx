/**
 * Edge component that renders a path from ELK-supplied waypoints.
 *
 * ELK's `ORTHOGONAL` edge routing returns each edge as a list of bend
 * points: [start, ...bends, end]. We render that as a single SVG path
 * with rounded corners at each bend so the edge reads as a smooth
 * orthogonal route through the layout's edge channels rather than a
 * bezier through whatever node bodies happen to be in the way.
 *
 * The arrowhead (markerEnd) gets attached to the SVG and orients along
 * the final segment automatically.
 */
import { type FC } from 'react';
import { BaseEdge, type EdgeProps } from '@xyflow/react';

const CORNER_RADIUS = 8;

type Point = { x: number; y: number };

/** Build an SVG path string from a polyline of points, rounding the
 *  corners at each interior bend by `radius`. */
function pathFromPoints(points: Point[], radius: number): string {
  if (points.length === 0) return '';
  if (points.length === 1) {
    const p = points[0];
    return `M ${p.x} ${p.y}`;
  }
  if (points.length === 2) {
    return `M ${points[0].x} ${points[0].y} L ${points[1].x} ${points[1].y}`;
  }

  const segments: string[] = [`M ${points[0].x} ${points[0].y}`];

  for (let i = 1; i < points.length - 1; i++) {
    const prev = points[i - 1];
    const cur = points[i];
    const next = points[i + 1];

    // Vector from cur → prev (we'll back off in this direction)
    const dxPrev = prev.x - cur.x;
    const dyPrev = prev.y - cur.y;
    const lenPrev = Math.hypot(dxPrev, dyPrev) || 1;
    const ux1 = dxPrev / lenPrev;
    const uy1 = dyPrev / lenPrev;

    // Vector from cur → next
    const dxNext = next.x - cur.x;
    const dyNext = next.y - cur.y;
    const lenNext = Math.hypot(dxNext, dyNext) || 1;
    const ux2 = dxNext / lenNext;
    const uy2 = dyNext / lenNext;

    const r = Math.min(radius, lenPrev / 2, lenNext / 2);

    const beforeX = cur.x + ux1 * r;
    const beforeY = cur.y + uy1 * r;
    const afterX = cur.x + ux2 * r;
    const afterY = cur.y + uy2 * r;

    segments.push(`L ${beforeX} ${beforeY}`);
    // Quadratic curve through the corner — control point at the corner.
    segments.push(`Q ${cur.x} ${cur.y} ${afterX} ${afterY}`);
  }

  const last = points[points.length - 1];
  segments.push(`L ${last.x} ${last.y}`);

  return segments.join(' ');
}

export const RoutedEdge: FC<EdgeProps> = ({
  id,
  data,
  markerEnd,
  style,
  // ELK gives us the routed points; React Flow falls back to source/target
  // coords if data.points is missing (shouldn't happen on a successful
  // ELK pass, but keeps us safe during transitions).
  sourceX,
  sourceY,
  targetX,
  targetY,
}) => {
  const points = (data?.points as Point[] | undefined) ?? [
    { x: sourceX, y: sourceY },
    { x: targetX, y: targetY },
  ];
  const path = pathFromPoints(points, CORNER_RADIUS);
  return <BaseEdge id={id} path={path} markerEnd={markerEnd} style={style} />;
};
