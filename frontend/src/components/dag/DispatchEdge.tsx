import { type FC } from 'react';
import {
  BaseEdge,
  getBezierPath,
  type EdgeProps,
} from '@xyflow/react';

const DISPATCH_COLOR = '#f59e0b';

export const DispatchEdge: FC<EdgeProps> = ({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  markerEnd,
  animated,
}) => {
  const [edgePath] = getBezierPath({
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
  });

  return (
    <>
      <BaseEdge
        id={id}
        path={edgePath}
        markerEnd={markerEnd}
        style={{
          stroke: DISPATCH_COLOR,
          strokeWidth: 2,
          strokeDasharray: '6 4',
        }}
        className={animated ? 'react-flow__edge-path-animated' : undefined}
      />
      {/* No label on the edge itself: the target card already reads
          "⚡ DISPATCHED / by <source>", and the pill was landing on top of
          card content — measured two overlaps of ~1,460px² covering the
          output row. The amber dashed stroke carries the meaning. */}
    </>
  );
};
