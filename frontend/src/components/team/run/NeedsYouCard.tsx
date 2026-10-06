import { useEffect, useId, useRef, useState } from 'react';
import type { LucideIcon } from 'lucide-react';
import {
  CircleAlert,
  CirclePause,
  Hand,
  Hourglass,
  ListOrdered,
  MessageCircleQuestionMark,
  RotateCcw,
  Send,
  Square,
  TriangleAlert,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { agoWords, isoOf, teamTime, teamTimeFull, waitTitle } from '@/lib/teamText';
import { answerLimit, checkAnswer, needsWordsTag, wordsLabel, type AnswerCheck } from '@/lib/teamAnswer';
import type { AnswerResult, TeamAnswerSender } from '@/hooks/useTeamAnswer';
import type { TeamLimits, TeamRun, TeamWait } from '@/types/team';
import { TeamCharCount } from '../TeamCharCount';
import { TeamNote } from '../TeamNote';
import { teamBtn, teamChip, teamChipTone } from '../teamUi';
import { AnswerResultNote } from './AnswerResultNote';
import { RoundCard } from './RoundCard';
import { StopAnswerDialog } from './StopAnswerDialog';

const KIND_ICONS: Record<string, LucideIcon> = {
  pause: CirclePause,
  stalled: Hourglass,
  recovery: TriangleAlert,
  question: MessageCircleQuestionMark,
};

function Since({ iso }: { iso: string | null }) {
  if (!iso) return null;
  return (
    <time dateTime={isoOf(iso)} title={teamTimeFull(iso)}>
      {teamTime(iso)}
    </time>
  );
}

/** The questions Temper asks after this one (R16): shown, never answerable. */
function NextQuestions({ next }: { next: TeamWait[] }) {
  return (
    <div data-next-questions="" className="border-t border-[var(--team-wait-card-border)] pt-3 [grid-area:nx]">
      <p className="m-0 text-sm text-temper-text-muted">
        {next.length === 1
          ? 'Temper asks one question at a time. This one comes next, after you answer:'
          : 'Temper asks one question at a time. These come next, in this order, after you answer:'}
      </p>
      <ul className="m-0 mt-2 flex list-none flex-col gap-2 p-0">
        {next.map((w) => (
          <li key={w.wait_id} className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-temper-text">
              <span className={cn(teamChip, teamChipTone.neutral)}>
                <ListOrdered className="h-3.5 w-3.5" aria-hidden="true" />
                Next
              </span>
              <b className="font-semibold">{waitTitle(w)}</b>
              {w.opened_at && (
                <span className="text-xs text-temper-text-muted">
                  · waiting since <Since iso={w.opened_at} />
                </span>
              )}
            </div>
            {/* On the same line when it fits, cut short with its full text on hover (board R16). */}
            {w.question && (
              <p className="m-0 min-w-[12rem] flex-1 truncate text-xs text-temper-text-muted" title={w.question}>
                {w.question}
              </p>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * The needs-you card (Design's spec, section 5.2): the question Temper
 * asks, the owner's answers as a radio group, the words box, and Send.
 *
 * Nothing is picked when it opens. Send is always enabled: the page checks
 * first (an answer picked, required words written, words within the
 * limit) and says what's missing, so nothing half-made is sent. stop asks
 * first (O1c). Answers go only through team_answer.
 */
export function NeedsYouCard({
  run,
  wait,
  next,
  limits,
  sender,
  result,
}: {
  run: TeamRun;
  wait: TeamWait;
  next: TeamWait[];
  limits: Partial<TeamLimits> | null;
  sender: TeamAnswerSender;
  /** The last answer's result, when it was for this question. */
  result: AnswerResult | null;
}) {
  const ids = useId();
  const titleId = `${ids}-title`;
  const answersErrorId = `${ids}-answers-error`;
  const wordsId = `${ids}-words`;
  const wordsCountId = `${ids}-words-count`;
  const wordsErrorId = `${ids}-words-error`;

  const [picked, setPicked] = useState<string | null>(null);
  const [texts, setTexts] = useState<Record<string, string>>({});
  const [problem, setProblem] = useState<Extract<AnswerCheck, { ok: false }> | null>(null);
  const [confirmStop, setConfirmStop] = useState<string | null>(null);
  const firstAnswer = useRef<HTMLInputElement | null>(null);
  const wordsBox = useRef<HTMLTextAreaElement | null>(null);
  const resultNote = useRef<HTMLDivElement | null>(null);

  // Focus moves only after the owner's own action: to the newest result.
  const resultSeq = result?.seq ?? null;
  useEffect(() => {
    if (resultSeq !== null) resultNote.current?.focus();
  }, [resultSeq]);

  const leader = run.trial.leader;
  const title = waitTitle(wait);
  const KindIcon = KIND_ICONS[wait.kind] ?? Hand;
  const option = wait.answers.find((a) => a.answer === picked) ?? null;
  const text = picked ? (texts[picked] ?? '') : '';
  const hasWordsBox = option !== null && option.needs_text !== 'none';
  const sending = sender.sending;
  const askedAgain = wait.asked_again ?? 0;
  const why = (wait.why ?? '').trim();

  function send() {
    const check = checkAnswer(option, text, wait, leader, limits);
    if (!check.ok) {
      setProblem(check);
      if (check.field === 'answers') firstAnswer.current?.focus();
      else wordsBox.current?.focus();
      return;
    }
    setProblem(null);
    if (!option) return;
    if (option.answer === 'stop') {
      setConfirmStop(check.text);
      return;
    }
    void sender.send(wait.wait_id, option.answer, check.text);
  }

  const sendLabel = sending ? 'Sending…' : option?.answer === 'stop' ? 'Stop the team…' : 'Send answer';
  const answersError = problem?.field === 'answers' ? problem.words : null;
  const wordsError = problem?.field === 'words' ? problem.words : null;
  const areas =
    next.length > 0
      ? "[grid-template-areas:'q'_'ans'_'nx'_'ctx'] xl:[grid-template-areas:'q_ans'_'ctx_ans'_'nx_nx']"
      : "[grid-template-areas:'q'_'ans'_'ctx'] xl:[grid-template-areas:'q_ans'_'ctx_ans']";

  return (
    <section
      data-card="needs-you"
      data-wait-kind={wait.kind}
      aria-labelledby={titleId}
      className="flex flex-col gap-3 rounded-lg border border-[var(--team-wait-card-border)] bg-[var(--team-wait-card-bg)] p-4"
    >
      <span className="inline-flex items-center gap-1.5 text-xs font-semibold uppercase tracking-[0.06em] text-[var(--badge-waiting-text)]">
        <Hand className="h-3.5 w-3.5" aria-hidden="true" />
        Needs you
      </span>

      <div className={cn('grid grid-cols-1 gap-x-6 gap-y-4 xl:grid-cols-[minmax(0,5fr)_minmax(0,6fr)]', areas)}>
        <div className="flex min-w-0 flex-col gap-2 [grid-area:q]">
          {/* The title sits atop the question's column, beside the answers (Design's R3). */}
          <div className="flex flex-col gap-1">
            <div className="flex items-center gap-2">
              <KindIcon className="h-4 w-4 shrink-0 text-[var(--badge-waiting-text)]" aria-hidden="true" />
              <h2 id={titleId} className="m-0 min-w-0 text-sm font-semibold text-temper-text">
                {title}
              </h2>
            </div>
            {(wait.opened_at || wait.header) && (
              <p className="m-0 flex flex-wrap items-center gap-x-1 text-xs text-temper-text-muted">
                {wait.opened_at && (
                  <span>
                    Waiting since <Since iso={wait.opened_at} /> ({agoWords(wait.opened_at)})
                  </span>
                )}
                {wait.opened_at && wait.header && <span aria-hidden="true">·</span>}
                {wait.header && (
                  <span className="font-mono" title="Temper's name for this question">
                    {wait.header}
                  </span>
                )}
              </p>
            )}
          </div>
          {askedAgain > 0 && (
            <TeamNote tone="warn" icon={RotateCcw} title={`Asked again (${askedAgain} ${askedAgain === 1 ? 'time' : 'times'})`}>
              The last answer wasn&apos;t one of the choices, so nothing was decided and Temper asked again. Pick one of
              the answers.
            </TeamNote>
          )}
          {wait.question && (
            <blockquote
              data-quote="engine"
              className="m-0 rounded-r-md border-l-[3px] border-[var(--team-wait-card-border)] bg-temper-panel px-3 py-2 text-sm text-temper-text whitespace-pre-wrap break-words"
            >
              {wait.question}
            </blockquote>
          )}
          {wait.kind === 'recovery' && why !== '' && why !== 'failed' && (
            <p className="m-0 text-xs text-temper-text">
              <span className="text-temper-text-muted">Why:</span> <span data-engine-words="">{why}</span>
            </p>
          )}
          {wait.kind === 'stalled' && (
            <p className="m-0 text-xs text-temper-text-muted">
              Not the run list&apos;s &ldquo;quiet&rdquo; mark: that one means Temper has heard nothing from a run for a
              while.
            </p>
          )}
        </div>

        <div className="flex min-w-0 flex-col gap-3 [grid-area:ans]">
          <fieldset className="m-0 min-w-0 border-0 p-0" aria-describedby={answersError ? answersErrorId : undefined}>
            <legend className="mb-2 p-0 text-xs font-semibold uppercase tracking-[0.06em] text-temper-text-muted">
              Your answer
            </legend>
            <div
              className={cn(
                'flex flex-col gap-2',
                answersError && 'border-l-[3px] border-[var(--badge-failed-text)] pl-3',
              )}
            >
              {wait.answers.map((a, i) => {
                const on = picked === a.answer;
                const tag = needsWordsTag(a);
                const nameId = `${ids}-answer-${i}`;
                const meansId = `${ids}-means-${i}`;
                return (
                  <label
                    key={a.answer}
                    data-answer={a.answer}
                    data-picked={on ? 'true' : 'false'}
                    className={cn(
                      // The keyboard ring goes round the whole row, as on the boards (R3b).
                      'flex min-h-10 cursor-pointer items-start gap-3 rounded-lg border bg-temper-panel p-3',
                      'has-[input:focus-visible]:outline-2 has-[input:focus-visible]:outline-offset-2 has-[input:focus-visible]:outline-temper-accent',
                      on
                        ? 'border-temper-accent shadow-[inset_0_0_0_1px_var(--color-temper-accent)]'
                        : 'border-temper-control hover:border-temper-text-muted',
                    )}
                  >
                    <input
                      ref={i === 0 ? firstAnswer : undefined}
                      type="radio"
                      name={`${ids}-answer`}
                      value={a.answer}
                      checked={on}
                      onChange={() => {
                        setPicked(a.answer);
                        if (problem?.field === 'answers' || problem?.field === 'words') setProblem(null);
                      }}
                      aria-labelledby={nameId}
                      aria-describedby={meansId}
                      className={cn(
                        'mt-0.5 h-4 w-4 shrink-0 cursor-pointer appearance-none rounded-full border-2 border-temper-control bg-transparent',
                        'checked:border-temper-accent checked:bg-[radial-gradient(var(--color-temper-accent)_0_3px,transparent_4px)]',
                        // The page-wide focus rule would square the dot off and ring it twice.
                        'focus-visible:rounded-full! focus-visible:outline-none! forced-colors:appearance-auto',
                      )}
                    />
                    <span className="min-w-0 flex-1">
                      <span id={nameId} className="block text-sm text-temper-text">
                        <b className="font-semibold">{a.answer}</b>
                        {tag && (
                          <>
                            {' '}
                            <span className="text-xs text-temper-text-muted">· {tag}</span>
                          </>
                        )}
                      </span>
                      <span id={meansId} data-engine-words="" className="block text-sm text-temper-text-muted">
                        {a.means}
                      </span>
                    </span>
                  </label>
                );
              })}
            </div>
            {answersError && (
              <p
                id={answersErrorId}
                className="m-0 mt-2 inline-flex items-center gap-1.5 text-sm font-semibold text-[var(--badge-failed-text)]"
              >
                <CircleAlert className="h-4 w-4 shrink-0" aria-hidden="true" />
                {answersError}
              </p>
            )}
          </fieldset>

          {hasWordsBox && option && (
            <div className="flex flex-col gap-1">
              <div className="flex flex-wrap items-baseline gap-2">
                <label htmlFor={wordsId} className="text-sm font-semibold text-temper-text">
                  {wordsLabel(option, wait, leader)}
                </label>
                <span className="text-xs text-temper-text-muted">
                  {option.needs_text === 'required' ? 'required' : 'optional'}
                </span>
                <TeamCharCount
                  id={wordsCountId}
                  className="ml-auto"
                  text={text}
                  limit={answerLimit(option.answer, limits)}
                />
              </div>
              <textarea
                ref={wordsBox}
                id={wordsId}
                value={text}
                onChange={(e) => {
                  const value = e.target.value;
                  setTexts((t) => ({ ...t, [option.answer]: value }));
                  if (problem?.field === 'words') setProblem(null);
                }}
                aria-required={option.needs_text === 'required' ? 'true' : undefined}
                aria-invalid={wordsError ? 'true' : undefined}
                aria-describedby={cn(wordsCountId, wordsError && wordsErrorId)}
                rows={4}
                className={cn(
                  'min-h-[88px] w-full resize-y rounded-md border bg-temper-panel px-3 py-2 text-sm text-temper-text',
                  wordsError ? 'border-[var(--badge-failed-border)]' : 'border-temper-control',
                )}
              />
              {wordsError && (
                <p
                  id={wordsErrorId}
                  className="m-0 inline-flex items-center gap-1.5 text-sm font-semibold text-[var(--badge-failed-text)]"
                >
                  <CircleAlert className="h-4 w-4 shrink-0" aria-hidden="true" />
                  {wordsError}
                </p>
              )}
            </div>
          )}

          {result && (
            <AnswerResultNote
              ref={resultNote}
              outcome={result.outcome}
              executionId={run.execution_id}
              hasWords={text.trim() !== ''}
            />
          )}

          <div className="flex justify-end">
            {/* With stop picked, Send turns into the boards' red "Stop the team" button (O1c). */}
            <button
              type="button"
              className={option?.answer === 'stop' ? teamBtn.dangerMd : teamBtn.primaryMd}
              onClick={send}
              disabled={sending}
            >
              {!sending &&
                (option?.answer === 'stop' ? (
                  <Square className="h-4 w-4" aria-hidden="true" />
                ) : (
                  <Send className="h-4 w-4" aria-hidden="true" />
                ))}
              <span>{sendLabel}</span>
            </button>
          </div>
        </div>

        {next.length > 0 && <NextQuestions next={next} />}

        <div className="min-w-0 [grid-area:ctx]">
          <RoundCard run={run} inWait />
        </div>
      </div>

      <StopAnswerDialog
        open={confirmStop !== null}
        onOpenChange={(open) => {
          if (!open) setConfirmStop(null);
        }}
        waitTitle={title}
        waitKind={wait.kind}
        words={confirmStop ?? ''}
        onConfirm={() => {
          const words = confirmStop ?? '';
          setConfirmStop(null);
          void sender.send(wait.wait_id, 'stop', words);
        }}
      />
    </section>
  );
}
