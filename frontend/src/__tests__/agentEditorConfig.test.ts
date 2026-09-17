/**
 * The Library agent editor's pure half.
 *
 * Bug 44: the Type dropdown offered "Conversational / Autonomous /
 * Reactive". The engine runs "llm" and "script". Every agent saved with an
 * offered type failed its first run with "Unknown agent type". The list
 * must come from the engine's registry, and a missing type must mean what
 * it means to the engine: llm.
 */
import { describe, expect, it } from 'vitest';

import {
  EMPTY_FORM,
  agentTypeOptions,
  buildAgentConfig,
  formFromAgent,
} from '@/components/studio/editors/agentEditorConfig';

const REGISTRY = ['llm', 'script'];

describe('agent type options', () => {
  it('offers exactly what the engine registers', () => {
    expect(agentTypeOptions(REGISTRY, 'llm').map((o) => o.value)).toEqual(['llm', 'script']);
  });

  it('never offers a word the engine does not have', () => {
    const values = agentTypeOptions(REGISTRY, 'llm').map((o) => o.value);
    for (const invented of ['conversational', 'autonomous', 'reactive', 'standard']) {
      expect(values).not.toContain(invented);
    }
  });

  it('shows a loaded type the registry lacks as itself, and says so', () => {
    const opts = agentTypeOptions(REGISTRY, 'plugin_type');
    expect(opts[0]).toEqual({
      value: 'plugin_type',
      label: 'plugin_type (not registered on this server)',
    });
    expect(opts.map((o) => o.value)).toEqual(['plugin_type', 'llm', 'script']);
  });

  it('shows only the current value while the registry is still loading', () => {
    expect(agentTypeOptions(undefined, 'script')).toEqual([{ value: 'script', label: 'script' }]);
  });

  it('defaults a new agent to llm', () => {
    expect(EMPTY_FORM.type).toBe('llm');
  });
});

describe('reading a config into the form', () => {
  it('reads a missing type as llm, the way the engine does', () => {
    expect(formFromAgent({ name: 'x' }).type).toBe('llm');
  });

  it('keeps a declared type', () => {
    expect(formFromAgent({ name: 'x', type: 'script' }).type).toBe('script');
  });
});

describe('building the config to save', () => {
  it('always names the agent, so the config says what it is', () => {
    const form = { ...EMPTY_FORM, name: 'fresh' };
    expect(buildAgentConfig({}, form).agent.name).toBe('fresh');
  });

  it('a no-op save on an agent with no type key does not invent one', () => {
    const raw = { name: 'x', system_prompt: 'hi' };
    const form = { ...EMPTY_FORM, name: 'x', ...formFromAgent(raw) };
    expect(buildAgentConfig(raw, form)).toEqual({ agent: raw });
  });

  it('a no-op save on a script agent is byte-identical (bug 25 holds)', () => {
    const raw = { name: 'ui_echo', type: 'script', script_template: 'echo', timeout_seconds: 20 };
    const form = { ...EMPTY_FORM, name: 'ui_echo', ...formFromAgent(raw) };
    expect(buildAgentConfig(raw, form)).toEqual({ agent: raw });
  });

  it('writes the type when the user changes it', () => {
    const raw = { name: 'x', system_prompt: 'hi' };
    const form = { ...EMPTY_FORM, name: 'x', ...formFromAgent(raw), type: 'script' };
    expect(buildAgentConfig(raw, form).agent.type).toBe('script');
  });

  it('a new agent left at the default carries no type key and no LLM defaults', () => {
    const form = { ...EMPTY_FORM, name: 'fresh', system_prompt: 'be brief' };
    expect(buildAgentConfig({}, form)).toEqual({ agent: { name: 'fresh', system_prompt: 'be brief' } });
  });

  it('carries script fields entered through the YAML panel', () => {
    // The YAML panel replaces the raw config; the form then only overlays
    // what it manages. A script_template must survive to the save body.
    const fromYaml = { name: 'y', type: 'script', script_template: '#!/bin/sh\necho ok' };
    const form = { ...EMPTY_FORM, name: 'y', ...formFromAgent(fromYaml) };
    expect(buildAgentConfig(fromYaml, form).agent).toMatchObject({
      type: 'script',
      script_template: '#!/bin/sh\necho ok',
    });
  });
});
