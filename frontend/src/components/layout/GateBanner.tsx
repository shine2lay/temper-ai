import { toast } from 'sonner';
import { PauseCircle } from 'lucide-react';
import { useGates } from '@/hooks/useGates';

interface GateBannerProps {
  executionId: string | undefined;
}

/**
 * Banner shown while a run is parked at a human-approval gate, with the
 * button that releases it. Without this the run just sat there looking hung.
 */
export function GateBanner({ executionId }: GateBannerProps) {
  const { gates, approve } = useGates(executionId);

  if (gates.length === 0) return null;

  return (
    <div className="shrink-0 border-b border-temper-border bg-[var(--color-temper-waiting)]/10 px-4 py-2">
      <div className="flex flex-wrap items-center gap-3">
        <PauseCircle
          className="size-4 shrink-0"
          style={{ color: 'var(--color-temper-waiting)' }}
          aria-hidden
        />
        <span className="text-sm text-temper-text">
          Waiting for approval:{' '}
          <span className="font-medium">
            {gates.map((g) => g.node_name).join(', ')}
          </span>
        </span>
        <span className="text-xs text-temper-text-muted">
          This run is paused until you approve it.
        </span>

        <div className="ml-auto flex items-center gap-2">
          {gates.map((gate) => (
            <button
              key={gate.node_name}
              onClick={() =>
                approve.mutate(gate.node_name, {
                  onSuccess: () => toast.success(`Approved "${gate.node_name}"`),
                  onError: (err: Error) =>
                    toast.error(`Could not approve: ${err.message}`),
                })
              }
              disabled={approve.isPending}
              className="rounded-md bg-temper-accent px-3 py-1 text-xs font-medium text-white transition-colors hover:brightness-110 disabled:opacity-50"
            >
              {approve.isPending
                ? 'Approving…'
                : gates.length > 1
                  ? `Approve ${gate.node_name}`
                  : 'Approve'}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
