/**
 * The Team page's part B: answering Temper from the needs-you card, Stop
 * run, and how an ended run reads. On the fixtures the routes really
 * answered (frontend/e2e/fixtures/team, made by
 * scripts/capture_team_fixtures.py). Nothing here starts a server.
 */
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { TeamApiError, TeamNoAnswerError } from '@/lib/teamApi';
import {
  answerFailed,
  answerRequestId,
  answerSent,
  checkAnswer,
  resultPlace,
  teamWaits,
  type AnswerTry,
} from '@/lib/teamAnswer';
import { branchWords, outcomeTitle, runListExplanation, stopAction, stopAnswerRunList } from '@/lib/teamOutcome';
import { waitTitle } from '@/lib/teamText';
import TeamRunView from '@/pages/team/TeamRunView';
import type { TeamAnswerOption, TeamAnswerResult, TeamRun } from '@/types/team';

import answer200Guide from '../../e2e/fixtures/team/answer-200-guide.json';
import answer200NeedsResume from '../../e2e/fixtures/team/answer-200-needs-resume.json';
import answer200Repeated from '../../e2e/fixtures/team/answer-200-repeated.json';
import answer200Stop from '../../e2e/fixtures/team/answer-200-stop.json';
import answer400GuidanceTooLong from '../../e2e/fixtures/team/answer-400-guidance-too-long.json';
import answer400GuideNeedsWords from '../../e2e/fixtures/team/answer-400-guide-needs-words.json';
import answer400NotAnAnswer from '../../e2e/fixtures/team/answer-400-not-an-answer.json';
import answer400NudgeTooLong from '../../e2e/fixtures/team/answer-400-nudge-too-long.json';
import answer400ReplyNeedsWords from '../../e2e/fixtures/team/answer-400-reply-needs-words.json';
import answer400ReplyTooLong from '../../e2e/fixtures/team/answer-400-reply-too-long.json';
import answer400StopTooLong from '../../e2e/fixtures/team/answer-400-stop-reason-too-long.json';
import answer400TakesNoWords from '../../e2e/fixtures/team/answer-400-takes-no-words.json';
import answer401 from '../../e2e/fixtures/team/answer-401.json';
import answer403 from '../../e2e/fixtures/team/answer-403.json';
import answer404AfterStop from '../../e2e/fixtures/team/answer-404-after-stop.json';
import answer404 from '../../e2e/fixtures/team/answer-404-no-longer-open.json';
import answer409Answered from '../../e2e/fixtures/team/answer-409-already-answered.json';
import answer409Rejected from '../../e2e/fixtures/team/answer-409-already-rejected.json';
import answer409AskedAgainOld from '../../e2e/fixtures/team/answer-409-asked-again-old.json';
import answer409NotAskedYet from '../../e2e/fixtures/team/answer-409-not-asked-yet.json';
import answer409Replaced from '../../e2e/fixtures/team/answer-409-replaced.json';
import answer409Reused from '../../e2e/fixtures/team/answer-409-request-id-reused.json';
import cancel200 from '../../e2e/fixtures/team/cancel-200.json';
import cancel400 from '../../e2e/fixtures/team/cancel-400-too-long.json';
import cancel404 from '../../e2e/fixtures/team/cancel-404.json';
import cancelEnded from '../../e2e/fixtures/team/cancel-ended.json';
import runCancelled from '../../e2e/fixtures/team/run-cancelled.json';
import runCancelledByCi from '../../e2e/fixtures/team/run-cancelled-by-ci.json';
import runDidntStart from '../../e2e/fixtures/team/run-didnt-start.json';
import runDone from '../../e2e/fixtures/team/run-done.json';
import runDoneAfterGuide from '../../e2e/fixtures/team/run-done-after-guide.json';
import runDoneBranchNotMade from '../../e2e/fixtures/team/run-done-branch-not-made.json';
import runDoneNoProject from '../../e2e/fixtures/team/run-done-no-project.json';
import runFailed from '../../e2e/fixtures/team/run-failed.json';
import runFailedCantGoOn from '../../e2e/fixtures/team/run-failed-cant-go-on.json';
import runAskedAgain from '../../e2e/fixtures/team/run-member-waiting-asked-again.json';
import runMemberWaitingFailed from '../../e2e/fixtures/team/run-member-waiting-failed.json';
import runQuestion from '../../e2e/fixtures/team/run-member-waiting-question.json';
import runCutOff from '../../e2e/fixtures/team/run-member-waiting.json';
import runUsageLimit from '../../e2e/fixtures/team/run-member-waiting-usage-limit.json';
import runPaused from '../../e2e/fixtures/team/run-paused.json';
import runTwoWaits from '../../e2e/fixtures/team/run-paused-two-waits.json';
import runQuiet from '../../e2e/fixtures/team/run-quiet.json';
import runRunning from '../../e2e/fixtures/team/run-running.json';
import runStopped from '../../e2e/fixtures/team/run-stopped.json';
import runStoppedByUnknown from '../../e2e/fixtures/team/run-stopped-by-unknown.json';
import runStoppedQuiet from '../../e2e/fixtures/team/run-stopped-quiet.json';
import runStoppedRecovery from '../../e2e/fixtures/team/run-stopped-recovery.json';
import statusOn from '../../e2e/fixtures/team/status-on.json';

interface Answer {
  status: number;
  body: unknown;
}

/** A POST that never gets a reply (the network failed). */
const NO_REPLY = 'no reply' as const;
type Reply = Answer | typeof NO_REPLY;

const asRun = (fixture: { body: unknown }) => fixture.body as TeamRun;

interface Sent {
  path: string;
  body: Record<string, unknown>;
}

/**
 * Serve the Team routes from fixtures. Each list hands out its answers in
 * order and repeats the last one: `run` for the reads of the run, `answer`
 * for team_answer and `cancel` for Stop run. Every POST is kept in `sent`.
 */
function serve({
  run = [runPaused],
  answer = [answer200Guide],
  cancel = [cancel200],
}: {
  run?: Answer[];
  answer?: Reply[];
  cancel?: Reply[];
} = {}) {
  const counts = { run: 0, answer: 0, cancel: 0 };
  const sent: Sent[] = [];
  const next = <T,>(list: T[], key: keyof typeof counts): T => list[Math.min(counts[key]++, list.length - 1)];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = new URL(String(input), 'http://temper.test').pathname;
    const method = (init?.method ?? 'GET').toUpperCase();
    let reply: Reply;
    if (method === 'POST') {
      sent.push({ path, body: JSON.parse(String(init?.body ?? '{}')) });
      if (/^\/api\/team\/runs\/[^/]+\/waits\/[^/]+\/answer$/.test(path)) reply = next(answer, 'answer');
      else if (/^\/api\/runs\/[^/]+\/cancel$/.test(path)) reply = next(cancel, 'cancel');
      else reply = { status: 500, body: { detail: `not served by this test: POST ${path}` } };
    } else if (path === '/api/team/status') reply = statusOn;
    else if (/^\/api\/team\/runs\/[^/]+$/.test(path)) reply = next(run, 'run');
    else reply = { status: 500, body: { detail: `not served by this test: ${path}` } };
    if (reply === NO_REPLY) throw new TypeError('Failed to fetch');
    return new Response(JSON.stringify(reply.body), {
      status: reply.status,
      headers: { 'content-type': 'application/json' },
    });
  });
  vi.stubGlobal('fetch', fetchMock);
  return { fetchMock, sent, counts };
}

function showRun(fixture: { body: unknown }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/team/runs/${asRun(fixture).execution_id}`]}>
        <Routes>
          <Route path="/team/runs/:executionId" element={<TeamRunView />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** The needs-you card, once the run is on screen. */
async function card(title: string) {
  const heading = await screen.findByRole('heading', { name: title });
  const section = heading.closest('section');
  if (!section) throw new Error('the needs-you card has no section');
  return within(section);
}

function pick(answer: string) {
  fireEvent.click(screen.getByRole('radio', { name: new RegExp(`^${answer}\\b`) }));
}

function send() {
  fireEvent.click(screen.getByRole('button', { name: /^(Send answer|Stop the team…)$/ }));
}

/** The result note of the last send, once Temper's reply is in. */
async function result() {
  const note = await vi.waitFor(() => {
    const el = document.getElementById('team-answer-result');
    if (!el) throw new Error('no result yet');
    return el;
  });
  return note;
}

/** What the page shows of a refusal: Temper's words, exactly as sent. */
function refusalWordsOf(fixture: { body: unknown }): string {
  const body = fixture.body as { problem?: string; message?: string; detail?: string };
  return body.problem ?? body.message ?? body.detail ?? '';
}

beforeEach(() => {
  vi.unstubAllGlobals();
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

// --- the checks made before a send --------------------------------------------------

const opt = (answer: string, needs_text: TeamAnswerOption['needs_text']): TeamAnswerOption => ({
  answer,
  needs_text,
  means: '',
});
const PAUSE = { kind: 'pause', member: null } as const;
const QUESTION = { kind: 'question', member: 'maker' } as const;

describe('answer checks', () => {
  it('asks for an answer first when none is picked', () => {
    expect(checkAnswer(null, 'anything', PAUSE, 'lead', null)).toEqual({
      ok: false,
      field: 'answers',
      words: 'Pick an answer first.',
    });
  });

  it('asks for the words an answer needs, saying who they are for', () => {
    expect(checkAnswer(opt('guide', 'required'), '', PAUSE, 'lead', null)).toEqual({
      ok: false,
      field: 'words',
      words: 'Write the words for lead first.',
    });
    expect(checkAnswer(opt('reply', 'required'), '   \n ', QUESTION, 'lead', null)).toEqual({
      ok: false,
      field: 'words',
      words: 'Write your reply to maker first.',
    });
  });

  it('lets optional words be left out, and sends spaces as no words', () => {
    expect(checkAnswer(opt('stop', 'optional'), '', PAUSE, 'lead', null)).toEqual({ ok: true, text: '' });
    expect(checkAnswer(opt('nudge', 'optional'), '  ', PAUSE, 'lead', null)).toEqual({ ok: true, text: '' });
    expect(checkAnswer(opt('stop', 'optional'), 'Enough for now.', PAUSE, 'lead', null)).toEqual({
      ok: true,
      text: 'Enough for now.',
    });
  });

  it('sends no words with an answer that takes none', () => {
    expect(checkAnswer(opt('continue', 'none'), 'left over', PAUSE, 'lead', null)).toEqual({ ok: true, text: '' });
  });

  it("stops words over the limit before sending, counting as the server counts", () => {
    const limits = statusOn.body.limits;
    expect(checkAnswer(opt('guide', 'required'), 'a'.repeat(20_000), PAUSE, 'lead', limits).ok).toBe(true);
    // An emoji is one character, as the server counts it.
    expect(checkAnswer(opt('guide', 'required'), '\u{1F642}'.repeat(20_000), PAUSE, 'lead', limits).ok).toBe(true);
    expect(checkAnswer(opt('guide', 'required'), 'a'.repeat(20_001), PAUSE, 'lead', limits)).toEqual({
      ok: false,
      field: 'words',
      words: 'Shorten your words first: they are 1 character over the limit of 20,000.',
    });
    expect(checkAnswer(opt('reply', 'required'), 'a'.repeat(20_002), QUESTION, 'lead', limits)).toEqual({
      ok: false,
      field: 'words',
      words: 'Shorten your reply first: it is 2 characters over the limit of 20,000.',
    });
    expect(checkAnswer(opt('nudge', 'optional'), 'a'.repeat(4_001), PAUSE, 'lead', limits)).toMatchObject({
      words: 'Shorten your words first: they are 1 character over the limit of 4,000.',
    });
    expect(checkAnswer(opt('stop', 'optional'), 'a'.repeat(2_003), PAUSE, 'lead', limits)).toMatchObject({
      words: 'Shorten your words first: they are 3 characters over the limit of 2,000.',
    });
  });

  it('uses the limits Temper sends', () => {
    expect(checkAnswer(opt('nudge', 'optional'), 'a'.repeat(11), PAUSE, 'lead', { nudge_max_chars: 10 })).toMatchObject(
      { words: 'Shorten your words first: they are 1 character over the limit of 10.' },
    );
  });
});

// --- one request id per answer --------------------------------------------------------

describe('request ids', () => {
  const ids = ['id-1', 'id-2', 'id-3'];
  const make = () => ids.shift() ?? 'id-more';

  it('gives each answer its own id, and the same one again only for a retry of the same answer', () => {
    const first = answerRequestId(null, 'w1', 'guide', 'Focus.', make);
    expect(first).toBe('id-1');
    const last: AnswerTry = { requestId: first, waitId: 'w1', answer: 'guide', text: 'Focus.' };
    expect(answerRequestId(last, 'w1', 'guide', 'Focus.', make)).toBe('id-1');
    expect(answerRequestId(last, 'w1', 'guide', 'Focus on saving.', make)).toBe('id-2');
    expect(answerRequestId(last, 'w1', 'stop', 'Focus.', make)).toBe('id-3');
    expect(answerRequestId(last, 'w2', 'guide', 'Focus.', make)).toBe('id-more');
  });
});

// --- Temper's replies, word for word -----------------------------------------------------

/** The error postTeamAnswer throws for a refusal fixture. */
function refusal(fixture: { status: number; body: unknown }): TeamApiError {
  const body = fixture.body as Record<string, unknown>;
  return new TeamApiError(fixture.status, 'detail' in body ? body.detail : body);
}

describe("Temper's replies", () => {
  it.each([
    ['guidance too long', answer400GuidanceTooLong],
    ['guide needs words', answer400GuideNeedsWords],
    ['not an answer', answer400NotAnAnswer],
    ['nudge too long', answer400NudgeTooLong],
    ['reply needs words', answer400ReplyNeedsWords],
    ['reply too long', answer400ReplyTooLong],
    ['reason for stopping too long', answer400StopTooLong],
    ['takes no words', answer400TakesNoWords],
    ['needs a key', answer401],
    ["a run's own key", answer403],
    ['not asked yet', answer409NotAskedYet],
    ['request id reused', answer409Reused],
  ])('shows a refusal in its own words: %s', (_name, fixture) => {
    expect(answerFailed(refusal(fixture), 'r-1')).toEqual({ kind: 'refused', words: refusalWordsOf(fixture) });
  });

  it('says a closed question is no longer open, in its own words', () => {
    for (const fixture of [answer404, answer404AfterStop]) {
      expect(answerFailed(refusal(fixture), 'r-1')).toEqual({
        kind: 'not_open',
        words: 'That question is no longer open',
      });
    }
  });

  it('says who answered first, from where and when', () => {
    expect(answerFailed(refusal(answer409Answered), 'r-1')).toEqual({
      kind: 'answered',
      by: 'owner',
      at: answer409Answered.body.answered_at,
      source: 'team_page',
    });
    expect(answerFailed(refusal(answer409AskedAgainOld), 'r-1')).toEqual({
      kind: 'answered',
      by: 'unknown caller',
      at: answer409AskedAgainOld.body.answered_at,
      source: 'api',
    });
  });

  it('tells a replaced question and an ended team apart', () => {
    expect(answerFailed(refusal(answer409Replaced), 'r-1')).toEqual({ kind: 'replaced' });
    expect(answerFailed(refusal(answer409Rejected), 'r-1')).toEqual({ kind: 'ended' });
  });

  it('keeps the request id when no reply came', () => {
    expect(answerFailed(new TeamNoAnswerError(), 'r-7')).toEqual({ kind: 'no_answer', requestId: 'r-7' });
  });

  it("shows NEEDS_RESUME in Temper's words, and a repeated answer as counted once", () => {
    expect(answerSent(answer200NeedsResume.body as TeamAnswerResult)).toEqual({
      kind: 'needs_resume',
      answer: 'guide',
      message:
        'Approved and kept. The run is not running, so it needs Resume; when it comes back it goes on with this answer without asking again.',
    });
    expect(answerSent(answer200Repeated.body as TeamAnswerResult)).toMatchObject({ kind: 'sent', repeated: true });
    expect(answerSent(answer200Stop.body as TeamAnswerResult)).toMatchObject({ kind: 'sent', answer: 'stop' });
  });
});

// --- which question and where a result shows ----------------------------------------------

describe('questions', () => {
  it('offers only the question Temper asks now; the others come after it', () => {
    const { wait, next } = teamWaits(asRun(runTwoWaits));
    expect(wait?.kind).toBe('pause');
    expect(next.map((w) => w.kind)).toEqual(['question']);
    expect(teamWaits(asRun(runStopped)).wait).toBeNull();
  });

  it('shows a result in the card, alone where the card was, or not at all once the owner moved on', () => {
    expect(resultPlace('w1', 'w1', null)).toBe('card');
    expect(resultPlace('w1', null, null)).toBe('alone');
    expect(resultPlace('w1', 'w2', ['w2'])).toBe('alone');
    expect(resultPlace('w1', 'w2', [])).toBe('none');
    expect(resultPlace(null, 'w2', null)).toBe('none');
  });

  it('titles each kind of question', () => {
    expect(waitTitle(asRun(runPaused).open_waits[0])).toBe(`Paused after round ${asRun(runPaused).open_waits[0].round}`);
    expect(waitTitle(asRun(runQuiet).open_waits[0])).toBe('Quiet: the team has nothing left to do');
    expect(waitTitle(asRun(runCutOff).open_waits[0])).toBe("lead's turn 1 was cut off");
    expect(waitTitle(asRun(runUsageLimit).open_waits[0])).toMatch(/^lead's turn \d+ was cut off by a usage limit$/);
    expect(waitTitle(asRun(runMemberWaitingFailed).open_waits[0])).toMatch(/^lead's turn \d+ failed$/);
    expect(waitTitle(asRun(runQuestion).open_waits[0])).toMatch(/^maker asks you/);
  });
});

// --- the needs-you card -----------------------------------------------------------------

describe('needs-you card', () => {
  const pauseTitle = waitTitle(asRun(runPaused).open_waits[0]);

  it("opens with nothing picked and Temper's question and answers word for word", async () => {
    serve();
    showRun(runPaused);
    const c = await card(pauseTitle);
    expect(c.getByText('Needs you')).toBeInTheDocument();
    // The header row starts with the "Needs you" chip, then the kind's title (spec 5.2).
    expect(c.getByText('Needs you').parentElement).toContainElement(c.getByRole('heading', { level: 2, name: pauseTitle }));
    const wait = asRun(runPaused).open_waits[0];
    expect(c.getByText(wait.question!)).toBeInTheDocument();
    for (const a of wait.answers) expect(c.getByText(a.means)).toBeInTheDocument();
    for (const radio of c.getAllByRole('radio')) expect(radio).not.toBeChecked();
    expect(c.getByRole('radio', { name: 'guide · needs words' })).toBeInTheDocument();
    expect(c.getByRole('radio', { name: 'stop · words optional' })).toBeInTheDocument();
    expect(c.getByRole('radio', { name: 'continue' })).toBeInTheDocument();
    // Send is enabled even with nothing picked: the page says what's missing.
    expect(c.getByRole('button', { name: 'Send answer' })).toBeEnabled();
  });

  it('says to pick an answer first, sends nothing and puts the focus on the first answer', async () => {
    const { sent } = serve();
    showRun(runPaused);
    const c = await card(pauseTitle);
    send();
    expect(c.getByText('Pick an answer first.')).toBeInTheDocument();
    expect(c.getAllByRole('radio')[0]).toHaveFocus();
    expect(c.getByRole('group', { name: 'Your answer' })).toHaveAccessibleDescription('Pick an answer first.');
    expect(sent).toHaveLength(0);
  });

  it('asks for the words guide needs under the words box, and sends nothing', async () => {
    const { sent } = serve();
    showRun(runPaused);
    const c = await card(pauseTitle);
    pick('guide');
    const box = c.getByLabelText('Words for lead');
    expect(box).toHaveAttribute('aria-required', 'true');
    send();
    expect(c.getByText('Write the words for lead first.')).toBeInTheDocument();
    expect(box).toHaveFocus();
    expect(box).toHaveAttribute('aria-invalid', 'true');
    expect(sent).toHaveLength(0);
  });

  it('asks for a reply to the member who asked', async () => {
    const { sent } = serve({ run: [runQuestion] });
    showRun(runQuestion);
    const c = await card(waitTitle(asRun(runQuestion).open_waits[0]));
    pick('reply');
    send();
    expect(c.getByText('Write your reply to maker first.')).toBeInTheDocument();
    expect(sent).toHaveLength(0);
  });

  it('stops words over the limit before sending, with the count saying how far over', async () => {
    const { sent } = serve({ run: [runQuiet] });
    showRun(runQuiet);
    const c = await card('Quiet: the team has nothing left to do');
    pick('nudge');
    fireEvent.change(c.getByLabelText('Words for lead'), { target: { value: 'a'.repeat(4_002) } });
    expect(c.getByText('4,002 / 4,000 · 2 over')).toBeInTheDocument();
    send();
    expect(c.getByText('Shorten your words first: they are 2 characters over the limit of 4,000.')).toBeInTheDocument();
    expect(sent).toHaveLength(0);
  });

  it('sends the picked answer with its words and a request id, then reads the run again', async () => {
    const { sent, counts } = serve({ run: [runPaused, runRunning] });
    showRun(runPaused);
    const c = await card(pauseTitle);
    pick('guide');
    fireEvent.change(c.getByLabelText('Words for lead'), {
      target: { value: 'Focus on the saving line; the rest is fine.' },
    });
    const readsBefore = counts.run;
    send();
    const note = await result();
    expect(note).toHaveTextContent('Answer sent: guide.');
    expect(note).toHaveTextContent('Temper has it. The page shows what happens next.');
    expect(sent).toHaveLength(1);
    const wait = asRun(runPaused).open_waits[0];
    expect(sent[0].path).toBe(`/api/team/runs/${asRun(runPaused).execution_id}/waits/${wait.wait_id}/answer`);
    expect(sent[0].body).toEqual({
      request_id: expect.any(String),
      answer: 'guide',
      text: 'Focus on the saving line; the rest is fine.',
    });
    await vi.waitFor(() => expect(counts.run).toBeGreaterThan(readsBefore));
    // The question closed: the card is gone, the result stays where it was.
    await vi.waitFor(() => expect(screen.queryByRole('heading', { name: pauseTitle })).toBeNull());
    expect(document.getElementById('team-answer-result')).toHaveTextContent('Answer sent: guide.');
  });

  it('sends the same request id again after no reply, so Temper counts the answer once', async () => {
    const { sent } = serve({ answer: [NO_REPLY, answer200Repeated] });
    showRun(runPaused);
    const c = await card(pauseTitle);
    pick('guide');
    fireEvent.change(c.getByLabelText('Words for lead'), { target: { value: 'Focus.' } });
    send();
    const failed = await result();
    expect(failed).toHaveTextContent("Temper didn't answer.");
    expect(failed).toHaveTextContent('Trying again is safe: the same request counts once.');
    const firstId = String(sent[0].body.request_id);
    expect(failed).toHaveTextContent(`Request ${firstId.slice(0, 8)} · your inputs are kept.`);
    // The words are kept for the retry.
    expect(c.getByLabelText('Words for lead')).toHaveValue('Focus.');
    send();
    await vi.waitFor(() => expect(sent).toHaveLength(2));
    expect(sent[1].body.request_id).toBe(firstId);
    expect(await screen.findByText('Temper already had it from your last try; it counted once.')).toBeInTheDocument();
  });

  it('gives a new answer a new request id once Temper has replied', async () => {
    const { sent } = serve({ answer: [answer400NotAnAnswer, answer200Guide] });
    showRun(runPaused);
    const c = await card(pauseTitle);
    pick('guide');
    fireEvent.change(c.getByLabelText('Words for lead'), { target: { value: 'Focus.' } });
    send();
    await result();
    send();
    await vi.waitFor(() => expect(sent).toHaveLength(2));
    expect(sent[1].body.request_id).not.toBe(sent[0].body.request_id);
  });

  it.each([
    ['guidance too long', answer400GuidanceTooLong],
    ['not an answer', answer400NotAnAnswer],
    ['takes no words', answer400TakesNoWords],
    ['needs a key', answer401],
    ["a run's own key", answer403],
    ['not asked yet', answer409NotAskedYet],
    ['request id reused', answer409Reused],
  ])("shows Temper's refusal word for word and keeps the words: %s", async (_name, fixture) => {
    serve({ answer: [fixture] });
    showRun(runPaused);
    const c = await card(pauseTitle);
    pick('guide');
    fireEvent.change(c.getByLabelText('Words for lead'), { target: { value: 'Focus.' } });
    send();
    const note = await result();
    expect(note).toHaveTextContent('Temper refused the answer:');
    expect(note).toHaveTextContent(`${refusalWordsOf(fixture)} Your words are kept.`);
    expect(within(note).getByRole('status')).toBeInTheDocument();
    expect(note).toHaveFocus();
    expect(c.getByLabelText('Words for lead')).toHaveValue('Focus.');
  });

  it('after a 409 reads the run again and shows who answered first, from where and when', async () => {
    const { counts } = serve({ run: [runPaused, runDoneAfterGuide], answer: [answer409Answered] });
    showRun(runPaused);
    await card(pauseTitle);
    pick('continue');
    const readsBefore = counts.run;
    send();
    const note = await result();
    expect(note).toHaveTextContent(/^Already answered by\s*You\s*from the dashboard at .+\.Your answer wasn't used\./);
    await vi.waitFor(() => expect(counts.run).toBeGreaterThan(readsBefore));
    await vi.waitFor(() => expect(screen.queryByRole('heading', { name: pauseTitle })).toBeNull());
    expect(document.getElementById('team-answer-result')).toHaveTextContent('Already answered by');
  });

  it('names an unknown caller who answered first through the API', async () => {
    serve({ run: [runAskedAgain], answer: [answer409AskedAgainOld] });
    showRun(runAskedAgain);
    await card(waitTitle(asRun(runAskedAgain).open_waits[0]));
    pick('retry');
    send();
    expect(await result()).toHaveTextContent(/Already answered by\s*an unknown caller\s*through the API at/);
  });

  it('says when a newer question replaced this one, or the team has ended', async () => {
    serve({ answer: [answer409Replaced] });
    showRun(runPaused);
    await card(pauseTitle);
    pick('continue');
    send();
    expect(await result()).toHaveTextContent(
      "This question was replaced by a newer one.Read the new question; your answer wasn't used.",
    );
    cleanup();
    serve({ answer: [answer409Rejected] });
    showRun(runPaused);
    await card(pauseTitle);
    pick('continue');
    send();
    expect(await result()).toHaveTextContent("The team has ended.Your answer wasn't used.");
  });

  it("says a closed question is no longer open, in Temper's words", async () => {
    serve({ answer: [answer404] });
    showRun(runPaused);
    await card(pauseTitle);
    pick('continue');
    send();
    expect(await result()).toHaveTextContent(
      'That question is no longer open.The page refreshes to show what changed.',
    );
  });

  it("says when the answer needs Resume, in Temper's words, with the run page", async () => {
    serve({ answer: [answer200NeedsResume] });
    showRun(runPaused);
    const c = await card(pauseTitle);
    pick('guide');
    fireEvent.change(c.getByLabelText('Words for lead'), { target: { value: 'Focus.' } });
    send();
    const note = await result();
    expect(note).toHaveTextContent(`Answer kept: guide.${answer200NeedsResume.body.message}`);
    expect(within(note).getByRole('link', { name: 'Open the run page' })).toHaveAttribute(
      'href',
      `/workflow/${asRun(runPaused).execution_id}`,
    );
  });

  it('asks before stopping the team: Keep the team sends nothing, Stop the team sends stop with the words', async () => {
    const { sent } = serve({ answer: [answer200Stop] });
    showRun(runPaused);
    const c = await card(pauseTitle);
    const shownWith = "Shown quoted with the outcome, labelled as yours, beside Temper's reason.";
    expect(c.queryByText('You confirm in the next step.')).toBeNull();
    pick('stop');
    expect(c.getByRole('button', { name: 'Stop the team…' })).toBeEnabled();
    // Design's words for a stop picked in the card (boards O1c, O1f).
    expect(c.getByLabelText('Your words with the stop')).toHaveAccessibleDescription(new RegExp(shownWith.replace('.', '\\.')));
    expect(c.getByText(shownWith)).toBeInTheDocument();
    expect(c.getByText('You confirm in the next step.')).toBeInTheDocument();
    fireEvent.change(c.getByLabelText('Your words with the stop'), {
      target: { value: 'We have what we need for now.' },
    });
    send();
    let dialog = await screen.findByRole('alertdialog', { name: 'Stop the team at this question?' });
    expect(within(dialog).getByText('The team ends here and nothing more is spent.')).toBeInTheDocument();
    expect(within(dialog).getByText(stopAnswerRunList('pause')!)).toBeInTheDocument();
    expect(within(dialog).getByText('We have what we need for now.')).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Keep the team' }));
    expect(screen.queryByRole('alertdialog')).toBeNull();
    expect(sent).toHaveLength(0);

    send();
    dialog = await screen.findByRole('alertdialog', { name: 'Stop the team at this question?' });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Stop the team' }));
    await vi.waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0].body).toMatchObject({ answer: 'stop', text: 'We have what we need for now.' });
  });

  it('says that a stop at a failed turn shows as failed in the run list', async () => {
    serve({ run: [runMemberWaitingFailed] });
    showRun(runMemberWaitingFailed);
    await card(waitTitle(asRun(runMemberWaitingFailed).open_waits[0]));
    pick('stop');
    send();
    const dialog = await screen.findByRole('alertdialog', { name: 'Stop the team at this question?' });
    expect(within(dialog).getByText(stopAnswerRunList('recovery')!)).toBeInTheDocument();
    expect(within(dialog).queryByText(stopAnswerRunList('pause')!)).toBeNull();
  });

  it("words the stop confirm's run-list line by the kind of question, as Design wrote it", () => {
    expect(stopAnswerRunList('pause')).toBe(
      "The run list will show this run as cancelled, like Stop run. This page shows Stopped, with Temper's reason and your words.",
    );
    expect(stopAnswerRunList('stalled')).toBe(stopAnswerRunList('pause'));
    expect(stopAnswerRunList('recovery')).toBe(
      "The run list will show this run as failed: Temper records a stop at a member's failed or unfinished turn as failed. This page shows Stopped, with Temper's reason and your words.",
    );
    // A kind Design hasn't worded yet gets no run-list line rather than a guess.
    expect(stopAnswerRunList('settings')).toBeNull();
  });

  it('answers only the question Temper asks now, and lists the next one', async () => {
    serve({ run: [runTwoWaits] });
    showRun(runTwoWaits);
    const c = await card(pauseTitle);
    expect(c.getByText('Temper asks one question at a time. This one comes next, after you answer:')).toBeInTheDocument();
    expect(c.getByText('Next')).toBeInTheDocument();
    // Only the pause's answers can be picked.
    expect(c.getAllByRole('radio').map((r) => (r as HTMLInputElement).value)).toEqual(['continue', 'guide', 'stop']);
  });

  it('says when Temper asked again, above its question', async () => {
    serve({ run: [runAskedAgain] });
    showRun(runAskedAgain);
    const wait = asRun(runAskedAgain).open_waits[0];
    const c = await card(waitTitle(wait));
    expect(c.getByText('Asked again (1 time)')).toBeInTheDocument();
    expect(
      c.getByText(
        "The last answer wasn't one of the choices, so nothing was decided and Temper asked again. Pick one of the answers.",
      ),
    ).toBeInTheDocument();
    expect(c.getByText(wait.question!)).toBeInTheDocument();
  });

  it("explains that the team's quiet is not the run list's quiet mark", async () => {
    serve({ run: [runQuiet] });
    showRun(runQuiet);
    const c = await card('Quiet: the team has nothing left to do');
    expect(
      c.getByText(/Not the run list.s .quiet. mark: that one means Temper has heard nothing from a run for a while\./),
    ).toBeInTheDocument();
  });

  it("shows why a turn was cut off, in Temper's words", async () => {
    serve({ run: [runUsageLimit] });
    showRun(runUsageLimit);
    const wait = asRun(runUsageLimit).open_waits[0];
    const c = await card(waitTitle(wait));
    expect(c.getByText(wait.why!)).toBeInTheDocument();
  });

  it('shows untrusted words as text, never as HTML', async () => {
    const run = structuredClone(asRun(runQuestion));
    run.open_waits[0].question = '<img src="x" onerror="alert(1)"><script>alert(2)</script> Plain?';
    serve({ run: [{ status: 200, body: run }] });
    const { container } = showRun({ body: run });
    const c = await card(waitTitle(run.open_waits[0]));
    expect(c.getByText(run.open_waits[0].question)).toBeInTheDocument();
    expect(container.querySelector('img, script')).toBeNull();
  });
});

// --- Stop run -----------------------------------------------------------------------------

describe('Stop run', () => {
  async function openStop(fixture: { body: unknown } = runPaused) {
    showRun(fixture);
    fireEvent.click(await screen.findByRole('button', { name: 'Stop run' }));
    return within(await screen.findByRole('alertdialog', { name: /^Stop run:/ }));
  }

  it('asks first, says what stops, and starts on the reason', async () => {
    serve();
    const d = await openStop();
    expect(d.getByText(asRun(runPaused).workflow)).toBeInTheDocument();
    expect(d.getByText("Every member's turn ends, and any open question is closed with your reason.")).toBeInTheDocument();
    expect(d.getByText('Nothing more is spent.')).toBeInTheDocument();
    expect(d.getByLabelText('Your reason')).toHaveFocus();
    expect(d.getByText('0 / 2,000')).toBeInTheDocument();
  });

  it('Keep running sends nothing', async () => {
    const { sent } = serve();
    const d = await openStop();
    fireEvent.click(d.getByRole('button', { name: 'Keep running' }));
    expect(screen.queryByRole('alertdialog')).toBeNull();
    expect(sent).toHaveLength(0);
  });

  it('stops the run with the reason, through the cancel route', async () => {
    const { sent } = serve({ run: [runPaused, runCancelled] });
    const d = await openStop();
    fireEvent.change(d.getByLabelText('Your reason'), { target: { value: 'Wrong goal; starting over.' } });
    expect(d.getByText('26 / 2,000')).toBeInTheDocument();
    fireEvent.click(d.getByRole('button', { name: 'Stop run' }));
    await vi.waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]).toEqual({
      path: `/api/runs/${asRun(runPaused).execution_id}/cancel`,
      body: { reason: 'Wrong goal; starting over.' },
    });
    await vi.waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull());
  });

  it('stops a reason over the limit before sending', async () => {
    const { sent } = serve();
    const d = await openStop();
    fireEvent.change(d.getByLabelText('Your reason'), { target: { value: 'a'.repeat(2_001) } });
    expect(d.getByText('2,001 / 2,000 · 1 over')).toBeInTheDocument();
    fireEvent.click(d.getByRole('button', { name: 'Stop run' }));
    expect(d.getByText('Shorten your reason first: it is 1 character over the limit of 2,000.')).toBeInTheDocument();
    expect(d.getByLabelText('Your reason')).toHaveFocus();
    expect(sent).toHaveLength(0);
  });

  it.each([
    ['no such run', cancel404],
    ['reason too long', cancel400],
  ])("shows Temper's refusal word for word, and stays open: %s", async (_name, fixture) => {
    serve({ cancel: [fixture] });
    const d = await openStop();
    fireEvent.click(d.getByRole('button', { name: 'Stop run' }));
    const note = await d.findByRole('status');
    expect(note).toHaveTextContent(`Temper refused: ${refusalWordsOf(fixture)} Nothing was stopped.`);
    expect(screen.getByRole('alertdialog')).toBeInTheDocument();
  });

  it('says nothing was stopped when the run had already ended, with one Close button (G13)', async () => {
    serve({ run: [runPaused, runDone], cancel: [cancelEnded] });
    const d = await openStop();
    fireEvent.change(d.getByLabelText('Your reason'), { target: { value: 'Enough.' } });
    fireEvent.click(d.getByRole('button', { name: 'Stop run' }));
    const note = await d.findByRole('status');
    // The run list's own badge names the status.
    expect(note).toHaveTextContent(
      /^Nothing was stopped\. The run had already ended \(\S*\s*completed\) before your stop reached Temper\. Your reason wasn't recorded\.$/,
    );
    expect(d.queryByRole('button', { name: 'Stop run' })).toBeNull();
    expect(d.queryByRole('button', { name: 'Keep running' })).toBeNull();
    const close = d.getAllByRole('button', { name: 'Close' }).at(-1)!;
    await vi.waitFor(() => expect(close).toHaveFocus());
  });

  it('leaves out the reason line when no reason was typed', async () => {
    serve({ run: [runPaused, runDone], cancel: [cancelEnded] });
    const d = await openStop();
    fireEvent.click(d.getByRole('button', { name: 'Stop run' }));
    const note = await d.findByRole('status');
    expect(note).not.toHaveTextContent("Your reason wasn't recorded.");
  });

  it('is not offered once the run has ended', async () => {
    serve({ run: [runDone] });
    showRun(runDone);
    await screen.findByRole('heading', { name: "Done: the leader's version was approved" });
    expect(screen.queryByRole('button', { name: 'Stop run' })).toBeNull();
  });
});

// --- ended runs ---------------------------------------------------------------------------

describe('ended runs', () => {
  it('words the run list status from run_status, never from the kind of question', () => {
    // Both lists say cancelled: no note.
    expect(runListExplanation(asRun(runCancelled))).toBeNull();
    expect(runListExplanation(asRun(runStopped))).toBeNull();
    expect(runListExplanation(asRun(runStoppedQuiet))).toBeNull();
    expect(runListExplanation(asRun(runStoppedRecovery))).toBe(
      "Why the run list says failed: Temper records a team stopped at a member's failed or unfinished turn as failed. Here the stop was a choice, not a crash: who stopped it and why are on the left.",
    );
    expect(runListExplanation(asRun(runDone))).toBeNull();
    expect(runListExplanation(asRun(runFailed))).toBeNull();
  });

  it('finds the stop that ended the team, by the kind of decision', () => {
    expect(stopAction(asRun(runCancelled))?.kind).toBe('stop');
    expect(stopAction(asRun(runStopped))).toMatchObject({ kind: 'answer', detail: { answer: 'stop' } });
    expect(stopAction(asRun(runDone))).toBeNull();
  });

  it('says where the approved version went', () => {
    expect(branchWords(null, null).kind).toBe('none');
    expect(branchWords({ name: 'team/x', made: true, why: null }, 'notes-app').words).toBe(
      'team/x in notes-app, at the approved commit (a local branch)',
    );
    expect(branchWords({ name: 'team/x', made: false, why: 'exists' }, 'notes-app').words).toBe(
      "branch not made: exists · the approved commit stays fetchable from Temper's kept copy.",
    );
  });

  it.each([
    ['done', runDone],
    ['stopped', runStopped],
    ['failed', runFailed],
    ['didnt_start', runDidntStart],
  ])('titles the %s outcome', (state, fixture) => {
    expect(asRun(fixture).state).toBe(state);
    expect(outcomeTitle(state)).not.toBe('');
  });

  async function outcome(fixture: { body: unknown }) {
    serve({ run: [fixture as Answer] });
    showRun(fixture);
    const title = outcomeTitle(asRun(fixture).state);
    const heading = await screen.findByRole('heading', { name: title, level: 2 });
    return within(heading.closest('section')!);
  }

  it("shows a stopped team: Temper's reason, who stopped it from where, their words and the run list", async () => {
    const o = await outcome(runStopped);
    const run = asRun(runStopped);
    expect(o.getByText("Temper's reason")).toBeInTheDocument();
    expect(o.getByText(run.outcome!.reason!)).toBeInTheDocument();
    expect(o.getByText('Stopped by').parentElement).toHaveTextContent(/^Stopped by\s*You\s*from the dashboard\s*·/);
    expect(o.getByText('Your words')).toBeInTheDocument();
    expect(o.getByText(run.outcome!.owner_words!)).toBeInTheDocument();
    // Stopped at the pause: the run list says cancelled too, so there is no note.
    expect(run.run_status).toBe('cancelled');
    expect(o.queryByText(/run list says/i)).toBeNull();
    expect(screen.queryByRole('radio')).toBeNull();
  });

  it('names who stopped it, also an unknown caller and a named key', async () => {
    let o = await outcome(runStoppedByUnknown);
    expect(o.getByText('Stopped by').parentElement).toHaveTextContent(
      /^Stopped by\s*an unknown caller\s*from an unknown place/,
    );
    cleanup();
    o = await outcome(runCancelledByCi);
    expect(o.getByText('Stopped by').parentElement).toHaveTextContent(/^Stopped by\s*temper-ci\s*through the API/);
  });

  it('explains a stop at a failed turn reading failed in the run list', async () => {
    const o = await outcome(runStoppedRecovery);
    expect(o.getByText(runListExplanation(asRun(runStoppedRecovery))!)).toBeInTheDocument();
  });

  it("shows a failed run's reason and problems word for word, and where to retry", async () => {
    const o = await outcome(runFailedCantGoOn);
    const run = asRun(runFailedCantGoOn);
    expect(o.getByText(run.outcome!.reason!)).toBeInTheDocument();
    expect(o.getByText('Resume it from the run page to retry or stop the turn.')).toBeInTheDocument();
  });

  it("shows a team that didn't start, and that nothing was spent", async () => {
    const o = await outcome(runDidntStart);
    expect(o.getByText(asRun(runDidntStart).outcome!.reason!)).toBeInTheDocument();
    expect(o.getByText('Nothing was spent.')).toBeInTheDocument();
  });

  it('shows a done team: summary, branch and the place kept for the debrief', async () => {
    const o = await outcome(runDone);
    const run = asRun(runDone);
    const firstLine = (run.outcome!.done!.summary ?? '').split('\n')[0].replace(/^#+\s*/, '');
    expect(o.getByText(firstLine, { exact: false })).toBeInTheDocument();
    expect(document.querySelector('[data-branch="made"]')).toHaveTextContent(
      /^team\/\S+ in \S+, at the approved commit \(a local branch\)$/,
    );
    expect(screen.getByRole('heading', { name: 'Debrief and lessons' })).toBeInTheDocument();
    expect(screen.getByText('M5, designed later')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Send answer' })).toBeNull();
  });

  it('says when no branch was made, and when there was no project to make one in', async () => {
    let o = await outcome(runDoneBranchNotMade);
    expect(o.getByText(/^branch not made: exists · the approved commit stays fetchable/)).toBeInTheDocument();
    cleanup();
    o = await outcome(runDoneNoProject);
    expect(
      o.getByText('No branch: this trial started from an empty project. Getting its files out comes later.'),
    ).toBeInTheDocument();
  });
});

// --- polling stays out of the way of an answer ------------------------------------------

describe('reading again after a send', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });

  it('keeps reading the run while it waits on you', async () => {
    const { counts } = serve();
    showRun(runPaused);
    await card(waitTitle(asRun(runPaused).open_waits[0]));
    const before = counts.run;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_050);
    });
    expect(counts.run).toBeGreaterThan(before);
    // The owner's pick survives a refresh.
    pick('continue');
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_050);
    });
    expect(screen.getByRole('radio', { name: 'continue' })).toBeChecked();
  });
});
