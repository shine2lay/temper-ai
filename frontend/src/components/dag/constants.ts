// Re-export layout constants for DAG components
export {
  STATUS_COLORS,
  STATUS_BG_COLORS,
  STAGE_PALETTE,
  LAYOUT,
} from '@/lib/constants';

/** Confidence score thresholds and their badge styles */
export const CONFIDENCE_STYLES = {
  high: { threshold: 0.8, className: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-400' },
  medium: { threshold: 0.5, className: 'bg-amber-100 text-amber-700 dark:bg-amber-950/50 dark:text-amber-400' },
  low: { threshold: 0, className: 'bg-red-100 text-red-700 dark:bg-red-950/50 dark:text-red-400' },
} as const;

export function confidenceBadgeClass(score: number): string {
  if (score >= CONFIDENCE_STYLES.high.threshold) return CONFIDENCE_STYLES.high.className;
  if (score >= CONFIDENCE_STYLES.medium.threshold) return CONFIDENCE_STYLES.medium.className;
  return CONFIDENCE_STYLES.low.className;
}

/**
 * Derive prompt/completion tokens from llm_calls when the top-level
 * fields are 0 (backend doesn't always aggregate them).
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function deriveTokenBreakdown(agent: any): { prompt: number; completion: number } {
  const prompt = agent.prompt_tokens ?? 0;
  const completion = agent.completion_tokens ?? 0;
  if (prompt > 0 || completion > 0) return { prompt, completion };

  // Aggregate from llm_calls
  const calls = agent.llm_calls ?? [];
  let p = 0, c = 0;
  for (const call of calls) {
    p += call.prompt_tokens ?? 0;
    c += call.completion_tokens ?? 0;
  }
  return { prompt: p, completion: c };
}

/** Colors used by the LoopBackEdge label */
export const LOOP_LABEL_COLORS = {
  background: 'var(--color-temper-panel)',
  text: '#ffa726',
  border: 'rgba(255, 167, 38, 0.3)',
} as const;
