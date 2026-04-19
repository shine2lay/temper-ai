import { type FC } from 'react';
import {
  BaseEdge,
  EdgeLabelRenderer,
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
  const [edgePath, labelX, labelY] = getBezierPath({
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
      <EdgeLabelRenderer>
        <div
          className="nodrag nopan pointer-events-none dispatch-edge-label"
          style={{
            position: 'absolute',
            transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
          }}
        >
          <span
            className="text-[10px] font-semibold px-2 py-0.5 rounded-full"
            style={{
              backgroundColor: 'rgb(30, 20, 5)',
              color: DISPATCH_COLOR,
              border: `1px solid ${DISPATCH_COLOR}`,
              whiteSpace: 'nowrap',
              boxShadow: '0 2px 8px rgba(0, 0, 0, 0.6)',
            }}
          >
            ⚡ dispatched
          </span>
        </div>
      </EdgeLabelRenderer>
    </>
  );
};
