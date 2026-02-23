/**
 * Custom edge component that visualizes data flow between stages.
 * Shows animated flow dots + floating labels with data key names.
 */
import { type FC } from 'react';
import {
  BaseEdge,
  EdgeLabelRenderer,
  getSmoothStepPath,
  type EdgeProps,
} from '@xyflow/react';

export interface DataFlowEdgeData extends Record<string, unknown> {
  /** Data keys flowing through this edge: ["suggestion_text", "workspace_path"] */
  dataKeys: string[];
  /** Whether this is a loop-back edge */
  isLoop: boolean;
  /** Loop label (e.g., "max 2") */
  loopLabel: string | null;
}

const MAX_VISIBLE_KEYS = 3;

/** Build a U-shaped path that drops below source, runs horizontally, then rises to target. */
const LOOP_DROP = 80; // px below the lower of source/target
const LOOP_RADIUS = 14;

function buildLoopPath(
  sx: number, sy: number, tx: number, ty: number,
): [path: string, labelX: number, labelY: number] {
  const bottom = Math.max(sy, ty) + LOOP_DROP;
  const r = LOOP_RADIUS;
  const goingLeft = tx < sx;
  const midX = (sx + tx) / 2;

  // Down from source, arc, horizontal, arc, up to target
  const path = goingLeft
    ? `M ${sx} ${sy} L ${sx} ${bottom - r} Q ${sx} ${bottom} ${sx - r} ${bottom} L ${tx + r} ${bottom} Q ${tx} ${bottom} ${tx} ${bottom - r} L ${tx} ${ty}`
    : `M ${sx} ${sy} L ${sx} ${bottom - r} Q ${sx} ${bottom} ${sx + r} ${bottom} L ${tx - r} ${bottom} Q ${tx} ${bottom} ${tx} ${bottom - r} L ${tx} ${ty}`;

  return [path, midX, bottom];
}

export const DataFlowEdge: FC<EdgeProps> = ({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  data,
  style,
}) => {
  const edgeData = data as DataFlowEdgeData | undefined;
  const dataKeys = edgeData?.dataKeys ?? [];
  const isLoop = edgeData?.isLoop ?? false;
  const loopLabel = edgeData?.loopLabel ?? null;

  // Loop-back edges use a custom U-shaped path that routes below all nodes;
  // regular edges use the standard smoothstep routing.
  const [edgePath, labelX, labelY] = isLoop
    ? buildLoopPath(sourceX, sourceY, targetX, targetY)
    : getSmoothStepPath({
        sourceX,
        sourceY,
        targetX,
        targetY,
        sourcePosition,
        targetPosition,
        borderRadius: 12,
      });

  const hasDataKeys = dataKeys.length > 0;
  const visibleKeys = dataKeys.slice(0, MAX_VISIBLE_KEYS);
  const overflowCount = dataKeys.length - MAX_VISIBLE_KEYS;

  // Loop-back edges get a warm orange glow; data-flow edges stay cool grey
  const trackColor = isLoop
    ? 'rgba(255, 167, 38, 0.15)'
    : 'rgba(100, 116, 139, 0.12)';
  const dotColor = isLoop
    ? 'var(--color-temper-loop-back)'
    : 'var(--color-temper-running)';

  return (
    <>
      {/* Background track (wider, dim) */}
      <path
        d={edgePath}
        fill="none"
        stroke={trackColor}
        strokeWidth={isLoop ? 12 : 8}
      />

      {/* Main edge path */}
      <BaseEdge
        id={id}
        path={edgePath}
        style={{
          ...style,
          strokeWidth: isLoop ? 2.5 : 2,
        }}
      />

      {/* Animated flow dot — loops flow source→target (later stage back to earlier) */}
      <circle r={isLoop ? 3.5 : 3} fill={dotColor} opacity="0.8">
        <animateMotion
          dur={isLoop ? '3.5s' : '2.5s'}
          repeatCount="indefinite"
          path={edgePath}
          keyPoints="0;1"
          keyTimes="0;1"
          calcMode="linear"
        />
      </circle>

      {/* Second flow dot (offset) for edges with data */}
      {hasDataKeys && (
        <circle r={isLoop ? 3 : 2.5} fill={dotColor} opacity="0.5">
          <animateMotion
            dur={isLoop ? '3.5s' : '2.5s'}
            repeatCount="indefinite"
            path={edgePath}
            begin={isLoop ? '1.75s' : '1.25s'}
            keyPoints="0;1"
            keyTimes="0;1"
            calcMode="linear"
          />
        </circle>
      )}

      {/* Edge label */}
      <EdgeLabelRenderer>
        {/* Loop label (positioned at the bottom of the U-shaped arc) */}
        {isLoop && loopLabel && (
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
                backgroundColor: 'rgba(26, 18, 37, 0.92)',
                color: '#ffa726',
                border: '1px solid rgba(255, 167, 38, 0.3)',
              }}
            >
              {loopLabel}
            </span>
          </div>
        )}

        {/* Data flow label (positioned slightly above edge midpoint) */}
        {!isLoop && hasDataKeys && (
          <div
            className="nodrag nopan pointer-events-none"
            style={{
              position: 'absolute',
              transform: `translate(-50%, -100%) translate(${labelX}px, ${labelY - 6}px)`,
            }}
          >
            <div
              className="flex items-center gap-1 px-2 py-1 rounded-md"
              style={{
                backgroundColor: 'rgba(15, 23, 42, 0.92)',
                border: '1px solid rgba(100, 116, 139, 0.25)',
                maxWidth: '220px',
              }}
            >
              <span className="text-[9px] text-blue-400/70 shrink-0">{dataKeys.length}x</span>
              <span className="text-[9px] text-temper-text-muted truncate">
                {visibleKeys.join(', ')}
                {overflowCount > 0 ? `, +${overflowCount}` : ''}
              </span>
            </div>
          </div>
        )}

        {/* "no data" indicator for dependency edges without explicit inputs */}
        {!isLoop && !hasDataKeys && (
          <div
            className="nodrag nopan pointer-events-none"
            style={{
              position: 'absolute',
              transform: `translate(-50%, -100%) translate(${labelX}px, ${labelY - 4}px)`,
            }}
          >
            <span
              className="text-[8px] px-1.5 py-0.5 rounded"
              style={{
                backgroundColor: 'rgba(15, 23, 42, 0.85)',
                color: 'rgba(148, 163, 184, 0.5)',
                border: '1px solid rgba(100, 116, 139, 0.15)',
              }}
            >
              stage_outputs
            </span>
          </div>
        )}
      </EdgeLabelRenderer>
    </>
  );
};
