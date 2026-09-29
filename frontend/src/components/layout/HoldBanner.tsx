/**
 * The clean-ups a failed run is holding back.
 *
 * When a run stops at a failure, the steps that would tear its setup down -- the dev stack,
 * the worktree -- are kept back, so the failed step can be tried again in the same place.
 * This says what is being held and how long is left, and lets you give up on it: the clean-ups
 * then run at once and the setup goes.
 */
import { useMutation } from '@tanstack/react-query';
import { authFetch } from '@/lib/authFetch';
import type { CleanupHoldInfo } from '@/types';

function timeLeft(seconds: number | null): string {
  if (seconds === null) return 'no time limit';
  if (seconds <= 0) return 'time is up';
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.round((seconds % 3600) / 60);
  if (hours >= 1) return `${hours}h ${minutes}m left`;
  if (minutes >= 1) return `${minutes}m left`;
  return `${Math.round(seconds)}s left`;
}

interface HoldBannerProps {
  hold: CleanupHoldInfo;
  onReleased?: () => void;
}

export function HoldBanner({ hold, onReleased }: HoldBannerProps) {
  const giveUp = useMutation({
    mutationFn: async () => {
      const res = await authFetch(`/api/runs/${hold.execution_id}/cleanup`, { method: 'POST' });
      if (!res.ok) throw new Error((await res.text().catch(() => '')) || `HTTP ${res.status}`);
      return res.json();
    },
    onSuccess: () => onReleased?.(),
  });

  return (
    <div className="px-4 py-3 border-b border-amber-300 bg-amber-50 dark:border-amber-500/20 dark:bg-amber-500/10 shrink-0">
      <div className="flex items-start gap-3">
        <div className="flex-1 min-w-0">
          <div className="text-xs font-semibold text-amber-800 dark:text-amber-300">
            Its setup is being kept for a resume
          </div>
          <div className="text-[11px] text-amber-700 dark:text-amber-200/80 mt-1">
            {hold.stopped_at && (
              <>Stopped at <span className="font-mono">{hold.stopped_at}</span>. </>
            )}
            Held: {hold.cleanups.map((c) => c.path).join(', ') || 'none'} — {timeLeft(hold.seconds_left)}.
          </div>
        </div>
        <button
          onClick={() => giveUp.mutate()}
          disabled={giveUp.isPending}
          className="shrink-0 px-2.5 py-1 rounded text-[11px] font-medium border border-amber-400 bg-amber-100 text-amber-900 hover:bg-amber-200 dark:border-transparent dark:bg-amber-500/20 dark:text-amber-200 dark:hover:bg-amber-500/30 disabled:opacity-50"
        >
          {giveUp.isPending ? 'Giving up…' : 'Give up'}
        </button>
      </div>
      {giveUp.isError && (
        <div className="text-[11px] text-red-600 dark:text-red-400 mt-1">{(giveUp.error as Error).message}</div>
      )}
    </div>
  );
}
