/**
 * What a resume would do, before it does it.
 *
 * A run that stopped at a failure keeps everything that finished. The preview says, for every
 * step, whether it keeps its result, runs again, or is made again because a clean-up undid it
 * -- and why. Tick any finished step to run it again too: whatever used its result comes with
 * it, which is why the preview is asked for afresh each time a box is ticked.
 */
import { useMemo, useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { authFetch } from '@/lib/authFetch';
import { cn } from '@/lib/utils';

type Action = 'keep' | 'rerun' | 'redo';

interface PlanStep {
  path: string;
  name: string;
  stage: string;
  action: Action;
  reason: string;
  kind: string;
  dispatched_by: string | null;
}

interface PlanGroup {
  stage: string;
  steps: PlanStep[];
}

interface ResumePlanResponse {
  execution_id: string;
  workflow_name: string;
  stopped_at: string | null;
  counts: Record<Action, number>;
  groups: PlanGroup[];
}

async function fetchPlan(executionId: string, rerun: string[]): Promise<ResumePlanResponse> {
  const query = rerun.length ? `?rerun=${encodeURIComponent(rerun.join(','))}` : '';
  const res = await authFetch(`/api/runs/${executionId}/resume-preview${query}`);
  if (!res.ok) throw new Error((await res.text().catch(() => '')) || `HTTP ${res.status}`);
  return res.json();
}

const ACTION_STYLE: Record<Action, string> = {
  keep: 'bg-temper-border/30 text-temper-text-dim',
  rerun: 'bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-400',
  redo: 'bg-sky-100 text-sky-800 dark:bg-sky-500/15 dark:text-sky-400',
};

const ACTION_WORD: Record<Action, string> = {
  keep: 'keeps its result',
  rerun: 'runs again',
  redo: 'made again',
};

interface ResumeDialogProps {
  executionId: string;
  onClose: () => void;
  onResumed: (newExecutionId: string) => void;
}

export function ResumeDialog({ executionId, onClose, onResumed }: ResumeDialogProps) {
  const [ticked, setTicked] = useState<string[]>([]);

  const { data, isLoading, error } = useQuery<ResumePlanResponse>({
    queryKey: ['resume-preview', executionId, ticked.join(',')],
    queryFn: () => fetchPlan(executionId, ticked),
  });

  const resume = useMutation({
    mutationFn: async () => {
      const res = await authFetch(`/api/runs/${executionId}/resume`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(ticked.length ? { rerun: ticked } : {}),
      });
      if (!res.ok) throw new Error((await res.text().catch(() => '')) || `HTTP ${res.status}`);
      return res.json() as Promise<{ execution_id: string }>;
    },
    onSuccess: (result) => onResumed(result.execution_id),
  });

  const counts = data?.counts;
  const total = useMemo(
    () => (data?.groups ?? []).reduce((n, g) => n + g.steps.length, 0),
    [data],
  );

  const toggle = (path: string) =>
    setTicked((old) => (old.includes(path) ? old.filter((p) => p !== path) : [...old, path]));

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="w-full max-w-3xl max-h-[85vh] flex flex-col rounded-lg border border-temper-border bg-temper-bg shadow-xl">
        <div className="flex items-start justify-between px-5 py-4 border-b border-temper-border/40">
          <div>
            <h2 className="text-base font-semibold text-temper-text">Resume this run</h2>
            <p className="text-xs text-temper-text-dim mt-1">
              {data?.stopped_at
                ? <>It stopped at <span className="font-mono text-temper-text">{data.stopped_at}</span>. Everything else keeps its result.</>
                : 'Everything that finished keeps its result.'}
            </p>
          </div>
          <button onClick={onClose} className="text-temper-text-dim hover:text-temper-text text-sm px-2">
            Close
          </button>
        </div>

        {counts && (
          <div className="flex gap-2 px-5 py-2 border-b border-temper-border/30 text-[11px]">
            <span className={cn('px-2 py-0.5 rounded', ACTION_STYLE.keep)}>{counts.keep ?? 0} kept</span>
            <span className={cn('px-2 py-0.5 rounded', ACTION_STYLE.rerun)}>{counts.rerun ?? 0} run again</span>
            <span className={cn('px-2 py-0.5 rounded', ACTION_STYLE.redo)}>{counts.redo ?? 0} made again</span>
            <span className="text-temper-text-dim ml-auto">{total} steps</span>
          </div>
        )}

        <div className="flex-1 overflow-y-auto min-h-0 px-5 py-3">
          {isLoading && <div className="text-sm text-temper-text-dim py-6 text-center">Working out what would run…</div>}
          {error && <div className="text-sm text-red-600 dark:text-red-400 py-6 text-center">Could not work it out: {(error as Error).message}</div>}
          {(data?.groups ?? []).map((group) => (
            <div key={group.stage || 'top'} className="mb-4">
              <div className="text-[11px] uppercase tracking-wide text-temper-text-dim mb-1">
                {group.stage || 'The run'}
              </div>
              <div className="rounded border border-temper-border/40 divide-y divide-temper-border/30">
                {group.steps.map((step) => (
                  <label
                    key={step.path}
                    className="flex items-center gap-3 px-3 py-2 cursor-pointer hover:bg-temper-border/10"
                  >
                    <input
                      type="checkbox"
                      className="accent-amber-500"
                      checked={step.action !== 'keep'}
                      disabled={step.action !== 'keep' && !ticked.includes(step.path)}
                      onChange={() => toggle(step.path)}
                    />
                    <span className="font-mono text-xs text-temper-text flex-1 truncate">{step.name}</span>
                    <span className="text-[11px] text-temper-text-dim truncate max-w-[45%]">{step.reason}</span>
                    <span className={cn('px-2 py-0.5 rounded text-[10px] shrink-0', ACTION_STYLE[step.action])}>
                      {ACTION_WORD[step.action]}
                    </span>
                  </label>
                ))}
              </div>
            </div>
          ))}
        </div>

        <div className="flex items-center justify-between px-5 py-3 border-t border-temper-border/40">
          <span className="text-[11px] text-temper-text-dim">
            Tick a step that finished to run it again; whatever used its result comes with it.
          </span>
          <div className="flex items-center gap-2">
            {resume.isError && (
              <span className="text-[11px] text-red-600 dark:text-red-400">{(resume.error as Error).message}</span>
            )}
            <button
              onClick={() => resume.mutate()}
              disabled={resume.isPending || isLoading}
              className={cn(
                'px-3 py-1.5 rounded text-xs font-medium transition-colors',
                'bg-temper-accent text-white hover:bg-temper-accent-dim',
                'disabled:opacity-50 disabled:cursor-not-allowed',
              )}
            >
              {resume.isPending ? 'Resuming…' : 'Resume'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
