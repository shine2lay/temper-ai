import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/** Format seconds as "Xm Ys" or "Xs" */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null) return '-';
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return `${mins}m ${secs.toFixed(0)}s`;
}

/** Format token count with K/M suffixes */
export function formatTokens(tokens: number | null | undefined): string {
  if (tokens == null) return '-';
  if (tokens >= 1_000_000) return `${(tokens / 1_000_000).toFixed(1)}M`;
  if (tokens >= 1_000) return `${(tokens / 1_000).toFixed(1)}K`;
  return String(tokens);
}

/** Format USD cost */
export function formatCost(cost: number | null | undefined): string {
  if (cost == null) return '-';
  if (cost < 0.01) return `$${cost.toFixed(4)}`;
  return `$${cost.toFixed(2)}`;
}

/** Compute elapsed seconds from a start timestamp to now */
export function elapsedSeconds(startedAt: string | null | undefined): number {
  if (!startedAt) return 0;
  const start = new Date(ensureUTC(startedAt)).getTime();
  return Math.max(0, (Date.now() - start) / 1000);
}

/** Normalize naive ISO-8601 strings to explicit UTC (port of data-store.js) */
export function ensureUTC(isoString: string): string {
  if (!isoString) return isoString;
  if (/[Zz]$/.test(isoString) || /[+-]\d{2}:\d{2}$/.test(isoString)) {
    return isoString;
  }
  return isoString + 'Z';
}

/** Truncate text to maxLines lines, each capped at maxChars characters */
export function truncateLines(text: string, maxLines = 2, maxChars = 40): string {
  const lines = text.split('\n').slice(0, maxLines);
  return lines.map(l => l.length > maxChars ? l.slice(0, maxChars) + '...' : l).join('\n');
}

/** Format a timestamp as HH:MM:SS, or HH:MM:SS.mmm when milliseconds are non-zero */
export function formatTimestamp(ts: string | null | undefined): string {
  if (!ts) return '-';
  const d = new Date(ensureUTC(ts));
  const time = d.toLocaleTimeString('en-US', { hour12: false });
  const ms = d.getMilliseconds();
  return ms > 0 ? `${time}.${String(ms).padStart(3, '0')}` : time;
}

/** Categorize an error message into a type with retryability info */
export function categorizeError(msg: string): { type: string; retryable: boolean } {
  const lower = msg.toLowerCase();
  if (lower.includes('timeout') || lower.includes('timed out')) return { type: 'Timeout', retryable: true };
  if (lower.includes('rate limit') || lower.includes('429')) return { type: 'Rate Limit', retryable: true };
  if (lower.includes('auth') || lower.includes('401') || lower.includes('403') || lower.includes('api key')) return { type: 'Auth', retryable: false };
  if (lower.includes('connection') || lower.includes('network') || lower.includes('econnrefused')) return { type: 'Network', retryable: true };
  if (lower.includes('invalid') || lower.includes('validation') || lower.includes('400')) return { type: 'Validation', retryable: false };
  if (lower.includes('not found') || lower.includes('404')) return { type: 'Not Found', retryable: false };
  if (lower.includes('500') || lower.includes('internal')) return { type: 'Server Error', retryable: true };
  return { type: 'Error', retryable: false };
}

/** Extract a short output preview from stage output data or agent output */
export function extractOutputPreview(outputData?: Record<string, unknown>, agentOutput?: string): string {
  const contentKeys = ['output', 'analysis', 'result', 'summary', 'answer', 'response', 'recommendation'];
  if (outputData) {
    for (const key of contentKeys) {
      const val = outputData[key];
      if (typeof val === 'string' && val.trim()) {
        return truncateLines(val, 2, 80);
      }
    }
  }
  if (agentOutput && agentOutput.trim()) {
    return truncateLines(agentOutput, 2, 80);
  }
  return '';
}

/** Format byte size as human-readable string */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
