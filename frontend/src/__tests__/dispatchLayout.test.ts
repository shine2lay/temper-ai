/**
 * Layout of runtime-created nodes.
 *
 * A dispatcher and the nodes it creates at runtime have no `depends_on`
 * between them, so nothing tied them together for the layout engine: every
 * dynamic run drew its nodes stacked at one coordinate with no edges — a
 * four-way fan-out rendered as a single card with three hidden underneath.
 */
import { describe, expect, it } from 'vitest';

import { LAYOUT } from '@/lib/constants';
import { layoutWithElk } from '@/lib/elkLayout';
import type { NodeExecution } from '@/types';

/** What the layout promises between columns (`nodeNodeBetweenLayers`). */
const COLUMN_GAP = 80;

function agent(id: string, name: string, extra: Partial<NodeExecution> = {}): NodeExecution {
  return {
    id,
    name,
    type: 'agent',
    status: 'completed',
    depends_on: [],
    ...extra,
  } as NodeExecution;
}

/** A dispatcher with four nodes it created, the shape the API returns. */
function dispatchTree(): NodeExecution[] {
  const children = ['alpha', 'beta', 'gamma', 'delta'].map((n, i) =>
    agent(`child-${i}`, `research_${n}`, { dispatched_by: 'scout' } as Partial<NodeExecution>),
  );
  return [
    agent('scout-1', 'scout', {
      child_nodes: children,
      dispatched_children: children.map((c) => c.name),
    } as Partial<NodeExecution>),
  ];
}

describe('dispatch layout', () => {
  it('gives every dynamically created node its own position', async () => {
    const result = await layoutWithElk(dispatchTree(), { hideSkipped: false });

    const positions = result.nodes.map((n) => `${Math.round(n.x)},${Math.round(n.y)}`);
    expect(result.nodes.length).toBeGreaterThanOrEqual(5);
    // Four children plus the dispatcher: five distinct places on the canvas.
    expect(new Set(positions).size).toBe(positions.length);
  });

  it('connects each dynamic node to whatever created it', async () => {
    const result = await layoutWithElk(dispatchTree(), { hideSkipped: false });
    expect(result.edges.length).toBeGreaterThanOrEqual(4);
  });

  it('still lays out a plain dependency chain', async () => {
    const chain = [
      agent('a', 'first'),
      agent('b', 'second', { depends_on: ['first'] } as Partial<NodeExecution>),
      agent('c', 'third', { depends_on: ['second'] } as Partial<NodeExecution>),
    ];
    const result = await layoutWithElk(chain, { hideSkipped: false });
    const xs = result.nodes.map((n) => Math.round(n.x));
    expect(new Set(xs).size).toBeGreaterThan(1);
  });

  it('leaves the promised gap between columns, measured against the card as drawn', async () => {
    // The layout reserved 220 for a card drawn 280 wide, so 60 of the 80
    // units between columns sat under the card: 20 were left, and a
    // fan-out's edges all bent inside that strip -- one dashed vertical
    // line with no telling which arrow reached which child.
    const result = await layoutWithElk(dispatchTree(), { hideSkipped: false });
    const scout = result.nodes.find((n) => n.id === 'scout-1')!;
    const child = result.nodes.find((n) => n.id === 'child-0')!;

    const gap = child.x - (scout.x + LAYOUT.AGENT_CARD_WIDTH);
    expect(gap).toBeGreaterThanOrEqual(COLUMN_GAP);
  });

  it('keeps dispatched children in the order they were dispatched', async () => {
    // Crossing minimisation is free to shuffle nodes that have no edges
    // between them, and it did: a, b, c came out c, a, b. The dispatcher's
    // order is the only order these nodes have, so it is the one to keep.
    const result = await layoutWithElk(dispatchTree(), { hideSkipped: false });
    const ys = ['child-0', 'child-1', 'child-2', 'child-3'].map(
      (id) => result.nodes.find((n) => n.id === id)!.y,
    );
    expect(ys).toEqual([...ys].sort((a, b) => a - b));
  });

  it('draws one card for a node that was attempted twice', async () => {
    // A retry or a re-attempted timeout returns one agent record per
    // attempt, all naming the same agent. Counting records rather than
    // distinct agents sent this down the pseudo-child path and produced a
    // second card at identical coordinates — invisible, and an ambiguous
    // click target. Attempts belong inside the card as iterations.
    const retried = [
      agent('node-1', 'slow', {
        agents: [
          { id: 'att-1', agent_name: 'ui_slow', status: 'failed' },
          { id: 'att-2', agent_name: 'ui_slow', status: 'failed' },
        ],
      } as unknown as Partial<NodeExecution>),
    ];
    const result = await layoutWithElk(retried, { hideSkipped: false });
    const positions = result.nodes.map((n) => `${Math.round(n.x)},${Math.round(n.y)}`);
    expect(new Set(positions).size).toBe(positions.length);
    expect(result.nodes.length).toBe(1);
  });

  describe('a dispatcher whose children dispatch again', () => {
    // The ui_dispatch_rounds shape: each round sends out five children and
    // the next round, which waits for the five. The API nests each round
    // inside the one that dispatched it, so the tree is four levels deep.
    const ROUNDS = 4;
    const KIDS = ['alpha', 'bravo', 'charlie', 'delta', 'echo'];

    function roundsTree(): NodeExecution[] {
      const build = (r: number): NodeExecution => {
        const name = r === 1 ? 'round' : `round_${r}`;
        const kids = KIDS.map((k) =>
          agent(`r${r}-${k}`, `r${r}_${k}`, { dispatched_by: name } as Partial<NodeExecution>),
        );
        const next = r < ROUNDS
          ? [{
            ...build(r + 1),
            dispatched_by: name,
            depends_on: kids.map((k) => k.name),
          } as NodeExecution]
          : [];
        return agent(`round-${r}`, name, {
          child_nodes: [...kids, ...next],
          dispatched_children: [...kids, ...next].map((c) => c.name),
        } as Partial<NodeExecution>);
      };
      return [build(1)];
    }

    const EXPECTED_NODES = ROUNDS * (1 + KIDS.length);

    it('draws every node once, none of them inside another', async () => {
      // The hoist lifted a round's children out but kept the round itself
      // with its children still inside, so rounds 3 and 4 were drawn twice:
      // once lifted and once inside round 2's box.
      const result = await layoutWithElk(roundsTree(), { hideSkipped: false });
      const ids = result.nodes.map((n) => n.id);
      expect(ids.length).toBe(EXPECTED_NODES);
      expect(new Set(ids).size).toBe(EXPECTED_NODES);
      expect(result.nodes.filter((n) => n.parentId)).toEqual([]);
    });

    it('draws each edge once, and one from every dispatcher to what it made', async () => {
      const result = await layoutWithElk(roundsTree(), { hideSkipped: false });
      const ids = result.edges.map((e) => e.id);
      expect(new Set(ids).size).toBe(ids.length);

      const pairs = new Set(result.edges.map((e) => `${e.source}>${e.target}`));
      for (let r = 1; r <= ROUNDS; r++) {
        for (const k of KIDS) expect(pairs).toContain(`round-${r}>r${r}-${k}`);
        if (r < ROUNDS) expect(pairs).toContain(`round-${r}>round-${r + 1}`);
      }
    });

    it('is as wide as its columns, not a container per round', async () => {
      // Rounds nested as containers laid out 5000px wide, with about 1500px
      // between a dispatcher and its children. Two columns per round
      // (dispatcher, children), each a card plus at most twice the promised
      // gap (edge lanes widen it past the minimum).
      const result = await layoutWithElk(roundsTree(), { hideSkipped: false });
      const columns = ROUNDS * 2;
      expect(result.width).toBeLessThanOrEqual(
        columns * (LAYOUT.AGENT_CARD_WIDTH + 2 * COLUMN_GAP),
      );

      const round2 = result.nodes.find((n) => n.id === 'round-2')!;
      const kid = result.nodes.find((n) => n.id === 'r2-alpha')!;
      expect(kid.x - (round2.x + round2.width)).toBeLessThanOrEqual(2 * COLUMN_GAP);
    });
  });
});
