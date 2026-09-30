/**
 * Finding your way around a big run: what a word matches, which node comes
 * next, what a filter keeps, and where the trouble is.
 *
 * The shape under test is the one a real `epd_propose` run has — six
 * `pitch_*` stages of three lenses each, every agent on its own model — so a
 * word like "lens" or "sonnet" has to answer with the right handful out of
 * dozens, in the order the graph lists them.
 */
import { describe, it, expect } from 'vitest';
import {
  buildFindEntries,
  entryMatches,
  entryPassesStatus,
  findMatches,
  litIds,
  litRosterIds,
  matchPosition,
  stepMatch,
  troubleKind,
  troubleOrder,
  type FindEntry,
  type GraphNode,
} from '@/lib/runSearch';

function stage(id: string, name: string, status = 'completed', extra: Partial<FindEntry> = {}): FindEntry {
  return { id, name, status, kind: 'stage', ...extra };
}

function agent(
  id: string,
  name: string,
  parentId: string,
  extra: Partial<FindEntry> = {},
): FindEntry {
  return {
    id,
    name,
    parentId,
    status: 'completed',
    kind: 'agent',
    model: 'claude-sonnet-4-5',
    provider: 'anthropic',
    ...extra,
  };
}

/** A run shaped like an `epd_propose` proposal: stages of three lenses each. */
function proposalRun(): FindEntry[] {
  const out: FindEntry[] = [stage('s-personas', 'personas'), agent('a-personas', 'personas', 's-personas')];
  for (const bet of ['b127', 'b133', 'b140']) {
    const sid = `s-pitch-${bet}`;
    out.push(stage(sid, `pitch_${bet}`));
    for (const lens of ['reach', 'code', 'break']) {
      out.push(agent(`a-${bet}-${lens}`, `lens_${lens}`, sid, { agentName: `epd_lens_${lens}` }));
    }
  }
  out.push(stage('s-report', 'report'), agent('a-report', 'report', 's-report', { model: 'gpt-5', provider: 'openai' }));
  return out;
}

describe('what a word matches', () => {
  it('finds part of a word, whatever the case', () => {
    const node = stage('s1', 'pitch_b133');
    expect(entryMatches(node, 'pitch')).toBe(true);
    expect(entryMatches(node, 'PITCH')).toBe(true);
    expect(entryMatches(node, 'b13')).toBe(true);
    expect(entryMatches(node, '  b133 ')).toBe(true);
    expect(entryMatches(node, 'reach')).toBe(false);
  });

  it('matches a stage name, an agent name and the model it ran on', () => {
    const node = agent('a1', 'lens_reach', 's1', {
      agentName: 'epd_lens_reach',
      model: 'claude-sonnet-4-5',
      provider: 'anthropic',
    });
    expect(entryMatches(node, 'lens_reach')).toBe(true);   // the node's name
    expect(entryMatches(node, 'epd_lens')).toBe(true);     // the agent's own name
    expect(entryMatches(node, 'sonnet')).toBe(true);       // the model
    expect(entryMatches(node, 'anthropic')).toBe(true);    // its provider
    expect(entryMatches(node, 'haiku')).toBe(false);
  });

  it('an empty word matches nothing, so the page stays as it was', () => {
    expect(entryMatches(stage('s1', 'anything'), '')).toBe(false);
    expect(entryMatches(stage('s1', 'anything'), '   ')).toBe(false);
    expect(findMatches(proposalRun(), '')).toEqual([]);
  });

  it('a node with no agent and no model is matched by its name alone', () => {
    const node = stage('s1', 'report', 'completed');
    expect(entryMatches(node, 'report')).toBe(true);
    expect(entryMatches(node, 'sonnet')).toBe(false);
  });
});

describe('the matches of a big run, in the order it draws them', () => {
  const run = proposalRun();

  it('answers with every hit, in graph order', () => {
    expect(findMatches(run, 'pitch')).toEqual(['s-pitch-b127', 's-pitch-b133', 's-pitch-b140']);
    expect(findMatches(run, 'lens_reach')).toEqual(['a-b127-reach', 'a-b133-reach', 'a-b140-reach']);
  });

  it('a model name finds every node that ran on it', () => {
    expect(findMatches(run, 'sonnet')).toHaveLength(10); // every agent but the report
    expect(findMatches(run, 'gpt-5')).toEqual(['a-report']);
  });

  it('the status filter narrows the count as well as the view', () => {
    const withTrouble = proposalRun().map((e) =>
      e.id === 'a-b133-code' ? { ...e, status: 'failed' } : e,
    );
    expect(findMatches(withTrouble, 'lens', 'failed')).toEqual(['a-b133-code']);
    expect(findMatches(withTrouble, 'lens', 'all')).toHaveLength(9);
  });

  it('a word nothing answers to gives an empty list', () => {
    expect(findMatches(run, 'zzz')).toEqual([]);
  });
});

describe('stepping through the matches', () => {
  const matches = ['a', 'b', 'c'];

  it('starts at the first, then walks on', () => {
    expect(stepMatch(matches, null)).toBe('a');
    expect(stepMatch(matches, 'a')).toBe('b');
    expect(stepMatch(matches, 'b')).toBe('c');
  });

  it('goes round at the end, and round the other way at the start', () => {
    expect(stepMatch(matches, 'c')).toBe('a');
    expect(stepMatch(matches, 'a', -1)).toBe('c');
    expect(stepMatch(matches, 'b', -1)).toBe('a');
  });

  it('backwards from nowhere lands on the last one', () => {
    expect(stepMatch(matches, null, -1)).toBe('c');
  });

  it('a node that is no longer a match starts again from the top', () => {
    expect(stepMatch(matches, 'gone')).toBe('a');
    expect(stepMatch(matches, 'gone', -1)).toBe('c');
  });

  it('no matches means nowhere to go', () => {
    expect(stepMatch([], null)).toBeNull();
    expect(stepMatch([], 'a')).toBeNull();
  });

  it('says which match you are on, for "3 of 11"', () => {
    expect(matchPosition(matches, 'c')).toBe(3);
    expect(matchPosition(matches, null)).toBe(0);
    expect(matchPosition(matches, 'gone')).toBe(0);
  });
});

describe('take me to the trouble', () => {
  it('goes to what failed, in run order', () => {
    const run = proposalRun().map((e) =>
      e.id === 'a-b127-code' || e.id === 'a-b140-break' ? { ...e, status: 'failed' } : e,
    );
    expect(troubleOrder(run)).toEqual(['a-b127-code', 'a-b140-break']);
    expect(troubleKind(run)).toBe('failed');
  });

  it('a timed-out node is trouble too', () => {
    const run = proposalRun().map((e) => (e.id === 'a-b133-code' ? { ...e, status: 'timeout' } : e));
    expect(troubleOrder(run)).toEqual(['a-b133-code']);
  });

  it('nothing failed: it goes to what is running now', () => {
    const run = proposalRun().map((e) =>
      e.id === 'a-b140-break' ? { ...e, status: 'running' } : e,
    );
    expect(troubleOrder(run)).toEqual(['a-b140-break']);
    expect(troubleKind(run)).toBe('running');
  });

  it('nothing running either: it goes to what waits on a person', () => {
    const run = proposalRun().map((e) =>
      e.id === 's-report' ? { ...e, status: 'waiting', gateWaiting: true } : e,
    );
    expect(troubleOrder(run)).toEqual(['s-report']);
    expect(troubleKind(run)).toBe('waiting');
  });

  it('a run where all is well has nowhere to send you', () => {
    expect(troubleOrder(proposalRun())).toEqual([]);
    expect(troubleKind(proposalRun())).toBe('none');
  });
});

describe('the status filter', () => {
  it('keeps what it names, and "all" keeps everything', () => {
    const running = stage('s1', 'work', 'running');
    const failed = stage('s2', 'work', 'failed');
    const gated = stage('s3', 'decide', 'waiting', { gateWaiting: true });
    const done = stage('s4', 'work', 'completed');

    expect(['all', 'running', 'failed', 'waiting'].map((f) =>
      entryPassesStatus(done, f as 'all'),
    )).toEqual([true, false, false, false]);
    expect(entryPassesStatus(running, 'running')).toBe(true);
    expect(entryPassesStatus(failed, 'failed')).toBe(true);
    expect(entryPassesStatus(gated, 'waiting')).toBe(true);
  });

  it('a node whose gate is unanswered counts as waiting on a person', () => {
    const gated = stage('s1', 'decide', 'running', { gateWaiting: true });
    expect(entryPassesStatus(gated, 'waiting')).toBe(true);
  });
});

describe('what stays bright', () => {
  it('nothing narrowing means nothing to dim', () => {
    expect(litIds(proposalRun(), '', 'all')).toBeNull();
  });

  it('an agent found by name keeps the stage it sits in bright', () => {
    const lit = litIds(proposalRun(), 'lens_break', 'all')!;
    expect(lit.has('a-b133-break')).toBe(true);
    expect(lit.has('s-pitch-b133')).toBe(true);   // so you can see where it is
    expect(lit.has('a-b133-reach')).toBe(false);  // its neighbour is not a hit
  });

  it('a stage found by name brings its agents with it', () => {
    const lit = litIds(proposalRun(), 'pitch_b133', 'all')!;
    expect(lit.has('s-pitch-b133')).toBe(true);
    expect(lit.has('a-b133-code')).toBe(true);
    expect(lit.has('s-pitch-b127')).toBe(false);
  });

  it('a status filter lights the node and where it sits, not its neighbours', () => {
    const run = proposalRun().map((e) =>
      e.id === 'a-b133-code' ? { ...e, status: 'failed' } : e,
    );
    const lit = litIds(run, '', 'failed')!;
    expect(lit.has('a-b133-code')).toBe(true);
    expect(lit.has('s-pitch-b133')).toBe(true);
    expect(lit.has('a-b133-reach')).toBe(false);
    expect(lit.has('s-pitch-b127')).toBe(false);
  });

  it('word and filter together keep only what passes both', () => {
    const run = proposalRun().map((e) =>
      e.id === 'a-b133-code' ? { ...e, status: 'failed' }
        : e.id === 'a-b127-reach' ? { ...e, status: 'failed' }
        : e,
    );
    const lit = litIds(run, 'code', 'failed')!;
    expect(lit.has('a-b133-code')).toBe(true);
    expect(lit.has('a-b127-reach')).toBe(false); // failed, but not the word
    expect(lit.has('a-b140-code')).toBe(false);  // the word, but not failed
  });

  it('a word nothing answers to leaves the whole run dim', () => {
    expect(litIds(proposalRun(), 'zzz', 'all')!.size).toBe(0);
  });
});

describe('reading the drawn graph', () => {
  /** A node as React Flow holds it, with only the fields finding reads. */
  function graphStage(id: string, name: string, x: number, status = 'completed'): GraphNode {
    return {
      id,
      type: 'stageGroup',
      position: { x, y: 0 },
      data: { stage: { id, name, status, type: 'stage' } },
    };
  }
  function graphAgent(
    id: string,
    name: string,
    parentId: string,
    x: number,
    y: number,
    agentPatch: Record<string, unknown> = {},
  ): GraphNode {
    return {
      id,
      type: 'agentNode',
      parentId,
      position: { x, y },
      data: {
        stage: { id, name, status: 'completed', type: 'agent' },
        agent: {
          id: `${id}-agent`,
          agent_name: name,
          status: 'completed',
          agent_config_snapshot: { agent: { model: 'claude-sonnet-4-5', provider: 'anthropic' } },
          ...agentPatch,
        },
      },
    };
  }

  it('reads a node\'s name, its agent and the model it ran on', () => {
    const entries = buildFindEntries([
      graphStage('s-pitch', 'pitch_b133', 0),
      graphAgent('n-lens', 'lens_code', 's-pitch', 40, 0, { agent_name: 'epd_lens_code' }),
    ]);
    expect(entries.map((e) => e.id)).toEqual(['s-pitch', 'n-lens']);
    expect(entries[1]).toMatchObject({
      kind: 'agent',
      parentId: 's-pitch',
      name: 'lens_code',
      agentName: 'epd_lens_code',
      model: 'claude-sonnet-4-5',
      provider: 'anthropic',
    });
    expect(findMatches(entries, 'sonnet')).toEqual(['n-lens']);
  });

  it('lists the run left to right, each stage followed by what is inside it', () => {
    const entries = buildFindEntries([
      // Handed over in the order the layout engine solved them, not the
      // order a person reads them in.
      graphAgent('n-b', 'second_agent', 's-second', 20, 0),
      graphStage('s-second', 'second', 400),
      graphStage('s-first', 'first', 0),
      graphAgent('n-a2', 'first_lower', 's-first', 20, 200),
      graphAgent('n-a1', 'first_upper', 's-first', 20, 0),
    ]);
    expect(entries.map((e) => e.id)).toEqual(['s-first', 'n-a1', 'n-a2', 's-second', 'n-b']);
  });

  it('a node whose agent failed is trouble, whatever the node says', () => {
    const entries = buildFindEntries([
      graphStage('s', 'pitch', 0, 'running'),
      graphAgent('n', 'lens_code', 's', 40, 0, { status: 'failed' }),
    ]);
    expect(troubleOrder(entries)).toEqual(['n']);
  });

  it('a gate still unanswered reads as waiting on a person', () => {
    const entries = buildFindEntries([
      {
        id: 'g',
        type: 'stageGroup',
        position: { x: 0, y: 0 },
        data: { stage: { id: 'g', name: 'approve', status: 'running', gate_status: 'waiting' } },
      },
    ]);
    expect(entries[0].gateWaiting).toBe(true);
    expect(entryPassesStatus(entries[0], 'waiting')).toBe(true);
  });

  it('skips whatever is not a node of the run', () => {
    expect(buildFindEntries([{ id: 'note', type: 'annotation', data: {} }])).toEqual([]);
  });
});

describe('the live panel\'s list, narrowed by the same word', () => {
  const roster = [
    {
      name: 'pitch_b133',
      agents: [
        { id: 'a1', name: 'lens_reach', model: 'claude-sonnet-4-5', status: 'completed' },
        { id: 'a2', name: 'lens_code', model: 'gpt-5', status: 'failed' },
      ],
    },
    {
      name: 'report',
      agents: [{ id: 'a3', name: 'writer', model: 'claude-opus-4-5', status: 'running' }],
    },
  ];

  it('nothing narrowing leaves the list alone', () => {
    expect(litRosterIds(roster, '', 'all')).toBeNull();
  });

  it('an agent name lights that row only', () => {
    expect([...litRosterIds(roster, 'reach', 'all')!]).toEqual(['a1']);
  });

  it('a stage name lights the agents that ran in it', () => {
    expect([...litRosterIds(roster, 'pitch', 'all')!]).toEqual(['a1', 'a2']);
  });

  it('a model name reaches the list as it reaches the graph', () => {
    expect([...litRosterIds(roster, 'gpt-5', 'all')!]).toEqual(['a2']);
  });

  it('the status filter narrows the list with no word at all', () => {
    expect([...litRosterIds(roster, '', 'failed')!]).toEqual(['a2']);
    expect([...litRosterIds(roster, '', 'running')!]).toEqual(['a3']);
  });
});
