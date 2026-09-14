/**
 * Studio load → save round-trip.
 *
 * Studio models a subset of the workflow schema. Anything outside that
 * subset must survive being opened and saved, otherwise editing one field
 * in the UI silently deletes unrelated configuration.
 */
import { describe, it, expect } from 'vitest';
import {
  parseWorkflowMeta,
  parseWorkflowStages,
  serializeWorkflowConfig,
} from '@/store/designPersistence';

/** Shape of configs/workflows/local/audit_branch.yaml (trimmed). */
const WORKFLOW = {
  workflow: {
    name: 'audit_branch',
    description: 'Audit fixture',
    defaults: { provider: 'claude', model: 'haiku' },
    inputs: {
      topic: { type: 'string', required: true },
      verdict: { type: 'string', required: true },
      n_lanes: { type: 'number', required: false },
    },
    outputs: {
      verdict: 'plan.structured.verdict',
      summary: 'synth.output',
    },
    nodes: [
      {
        name: 'plan',
        type: 'agent',
        agent: 'audit_planner',
        outputs: { verdict: 'string', items: 'list', count: 'number' },
      },
      {
        name: 'complex_path',
        type: 'stage',
        strategy: 'parallel',
        depends_on: ['plan'],
        condition: { source: 'plan.structured.verdict', operator: 'equals', value: 'complex' },
        agents: [
          { agent: 'audit_worker', name: 'first_item', task_template: 'FIRST: {{ item }}' },
          { agent: 'audit_worker', name: 'last_item', task_template: 'LAST: {{ item }}' },
        ],
      },
      {
        name: 'lanes',
        type: 'template',
        for_each: 'input.n_lanes',
        as: 'i',
        template: [
          { name: 'lane_{{ i }}', type: 'agent', agent: 'audit_worker', depends_on: ['plan'] },
        ],
      },
    ],
  },
} as Record<string, unknown>;

function roundTrip(config: Record<string, unknown>) {
  const meta = parseWorkflowMeta('audit_branch', config);
  const stages = parseWorkflowStages(config);
  const out = serializeWorkflowConfig(meta, stages) as Record<string, unknown>;
  const inner = (out.workflow ?? out) as Record<string, unknown>;
  const nodes = (inner.nodes ?? inner.stages) as Record<string, unknown>[];
  return { inner, nodes };
}

describe('Studio workflow round-trip', () => {
  it('keeps workflow-level inputs and outputs', () => {
    const { inner } = roundTrip(WORKFLOW);
    expect(inner.inputs).toEqual({
      topic: { type: 'string', required: true },
      verdict: { type: 'string', required: true },
      n_lanes: { type: 'number', required: false },
    });
    expect(inner.outputs).toEqual({
      verdict: 'plan.structured.verdict',
      summary: 'synth.output',
    });
  });

  it('keeps per-agent overrides inside a stage', () => {
    const { nodes } = roundTrip(WORKFLOW);
    const stage = nodes.find((n) => n.name === 'complex_path')!;
    expect(stage.agents).toEqual([
      { agent: 'audit_worker', name: 'first_item', task_template: 'FIRST: {{ item }}' },
      { agent: 'audit_worker', name: 'last_item', task_template: 'LAST: {{ item }}' },
    ]);
  });

  it('does not collapse two entries of the same agent into duplicates', () => {
    const { nodes } = roundTrip(WORKFLOW);
    const stage = nodes.find((n) => n.name === 'complex_path')!;
    const names = (stage.agents as Record<string, unknown>[]).map((a) => a.name);
    expect(new Set(names).size).toBe(names.length);
  });

  it('passes through node types Studio cannot edit', () => {
    const { nodes } = roundTrip(WORKFLOW);
    const template = nodes.find((n) => n.name === 'lanes')!;
    expect(template.type).toBe('template');
    expect(template.for_each).toBe('input.n_lanes');
    expect(template.template).toEqual([
      { name: 'lane_{{ i }}', type: 'agent', agent: 'audit_worker', depends_on: ['plan'] },
    ]);
  });

  it('keeps a plain agent node addressable', () => {
    const { nodes } = roundTrip(WORKFLOW);
    const plan = nodes.find((n) => n.name === 'plan')!;
    expect(plan.agent).toBe('audit_planner');
    expect(plan.outputs).toEqual({ verdict: 'string', items: 'list', count: 'number' });
  });
});
