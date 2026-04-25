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
 *   - If there are no intermediate bends (straight edge), fall back
 *     to React Flow's smoothstep so we don't draw a bare line.
 */
import { type FC } from 'react';
import { BaseEdge, getSmoothStepPath, type EdgeProps } from '@xyflow/react';

const CORNER_RADIUS = 8;

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

/**
 * Stitch live endpoints to cached middle bends, keeping the path
 * orthogonal (every segment is purely horizontal or purely vertical).
 *
 * The source bend usually shares Y with the source endpoint; the
 * target bend usually shares Y with the target endpoint. If they
 * don't, we insert an intermediate corner so the shape stays clean.
 */
function stitchPath(
  liveSrc: Point,
  liveTgt: Point,
  middleBends: Point[],
): Point[] {
  if (middleBends.length === 0) return [liveSrc, liveTgt];

  const out: Point[] = [liveSrc];

  // Bridge live source → first bend.
  const firstBend = middleBends[0];
  if (Math.abs(liveSrc.y - firstBend.y) > 0.5 && Math.abs(liveSrc.x - firstBend.x) > 0.5) {
    // Diagonal — insert intermediate corner that holds source's Y
    // until reaching first bend's X (a horizontal-then-vertical step).
    out.push({ x: firstBend.x, y: liveSrc.y });
  }

  for (const b of middleBends) out.push(b);

  // Bridge last bend → live target.
  const lastBend = middleBends[middleBends.length - 1];
  if (Math.abs(liveTgt.y - lastBend.y) > 0.5 && Math.abs(liveTgt.x - lastBend.x) > 0.5) {
    out.push({ x: lastBend.x, y: liveTgt.y });
  }
  out.push(liveTgt);
  return out;
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

  // Strip ELK's cached endpoint guesses; keep only the bend points.
  const middleBends = cached.length >= 2 ? cached.slice(1, -1) : cached;

  const stitched = stitchPath(liveSrc, liveTgt, middleBends);

  // Straight edge with no bends — smoothstep gives a nicer curve than
  // a bare line.
  const path =
    stitched.length <= 2
      ? getSmoothStepPath({
          sourceX, sourceY, targetX, targetY,
          sourcePosition, targetPosition,
          borderRadius: CORNER_RADIUS,
        })[0]
      : pathFromPoints(stitched, CORNER_RADIUS);

  return <BaseEdge id={id} path={path} markerEnd={markerEnd} style={style} />;
};
