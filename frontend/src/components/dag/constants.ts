// Re-export layout constants for DAG components
export {
  STATUS_COLORS,
  STATUS_BG_COLORS,
  STAGE_PALETTE,
  LAYOUT,
} from '@/lib/constants';

/** Confidence score thresholds and their badge styles */
export const CONFIDENCE_STYLES = {
  high: { threshold: 0.8, className: 'bg-emerald-950/50 text-emerald-400' },
  medium: { threshold: 0.5, className: 'bg-amber-950/50 text-amber-400' },
  low: { threshold: 0, className: 'bg-red-950/50 text-red-400' },
} as const;

export function confidenceBadgeClass(score: number): string {
  if (score >= CONFIDENCE_STYLES.high.threshold) return CONFIDENCE_STYLES.high.className;
  if (score >= CONFIDENCE_STYLES.medium.threshold) return CONFIDENCE_STYLES.medium.className;
  return CONFIDENCE_STYLES.low.className;
}

/** Colors used by the LoopBackEdge label */
export const LOOP_LABEL_COLORS = {
  background: 'var(--color-temper-panel)',
  text: '#ffa726',
  border: 'rgba(255, 167, 38, 0.3)',
} as const;
