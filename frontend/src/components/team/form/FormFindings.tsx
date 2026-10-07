import type { Ref } from 'react';
import { CircleAlert, CircleX, Info } from 'lucide-react';
import { cn } from '@/lib/utils';
import { goToAnchor, placeAnchor, problemCount, type PlacedFinding } from '@/lib/teamForm';
import type { TeamFinding } from '@/types/team';

/** A finding's words, linked to its place when it has one (field null: plain text). */
export function FindingLink({ placed }: { placed: PlacedFinding }) {
  const anchor = placeAnchor(placed.place);
  if (!anchor) return <span data-engine-words>{placed.finding.text}</span>;
  return (
    <a
      href={`#${anchor}`}
      data-engine-words
      onClick={(event) => {
        if (goToAnchor(anchor)) event.preventDefault();
      }}
      // inline-block + min-h-6: a 24 px target (WCAG 2.5.8) for a one-line problem.
      className="inline-block min-h-6 py-[3px] break-words text-temper-text underline decoration-[var(--badge-failed-border)] underline-offset-2 hover:decoration-temper-text"
    >
      {placed.finding.text}
    </a>
  );
}

/**
 * The top list of every problem (GOV.UK error summary; boards F3, S1):
 * Temper's words in Temper's order, each linked to its field. Its heading
 * takes the focus when it appears.
 */
export function FindingsSummary({
  from,
  placed,
  headingRef,
}: {
  from: 'check' | 'start';
  placed: PlacedFinding[];
  headingRef: Ref<HTMLHeadingElement>;
}) {
  const title =
    from === 'start'
      ? `Temper didn't start the project: ${problemCount(placed.length)}`
      : `The check found ${problemCount(placed.length)}`;
  return (
    <div
      data-testid="team-form-problems"
      data-note="bad"
      className="flex items-start gap-2 rounded-lg border border-[var(--badge-failed-border)] bg-[var(--badge-failed-bg)] px-4 py-3 text-sm text-temper-text"
    >
      <CircleX className="mt-0.5 h-4 w-4 shrink-0 text-[var(--badge-failed-text)]" aria-hidden="true" />
      <div className="min-w-0 flex-1">
        <h2 ref={headingRef} tabIndex={-1} className="m-0 text-sm font-semibold text-temper-text">
          {title}
        </h2>
        <p className="m-0 mt-1 text-xs text-temper-text-muted">Nothing was saved. Your inputs are kept below.</p>
        <ul className="m-0 mt-2 flex list-disc flex-col gap-1.5 pl-5">
          {placed.map((p, i) => (
            <li key={i}>
              <FindingLink placed={p} />
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

/** A field's problems, word for word, in the error style. */
export function FieldProblems({ id, problems, className }: { id: string; problems: readonly TeamFinding[]; className?: string }) {
  if (problems.length === 0) return null;
  return (
    <div className={cn('flex flex-col gap-1', className)}>
      {problems.map((p, i) => (
        <p
          key={i}
          id={`${id}-problem-${i}`}
          data-field-problem
          className="m-0 flex items-start gap-1.5 text-sm font-semibold break-words text-[var(--badge-failed-text)]"
        >
          <CircleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          <span>
            <span className="sr-only">Error: </span>
            <span data-engine-words>{p.text}</span>
          </span>
        </p>
      ))}
    </div>
  );
}

/** A field's notes from Temper: information, never problems (board F2b). */
export function FieldNotes({ id, notes, className }: { id: string; notes: readonly TeamFinding[]; className?: string }) {
  if (notes.length === 0) return null;
  return (
    <div className={cn('flex flex-col gap-1', className)}>
      {notes.map((n, i) => (
        <p
          key={i}
          id={`${id}-note-${i}`}
          data-field-note
          className="m-0 flex items-start gap-1.5 text-xs break-words text-temper-text-muted"
        >
          <Info className="mt-px h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          <span>
            Temper&apos;s note: <span data-engine-words>{n.text}</span>
          </span>
        </p>
      ))}
    </div>
  );
}
