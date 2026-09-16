/**
 * Layout of runtime-created nodes.
 *
 * A dispatcher and the nodes it creates at runtime have no `depends_on`
 * between them, so nothing tied them together for the layout engine: every
 * dynamic run drew its nodes stacked at one coordinate with no edges — a
 * four-way fan-out rendered as a single card with three hidden underneath.
 */
import { describe, expect, it } from 'vitest';

import { layoutWithElk } from '@/lib/elkLayout';
import type { NodeExecution } from '@/types';

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
});
