/**
 * Custom edge component for loop-back retry arrows.
 * Draws a simple U-shaped path: straight down from source,
 * horizontal to target, straight up into target bottom handle.
 */
import { type FC, useMemo } from 'react';
import { BaseEdge, EdgeLabelRenderer, type EdgeProps } from '@xyflow/react';
import { LOOP_LABEL_COLORS } from './constants';

const LOOP_DROP = 80;
const LOOP_RADIUS = 14;

function buildLoopPath(
  sx: number, sy: number, tx: number, ty: number,
): [path: string, labelX: number, labelY: number] {
  const bottom = Math.max(sy, ty) + LOOP_DROP;
  const r = LOOP_RADIUS;
  const labelX = (sx + tx) / 2;

  const path = [
    // Start at source bottom handle
    `M ${sx} ${sy}`,
    // Straight down to loop bottom
    `L ${sx} ${bottom - r}`,
    `Q ${sx} ${bottom} ${sx - r} ${bottom}`,
    // Horizontal to directly under target center
    `L ${tx + r} ${bottom}`,
    `Q ${tx} ${bottom} ${tx} ${bottom - r}`,
    // Straight up into target bottom handle
    `L ${tx} ${ty}`,
  ].join(' ');

  return [path, labelX, bottom];
}

export const LoopBackEdge: FC<EdgeProps> = ({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  label,
  style,
}) => {
  const [edgePath, labelX, labelY] = useMemo(
    () => buildLoopPath(sourceX, sourceY, targetX, targetY),
    [sourceX, sourceY, targetX, targetY],
  );

  return (
    <>
      <BaseEdge id={id} path={edgePath} style={style} />
      {label && (
        <EdgeLabelRenderer>
          <div
            className="nodrag nopan pointer-events-none"
            style={{
              position: 'absolute',
              transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY + 14}px)`,
            }}
          >
            <span
              className="text-[10px] font-semibold px-2 py-0.5 rounded-full"
              style={{
                backgroundColor: LOOP_LABEL_COLORS.background,
                color: LOOP_LABEL_COLORS.text,
                border: `1px solid ${LOOP_LABEL_COLORS.border}`,
              }}
            >
              {label}
            </span>
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
};
