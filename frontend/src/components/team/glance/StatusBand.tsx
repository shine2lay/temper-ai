/**
 * The status band: Now / You / Spend, one row on a wide screen and stacked
 * on a phone, always on the first screen (D9: a compact band under 768 px).
 * Now has one big word, one sentence and who is working (D8); You answers
 * the team's own questions in place and opens a member's question in its
 * answer view (through the existing answer path: same request ids, checks,
 * refusals and stop dialog); Spend measures against the next check-in.
 */
import { useEffect, useId, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { ExternalLink, Plus, Square } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useIsNarrow } from '@/lib/useMediaQuery';
import { nowCell, phaseEnded, spendCell, youCell, workingNow, type GlanceRun } from '@/lib/teamGlance';
import { checkAnswer, wordsLabel, type AnswerCheck } from '@/lib/teamAnswer';
import type { TeamAnswerSender } from '@/hooks/useTeamAnswer';
import type { TeamAnswerOption, TeamStatus, TeamWait } from '@/types/team';
import { teamCard, teamLink } from '@/components/team/teamUi';
import { AnswerResultNote } from '@/components/team/run/AnswerResultNote';
import { StopAnswerDialog } from '@/components/team/run/StopAnswerDialog';
import { GIcon } from './glanceUi';
import { NowVersion } from './NowVersion';
import { glanceAnswerLabel, glanceBandLabel, glanceBtn, toneText } from './glanceStyle';

/**
 * Cell padding and label spacing: tighter on a phone (D9: 12 px by 14, as the reference). On a phone the label sits
 * 2 px above its cell's first line, as the reference's `.band .label { margin-bottom: 2px }`: its margin takes back
 * the cell's gap (4 px; 6 px in You), so with D97's two version lines the band still ends on the first screen.
 */
const CELL = 'flex min-w-0 flex-col px-[14px] py-3 md:p-4';
const LABEL = cn(glanceBandLabel, 'max-md:-mb-0.5 md:mb-1');
const LABEL_YOU = cn(glanceBandLabel, 'max-md:-mb-1 md:mb-1');

/**
 * D84 + D111: on a phone Now lists 1 working member, and none while the stale
 * note takes its own room, so the band ends on the first screen with the two
 * version lines; 768 px and wider keep SPEC's 3. "and N more working" counts
 * the rest, only under at least one row (D113: with none the list is left out
 * and the count line keeps the number).
 */
function workingRowsMax(narrow: boolean, stale: boolean): number {
  if (!narrow) return 3;
  return stale ? 0 : 1;
}

/**
 * D8: who is working and on what, one line each, inside Now at every width,
 * so the band alone answers "what is going on" on the first screen. Full
 * words stay on the member's card.
 */
function WorkingList({ run, stale }: { run: GlanceRun; stale: boolean }) {
  const narrow = useIsNarrow();
  const { rows, more } = workingNow(run, workingRowsMax(narrow, stale));
  if (rows.length === 0) return null;
  return (
    <ul
      className="m-0 flex list-none flex-col gap-0.5 p-0 text-sm"
      aria-label={stale ? 'Working when last seen' : 'Working now'}
      data-testid="glance-working"
    >
      {rows.map((r) => (
        // D72: one word space between the parts, the icon 6 px from them. D74: a
        // name too long for the line wraps beside its icon (never the icon alone on
        // a line); what it is on stays one line, cut with an ellipsis.
        <li key={r.name} className="flex min-w-0 flex-wrap items-center text-temper-text-muted" data-testid="glance-working-row">
          <GIcon name={r.icon} className={cn('mr-1.5 h-4 w-4 flex-none', toneText[r.tone])} />
          <b className="mr-[0.25em] max-w-[calc(100%-22px-0.25em)] font-semibold [overflow-wrap:anywhere] text-temper-text">
            {r.name}
          </b>
          <span className={cn('flex-none', r.text && 'mr-[0.25em]')}>{r.words}</span>
          {r.text && (
            <span className="min-w-[7em] flex-[1_1_7em] truncate" data-testid="glance-working-on">
              {r.quoted ? `\u201c${r.text}\u201d` : r.text}
            </span>
          )}
        </li>
      ))}
      {more > 0 && <li className="text-temper-text-muted">and {more} more working</li>}
    </ul>
  );
}

function NowBox({ run, agesAt, stale, lastAt }: { run: GlanceRun; agesAt: number | null; stale: boolean; lastAt?: string | null }) {
  const cell = nowCell(run, agesAt, stale, lastAt);
  return (
    <div className={cn('glance-now glance-edge-left gap-1', CELL)} data-tone={cell.edge} data-testid="glance-now">
      <h3 className={LABEL}>Now</h3>
      {/* SPEC 4: the word 26 px (22 on a phone), the sentence 18 (16), the counts 15; the version lines 16 (D97). */}
      <p
        className={cn(
          'glance-now-word m-0 flex items-start gap-2 text-[22px] leading-7 font-semibold md:text-[26px] md:leading-8',
          toneText[cell.edge],
        )}
      >
        <GIcon name={cell.icon} className="mt-1 h-5 w-5 shrink-0 md:mt-1.5" />
        {/* D48: frozen data can't say what runs now. D116: a long word breaks into even lines. */}
        <span className="min-w-0 break-words text-balance" data-testid="glance-now-word">
          {stale ? `Last seen: ${cell.word}` : cell.word}
        </span>
      </p>
      {cell.sentence && (
        <p className="m-0 text-base break-words text-temper-text md:text-lg" data-testid="glance-now-sentence">
          {cell.sentence}
        </p>
      )}
      {/* D105: an interrupted run's reason, Temper's words, as the sentence's second line. */}
      {cell.reason && (
        <p className="m-0 text-base break-words text-temper-text md:text-lg" data-testid="glance-now-reason">
          {cell.reason}
        </p>
      )}
      {cell.countLine && <p className="m-0 text-[15px] text-temper-text-muted">{cell.countLine}</p>}
      <WorkingList run={run} stale={stale} />
      <NowVersion latest={run.work.latest} agesAt={agesAt} />
    </div>
  );
}

function WordsBox({
  option,
  wait,
  leader,
  limits,
  busy,
  onSend,
  onCancel,
  describedBy,
}: {
  option: TeamAnswerOption;
  wait: TeamWait;
  leader: string;
  limits: TeamStatus['limits'] | null;
  busy: boolean;
  onSend: (text: string) => void;
  onCancel: () => void;
  /** The id of words that go with the box (Temper's note under a member's question). */
  describedBy?: string;
}) {
  const id = useId();
  const [text, setText] = useState('');
  const [check, setCheck] = useState<AnswerCheck | null>(null);
  const area = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    area.current?.focus();
  }, []);
  const bad = check && !check.ok ? check.words : null;
  return (
    <form
      className="flex flex-col gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        const c = checkAnswer(option, text, wait, leader, limits);
        setCheck(c);
        if (c.ok) onSend(c.text);
      }}
    >
      <label htmlFor={`${id}-words`} className="text-sm text-temper-text">
        {wordsLabel(option, wait, leader)}
      </label>
      <textarea
        id={`${id}-words`}
        ref={area}
        rows={3}
        value={text}
        onChange={(e) => setText(e.target.value)}
        aria-invalid={bad ? true : undefined}
        aria-describedby={[describedBy, bad ? `${id}-bad` : null].filter(Boolean).join(' ') || undefined}
        className="w-full min-w-0 rounded-md border border-temper-control bg-temper-surface p-2 text-sm text-temper-text"
      />
      {bad && (
        <p id={`${id}-bad`} className="m-0 text-sm text-[var(--badge-failed-text)]">
          {bad}
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        <button type="submit" className={glanceBtn.primary} disabled={busy}>
          Send {glanceAnswerLabel({ ...option, needs_text: 'none' }).toLowerCase()}
        </button>
        <button type="button" className={glanceBtn.secondary} onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}

function YouBox({
  run,
  wait,
  sender,
  limits,
  executionId,
  rawLeader,
  staleFor,
}: {
  run: GlanceRun;
  wait: TeamWait | null;
  sender: TeamAnswerSender;
  limits: TeamStatus['limits'] | null;
  executionId: string;
  rawLeader: string;
  staleFor: string | null;
}) {
  const id = useId();
  const cell = youCell(run, staleFor);
  const [open, setOpen] = useState<{ waitId: string; option: TeamAnswerOption } | null>(null);
  // The wait whose answer view is open (a member's question or held turn).
  const [viewFor, setViewFor] = useState<string | null>(null);
  const [stopOpen, setStopOpen] = useState(false);
  const answerButton = useRef<HTMLButtonElement>(null);
  const firstAnswer = useRef<HTMLButtonElement>(null);
  const focusBack = useRef(false);
  const shownWait = cell.waitId && wait && wait.wait_id === cell.waitId ? wait : null;
  const inView = cell.action === 'answer';
  const viewing = inView && shownWait !== null && viewFor === shownWait.wait_id;
  // Temper's fixed line under a member's own question, exactly as sent, never made
  // up (null on every other wait). D79: under the question in the wide band; the
  // phone's compact band (D9) leaves it to the answer view, right above the box.
  // Said once: while the answer view is open, only the view has it.
  const supplied = shownWait && typeof shownWait.note === 'string' && shownWait.note !== '' ? shownWait.note : null;
  const note = viewing ? supplied : null;
  // A words box belongs to its question: a new question shows its own answers.
  const words = open && shownWait && open.waitId === shownWait.wait_id ? open.option : null;
  const setWords = (option: TeamAnswerOption | null) =>
    setOpen(option && shownWait ? { waitId: shownWait.wait_id, option } : null);
  const send = (option: TeamAnswerOption, text: string) => {
    if (!shownWait) return;
    setOpen(null);
    setViewFor(null);
    void sender.send(shownWait.wait_id, option.answer, text);
  };
  const openView = () => {
    if (!shownWait) return;
    setViewFor(shownWait.wait_id);
    // One answer that takes words (a member's question): straight to its box.
    const only = shownWait.answers.length === 1 ? shownWait.answers[0] : null;
    setWords(only && only.answer !== 'stop' && only.needs_text !== 'none' ? only : null);
  };
  const closeView = () => {
    focusBack.current = true;
    setOpen(null);
    setViewFor(null);
  };
  // Opening moves focus into the view (the words box focuses its own field);
  // closing gives it back to Answer.
  useEffect(() => {
    if (viewing && !words) firstAnswer.current?.focus();
    if (!viewing && focusBack.current) {
      focusBack.current = false;
      answerButton.current?.focus();
    }
  }, [viewing, words]);
  const result = sender.result;
  const needs = cell.tone === 'needs';
  const answers = shownWait && (
    <div className="flex flex-wrap gap-2" data-testid="glance-answers">
      {shownWait.answers.map((o, i) => (
        <button
          key={o.answer}
          ref={i === 0 ? firstAnswer : undefined}
          type="button"
          disabled={sender.sending}
          className={o.answer === 'stop' ? glanceBtn.danger : i === 0 ? glanceBtn.primary : glanceBtn.secondary}
          title={o.means}
          onClick={() => {
            if (o.answer === 'stop') setStopOpen(true);
            else if (o.needs_text === 'none') send(o, '');
            else setWords(o);
          }}
        >
          {/* D92: "Stop project" with the header's square icon. */}
          {o.answer === 'stop' && <Square className="h-4 w-4 shrink-0" aria-hidden="true" />}
          {glanceAnswerLabel(o)}
        </button>
      ))}
      {viewing && (
        <button type="button" className={glanceBtn.secondary} onClick={closeView}>
          Cancel
        </button>
      )}
    </div>
  );
  const wordsBox = shownWait && words && (
    <WordsBox
      option={words}
      wait={shownWait}
      leader={rawLeader}
      limits={limits}
      busy={sender.sending}
      onSend={(text) => send(words, text)}
      onCancel={() => (viewing && shownWait.answers.length > 1 ? setWords(null) : closeView())}
      describedBy={note ? `${id}-note` : undefined}
    />
  );
  return (
    <div
      className={cn('gap-1.5 md:gap-2', CELL, needs && 'glance-edge-top')}
      data-tone={needs ? 'yellow' : undefined}
      data-testid="glance-you"
    >
      <h3 className={LABEL_YOU}>You</h3>
      <p
        className={cn(
          // D99: the You title is 20 px from 768 px up, 17 px under it.
          'm-0 flex items-start gap-2 text-[17px] leading-[1.3] font-semibold break-words md:text-xl',
          needs
            ? toneText.yellow
            : cell.tone === 'ended' || cell.tone === 'stale'
              ? 'text-temper-text'
              : toneText.green,
        )}
        data-testid="glance-you-title"
      >
        <GIcon
          name={needs ? 'alert' : cell.tone === 'ended' ? 'circle' : cell.tone === 'stale' ? 'clock' : 'check'}
          className="mt-0.5 h-[18px] w-[18px] shrink-0 md:mt-1 md:h-5 md:w-5"
        />
        <span className="min-w-0">
          {cell.title}
          {cell.more > 0 && <span className="font-normal text-temper-text-muted"> and {cell.more} more</span>}
        </span>
      </p>
      {supplied && !viewing && (
        <p className="m-0 text-sm break-words text-temper-text-muted max-md:hidden" data-testid="glance-you-note">
          {supplied}
        </p>
      )}
      {cell.line && (
        // D9: a phone leaves out the hint; it says nothing about this run.
        <p className={cn('m-0 text-sm text-temper-text-muted', cell.hint && 'max-md:hidden')}>{cell.line}</p>
      )}
      {cell.action === 'answers' && shownWait && shownWait.question && cell.title.indexOf(shownWait.question) < 0 && (
        <p className="m-0 text-sm break-words text-temper-text-muted" data-engine-words="">
          {shownWait.question}
        </p>
      )}
      {cell.action === 'answers' && shownWait && (words ? wordsBox : answers)}
      {inView && (cell.from || (shownWait && !viewing)) && (
        // D9: "From <member>" shares its row with Answer.
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1" data-testid="glance-from-row">
          {cell.from && <span className="text-sm text-temper-text-muted">{cell.from}</span>}
          {shownWait && !viewing && (
            <button
              ref={answerButton}
              type="button"
              className={glanceBtn.primary}
              disabled={sender.sending}
              onClick={openView}
            >
              Answer
            </button>
          )}
        </div>
      )}
      {viewing && shownWait && (
        // The answer view (D79): titled with Temper's header ("builder asks"), then the
        // whole question (D62), Temper's note and the answers.
        <div
          role="group"
          aria-labelledby={shownWait.header ? `${id}-header` : `${id}-question`}
          className="flex flex-col gap-2"
          data-testid="glance-answer-view"
        >
          {shownWait.header && (
            <p
              id={`${id}-header`}
              className="m-0 text-sm font-semibold break-words text-temper-text"
              data-testid="glance-answer-header"
            >
              {shownWait.header}
            </p>
          )}
          {(shownWait.question || !shownWait.header) && (
            <p
              id={`${id}-question`}
              className="m-0 text-sm whitespace-pre-line break-words text-temper-text"
              data-testid="glance-question"
            >
              {shownWait.question || cell.title}
            </p>
          )}
          {note && (
            <p
              id={`${id}-note`}
              className="m-0 text-sm whitespace-pre-line break-words text-temper-text-muted"
              data-testid="glance-question-note"
            >
              {note}
            </p>
          )}
          {words ? wordsBox : answers}
        </div>
      )}
      {shownWait && (
        <StopAnswerDialog
          open={stopOpen}
          onOpenChange={setStopOpen}
          waitTitle={shownWait.header || cell.title}
          waitKind={shownWait.kind}
          answerLabel={shownWait.kind === 'settings' ? 'Stop the team' : 'stop'}
          words=""
          onConfirm={() => {
            setStopOpen(false);
            const stop = shownWait.answers.find((o) => o.answer === 'stop');
            if (stop) send(stop, '');
          }}
        />
      )}
      {cell.action === 'summary' && (
        <p className="m-0">
          <a href="#glance-summary" className={teamLink}>
            Read the summary
          </a>
        </p>
      )}
      {cell.action === 'next' && (
        // D90 + D91: "New project" is this view's one main action, a 44 px solid button; the run page stays a link.
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <Link to="/team/new" className={glanceBtn.primary} data-testid="glance-new-project">
            <Plus className="h-4 w-4 shrink-0" aria-hidden="true" />
            <span>New project</span>
          </Link>
          <Link to={`/workflow/${executionId}`} className={cn(teamLink, 'text-sm')}>
            <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
            <span>Open the run page</span>
          </Link>
        </div>
      )}
      {result && <AnswerResultNote outcome={result.outcome} executionId={executionId} hasWords={false} />}
    </div>
  );
}

function SpendBox({ run }: { run: GlanceRun }) {
  const cell = spendCell(run);
  return (
    <div className={cn('gap-1 md:gap-1.5', CELL)} data-testid="glance-spend">
      <h3 className={LABEL}>Spend</h3>
      {/* D9: number and bar share one row on a phone. */}
      <div className="flex min-w-0 flex-col gap-1.5 max-md:flex-row max-md:items-center max-md:gap-3">
        <p className="m-0 flex flex-wrap items-baseline gap-x-2 max-md:shrink-0">
          {/* SPEC 4: the amount 26 px semibold (22 on a phone), "of $100" 18 px muted. */}
          <span className="text-[22px] leading-7 font-semibold text-temper-text md:text-[26px] md:leading-8">{cell.amount}</span>
          {cell.of && <span className="text-lg text-temper-text-muted">{cell.of}</span>}
        </p>
        {cell.fraction !== null && (
          <div className="glance-bar max-md:min-w-12 max-md:flex-1" data-warn={cell.tone === 'warn'} aria-hidden="true">
            <i style={{ transform: `scaleX(${cell.fraction})` }} />
          </div>
        )}
      </div>
      {/* D98: the next check-in line 16 px in --text-2; an ended run's total line as before. */}
      {cell.line && (
        <p
          className={cn('m-0', phaseEnded(run.phase.name) ? 'text-sm text-temper-text-muted' : 'text-base text-temper-text-2')}
          data-testid="glance-spend-line"
        >
          {cell.line}
        </p>
      )}
    </div>
  );
}

/**
 * The band while the first read is on its way (SPEC 10): the three labels
 * over skeleton bars, in the loaded band's own cells and grid, so its shape
 * doesn't jump when the page arrives (D70).
 */
export function StatusBandSkeleton() {
  const bar = 'rounded-md bg-temper-surface';
  return (
    <section
      aria-labelledby="glance-band-title"
      aria-busy="true"
      className={cn(teamCard, 'glance-band min-w-0 overflow-hidden')}
      data-testid="glance-band-loading"
    >
      <h2 id="glance-band-title" className="sr-only">
        Status
      </h2>
      <div className="glance-band-grid min-w-0">
        {['Now', 'You', 'Spend'].map((label) => (
          <div key={label} className={cn('gap-1', CELL, label === 'Now' && 'glance-edge-left')} data-testid="glance-band-loading-cell">
            <h3 className={LABEL}>{label}</h3>
            <div className={cn(bar, 'my-1 h-6 w-[70%]')} aria-hidden="true" />
            <div className={cn(bar, 'my-1 h-4 w-[90%]')} aria-hidden="true" />
          </div>
        ))}
      </div>
    </section>
  );
}

export function StatusBand({
  run,
  now,
  agesAt = now,
  staleFor = null,
  wait,
  sender,
  limits,
  executionId,
  lastAt,
}: {
  run: GlanceRun;
  /** Temper's clock: durations count to it. */
  now: number | null;
  /** D105: the newest time Temper recorded in the loaded reply and feed (lastRecordedAt). */
  lastAt?: string | null;
  /** The clock every "ago" counts to: Temper's, plus the time it hasn't answered (D64). */
  agesAt?: number | null;
  /** How long Temper hasn't answered ("2 min"), while it doesn't. */
  staleFor?: string | null;
  wait: TeamWait | null;
  sender: TeamAnswerSender;
  limits: TeamStatus['limits'] | null;
  executionId: string;
}) {
  const stale = staleFor !== null;
  return (
    <section
      aria-labelledby="glance-band-title"
      className={cn(teamCard, 'glance-band min-w-0 overflow-hidden')}
      data-testid="glance-band"
    >
      <h2 id="glance-band-title" className="sr-only">
        Status
      </h2>
      {/* SPEC layout table: stacked on a phone; Now across the top with You and Spend under it; one row of three once the band is 900 px wide (glance.css). */}
      <div className="glance-band-grid min-w-0">
        <NowBox run={run} agesAt={agesAt} stale={stale} lastAt={lastAt} />
        <YouBox
          run={run}
          wait={wait}
          sender={sender}
          limits={limits}
          executionId={executionId}
          rawLeader={run.leader}
          staleFor={staleFor}
        />
        <SpendBox run={run} />
      </div>
    </section>
  );
}
