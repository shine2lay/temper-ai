#!/usr/bin/env node
/**
 * Free-flowing Team fixtures for the glance page.
 *
 * Temper's nine real replies are the source of truth: e2e/fixtures/team/flow/real/
 * holds them unchanged (working, idle, share, check_in, closing, done,
 * done_refused, stalled, failed; each run reply with its -events reply), exported by
 * Temper's FLOW #80 from its real serializers. The states Temper did not send are
 * derived here from one of them, changing only fields Temper's field list
 * (FLOW/api-fields.md) defines. Each derived reply says so in its "_fixture" key:
 * "derived from <real state>: <what changed>".
 *
 * Rules kept for every derived reply:
 * - every new message gets its own message_id (Design D6);
 * - a flow reply has no round and no reviews (Design D21);
 * - events_total is the number of events in the feed; events_cursor is the newest
 *   seq (a position, not a count);
 * - as_of is when the reply was built; ended runs keep a frozen elapsed_s.
 *
 *   node scripts/make_flow_fixtures.mjs   (from frontend/) -> e2e/fixtures/team/flow/derived/
 *   node scripts/make_flow_fixtures.mjs --import-real <serializer-replies-folder>
 *     copies all nine pairs byte for byte, then rebuilds derived states (no server or capture).
 */
import { createHash } from 'node:crypto';
import { mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const FLOW = join(dirname(fileURLToPath(import.meta.url)), '..', 'e2e', 'fixtures', 'team', 'flow');
const REAL = join(FLOW, 'real');
const OUT = join(FLOW, 'derived');

const readJson = (file) => JSON.parse(readFileSync(join(REAL, file), 'utf8'));
const real = (state) => ({ run: readJson(`${state}.json`), feed: readJson(`${state}-events.json`) });
const clone = (x) => structuredClone(x);
/** Temper's nine real replies, each with its -events file. */
const REAL_STATES = ['working', 'idle', 'share', 'check_in', 'closing', 'done', 'done_refused', 'stalled', 'failed'];

// Import only a complete supplied snapshot. Read and validate every source
// before writing anything; never generate, run or edit Temper's serializers.
// --import-snapshot binds the final FLOW, G6 and G7 synthetic exports to their
// unchanged manifests. api-fields.md's documented wording amendment is not a sample.
if (process.argv[2] === '--import-snapshot') {
  if (process.argv.length !== 4) throw new Error('usage: make_flow_fixtures.mjs --import-snapshot <snapshot-folder>');
  const groups = [
    ['INPUTS-f928ed03.sha256', 'api-fixtures', 'real'],
    ['G6-INPUTS.sha256', 'api-fixtures-g6', 'real-g6'],
    ['G7-INPUTS.sha256', 'api-fixtures-g7', 'real-g7'],
  ];
  const pending = [];
  for (const [manifest, source, dest] of groups) {
    const bytes = readFileSync(join(process.argv[3], manifest));
    const lines = bytes.toString('utf8').split('\n').map((line) => /^([0-9a-f]{64}) [ *](.+)$/.exec(line)).filter(Boolean);
    for (const [, hash, name] of lines) {
      if (name === 'api-fields.md') continue; // Separately reviewed documentation amendment.
      const sample = readFileSync(join(process.argv[3], name));
      if (createHash('sha256').update(sample).digest('hex') !== hash) throw new Error(`snapshot hash mismatch: ${name}`);
      if (!name.startsWith(`${source}/`)) continue;
      const body = JSON.parse(sample.toString('utf8'));
      if (name.endsWith('-events.json') ? !Array.isArray(body.events) : body.kind !== 'flow') throw new Error(`invalid reply: ${name}`);
      pending.push({ file: join(FLOW, dest, name.slice(source.length + 1)), bytes: sample });
    }
    pending.push({ file: join(FLOW, dest, manifest), bytes });
  }
  for (const { file, bytes } of pending) {
    mkdirSync(dirname(file), { recursive: true });
    writeFileSync(file, bytes);
  }
  console.log(`Bound ${pending.length - groups.length} unchanged serializer replies and ${groups.length} manifests.`);
  process.exit(0); // Preserve the older, explicitly derived scenario inputs.
}
if (process.argv.length > 2) {
  if (process.argv.length !== 4 || process.argv[2] !== '--import-real') {
    throw new Error('usage: make_flow_fixtures.mjs [--import-real <serializer-replies-folder>]');
  }
  const inputs = REAL_STATES.flatMap((state) => ['', '-events'].map((suffix) => {
    const name = `${state}${suffix}.json`;
    const bytes = readFileSync(join(process.argv[3], name));
    const body = JSON.parse(bytes.toString('utf8'));
    if (suffix ? !Array.isArray(body.events) : body.kind !== 'flow') throw new Error(`invalid serializer reply: ${name}`);
    return { name, bytes };
  }));
  mkdirSync(REAL, { recursive: true });
  for (const { name, bytes } of inputs) writeFileSync(join(REAL, name), bytes);
  console.log(`Imported ${inputs.length} unchanged serializer replies.`);
}

// ---------------------------------------------------------------------------
// Small helpers in Temper's own formats
// ---------------------------------------------------------------------------

/** Temper's times to microseconds and back (2026-10-09T10:12:48.974900+00:00), keeping every digit. */
function micros(time) {
  const [, whole, fraction = '', zone] = /^(.*T\d\d:\d\d:\d\d)(?:\.(\d+))?(.*)$/.exec(time);
  return Date.parse(`${whole}${zone}`) * 1000 + Number(fraction.padEnd(6, '0').slice(0, 6));
}
function iso(us) {
  const whole = new Date(Math.floor(us / 1000)).toISOString().slice(0, 19);
  return `${whole}.${String(us % 1_000_000).padStart(6, '0')}+00:00`;
}
const ms = (time) => micros(time) / 1000;
const later = (time, seconds) => iso(micros(time) + Math.round(seconds * 1_000_000));

/** A 32-hex id like Temper's, the same on every run of this script. */
const hexId = (label) => createHash('md5').update(`flow-fixture:${label}`).digest('hex');

const member = (run, name) => {
  const found = run.members.find((m) => m.name === name);
  if (!found) throw new Error(`no member ${name}`);
  return found;
};

const PHASE_NULLS = {
  since: null, running: 0, asked: false, reason: null, resumes_at: null, resets_known: null,
  usage: null, usage_checked_at: null, resume_verified: false, blocked_windows: [],
};

function setPhase(run, phase) {
  run.phase = { name: phase.name, words: phase.words, ...PHASE_NULLS, ...phase };
}

/** Count the members by state, and the running turns. */
function recount(run) {
  const counts = { members: run.members.length, working: 0, ready: 0, idle: 0, held: 0, failed: 0, ended: 0 };
  for (const m of run.members) counts[m.state] += 1;
  run.counts = counts;
  run.phase.running = counts.working;
}

function setSpend(run, spend) {
  run.spend = { ...run.spend, ...spend };
  run.cost_usd = run.spend.cost_usd;
}

function idleMember(m, at, reason, note) {
  Object.assign(m, {
    state: 'idle',
    activity: 'idle',
    since: at,
    turn_no: null,
    idle_reason: reason,
    idle_note: note,
    tools_now: null,
    ready_messages: 0,
    wait_id: null,
    last_activity_at: at,
  });
}

function workingMember(m, turnNo, at, tools = []) {
  Object.assign(m, {
    state: 'working',
    activity: 'working',
    since: at,
    turn_no: turnNo,
    turns: turnNo,
    idle_reason: null,
    idle_note: null,
    tools_now: tools,
    ready_messages: 0,
    wait_id: null,
    last_turn: {
      turn_no: turnNo,
      state: 'running',
      started_at: at,
      ended_at: null,
      error: null,
      account_slot: null,
      retry_of: null,
      ended_by: null,
    },
    last_activity_at: at,
  });
}

function heldMember(m, waitId, at) {
  Object.assign(m, {
    state: 'held',
    activity: 'waiting_on_owner',
    since: at,
    turn_no: null,
    idle_reason: null,
    idle_note: null,
    tools_now: null,
    wait_id: waitId,
    last_activity_at: at,
  });
}

function endedMember(m, at) {
  Object.assign(m, {
    state: 'ended',
    activity: 'ended',
    since: at,
    turn_no: null,
    idle_reason: null,
    idle_note: null,
    tools_now: null,
    ready_messages: 0,
    wait_id: null,
  });
}

/** Append events after the feed's newest seq. */
function appender(events) {
  let seq = events.length ? events[events.length - 1].seq : 0;
  return (kind, at, who, extra = {}) => {
    seq += 1;
    const event = { seq, at, kind, member: who, ...extra };
    events.push(event);
    return event;
  };
}

/** A message event and its timeline entry, in Temper's shapes. */
function message(add, run, { at, from, fromKind = 'member', to, kind, text, id }) {
  const event = add('message', at, from, {
    from,
    from_kind: fromKind,
    to,
    message_kind: kind,
    text,
    message_id: id,
    mid_turn: false,
  });
  run.timeline.entries.push({
    event_type: `message: ${kind}`,
    from_agent: from,
    to_agent: to,
    timestamp: at,
    data: { message_id: id, state: 'consumed', deliveries: 1, preview: text },
    entry: 'message',
    message_kind: kind,
  });
  return event;
}

/** Timeline entries that copy their event (idle, wake): Temper flattens the event into the entry. */
function eventEntry(run, event) {
  run.timeline.entries.push({
    event_type: event.kind,
    from_agent: event.member,
    timestamp: event.at,
    data: { ...event },
    entry: event.kind,
    ...event,
  });
}

function turnEntry(run, who, turnNo, state, at, endedAt = null) {
  run.timeline.entries.push({
    event_type: `turn ${turnNo}: ${state}`,
    from_agent: who,
    timestamp: at,
    data: { turn_id: hexId(`turn:${run.execution_id}:${who}:${turnNo}`), turn_no: turnNo, state, ended_at: endedAt, account_slot: null },
    entry: 'member_turn',
  });
}

/**
 * A wait's timeline entry (team_leader's owner_wait rows): event_type names the ledger's
 * kind (a member's question is "owner"); data carries the subject's member, turn_no and
 * header where it has them (a recovery's header is team_view's fallback, not the subject's).
 */
function waitEntry(run, wait, state = 'open') {
  run.timeline.entries.push({
    event_type: `owner wait: ${wait.kind === 'question' ? 'owner' : wait.kind}`,
    from_agent: 'temper',
    to_agent: 'owner',
    timestamp: wait.opened_at,
    data: {
      wait_id: wait.wait_id,
      state,
      ...(wait.member ? { member: wait.member, turn_no: wait.turn_no } : {}),
      ...(wait.kind !== 'recovery' ? { header: wait.header } : {}),
    },
    entry: 'owner_wait',
    wait_kind: wait.kind,
  });
}

function answerEntry(run, waitId, waitKind, answer, at) {
  for (const entry of run.timeline.entries) {
    if (entry.entry === 'owner_wait' && entry.data?.wait_id === waitId) entry.data = { ...entry.data, state: 'answered', answer };
  }
  run.timeline.entries.push({
    event_type: `owner answer: ${answer}`,
    from_agent: 'owner',
    timestamp: at,
    data: { wait_id: waitId, answer },
    entry: 'owner_answer',
    wait_kind: waitKind,
    answered_by: 'owner',
    answered_source: 'team_page',
  });
}

function decisionEntry(run, decision, by, reason, at) {
  run.timeline.entries.push({
    event_type: `decision: ${decision}`,
    from_agent: by,
    timestamp: at,
    data: { reason },
    entry: 'decision',
    decision,
  });
}

/** An open wait in Temper's open_waits shape. */
function openWait({ id, kind, header, question, replyHint = null, answers, words, scope, member: who = null, turnNo = null, at, extra = {} }) {
  return {
    wait_id: id,
    event_id: `fixture-gate-${id.slice(0, 6)}`,
    node_name: `build.team~ask-${id}`,
    asked: true,
    kind,
    header,
    question,
    reply_hint: replyHint,
    answers,
    words,
    scope,
    at_usd: null,
    next_check_in_usd: null,
    member: who,
    turn_no: turnNo,
    why: null,
    note: null,
    account_slot: null,
    limit: null,
    resets: null,
    asked_again: 0,
    settings_changes: null,
    pins: null,
    opened_at: at,
    ...extra,
  };
}

/**
 * you.first for a wait (flow_view.you()): the wait's own header (a member's question:
 * "<member> asks", Temper 76a1d5c7); no `note` here, only in open_waits.
 */
const youFirst = (wait) => ({
  wait_id: wait.wait_id,
  kind: wait.kind,
  member: wait.member,
  header: wait.header,
  words: wait.words,
  opened_at: wait.opened_at,
});

/**
 * Temper's one-line words for a wait (team_view.wait_words): the question up to its
 * first ". ", then its first non-empty line, cut to 159 characters + "…" past 160.
 */
function waitWords(question) {
  const first = String(question ?? '').split('. ')[0];
  for (const raw of first.split(/\r\n|[\n\r\v\f\x1c-\x1e\x85\u2028\u2029]/)) {
    const line = raw.trim();
    if (!line) continue;
    const chars = Array.from(line);
    return chars.length <= 160 ? line : `${chars.slice(0, 159).join('')}\u2026`;
  }
  return null;
}

/** Temper's fixed line under a member's own question (team_flow.MEMBER_QUESTION_NOTE, 76a1d5c7, Security S1). */
const MEMBER_QUESTION_NOTE = "A team member's words, not Temper's. Never put a key or password in an answer.";

/**
 * A member's own question (native ask_owner, FLOW M1-M3; team_flow._finish ->
 * ledger.finish_turn): its turn completes, then a wait of ledger kind "owner" opens
 * with the question, header "<member> asks" and Temper's fixed note (76a1d5c7), no
 * reply syntax; the page sees kind "question", scope "member" and one answer, reply
 * (team_view.answers_for).
 */
function memberQuestion({ id, who, turnNo, question, at }) {
  return openWait({
    id,
    kind: 'question',
    header: `${who} asks`,
    question,
    replyHint: null,
    answers: [{ answer: 'reply', needs_text: 'required', means: `${who} gets your reply at its next turn.` }],
    words: waitWords(question),
    scope: 'member',
    member: who,
    turnNo,
    at,
    extra: { note: MEMBER_QUESTION_NOTE },
  });
}

/** Design's long question (fixtures.mjs question-long): 906 characters, under ask_owner's 1,000. */
const LONG_QUESTION =
  'Before I finish the export dialog I need one decision from you about the file name, because the three options change what people see in their downloads folder and I can\u2019t tell which one you\u2019d prefer. Option one is the report\u2019s title followed by today\u2019s date, for example Quarterly sales 2026-10-09.csv, which is easy to read but can collide when someone exports the same report twice in one day. Option two adds the time as well, Quarterly sales 2026-10-09 14-05.csv, which never collides but makes the names long and harder to scan in a list. Option three uses a short code and the date, QS-20261009.csv, which sorts nicely and stays short but means nothing to someone who didn\u2019t build the report. Frontend says the dialog can show the full name before saving either way, and QA says all three pass our tests. Which of the three should the export use by default, and may people change it before they save?';

const STOP_CANCELLED = {
  answer: 'stop',
  needs_text: 'optional',
  means: 'The team stops here and the run ends cancelled. Any words you give are kept with it.',
};

/**
 * Temper's own bookkeeping (limit_checked): it takes a seq number but is never
 * in the feed, so the cursor runs ahead of the events the page counts.
 */
/**
 * The run's last_activity_at as flow_view counts it: the newest ledger event other than a
 * wait opening (the feed's wait_opened and limit), Temper's hidden bookkeeping (`hidden`
 * times, like limit_checked) included.
 */
function activityAt(events, hidden = []) {
  const times = [...events.filter((e) => !['wait_opened', 'limit'].includes(e.kind)).map((e) => e.at), ...hidden];
  return times.reduce((a, b) => (ms(b) > ms(a) ? b : a));
}

function hiddenEvent(events, add, kind, at, who, extra = {}) {
  const event = add(kind, at, who, extra);
  events.splice(events.indexOf(event), 1);
  return event.seq;
}

// Usage limits (api-fields section 3; Temper flow-teams 76a1d5c7, team_flow._open_limit and
// _refresh_limit, accounts.limit_after_check, flow_view's limit phase and feed). Temper's own
// questions name the run's kept account slot (team_runtime: account.slot, or "unknown"); a
// fresh reading needs that slot, because without one the usage check is always
// unavailable (host_helper.usage: bad_slot).
const slotOf = (run) => run.account?.slot || 'unknown';
function readSlot(run) {
  const slot = run.account?.slot;
  if (!slot) throw new Error('a fresh usage reading needs a kept account slot (Temper reads bad_slot without one)');
  return slot;
}
const LIMIT_PAD_S = 30;
const LIMIT_RECHECK_S = 15 * 60;
const LIMIT_WORDS = {
  five_hour: 'The account hit its usage limit; it carries on only after fresh usage shows room',
  weekly: 'The account hit its weekly limit; the team waits, then asks you before restarting',
  unavailable: 'Usage cannot be checked; the team keeps waiting',
  asked: 'Usage is available again: restart or stop?',
};
const LIMIT_RESTART = {
  answer: 'restart',
  needs_text: 'none',
  means: "Restart on the same account after its weekly limit reset, keeping the team's work.",
};

/**
 * A usage limit stops checker's turn 1: Temper requeues it (a "cancelled"
 * turn_end, the turn superseded, its message pending again) and holds the team.
 */
function limitStops(add, run, at) {
  add('turn_end', at, 'checker', { turn_no: 1, ended: 'cancelled', ended_by: null, cost_usd: null, tool_calls: null });
  const checker = member(run, 'checker');
  Object.assign(checker, {
    state: 'ready',
    activity: 'idle',
    since: at,
    turn_no: null,
    tools_now: null,
    ready_messages: 1,
    last_turn: { ...checker.last_turn, state: 'superseded', ended_at: at, error: 'checker turn 1: limit' },
    last_activity_at: at,
    // An ended turn's receipt: what Temper's own fixture runs report (team_view._effective).
    effective: { model: 'unknown', thinking: 'unknown' },
  });
  for (const entry of run.timeline.entries) {
    if (entry.entry === 'member_turn' && entry.from_agent === 'checker') {
      entry.event_type = 'turn 1: superseded';
      entry.data = { ...entry.data, state: 'superseded', ended_at: at };
    }
  }
}

/** The limit wait opening, as the feed shows it: Temper's current schedule for it, never a wait_opened. */
function limitEvent(add, at, subject) {
  return add('limit', at, 'checker', {
    resumes_at: subject.resumes_at,
    resets_known: subject.how === 'reset',
    weekly: subject.kind !== 'five_hour',
  });
}

/** lead and builder finish their turns and go idle while the limit holds checker's. */
function othersFinish(add, run, at) {
  const costs = { lead: 4.0, builder: 6.5 };
  let t = at;
  for (const who of ['lead', 'builder']) {
    add('turn_end', t, who, { turn_no: 1, ended: 'completed', ended_by: null, cost_usd: costs[who], tool_calls: 3 });
    const m = member(run, who);
    m.last_turn = { ...m.last_turn, state: 'completed', ended_at: t };
    m.cost_usd = costs[who];
    m.effective = { model: 'unknown', thinking: 'unknown' };
    for (const entry of run.timeline.entries) {
      if (entry.entry === 'member_turn' && entry.from_agent === who) {
        entry.event_type = 'turn 1: completed';
        entry.data = { ...entry.data, state: 'completed', ended_at: t };
      }
    }
    const note = `${who}: waiting for the next part`;
    const idle = add('idle', later(t, 0.001), who, { note, reason: 'idle_call' });
    eventEntry(run, idle);
    idleMember(m, idle.at, 'idle_call', note);
    t = later(t, 15);
  }
  const cost = costs.lead + costs.builder;
  setSpend(run, { cost_usd: cost, since_check_in_usd: cost });
}

/** A limit's wait item in open_waits: only once Temper's own check verified room (weekly). */
function limitWait(run, subject, at) {
  return openWait({
    id: hexId(`limit:${subject.how}`),
    kind: 'limit',
    header: 'usage-limit',
    question: subject.question,
    replyHint: "Reply 'restart' or 'stop'.",
    answers: [LIMIT_RESTART, STOP_CANCELLED],
    words: subject.question.split('. ')[0],
    scope: 'team',
    member: 'checker',
    turnNo: 1,
    at,
    extra: {
      account_slot: run.account?.slot ?? null,
      limit: subject.limit,
      resets: subject.resets,
      resumes_at: subject.resumes_at,
      usage: subject.usage,
      usage_checked_at: subject.usage_checked_at,
      resume_verified: subject.resume_verified,
      blocked_windows: subject.blocked_windows,
      asked_again: null,
    },
  });
}

/** The limit phase Temper sends for a held team (flow_view's limit branch). */
function limitPhase(run, subject, { since, asked }) {
  const reading = subject.usage ?? {};
  setPhase(run, {
    name: 'limit',
    words: asked
      ? LIMIT_WORDS.asked
      : reading.status === 'unavailable'
        ? LIMIT_WORDS.unavailable
        : LIMIT_WORDS[subject.kind],
    since,
    asked,
    reason: reading.reason ?? null,
    resumes_at: subject.resumes_at,
    resets_known: subject.how === 'reset',
    usage: subject.usage,
    usage_checked_at: subject.usage_checked_at,
    resume_verified: subject.resume_verified,
    blocked_windows: subject.blocked_windows,
  });
}

/**
 * A weekly limit stops checker's turn; lead and builder finish and go idle;
 * at the scheduled check Temper reads the account (`reading`, or unavailable)
 * and writes its hidden limit_checked. `after` is the subject after the check.
 */
function weeklyChecked({ run, events }, after) {
  const add = appender(events);
  const hit = later(run.as_of, 10);
  const reset = later(hit, 2 * 3600);
  const subject = {
    kind: 'weekly',
    limit: 'weekly',
    resets: reset,
    how: 'reset',
    resumes_at: later(reset, LIMIT_PAD_S),
    usage: null,
    usage_checked_at: null,
    resume_verified: false,
    blocked_windows: [],
  };
  limitStops(add, run, hit);
  const opened = later(hit, 0.001);
  // The feed shows the limit with Temper's current schedule for it, so the check rewrites it below.
  const limit = limitEvent(add, opened, subject);
  othersFinish(add, run, later(hit, 20));
  const check = subject.resumes_at;
  const checked = { ...subject, ...after(check), usage_checked_at: check };
  Object.assign(limit, { resumes_at: checked.resumes_at, resets_known: checked.how === 'reset' });
  const cursor = hiddenEvent(events, add, 'limit_checked', check, 'checker', { status: checked.resume_verified ? 'ok' : 'held' });
  return { hit: opened, checked, check, cursor };
}

/** The run's end: frozen elapsed_s, members ended, no open waits. */
function endRun(run, at, { state, runStatus, phase, outcome }) {
  run.state = state;
  run.run_status = runStatus;
  setPhase(run, { ...phase, since: at });
  run.outcome = outcome;
  run.open_waits = [];
  run.you = { count: 0, first: null };
  for (const m of run.members) endedMember(m, at);
  run.elapsed_s = Math.round((ms(at) - ms(run.started_at)) / 1000);
  recount(run);
}

// ---------------------------------------------------------------------------
// Map stories (Design D42-D45, D47): who messaged whom, on teams of 2 to 6
// ---------------------------------------------------------------------------

/** The map's team, the leader first, then the members in the order the ring places them. */
const MAP_TEAM = ['lead', 'builder', 'checker', 'designer', 'tester', 'writer'];
/** The work the leader sends to the members the working reply doesn't have. */
const MAP_PARTS = {
  builder: 'Build the builder part and share it.',
  checker: 'Build the checker part and share it.',
  designer: 'Design the README layout and share it.',
  tester: 'Test the README steps on a clean machine.',
  writer: 'Write the Usage section and share it.',
};
/** Map states read 50 minutes after the working reply, so its first messages are old (D42's 10 minutes). */
const MAP_LATER_S = 50 * 60;

/**
 * Temper's working reply with its team cut or grown to `size` members. A
 * member it adds is a copy of checker that waits from the start like the
 * others (idle, reason start) and is in the trial's member list; a member it
 * cuts takes its events, entries and links with it. The feed is renumbered.
 */
function mapTeam(run, events, size) {
  const names = MAP_TEAM.slice(0, size);
  const gone = new Set(run.members.map((m) => m.name).filter((n) => !names.includes(n)));
  const template = clone(member(run, 'checker'));
  const trialTemplate = clone(run.trial.members.find((m) => m.name === 'checker'));
  const kept = events.filter((e) => !gone.has(e.member) && !gone.has(e.from) && !gone.has(e.to));
  const lastStart = kept.filter((e) => e.kind === 'idle' && e.reason === 'start').at(-1);
  const added = names.filter((n) => !run.members.some((m) => m.name === n));
  const starts = added.map((name, i) => ({
    seq: 0,
    at: later(lastStart.at, 0.0001 * (i + 1)),
    kind: 'idle',
    member: name,
    note: null,
    reason: 'start',
  }));
  kept.splice(kept.indexOf(lastStart) + 1, 0, ...starts);
  const seqOf = new Map();
  kept.forEach((e, i) => {
    if (e.seq) seqOf.set(e.seq, i + 1);
    e.seq = i + 1;
  });
  events.splice(0, events.length, ...kept);
  run.timeline.entries = run.timeline.entries.filter((e) => !gone.has(e.from_agent) && !gone.has(e.to_agent));
  for (const entry of run.timeline.entries) {
    if (typeof entry.seq === 'number') {
      entry.seq = seqOf.get(entry.seq);
      entry.data = { ...entry.data, seq: entry.seq };
    }
  }
  for (const start of starts) eventEntry(run, start);
  run.members = run.members.filter((m) => !gone.has(m.name));
  run.trial.members = run.trial.members.filter((m) => !gone.has(m.name));
  added.forEach((name, i) => {
    const m = { ...clone(template), name };
    idleMember(m, starts[i].at, 'start', null);
    Object.assign(m, { turns: 0, last_turn: null, on: null, last_sent: null, last_share: null, cost_usd: 0 });
    run.members.push(m);
    run.trial.members.push({ ...clone(trialTemplate), name });
  });
  run.trial.max_parallel = size;
  run.links = run.links.filter((l) => !gone.has(l.from) && !gone.has(l.to));
}

function endTurnEntry(run, who, turnNo, at) {
  const entry = run.timeline.entries.find((e) => e.entry === 'member_turn' && e.from_agent === who && e.data.turn_no === turnNo);
  if (entry) {
    entry.event_type = `turn ${turnNo}: completed`;
    entry.data = { ...entry.data, state: 'completed', ended_at: at };
  }
}

/**
 * Plays turns on a map team. Each act is one turn's release: the sender's turn
 * ends, its messages follow a millisecond apart (each its own message_id), then
 * its next turn starts, or it waits (then: 'idle'). An idle receiver wakes and
 * starts a turn; a working one keeps the message for its next turn.
 */
function playActs(run, events, acts, tag) {
  const add = appender(events);
  const sim = new Map(
    run.members.map((m) => [
      m.name,
      {
        state: m.state,
        turns: m.turns ?? 0,
        turnAt: m.since,
        cost: m.cost_usd ?? 0,
        on: m.on,
        lastSent: m.last_sent ?? null,
        lastTurn: m.last_turn,
        ready: 0,
        idleAt: m.state === 'idle' ? m.since : null,
        idleReason: m.idle_reason,
        idleNote: m.idle_note,
        activity: m.last_activity_at,
      },
    ]),
  );
  const startTurn = (x, who, at) => {
    x.turns += 1;
    Object.assign(x, { state: 'working', turnAt: at, ready: 0, activity: at });
    add('turn_start', at, who, { turn_no: x.turns, retry_of: null });
    turnEntry(run, who, x.turns, 'running', at);
  };
  let n = 0;
  for (const act of acts) {
    const s = sim.get(act.from);
    if (s.state !== 'working') throw new Error(`${tag}: ${act.from} sends while ${s.state}`);
    add('turn_end', act.at, act.from, { turn_no: s.turns, ended: 'completed', ended_by: null, cost_usd: 1.0, tool_calls: 3 });
    s.cost += 1;
    s.lastTurn = { turn_no: s.turns, state: 'completed', started_at: s.turnAt, ended_at: act.at, error: null, account_slot: null, retry_of: null, ended_by: null };
    endTurnEntry(run, act.from, s.turns, act.at);
    let at = act.at;
    for (const [to, text] of act.to) {
      at = later(at, 0.001);
      const msg = message(add, run, { at, from: act.from, to, kind: act.kind ?? 'info', text, id: hexId(`${tag}:${n++}`) });
      s.lastSent = { to, kind: msg.message_kind, text, at, message_id: msg.message_id };
      s.on = { kind: 'message', text, to, from: act.from, at, message_id: msg.message_id };
      s.activity = at;
      const r = sim.get(to);
      if (r.state === 'idle') {
        eventEntry(run, add('wake', later(at, 0.0002), to, { by: act.from }));
        startTurn(r, to, later(at, 0.0004));
        r.on = { kind: msg.message_kind, text, from: act.from, at, message_id: msg.message_id };
      } else {
        r.ready += 1;
      }
    }
    if (act.then === 'idle') {
      const idleAt = later(at, 0.002);
      eventEntry(run, add('idle', idleAt, act.from, { note: act.note, reason: 'idle_call' }));
      Object.assign(s, { state: 'idle', idleAt, idleReason: 'idle_call', idleNote: act.note, activity: idleAt });
    } else {
      startTurn(s, act.from, later(at, 0.003));
    }
  }
  for (const m of run.members) {
    const x = sim.get(m.name);
    if (x.state === 'working') workingMember(m, x.turns, x.turnAt, m.tools_now ?? []);
    else {
      idleMember(m, x.idleAt, x.idleReason, x.idleNote);
      m.last_turn = x.lastTurn;
    }
    Object.assign(m, { turns: x.turns, cost_usd: x.cost, on: x.on, last_sent: x.lastSent, ready_messages: x.ready, last_activity_at: x.activity });
  }
  const cost = run.members.reduce((sum, m) => sum + m.cost_usd, 0);
  setSpend(run, { cost_usd: cost, since_check_in_usd: cost });
  run.last_activity_at = events.at(-1).at;
}

/** links as Temper counts them: member-to-member messages in the hour before as_of, each counted at its own time (D68). */
function relink(run, events, asOf) {
  const names = new Set(run.members.map((m) => m.name));
  const from = ms(asOf) - 3_600_000;
  const links = new Map();
  for (const e of events) {
    if (e.kind !== 'message' || e.from_kind !== 'member' || !names.has(e.from) || !names.has(e.to) || ms(e.at) < from) continue;
    const key = `${e.from}>${e.to}`;
    const link = links.get(key) ?? { from: e.from, to: e.to, count: 0, last_at: e.at };
    link.count += 1;
    if (ms(e.at) >= ms(link.last_at)) link.last_at = e.at;
    links.set(key, link);
  }
  run.links = [...links.values()];
}

function mapPhase(run) {
  const working = run.members.filter((m) => m.state === 'working').length;
  setPhase(run, { name: 'working', words: `${working} of ${run.members.length} members are working` });
}

/**
 * Each team's messages in the 10 minutes before the map is read, in seconds
 * before it. Teams of 5 and 6 have five recent pairs, one more than the four
 * lines (D42); the leader's first work requests are 48-50 minutes old.
 */
const MAP_ACTS = {
  2: [{ at: -120, from: 'builder', to: [['lead', 'The builder part is shared. Take a look when you can.']] }],
  3: [
    { at: -360, from: 'checker', to: [['builder', 'The install step fails on a clean machine.']] },
    { at: -240, from: 'builder', to: [['lead', 'The builder part is shared, with the install step fixed.']] },
    { at: -120, from: 'checker', to: [['lead', 'Every command in the README runs as written.']] },
  ],
  4: [
    { at: -480, from: 'builder', to: [['checker', 'Please run my install steps.']] },
    { at: -360, from: 'designer', to: [['checker', 'The layout is shared; check the headings.']] },
    { at: -240, from: 'designer', to: [['lead', 'The layout is shared.']] },
    { at: -40, from: 'builder', to: [['lead', 'The builder part is shared.']] },
  ],
  5: [
    { at: -540, from: 'designer', to: [['lead', 'The layout is shared.']] },
    { at: -420, from: 'builder', to: [['checker', 'Please run my install steps.']] },
    { at: -300, from: 'checker', to: [['lead', 'The install steps pass.']] },
    { at: -180, from: 'designer', to: [['tester', 'Please test the layout on a phone.']] },
    { at: -75, from: 'builder', to: [['lead', 'The builder part is shared.']] },
  ],
  6: [
    { at: -480, from: 'checker', to: [['lead', 'The install steps pass.']] },
    { at: -360, from: 'designer', to: [['tester', 'Please test the layout on a phone.']] },
    { at: -240, from: 'writer', to: [['lead', 'The Usage section is shared.']] },
    { at: -120, from: 'checker', to: [['designer', 'Two headings are out of order.']] },
    { at: -40, from: 'builder', to: [['lead', 'The builder part is shared.']] },
  ],
};

/**
 * A team of `size` from the working reply, 50 minutes on: 90 s in the leader's
 * turn 1 ends with work for the members the reply doesn't have, and it waits;
 * then the team's recent messages (MAP_ACTS), then `more` (seconds after the
 * read). Returns the read time T; the same size always gives the same feed, so
 * a state built on it carries on where it ends.
 */
function mapStory(run, events, size, more = []) {
  const base = run.as_of;
  const read = later(base, MAP_LATER_S);
  mapTeam(run, events, size);
  const extras = MAP_TEAM.slice(3, size);
  const acts = [
    { at: later(base, 90), from: 'lead', kind: 'work_request', then: 'idle', note: 'lead: waiting for the parts', to: extras.map((n) => [n, MAP_PARTS[n]]) },
    ...[...MAP_ACTS[size], ...more].map((a) => ({ ...a, at: later(read, a.at) })),
  ];
  playActs(run, events, acts, `map-${size}`);
  return read;
}

/** A map state read at `asOf`: links from the feed's last hour, the phase from the members. */
function mapRead(run, events, asOf) {
  relink(run, events, asOf);
  mapPhase(run);
  return asOf;
}

// ---------------------------------------------------------------------------
// The derived states
// ---------------------------------------------------------------------------

const GOAL_SEQ = 3; // working's feed: 1 goal to the leader, 2-3 the others idle at the start

const DERIVED = {
  /** Before any turn: the leader has the goal, the others wait for its first message. */
  starting: {
    from: 'working',
    why: 'phase starting before any turn; feed cut to the goal and the two start idles; the leader ready with the goal, the others idle (start)',
    build({ run, events }) {
      events.splice(GOAL_SEQ);
      const goal = events[0];
      const asOf = later(events[GOAL_SEQ - 1].at, 0.0003);
      run.as_of = asOf;
      run.state = 'starting';
      setPhase(run, { name: 'starting', words: 'Starting: the leader has the goal', since: run.started_at });
      const lead = member(run, 'lead');
      Object.assign(lead, {
        state: 'ready',
        activity: 'idle',
        since: goal.at,
        turns: 0,
        turn_no: null,
        last_turn: null,
        on: { kind: 'goal', text: goal.text, from: goal.from, at: goal.at, message_id: goal.message_id },
        tools_now: null,
        ready_messages: 1,
        last_sent: null,
        last_activity_at: goal.at,
      });
      for (const name of ['builder', 'checker']) {
        const m = member(run, name);
        const start = events.find((e) => e.kind === 'idle' && e.member === name);
        idleMember(m, start.at, 'start', null);
        Object.assign(m, { turns: 0, last_turn: null, on: null });
      }
      run.links = [];
      run.timeline.entries = run.timeline.entries.slice(0, GOAL_SEQ);
      run.last_activity_at = events[GOAL_SEQ - 1].at;
      return asOf;
    },
  },

  /** The leader works on the goal; the others still wait for its first message (journey step 1). */
  start: {
    from: 'working',
    why: 'the leader in turn 1 on the goal; builder and checker idle (start); feed cut to the goal and the two start idles, so the real working feed follows it',
    build({ run, events }) {
      events.splice(GOAL_SEQ);
      const goal = events[0];
      const turnAt = later(events[GOAL_SEQ - 1].at, 0.0002);
      const asOf = later(turnAt, 0.0001);
      run.as_of = asOf;
      setPhase(run, { name: 'working', words: '1 of 3 members are working' });
      const lead = member(run, 'lead');
      workingMember(lead, 1, turnAt, []);
      Object.assign(lead, {
        on: { kind: 'goal', text: goal.text, from: goal.from, at: goal.at, message_id: goal.message_id },
        last_sent: null,
      });
      for (const name of ['builder', 'checker']) {
        const m = member(run, name);
        const start = events.find((e) => e.kind === 'idle' && e.member === name);
        idleMember(m, start.at, 'start', null);
        Object.assign(m, { turns: 0, last_turn: null, on: null });
      }
      run.links = [];
      run.timeline.entries = run.timeline.entries.slice(0, GOAL_SEQ);
      turnEntry(run, 'lead', 1, 'running', turnAt);
      run.last_activity_at = turnAt;
      return asOf;
    },
  },

  /** The leader's turn ends and releases seven messages at once (more than the six dots). */
  burst: {
    from: 'working',
    why: "the leader's turn 1 ends and releases 7 messages at once (each its own message_id); the leader idle, builder and checker still in turn 1",
    build({ run, events }) {
      const add = appender(events);
      const end = later(run.as_of, 35);
      add('turn_end', end, 'lead', { turn_no: 1, ended: 'completed', ended_by: null, cost_usd: 5.0, tool_calls: 6 });
      const sent = [
        ['builder', 'info', 'Start with one line that says what the project does.'],
        ['checker', 'info', 'Check that every command in the README runs as written.'],
        ['builder', 'info', 'Add an Install section with the two setup commands.'],
        ['checker', 'info', 'Flag any step that needs a tool the project does not list.'],
        ['builder', 'info', 'Keep it under 40 lines.'],
        ['checker', 'info', 'Read it once as someone new to the project.'],
        ['builder', 'info', "Use the project's name as the title."],
      ];
      let at = end;
      let last = null;
      sent.forEach(([to, kind, text], i) => {
        at = later(end, 0.001 * (i + 1));
        last = message(add, run, { at, from: 'lead', to, kind, text, id: hexId(`burst:${i}`) });
      });
      const idleAt = later(at, 0.002);
      const idle = add('idle', idleAt, 'lead', { note: 'lead: waiting for the parts', reason: 'idle_call' });
      eventEntry(run, idle);
      const lead = member(run, 'lead');
      idleMember(lead, idleAt, 'idle_call', 'lead: waiting for the parts');
      Object.assign(lead, {
        cost_usd: 5.0,
        last_turn: { ...lead.last_turn, state: 'completed', ended_at: end },
        on: { kind: 'message', text: last.text, to: last.to, from: 'lead', at: last.at, message_id: last.message_id },
        last_sent: { to: last.to, kind: last.message_kind, text: last.text, at: last.at, message_id: last.message_id },
      });
      for (const entry of run.timeline.entries) {
        if (entry.entry === 'member_turn' && entry.from_agent === 'lead') {
          entry.event_type = 'turn 1: completed';
          entry.data = { ...entry.data, state: 'completed', ended_at: end };
        }
      }
      for (const link of run.links) {
        const extra = sent.filter(([to]) => to === link.to).length;
        link.count += extra;
        link.last_at = [...events].reverse().find((e) => e.kind === 'message' && e.from === 'lead' && e.to === link.to).at;
      }
      const asOf = later(end, 5);
      run.as_of = asOf;
      setPhase(run, { name: 'working', words: '2 of 3 members are working' });
      setSpend(run, { cost_usd: 5.0, since_check_in_usd: 5.0 });
      recount(run);
      run.last_activity_at = idleAt;
      return asOf;
    },
  },

  /** A deploy changed the team's settings while it waited at the check-in. */
  settings: {
    from: 'check_in',
    why: "a settings question opened while the team waited at the check-in: settings first, the check-in's wait not asked while it is open",
    build({ run, events }) {
      const add = appender(events);
      const at = later(run.as_of, 20);
      const wait = openWait({
        id: hexId('settings:wait'),
        kind: 'settings',
        header: 'settings-changed',
        question: "A deploy changed the team's settings while it waited. Go on with the new settings, or stop?",
        replyHint: "Reply 'go on' or 'stop'.",
        answers: [
          { answer: 'go on', needs_text: 'none', means: 'The team carries on with the new settings.' },
          STOP_CANCELLED,
        ],
        words: "A deploy changed the team's settings while it waited",
        scope: 'team',
        at,
      });
      add('wait_opened', at, null, { wait_id: wait.wait_id, wait_kind: 'settings', words: wait.words });
      run.open_waits = [wait, ...run.open_waits.map((w) => ({ ...w, asked: false }))];
      run.you = { count: 1, first: youFirst(wait) };
      waitEntry(run, wait);
      run.state = 'settings_changed';
      setPhase(run, { name: 'settings', words: 'Settings changed: go on or stop?', since: at, asked: true });
      recount(run);
      run.last_activity_at = at;
      const asOf = later(at, 30);
      run.as_of = asOf;
      return asOf;
    },
  },

  /** A 5-hour limit stops one turn; two finish. Before any check: no reading, a known reset. */
  limit: {
    from: 'working',
    why: "phase limit: a 5-hour limit stopped checker's turn (requeued, ready) while lead's and builder's turns finish; Temper read a future reset, has not checked usage yet (no reading, nothing blocked), and checks 30 s after the reset; not answerable, so no open wait",
    build({ run, events }) {
      const add = appender(events);
      const hit = later(run.as_of, 10);
      const reset = later(hit, 47 * 60);
      const subject = {
        kind: 'five_hour', how: 'reset', resumes_at: later(reset, LIMIT_PAD_S),
        usage: null, usage_checked_at: null, resume_verified: false, blocked_windows: [],
      };
      limitStops(add, run, hit);
      const opened = later(hit, 0.001);
      limitEvent(add, opened, subject);
      limitPhase(run, subject, { since: opened, asked: false });
      recount(run);
      run.last_activity_at = opened;
      const asOf = later(opened, 20);
      run.as_of = asOf;
      return asOf;
    },
  },

  /** A weekly limit; at the check a fresh reading shows room, so Temper asks restart / stop. */
  limit_asked: {
    from: 'working',
    why: "a weekly limit stopped checker's turn, lead and builder finished idle; at the check after the reset a complete fresh reading shows room (resume_verified, resumes_at = the check time, resets_known false): Temper's limit wait is in open_waits and you, asked, with restart / stop",
    build({ run, events }) {
      const { hit, checked, check, cursor } = weeklyChecked({ run, events }, (now) => ({
        how: 'verified',
        resumes_at: now,
        resume_verified: true,
        blocked_windows: [],
        usage: {
          status: 'ok',
          observed_at: now,
          windows: [
            { key: '5h', used_percent: 12, resets_at: later(now, 3 * 3600) },
            { key: '7d', used_percent: 64, resets_at: later(now, 5 * 86400) },
          ],
        },
        question: `Account ${readSlot(run)}'s fresh usage check shows room again. The team keeps its work and waits for your answer before restarting.`,
      }));
      const wait = limitWait(run, checked, hit);
      run.open_waits = [wait];
      run.you = { count: 1, first: youFirst(wait) };
      waitEntry(run, wait);
      limitPhase(run, checked, { since: hit, asked: true });
      recount(run);
      run.last_activity_at = activityAt(events, [check]);
      const asOf = later(check, 45);
      run.as_of = asOf;
      return { asOf, cursor };
    },
  },

  /** A weekly limit whose reset passed, but the fresh check still shows the week spent: no question. */
  limit_spent: {
    from: 'working',
    why: 'a weekly limit; the read reset time passed and Temper checked: the 7-day window is still at 100% with no usable reset time, so it holds (blocked 7d, not verified), rechecks in 15 minutes and asks nothing: no open wait, no Restart',
    build({ run, events }) {
      const { hit, checked, check, cursor } = weeklyChecked({ run, events }, (now) => ({
        how: 'recheck',
        resumes_at: later(now, LIMIT_RECHECK_S),
        resume_verified: false,
        blocked_windows: ['7d'],
        usage: {
          status: 'ok',
          observed_at: now,
          windows: [
            { key: '5h', used_percent: 3, resets_at: later(now, 4 * 3600) },
            { key: '7d', used_percent: 100, resets_at: null },
          ],
        },
        question: `Account ${readSlot(run)} is still at its usage limit. The team keeps its work and waits. Next usage check: ${later(now, LIMIT_RECHECK_S)}. When usage shows room, it asks you before restarting.`,
      }));
      run.open_waits = [];
      run.you = { count: 0, first: null };
      limitPhase(run, checked, { since: hit, asked: false });
      recount(run);
      run.last_activity_at = activityAt(events, [check]);
      const asOf = later(check, 45);
      run.as_of = asOf;
      return { asOf, cursor };
    },
  },

  /** A weekly limit whose usage can't be read at the check: it keeps waiting and checks again. */
  limit_unavailable: {
    from: 'working',
    why: "a weekly limit; at the check Temper's usage reader is unreachable (usage unavailable, reason helper_unreachable): the hold stays, nothing verified, nothing blocked newly known, next check in 15 minutes, no usable reset time; no open wait, no Restart",
    build({ run, events }) {
      const { hit, checked, check, cursor } = weeklyChecked({ run, events }, (now) => ({
        how: 'recheck',
        resumes_at: later(now, LIMIT_RECHECK_S),
        resume_verified: false,
        blocked_windows: [],
        usage: { status: 'unavailable', reason: 'helper_unreachable' },
        question: `Account ${slotOf(run)} could not be checked; this is not proof that its usage limit reset. The team keeps its work and waits. Next usage check: ${later(now, LIMIT_RECHECK_S)}. When usage shows room, it asks you before restarting.`,
      }));
      run.open_waits = [];
      run.you = { count: 0, first: null };
      limitPhase(run, checked, { since: hit, asked: false });
      recount(run);
      run.last_activity_at = activityAt(events, [check]);
      const asOf = later(check, 45);
      run.as_of = asOf;
      return { asOf, cursor };
    },
  },

  /**
   * A 5-hour limit whose timed wake found the start check unavailable (FLOW M6,
   * parked.repark_timer_refusal): the run stays parked and only its check time moves.
   */
  limit_start_check: {
    from: 'working',
    why: "phase limit: a 5-hour limit stopped checker's turn, lead and builder finished idle; at the timed wake 30 s after the reset Temper's start check could not read usage, so the run stays parked (run_status waiting): usage unavailable (start_check_unavailable), not verified, no fresh usage-check time, no usable reset time, next check in 15 minutes; Temper's own wait, so no open wait and no Restart",
    build({ run, events }) {
      const add = appender(events);
      const hit = later(run.as_of, 10);
      const reset = later(hit, 47 * 60);
      const subject = {
        kind: 'five_hour', how: 'reset', resumes_at: later(reset, LIMIT_PAD_S),
        usage: null, usage_checked_at: null, resume_verified: false, blocked_windows: [],
      };
      limitStops(add, run, hit);
      const opened = later(hit, 0.001);
      const limit = limitEvent(add, opened, subject);
      othersFinish(add, run, later(hit, 20));
      // The wake is due at resumes_at; the start check refuses a moment later.
      const check = later(subject.resumes_at, 2);
      const checked = {
        ...subject,
        how: 'recheck',
        resumes_at: later(check, LIMIT_RECHECK_S),
        usage: { status: 'unavailable', reason: 'start_check_unavailable' },
        usage_checked_at: null,
      };
      // The feed shows the limit with Temper's current schedule for it.
      Object.assign(limit, { resumes_at: checked.resumes_at, resets_known: false });
      const cursor = hiddenEvent(events, add, 'limit_checked', check, 'checker', {
        status: 'unavailable', reason: 'start_check_unavailable', verified: false, resumes_at: checked.resumes_at,
      });
      run.open_waits = [];
      run.you = { count: 0, first: null };
      run.run_status = 'waiting';
      limitPhase(run, checked, { since: opened, asked: false });
      recount(run);
      run.last_activity_at = activityAt(events, [check]);
      const asOf = later(check, 45);
      run.as_of = asOf;
      return { asOf, cursor };
    },
  },

  /** Temper is restarting: running turns finish, no new turn starts (a ready leader waits: D1). */
  draining: {
    from: 'working',
    why: "phase draining (no feed event for it): the leader's turn ended and builder's mid-turn message waits for it, so the leader is ready; builder and checker finish their turns",
    build({ run, events }) {
      const add = appender(events);
      const since = later(run.as_of, 5);
      const end = later(run.as_of, 8);
      add('turn_end', end, 'lead', { turn_no: 1, ended: 'completed', ended_by: null, cost_usd: 5.0, tool_calls: 6 });
      const note = message(add, run, {
        at: later(end, 3),
        from: 'builder',
        to: 'lead',
        kind: 'info',
        text: 'The README skeleton is in; the Install section is next.',
        id: hexId('draining:builder'),
      });
      const lead = member(run, 'lead');
      Object.assign(lead, {
        state: 'ready',
        activity: 'idle',
        since: end,
        turn_no: null,
        tools_now: null,
        ready_messages: 1,
        cost_usd: 5.0,
        last_turn: { ...lead.last_turn, state: 'completed', ended_at: end },
        last_activity_at: end,
      });
      for (const entry of run.timeline.entries) {
        if (entry.entry === 'member_turn' && entry.from_agent === 'lead') {
          entry.event_type = 'turn 1: completed';
          entry.data = { ...entry.data, state: 'completed', ended_at: end };
        }
      }
      const back = run.links.find((l) => l.from === 'builder' && l.to === 'lead');
      if (back) Object.assign(back, { count: back.count + 1, last_at: note.at });
      else run.links.push({ from: 'builder', to: 'lead', count: 1, last_at: note.at });
      setPhase(run, { name: 'draining', words: 'Temper is restarting: the team carries on after it', since });
      setSpend(run, { cost_usd: 5.0, since_check_in_usd: 5.0 });
      recount(run);
      run.last_activity_at = note.at;
      const asOf = later(note.at, 4);
      run.as_of = asOf;
      return asOf;
    },
  },

  /** Temper restarted under three running turns and the run ended without the team ending. */
  interrupted: {
    from: 'working',
    why: 'the run ended without the team ending (Temper restarted under 3 running turns): phase interrupted, no outcome, elapsed_s frozen at the end while as_of is 5 min later',
    build({ run }) {
      const end = later(run.as_of, 10);
      const reason = 'Temper restarted while 3 turns were running.';
      endRun(run, end, {
        state: 'interrupted',
        runStatus: 'failed',
        phase: { name: 'interrupted', words: 'Interrupted', reason },
        outcome: null,
      });
      const asOf = later(end, 300);
      run.as_of = asOf;
      return asOf;
    },
  },

  /** Two members asked the owner a question: nothing runs until he answers. */
  waiting: {
    from: 'idle',
    why: "the leader's and the checker's turns end with a question to you each (native ask_owner: the turn completes, no idle, a member-scope question wait opens; oldest first); builder idle; nothing runs",
    build({ run, events }) {
      const asks = {
        lead: 'Should the README cover Windows setup too, or only macOS and Linux? The project has no Windows notes yet.',
        checker: 'Is it fine to run the install commands on this machine to check them? They download about 200 MB.',
      };
      const waits = [];
      for (const event of events) {
        const question = asks[event.member];
        if (!question) continue;
        if (event.kind === 'idle' && event.reason === 'idle_call') {
          // The member asked instead of resting: its idle becomes the question's wait_opened.
          const wait = memberQuestion({ id: hexId(`waiting:${event.member}`), who: event.member, turnNo: 1, question, at: event.at });
          waits.push(wait);
          for (const key of Object.keys(event)) if (!['seq', 'at', 'member'].includes(key)) delete event[key];
          Object.assign(event, { kind: 'wait_opened', wait_id: wait.wait_id, wait_kind: 'question', words: wait.words });
        }
      }
      // Reorder keys like Temper's events: seq, at, kind, member, extras.
      for (let i = 0; i < events.length; i += 1) {
        const { seq, at, kind, member: who, ...extra } = events[i];
        events[i] = { seq, at, kind, member: who, ...extra };
      }
      run.timeline.entries = run.timeline.entries.filter((e) => !(e.entry === 'idle' && asks[e.member] && e.reason === 'idle_call'));
      for (const wait of waits) {
        waitEntry(run, wait);
        heldMember(member(run, wait.member), wait.wait_id, wait.opened_at);
      }
      run.open_waits = waits;
      run.you = { count: waits.length, first: youFirst(waits[0]) };
      run.state = 'member_waiting';
      // flow_view: the waiting phase is dated by the oldest question the owner can answer.
      setPhase(run, {
        name: 'waiting_for_owner',
        words: `Waiting for you: ${waits.length} questions`,
        since: waits[0].opened_at,
        asked: true,
      });
      recount(run);
      run.last_activity_at = activityAt(events);
      const asOf = later(run.as_of, 45);
      run.as_of = asOf;
      return asOf;
    },
  },

  /** One member asks you a long question (ask_owner) while the others keep working. */
  member_question: {
    from: 'working',
    why: "builder's turn 1 ends with its own 906-character question to you (native ask_owner): the turn completes, a member-scope question wait opens and only builder is held; lead and checker keep working",
    build({ run, events }) {
      const add = appender(events);
      const end = later(run.as_of, 30);
      add('turn_end', end, 'builder', { turn_no: 1, ended: 'completed', ended_by: null, cost_usd: 6.5, tool_calls: 4 });
      // ledger.finish_turn: the turn's end, then the wait row, then its wait_opened event.
      const opened = later(end, 0.0005);
      const wait = memberQuestion({ id: hexId('member_question:builder'), who: 'builder', turnNo: 1, question: LONG_QUESTION, at: opened });
      const asked = add('wait_opened', later(opened, 0.0003), 'builder', { wait_id: wait.wait_id, wait_kind: 'question', words: wait.words });
      const builder = member(run, 'builder');
      heldMember(builder, wait.wait_id, opened);
      Object.assign(builder, {
        cost_usd: 6.5,
        effective: { model: 'unknown', thinking: 'unknown' },
        last_turn: { ...builder.last_turn, state: 'completed', ended_at: end },
        last_activity_at: asked.at,
      });
      for (const entry of run.timeline.entries) {
        if (entry.entry === 'member_turn' && entry.from_agent === 'builder') {
          entry.event_type = 'turn 1: completed';
          entry.data = { ...entry.data, state: 'completed', ended_at: end };
        }
      }
      waitEntry(run, wait);
      run.open_waits = [wait];
      run.you = { count: 1, first: youFirst(wait) };
      run.state = 'member_waiting';
      setPhase(run, { name: 'working', words: '2 of 3 members are working' });
      setSpend(run, { cost_usd: 6.5, since_check_in_usd: 6.5 });
      recount(run);
      run.last_activity_at = activityAt(events);
      const asOf = later(end, 20);
      run.as_of = asOf;
      return asOf;
    },
  },

  /** Spend passed the check-in while the checker's turn runs: it finishes first, then you are asked. */
  check_in_running: {
    from: 'idle',
    why: "spend reached the check-in ($100.40) while the checker's turn 1 still runs: phase check_in not asked yet, no wait open; feed cut before the checker's turn end",
    build({ run, events }) {
      const cut = events.findIndex((e) => e.kind === 'turn_end' && e.member === 'checker');
      events.splice(cut);
      const last = events[events.length - 1];
      const checker = member(run, 'checker');
      const started = run.timeline.entries.find((e) => e.entry === 'member_turn' && e.from_agent === 'checker');
      workingMember(checker, 1, started.timestamp, [{ name: 'Bash', count: 3 }]);
      Object.assign(checker, { cost_usd: 45.4, last_activity_at: started.timestamp });
      started.event_type = 'turn 1: running';
      started.data = { ...started.data, state: 'running', ended_at: null };
      run.timeline.entries = run.timeline.entries.filter((e) => !(e.entry === 'idle' && e.member === 'checker' && e.reason === 'idle_call'));
      setSpend(run, { cost_usd: 100.4, last_check_in_usd: 0, next_check_in_usd: 100, since_check_in_usd: 100.4, check_ins: 0 });
      run.state = 'running';
      setPhase(run, { name: 'check_in', words: 'Check-in at $100.40: 1 turn finishing', since: last.at });
      recount(run);
      run.last_activity_at = last.at;
      const asOf = later(last.at, 0.0003);
      run.as_of = asOf;
      return asOf;
    },
  },

  /** The owner answered the check-in with guidance: the leader takes it in turn 2 (journey step after the check-in). */
  resumed: {
    from: 'check_in',
    why: "you answered the check-in with Guide: wait_answered, your guide message to the leader, its wake and turn 2; the next check-in at $205",
    build({ run, events }) {
      const add = appender(events);
      const wait = run.open_waits[0];
      const at = later(run.as_of, 60);
      add('wait_answered', at, null, { wait_id: wait.wait_id, wait_kind: 'pause', answer: 'guide', by: 'owner' });
      answerEntry(run, wait.wait_id, 'pause', 'guide', at);
      const sentAt = later(at, 0.001);
      message(add, run, {
        at: sentAt,
        from: 'owner',
        fromKind: 'owner',
        to: 'lead',
        kind: 'guide',
        text: GUIDE_TEXT,
        id: hexId('resumed:guide'),
      });
      const wake = add('wake', later(sentAt, 0.001), 'lead', { by: 'owner' });
      eventEntry(run, wake);
      const turnAt = later(sentAt, 0.01);
      add('turn_start', turnAt, 'lead', { turn_no: 2, retry_of: null });
      workingMember(member(run, 'lead'), 2, turnAt, [{ name: 'Read', count: 1 }]);
      turnEntry(run, 'lead', 2, 'running', turnAt);
      run.open_waits = [];
      run.you = { count: 0, first: null };
      run.state = 'running';
      setSpend(run, { last_check_in_usd: run.spend.cost_usd, next_check_in_usd: run.spend.cost_usd + run.spend.pause_every_usd, since_check_in_usd: 0 });
      setPhase(run, { name: 'working', words: '1 of 3 members are working' });
      recount(run);
      run.last_activity_at = turnAt;
      const asOf = later(turnAt, 4);
      run.as_of = asOf;
      return asOf;
    },
  },

  /** The owner answered the check-in with Stop: the run ends cancelled. */
  stopped: {
    from: 'check_in',
    why: 'you answered the check-in with Stop and your words: the run ended cancelled (outcome stopped), elapsed_s frozen while as_of is 2 min later',
    build({ run, events }) {
      const add = appender(events);
      const wait = run.open_waits[0];
      const at = later(run.as_of, 30);
      const reason = 'The owner stopped the team.';
      add('wait_answered', at, null, { wait_id: wait.wait_id, wait_kind: 'pause', answer: 'stop', by: 'owner' });
      answerEntry(run, wait.wait_id, 'pause', 'stop', at);
      const end = later(at, 0.002);
      add('ended', end, null, { decision: 'stopped', reason });
      decisionEntry(run, 'stopped', 'owner', reason, end);
      endRun(run, end, {
        state: 'stopped',
        runStatus: 'cancelled',
        phase: { name: 'stopped', words: 'Stopped by the owner', reason },
        outcome: { decision: 'stopped', reason, owner_words: 'Out of time for today.', problems: [], by: 'owner', at: end, done: null },
      });
      run.last_activity_at = at;
      const asOf = later(end, 120);
      run.as_of = asOf;
      return asOf;
    },
  },

  /** The owner stopped builder's failed turn: the run ends failed (the whole run, not one turn). */
  run_failed: {
    from: 'failed',
    why: "you answered builder's failed turn with Stop: the run ended failed (outcome failed), elapsed_s frozen while as_of is 2 min later",
    build({ run, events }) {
      const add = appender(events);
      const wait = run.open_waits[0];
      const at = later(run.as_of, 40);
      const reason = "builder's turn 1 failed after its automatic retry, and you stopped the team.";
      add('wait_answered', at, null, { wait_id: wait.wait_id, wait_kind: 'recovery', answer: 'stop', by: 'owner' });
      answerEntry(run, wait.wait_id, 'recovery', 'stop', at);
      const end = later(at, 0.002);
      add('ended', end, null, { decision: 'failed', reason });
      decisionEntry(run, 'failed', 'temper', reason, end);
      endRun(run, end, {
        state: 'failed',
        runStatus: 'failed',
        phase: { name: 'failed', words: "Failed: builder's turn 1 failed", reason },
        outcome: { decision: 'failed', reason, owner_words: null, problems: [], by: 'owner', at: end, done: null },
      });
      run.last_activity_at = at;
      const asOf = later(end, 120);
      run.as_of = asOf;
      return asOf;
    },
  },

  // Map states (D42-D45, D47). One per team size, then states that carry on from the team of 6.
  ...Object.fromEntries(
    [2, 3, 4, 5, 6].map((size) => [
      `map_members_${size}`,
      {
        from: 'working',
        why:
          `a team of ${size} read 50 minutes in: the leader's first work requests are old; ` +
          `${MAP_ACTS[size].length} member messages in the last 10 minutes` +
          (size >= 5 ? ', so five recent pairs for four lines' : '') +
          '; links counted from the feed for the hour before as_of',
        build({ run, events }) {
          return mapRead(run, events, mapStory(run, events, size));
        },
      },
    ]),
  ),

  /** The team of 6, then the leader's turn releases eight messages over five pairs in one second. */
  map_burst: {
    from: 'working',
    why: "map_members_6, then 40 s later the leader's turn releases 8 messages in one second over 5 pairs (builder, checker and designer 2 each, tester and writer 1)",
    build({ run, events }) {
      const read = mapStory(run, events, 6, [
        {
          at: 40,
          from: 'lead',
          to: [
            ['builder', 'Add the two setup commands to Install.'],
            ['checker', 'Check the Install section once it is in.'],
            ['designer', 'Keep the headings in the order of the steps.'],
            ['tester', 'Run the steps again after the Install change.'],
            ['writer', 'Add one example to Usage.'],
            ['builder', 'Keep the README under 40 lines.'],
            ['checker', 'Flag any step that needs a tool the project does not list.'],
            ['designer', "Use the project's name as the title."],
          ],
        },
      ]);
      return mapRead(run, events, later(read, 45));
    },
  },

  /** Six members at the start: only the leader has the goal (owner, bp-8d6a7652). */
  map_fanout_before: {
    from: 'working',
    why: 'a team of 6 at the start: the leader in turn 1 on the goal, the five others idle (start); feed cut to the goal and the start idles',
    build({ run, events }) {
      DERIVED.start.build({ run, events });
      mapTeam(run, events, 6);
      run.last_activity_at = events.at(-1).at;
      return mapRead(run, events, later(events.at(-1).at, 0.001));
    },
  },

  /** The leader's first turn ends with work for all five members in one second. */
  map_fanout: {
    from: 'working',
    why: "map_fanout_before, then the leader's turn 1 ends with a work request to each of the five members in one second; each wakes and starts turn 1; the leader waits",
    build({ run, events }) {
      DERIVED.map_fanout_before.build({ run, events });
      const end = later(run.as_of, 30);
      const to = MAP_TEAM.slice(1).map((n) => [n, MAP_PARTS[n]]);
      playActs(run, events, [{ at: end, from: 'lead', kind: 'work_request', then: 'idle', note: 'lead: waiting for the parts', to }], 'map-fanout');
      return mapRead(run, events, later(end, 2));
    },
  },

  /** The team of 6 read 11 minutes later with nothing new: no recent pair, every pair older (D45). */
  map_quiet: {
    from: 'working',
    why: 'map_members_6 read 11 minutes later with no new event: every pair is 12 to 59 minutes old; links counted for the hour before as_of',
    build({ run, events }) {
      return mapRead(run, events, later(mapStory(run, events, 6), 11 * 60));
    },
  },

  /** The team of 6, then builder shares, every turn ends and the team is done (D47: no Animate switch). */
  map_ended: {
    from: 'working',
    why: "map_members_6, then builder shares version 1, every running turn ends, and the run ends done (outcome copied from Temper's done reply); as_of 1 s after the end",
    build({ run, events }) {
      const read = mapStory(run, events, 6);
      const done = real('done').run;
      const add = appender(events);
      const shareAt = later(read, 10);
      const latest = { ...clone(done.work.latest), at: shareAt };
      add('share', shareAt, 'builder', { version_no: 1, commit_short: latest.commit_short, note: latest.note, files_changed: latest.files_changed });
      run.work = { ...clone(done.work), latest, shares: [latest] };
      member(run, 'builder').last_share = { version_no: 1, commit_short: latest.commit_short, note: latest.note, at: shareAt };
      let at = later(read, 15);
      for (const m of run.members.filter((x) => x.state === 'working')) {
        at = later(at, 0.01);
        add('turn_end', at, m.name, { turn_no: m.turn_no, ended: 'completed', ended_by: null, cost_usd: 1.0, tool_calls: 3 });
        endTurnEntry(run, m.name, m.turn_no, at);
        m.cost_usd += 1;
        m.last_turn = { ...m.last_turn, state: 'completed', ended_at: at };
        eventEntry(run, add('idle', later(at, 0.001), m.name, { note: `${m.name}: my part is done`, reason: 'idle_call' }));
      }
      const end = later(read, 20);
      add('ended', end, null, { decision: 'done', reason: 'team_done' });
      add('done', later(end, 0.01), 'lead', { summary: done.work.summary, version_no: 1, commit_short: latest.commit_short });
      const cost = run.members.reduce((sum, m) => sum + m.cost_usd, 0);
      setSpend(run, { cost_usd: cost, since_check_in_usd: cost });
      const turns = Object.fromEntries(run.members.map((m) => [m.name, m.turns]));
      endRun(run, end, {
        state: 'done',
        runStatus: 'completed',
        phase: { name: 'done', words: 'Done' },
        outcome: { ...clone(done.outcome), at: end, done: { ...clone(done.outcome.done), turns, cost_usd: cost } },
      });
      run.last_activity_at = events.at(-1).at;
      const asOf = later(end, 1);
      relink(run, events, asOf);
      return asOf;
    },
  },
};

/** The guidance the journey types at the check-in; resumed's guide message carries it. */
const GUIDE_TEXT = 'Keep the README under 40 lines and add a Usage section.';

// ---------------------------------------------------------------------------
// Write
// ---------------------------------------------------------------------------

/**
 * Design D26 (fixture truth): seq order is time order, and no event, member
 * state time, last send or open wait is after the reply's as_of.
 */
function checkTruth(name, run, feed) {
  let seq = 0;
  let at = -Infinity;
  for (const e of feed.events) {
    if (!(e.seq > seq)) throw new Error(`${name}: seq ${e.seq} does not rise`);
    if (ms(e.at) < at) throw new Error(`${name}: event ${e.seq} is older than the event before it (D26)`);
    seq = e.seq;
    at = ms(e.at);
    if (ms(e.at) > ms(run.as_of)) throw new Error(`${name}: event ${e.seq} is after as_of (D26)`);
  }
  const times = [
    ['last_activity_at', run.last_activity_at],
    ['phase.since', run.phase?.since],
    ...run.members.flatMap((m) => [
      [`${m.name}.since`, m.since],
      [`${m.name}.on.at`, m.on?.at],
      [`${m.name}.last_sent.at`, m.last_sent?.at],
      [`${m.name}.last_activity_at`, m.last_activity_at],
    ]),
    ...(run.open_waits ?? []).map((w) => [`wait ${w.wait_id}.opened_at`, w.opened_at]),
    ['you.first.opened_at', run.you?.first?.opened_at],
  ];
  for (const [where, value] of times) {
    if (value && ms(value) > ms(run.as_of)) throw new Error(`${name}: ${where} ${value} is after as_of (D26)`);
  }
}

function checkReply(name, run, feed) {
  for (const key of ['round', 'reviews']) {
    if (key in run) throw new Error(`${name}: a flow reply has no ${key} (D21)`);
  }
  const ids = feed.events.filter((e) => e.kind === 'message').map((e) => e.message_id);
  if (new Set(ids).size !== ids.length) throw new Error(`${name}: two messages share a message_id (D6)`);
  checkTruth(name, run, feed);
  const counted = Object.fromEntries(['working', 'ready', 'idle', 'held', 'failed', 'ended'].map((s) => [s, run.members.filter((m) => m.state === s).length]));
  for (const [state, n] of Object.entries(counted)) {
    if (run.counts[state] !== n) throw new Error(`${name}: counts.${state} is ${run.counts[state]}, members say ${n}`);
  }
}

// Temper's own replies are held to the same truth rule; a break there is Temper's to fix, so it stops here.
for (const state of REAL_STATES) {
  const { run, feed } = real(state);
  checkTruth(`real ${state}`, run, feed);
}

mkdirSync(OUT, { recursive: true });
for (const file of readdirSync(OUT)) if (file.endsWith('.json')) rmSync(join(OUT, file));

for (const [name, spec] of Object.entries(DERIVED)) {
  const source = real(spec.from);
  const run = clone(source.run);
  const events = clone(source.feed.events);
  const built = spec.build({ run, events });
  // A build may hide Temper's own bookkeeping (a seq the feed never shows): the cursor then runs ahead.
  const { asOf, cursor = 0 } = typeof built === 'string' ? { asOf: built } : built;
  run.as_of = asOf;
  recount(run);
  run.timeline.entries.sort((a, b) => ms(a.timestamp) - ms(b.timestamp));
  run.events_total = events.length;
  run.events_cursor = Math.max(cursor, events.length ? events[events.length - 1].seq : 0);
  if (!['done', 'stopped', 'failed', 'interrupted'].includes(run.phase.name)) {
    run.elapsed_s = Math.round((ms(asOf) - ms(run.started_at)) / 1000);
  }
  const fixture = `derived from ${spec.from}: ${spec.why}`;
  const body = { _fixture: fixture, ...run };
  const feed = { _fixture: fixture, events, cursor: run.events_cursor, more: false, as_of: later(asOf, 0.009) };
  checkReply(name, body, feed);
  writeFileSync(join(OUT, `${name}.json`), `${JSON.stringify(body, null, 2)}\n`);
  writeFileSync(join(OUT, `${name}-events.json`), `${JSON.stringify(feed, null, 2)}\n`);
  console.log(`${name}: derived from ${spec.from} (${events.length} events, as_of ${asOf})`);
}
