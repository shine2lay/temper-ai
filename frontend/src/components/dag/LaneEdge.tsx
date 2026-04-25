/**
 * Lane-routed smoothstep edge.
 *
 * Standard smoothstep edges all turn at the midpoint between source and
 * target, which means N edges fanning out from the same source to N
 * different targets all pass through the same X coordinate — they
 * overlap each other and frequently cut through whatever nodes happen
 * to be in that column gap.
 *
 * This edge type takes a `data.laneIdx` (0..laneCount-1) and shifts the
 * vertical segment by `(laneIdx - centerOffset) * LANE_WIDTH`, giving
 * each edge its own parallel "lane" through the corridor between
 * columns. The result reads like freeway lanes: one edge per lane, no
 * overlap, no cutting through siblings.
 */
import { type FC } from 'react';
import {
  BaseEdge,
  getSmoothStepPath,
  type EdgeProps,
} from '@xyflow/react';

const LANE_WIDTH = 22;

export const LaneEdge: FC<EdgeProps> = ({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  data,
  markerEnd,
  style,
}) => {
  const laneIdx = (data?.laneIdx as number | undefined) ?? 0;
  const laneCount = (data?.laneCount as number | undefined) ?? 1;
  const offset = (laneIdx - (laneCount - 1) / 2) * LANE_WIDTH;

  const [path] = getSmoothStepPath({
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
    centerX: (sourceX + targetX) / 2 + offset,
    borderRadius: 8,
  });

  return <BaseEdge id={id} path={path} markerEnd={markerEnd} style={style} />;
};
