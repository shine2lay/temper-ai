/**
 * The New project form on either engine (lib/teamForm.ts), and the Projects
 * list's round words (lib/teamTrials.ts). The words are Design's settled
 * ones (SPEC section 14 b, D55).
 *
 * The form follows the server: the new engine (free-flowing teams) says its
 * check-in default in GET /api/team/status and gets pause_every_usd and
 * max_parallel, never pause_after_rounds, which it refuses. Today's server
 * gets exactly what it gets today. The statuses are the captured status-on
 * fixture, as today's server answers it, and the same with the new engine's
 * defaults and limits (FLOW api-fields section 2).
 */
import { describe, expect, it } from 'vitest';
import {
  emptyForm,
  FIELD_ANCHORS,
  formKind,
  maxParallelHelp,
  newMember,
  pauseEveryDefault,
  pauseEveryShown,
  placeFinding,
  placeFindings,
  sentRows,
  trialInput,
  trialRequestId,
  type TrialForm,
} from '@/lib/teamForm';
import { hasRounds, noProjectsWords, roundColumnNamed, trialPhrase, trialRows } from '@/lib/teamTrials';
import type { TeamStatus, TeamTrialItem } from '@/types/team';

import statusOn from '../../e2e/fixtures/team/status-on.json';
import trialsList from '../../e2e/fixtures/team/trials-list.json';

/** Today's server: no check-in default. */
const TODAY = statusOn.body as unknown as TeamStatus;

/** The new engine: status-on with its defaults and limits (FLOW api-fields section 2). */
const FLOW: TeamStatus = {
  ...TODAY,
  defaults: { ...TODAY.defaults, pause_every_usd: 100, max_parallel: null },
  limits: { ...TODAY.limits, pause_every_usd: { min: 1, max: 10000 } },
};

/** Today's request, key by key, in today's order. */
const TODAY_KEYS = ['goal', 'members', 'leader', 'pause_after_rounds', 'communication', 'project_path'];
const FLOW_KEYS = ['goal', 'members', 'leader', 'pause_every_usd', 'max_parallel', 'communication', 'project_path'];

/** A filled form: a lead planner and a builder, with every field of both engines typed in. */
function filled(change: Partial<TrialForm> = {}): TrialForm {
  const lead = { ...newMember(TODAY, 'a'), role: 'planner', name: 'lead', named: true };
  const maker = { ...newMember(TODAY, 'b'), role: 'builder', name: '', named: false };
  return {
    ...emptyForm(TODAY),
    goal: 'Write a short welcome note for the notes app.',
    members: [lead, maker],
    leader: 'a',
    pause: '3',
    pauseEvery: '50',
    maxParallel: '2',
    ...change,
  };
}

describe('the New project form on either engine', () => {
  it('follows the server: a check-in default in its status is the new engine; none, or no status, is today', () => {
    expect(formKind(TODAY)).toBe('rounds');
    expect(formKind(null)).toBe('rounds');
    expect(formKind(FLOW)).toBe('flow');
    // Has the key, whatever its value: the new engine.
    expect(formKind({ defaults: { ...TODAY.defaults, pause_every_usd: 0 } })).toBe('flow');

    const empty = emptyForm(FLOW);
    expect(empty.pause).toBe('');
    expect(empty.pauseEvery).toBeNull();
    expect(empty.maxParallel).toBe('');
    // Untouched, Check in every shows Temper's default; as typed once the owner types, even empty.
    expect(pauseEveryDefault(FLOW)).toBe('100');
    expect(pauseEveryDefault(TODAY)).toBe('');
    expect(pauseEveryShown(empty, FLOW)).toBe('100');
    expect(pauseEveryShown({ pauseEvery: '' }, FLOW)).toBe('');
    expect(pauseEveryShown({ pauseEvery: '75.5' }, FLOW)).toBe('75.5');
  });

  it("sends today's server exactly today's request, whatever the new fields hold", () => {
    for (const status of [TODAY, null]) {
      const input = trialInput(filled(), status);
      expect(Object.keys(input)).toEqual(TODAY_KEYS);
      expect(input).toEqual({
        goal: 'Write a short welcome note for the notes app.',
        members: [
          { role: 'planner', name: 'lead', tools: TODAY.tools.default },
          { role: 'builder', tools: TODAY.tools.default },
        ],
        leader: 'lead',
        pause_after_rounds: 3,
        communication: 'all',
        project_path: null,
      });
    }
    // The form's one argument still means today's request.
    expect(trialInput(filled())).toEqual(trialInput(filled(), TODAY));
    expect(trialInput(filled({ pause: '' }), TODAY).pause_after_rounds).toBeNull();
  });

  it('sends the new engine the check-in and members at once, and never pause_after_rounds', () => {
    const input = trialInput(filled(), FLOW);
    expect(Object.keys(input)).toEqual(FLOW_KEYS);
    expect(input).not.toHaveProperty('pause_after_rounds');
    expect(input).toMatchObject({ leader: 'lead', pause_every_usd: 50, max_parallel: 2, communication: 'all' });

    // Untouched: Temper's default as shown; Max members empty: every member (null).
    const untouched = trialInput(filled({ pauseEvery: null, maxParallel: '' }), FLOW);
    expect(untouched).toMatchObject({ pause_every_usd: 100, max_parallel: null });
    // Emptied by the owner: null, which Temper takes as its default ($100); typed as written.
    const typed = trialInput(filled({ pauseEvery: '  ', maxParallel: '3', project: '/srv/example/projects/notes-app' }), FLOW);
    expect(typed).toMatchObject({ pause_every_usd: null, max_parallel: 3, project_path: '/srv/example/projects/notes-app' });
    expect(trialInput(filled({ pauseEvery: '12.5' }), FLOW).pause_every_usd).toBe(12.5);
  });

  it('starts a new request when the engine changed between tries, and keeps it while nothing did', () => {
    const form = filled();
    const before = { requestId: 'req-1', input: trialInput(form, TODAY) };
    let n = 0;
    const make = () => `req-new-${++n}`;
    expect(trialRequestId(before, trialInput(form, TODAY), make)).toBe('req-1');
    expect(trialRequestId(before, trialInput(form, FLOW), make)).toBe('req-new-1');
  });

  it("places the new engine's problems under their own fields", () => {
    const form = filled();
    const rows = sentRows(form);
    const every = { field: 'pause_every_usd', text: 'pause_every_usd: must be a number of US dollars from 1 to 10000' };
    const atOnce = { field: 'max_parallel', text: "max_parallel: is 3, more than the team's 2 member(s)" };
    const gone = {
      field: 'pause_after_rounds',
      text: 'pause_after_rounds is gone: teams work free-flowing now; set pause_every_usd (default 100)',
    };
    expect(placeFinding(every, rows)).toEqual({ kind: 'field', field: 'pause_every_usd' });
    expect(placeFinding(atOnce, rows)).toEqual({ kind: 'field', field: 'max_parallel' });

    const placed = placeFindings([atOnce, gone, every], rows);
    expect(placed.fields.pause_every_usd).toEqual([every]);
    expect(placed.fields.max_parallel).toEqual([atOnce]);
    expect(placed.fields.pause_after_rounds).toEqual([gone]);
    expect(placed.all.map((p) => p.finding)).toEqual([atOnce, gone, every]);
    expect(FIELD_ANCHORS.pause_every_usd).toBe('team-pause-every');
    expect(FIELD_ANCHORS.max_parallel).toBe('team-max-parallel');
    expect(FIELD_ANCHORS.pause_after_rounds).toBe('team-pause');
  });
});

describe("the Projects list's round words", () => {
  const items = (trialsList.body as { trials: TeamTrialItem[] }).trials;

  it("says nothing about rounds for a free-flowing team; today's items keep them", () => {
    const flow: TeamTrialItem = { ...items[0], kind: 'flow', round: undefined };
    expect(hasRounds(flow)).toBe(false);
    expect(hasRounds(items[0])).toBe(true);
    expect(hasRounds({ ...items[0], kind: 'rounds' })).toBe(true);

    // The Round column keeps its name unless every row on the page is free-flowing.
    expect(roundColumnNamed(trialRows(items, 0))).toBe(true);
    expect(roundColumnNamed(trialRows([flow, items[1]], 0))).toBe(true);
    expect(roundColumnNamed(trialRows([flow, { ...flow, trial_id: 'other', execution_id: 'other-run' }], 0))).toBe(false);
    expect(roundColumnNamed([])).toBe(true);
  });

  it("says Design's words: an interrupted round run, no projects, the members-at-once range", () => {
    // Only the new engine marks a run as a round team's; it can't resume one.
    const halted = { state: 'interrupted', run_status: 'interrupted' };
    expect(trialPhrase({ ...halted, kind: 'rounds' })).toBe("interrupted; this Temper can't resume a round run");
    expect(trialPhrase(halted)).toBe('resume it from the run page');
    expect(trialPhrase({ ...halted, kind: 'flow' })).toBe('resume it from the run page');
    // Paused at a check-in: today's badge alone, no amount.
    expect(trialPhrase({ state: 'paused', run_status: 'waiting', kind: 'flow' })).toBeNull();

    expect(noProjectsWords('flow')).toBe(
      'Start one: the leader gets your goal and messages the others their work, and Temper checks in with you as spend grows.',
    );
    expect(noProjectsWords('rounds')).toMatch(/^A project puts a few pi roles on one goal\. They work in rounds/);

    expect(maxParallelHelp(1)).toBe('How many members may work at the same moment: 1 to 1. Leave it empty for all of them.');
    expect(maxParallelHelp(12)).toBe('How many members may work at the same moment: 1 to 12. Leave it empty for all of them.');
  });
});
