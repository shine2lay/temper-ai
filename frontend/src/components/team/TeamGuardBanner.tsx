import { useId, useState } from 'react';
import { ChevronDown, ChevronUp, Info, ShieldAlert, X } from 'lucide-react';
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
    rest: '#45 is off: anyone who can reach Temper can answer, message or stop a project. One sent without your credential shows as "unknown caller".',
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
 * `textScale="glance"`: the glance page's type, where no text is under 14 px
 * (its "Show details" button too); the New project form uses it too, for its
 * phone text (the button shows on a phone only); the other Team pages keep theirs.
 * `look="calm"` (the glance page, D96): it is about who may answer, not about this
 * run, and yellow means "you're asked" (D88). So the card's own panel fill and a
 * 1 px line-colour border, a muted info icon and 15 px text in the secondary
 * text colour (--text-2), the lead sentence semibold; words, place, hide button
 * and "Show details" as before.
 */
export function TeamGuardBanner({
  mode,
  className,
  textScale = 'team',
  look = 'warn',
}: {
  mode: TeamGuardMode | string | undefined;
  className?: string;
  textScale?: 'team' | 'glance';
  look?: 'warn' | 'calm';
}) {
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

  const calm = look === 'calm';
  return (
    <TeamNote
      tone={calm ? 'neutral' : 'warn'}
      icon={calm ? Info : ShieldAlert}
      iconClassName={calm ? 'mt-[3px]' : undefined}
      className={cn('shrink-0', calm && 'border-temper-control text-[15px]', className)}
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
      <p className={cn('m-0', calm && 'text-temper-text-2')} data-guard-mode={mode} data-guard-look={look}>
        <b className="font-semibold">{words.lead}</b>{' '}
        <span id={detailsId} hidden={narrow && !details}>
          {words.rest}
        </span>
      </p>
      {narrow && (
        <button
          type="button"
          className={cn(teamBtn.ghostXs, '-ml-2.5 mt-1', textScale === 'glance' && 'text-sm')}
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
