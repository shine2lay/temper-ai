import { useState } from 'react';
import { categorizeError } from '@/lib/utils';

interface ErrorDisplayProps {
  error: string;
  compact?: boolean;
}

const COMPACT_CHAR_LIMIT = 100;

export function ErrorDisplay({ error, compact }: ErrorDisplayProps) {
  const [expanded, setExpanded] = useState(false);
  const { type, retryable } = categorizeError(error);
  const isLong = error.length > COMPACT_CHAR_LIMIT;

  if (compact) {
    return (
      <div className="px-2 py-0.5 rounded text-[10px] bg-red-100 text-red-700 dark:bg-red-950/50 dark:text-red-400 truncate" title={error}>
        {error}
      </div>
    );
  }

  return (
    <div className="rounded-md bg-red-50 border border-red-200 p-3 text-sm text-red-700 dark:bg-red-950/30 dark:border-red-900/30 dark:text-red-400">
      <div className="flex items-center gap-2 mb-1">
        <span className="text-xs font-medium px-1.5 py-0.5 rounded bg-red-100 border border-red-300 dark:bg-red-950 dark:border-red-900/50">{type}</span>
        {retryable && <span className="text-xs text-amber-600 dark:text-amber-400">Retryable</span>}
      </div>
      <div className={!expanded && isLong ? 'line-clamp-2' : undefined}>
        {error}
      </div>
      {isLong && (
        <button
          className="mt-1 text-xs text-red-600/70 hover:text-red-700 dark:text-red-400/70 dark:hover:text-red-400 transition-colors"
          onClick={() => setExpanded(!expanded)}
        >
          {expanded ? 'Show less' : 'Show more'}
        </button>
      )}
    </div>
  );
}
