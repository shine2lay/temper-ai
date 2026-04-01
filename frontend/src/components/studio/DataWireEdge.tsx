/**
 * Minimal edge component for per-field data wires.
 * Green/emerald bezier path connecting specific output→input ports.
 * Uses bezier curves (not smooth-step) for graceful routing even when
 * source and target handles are at very different vertical positions.
 */
import { type FC } from 'react';
import { BaseEdge, getBezierPath, type EdgeProps } from '@xyflow/react';

export const DataWireEdge: FC<EdgeProps> = ({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  style,
  selected,
  markerEnd,
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
    <BaseEdge
      id={id}
      path={edgePath}
      markerEnd={markerEnd}
      style={{
        ...style,
        strokeWidth: selected ? 2.5 : (style?.strokeWidth ?? 1.5),
        filter: selected ? 'drop-shadow(0 0 3px #10b981)' : undefined,
      }}
    />
  );
};
