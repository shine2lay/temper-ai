import { useId, useState } from 'react';
import { ChevronDown, ChevronUp, ShieldAlert, X } from 'lucide-react';
import { useIsNarrow } from '@/lib/useMediaQuery';
import { cn } from '@/lib/utils';
import type { TeamGuardMode } from '@/types/team';
import { TeamNote } from './TeamNote';
import { teamBtn } from './teamUi';

const KEY = 'temper.team.guard-banner-hidden';

/** Design's words for each mode the guard (#45) can be in short of enforce (boards O6a, O6b). */
const WORDS: Record<'record' | 'off', { lead: string; rest: string }> = {
  record: {
    lead: "Answers, messages and stops aren't limited to you yet.",
    rest: 'Temper records who did each one (#45 is in record mode) but refuses no one. One sent without your credential shows as "unknown caller".',
  },
  off: {
    lead: "Answers, messages and stops aren't limited to you.",
    rest: '#45 is off: anyone who can reach Temper can answer, message or stop a project.',
  },
};

function hiddenFor(): string | null {
  try {
    return window.sessionStorage.getItem(KEY);
  } catch {
    return null;
  }
}

/**
 * Says who else can act on a trial while the guard isn't enforcing (SPEC
 * shared parts, boards O6 and O6r): under the header of every Team page,
 * from team_status.guard_mode. Never shown in enforce. Hidden for the rest
 * of the session once the owner closes it; a change of mode shows it again.
 * On a phone-width screen it shows its first sentence, with the rest behind
 * "Show details", so it doesn't push the page down by half a screen.
 */
export function TeamGuardBanner({ mode, className }: { mode: TeamGuardMode | string | undefined; className?: string }) {
  const [hidden, setHidden] = useState<string | null>(hiddenFor);
  const [details, setDetails] = useState(false);
  const narrow = useIsNarrow();
  const detailsId = useId();
  if (mode !== 'record' && mode !== 'off') return null;
  if (hidden === mode) return null;
  const words = WORDS[mode];

  function hide() {
    try {
      window.sessionStorage.setItem(KEY, String(mode));
    } catch {
      // Storage can be off: then it is hidden until the page reloads.
    }
    setHidden(String(mode));
  }

  return (
    <TeamNote
      tone="warn"
      icon={ShieldAlert}
      className={cn('shrink-0', className)}
      action={
        <button
          type="button"
          onClick={hide}
          aria-label="Hide this notice for this session"
          title="Hide this notice for this session"
          className="inline-flex h-6 w-6 items-center justify-center rounded-md text-temper-text-muted hover:bg-temper-surface hover:text-temper-text"
        >
          <X className="h-4 w-4" aria-hidden="true" />
        </button>
      }
    >
      <p className="m-0" data-guard-mode={mode}>
        <b className="font-semibold">{words.lead}</b>{' '}
        <span id={detailsId} hidden={narrow && !details}>
          {words.rest}
        </span>
      </p>
      {narrow && (
        <button
          type="button"
          className={cn(teamBtn.ghostXs, '-ml-2.5 mt-1')}
          aria-expanded={details}
          aria-controls={detailsId}
          onClick={() => setDetails((v) => !v)}
        >
          {details ? <ChevronUp className="h-4 w-4" aria-hidden="true" /> : <ChevronDown className="h-4 w-4" aria-hidden="true" />}
          <span>{details ? 'Hide details' : 'Show details'}</span>
        </button>
      )}
    </TeamNote>
  );
}
