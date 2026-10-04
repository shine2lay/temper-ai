/**
 * YAML Preview panel — shows the complete workflow bundle:
 * workflow config + all referenced agent configs.
 * Users can view individual files or download everything as a bundle.
 */
import { useState, useMemo, useCallback, useEffect } from 'react';
import yaml from 'js-yaml';
import { useDesignStore } from '@/store/designStore';
import { CopyButton } from '@/components/shared/CopyButton';
import { authFetch } from '@/lib/authFetch';

interface YamlPreviewProps {
  open: boolean;
  onClose: () => void;
}

type ViewMode = 'bundle' | 'workflow' | string; // string = agent name

export function YamlPreview({ open, onClose }: YamlPreviewProps) {
  const stages = useDesignStore((s) => s.stages);
  const meta = useDesignStore((s) => s.meta);
  const [view, setView] = useState<ViewMode>('bundle');
  const [agentConfigs, setAgentConfigs] = useState<Record<string, string>>({});

  // All agent names in the workflow
  const agentNames = useMemo(() => {
    const names = new Set<string>();
    for (const s of stages) {
      for (const a of s.agents) names.add(a);
    }
    return Array.from(names).sort();
  }, [stages]);

  // Serialize workflow to YAML
  const workflowYaml = useMemo(() => {
    try {
      const config = useDesignStore.getState().toWorkflowConfig();
      return yaml.dump(config, { indent: 2, lineWidth: 120, noRefs: true });
    } catch (e) {
      return `# Error serializing: ${e}`;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stages, meta]);

  // Fetch all agent configs when panel opens
  useEffect(() => {
    if (!open || agentNames.length === 0) return;
    const fetchAll = async () => {
      const results: Record<string, string> = {};
      for (const name of agentNames) {
        try {
          const res = await authFetch(`/api/studio/configs/agent/${name}`);
          if (res.ok) {
            const json = await res.json();
            const data = json.config_data ?? json;
            results[name] = yaml.dump(data, { indent: 2, lineWidth: 120, noRefs: true });
          } else {
            results[name] = `# Agent '${name}' not found in config store`;
          }
        } catch {
          results[name] = `# Error loading agent '${name}'`;
        }
      }
      setAgentConfigs(results);
    };
    fetchAll();
  }, [open, agentNames]);

  // Build the full bundle with inline documentation
  const bundleYaml = useMemo(() => {
    const wfName = meta.name || 'workflow';
    const parts: string[] = [];

    parts.push(`# ============================================================`);
    parts.push(`# Temper AI Workflow Bundle`);
    parts.push(`# Generated from Studio — all files needed to run this workflow`);
    parts.push(`#`);
    parts.push(`# To use: split into individual files and place in your configs/ directory`);
    parts.push(`#   configs/workflows/${wfName}.yaml`);
    for (const name of agentNames) {
      parts.push(`#   configs/agents/${name}.yaml`);
    }
    parts.push(`#`);
    parts.push(`# Run: POST /api/runs { "workflow": "${wfName}", "inputs": { "task": "..." } }`);
    parts.push(`# ============================================================\n`);

    // Workflow file with annotations
    parts.push(`# ── Workflow: ${wfName} ──────────────────────────────────────`);
    parts.push(`# File: configs/workflows/${wfName}.yaml\n`);
    parts.push(annotateWorkflowYaml(workflowYaml));

    // Agent files with annotations
    for (const name of agentNames) {
      parts.push(`\n# ── Agent: ${name} ──────────────────────────────────────────`);
      parts.push(`# File: configs/agents/${name}.yaml\n`);
      parts.push(annotateAgentYaml(agentConfigs[name] ?? `# Loading...`));
    }

    return parts.join('\n');
  }, [workflowYaml, agentConfigs, agentNames, meta.name]);

  // Download as a single file
  const handleDownload = useCallback(() => {
    const wfName = meta.name || 'workflow';
    const blob = new Blob([bundleYaml], { type: 'text/yaml' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${wfName}_bundle.yaml`;
    a.click();
    URL.revokeObjectURL(url);
  }, [bundleYaml, meta.name]);

  // Content for current view
  const currentContent = useMemo(() => {
    if (view === 'bundle') return bundleYaml;
    if (view === 'workflow') return workflowYaml;
    return agentConfigs[view] ?? 'Loading...';
  }, [view, bundleYaml, workflowYaml, agentConfigs]);

  // File path for current view
  const currentPath = useMemo(() => {
    const wfName = meta.name || 'workflow';
    if (view === 'bundle') return `All files (${1 + agentNames.length} files)`;
    if (view === 'workflow') return `configs/workflows/${wfName}.yaml`;
    return `configs/agents/${view}.yaml`;
  }, [view, meta.name, agentNames.length]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex">
      {/* Backdrop */}
      <div className="flex-1" onClick={onClose} />

      {/* Panel */}
      <div className="w-[650px] h-full bg-temper-bg border-l border-temper-border shadow-2xl flex flex-col">
        {/* Header */}
        <div className="flex items-center gap-3 px-4 py-3 border-b border-temper-border shrink-0">
          <h2 className="text-sm font-semibold text-temper-text flex-1">YAML Preview</h2>
          <button
            onClick={handleDownload}
            className="text-xs px-2.5 py-1 rounded bg-temper-accent/10 text-temper-accent hover:bg-temper-accent/20 transition-colors font-medium"
          >
            Download Bundle
          </button>
          <button
            onClick={onClose}
            className="w-6 h-6 flex items-center justify-center rounded text-temper-text-dim hover:text-temper-text hover:bg-temper-surface transition-colors"
          >
            &times;
          </button>
        </div>

        {/* Tab bar */}
        <div className="flex items-center gap-1 px-4 py-2 border-b border-temper-border/50 overflow-x-auto shrink-0">
          <TabButton active={view === 'bundle'} onClick={() => setView('bundle')} label="All Files" />
          <span className="text-temper-border mx-1">|</span>
          <TabButton active={view === 'workflow'} onClick={() => setView('workflow')} label="workflow" />
          {agentNames.map((name) => (
            <TabButton key={name} active={view === name} onClick={() => setView(name)} label={name} />
          ))}
        </div>

        {/* File path indicator */}
        <div className="px-4 py-1.5 bg-temper-surface/30 border-b border-temper-border/30 shrink-0 flex items-center gap-2">
          <span className="text-[10px] font-mono text-temper-text-dim">{currentPath}</span>
          <div className="ml-auto">
            <CopyButton text={currentContent} />
          </div>
        </div>

        {/* YAML content */}
        <div className="flex-1 overflow-auto">
          <pre className="p-4 text-[11px] font-mono text-temper-text leading-relaxed whitespace-pre-wrap">
            {currentContent}
          </pre>
        </div>
      </div>
    </div>
  );
}

// ── Annotation helpers ──────────────────────────────────────────

/** Inline comments for workflow YAML fields */
const WF_COMMENTS: Record<string, string> = {
  'workflow:': '',
  '  name:': '# Workflow identifier — used in API calls and file paths',
  '  defaults:': '# Default LLM settings — inherited by all agents unless overridden',
  '    provider:': '# LLM provider: vllm, openai, anthropic, gemini, ollama',
  '    model:': '# Model name — must match what the provider serves',
  '  nodes:': '# Execution graph — stages run in topological order based on depends_on',
  '      type: agent': '# Single-agent stage — one agent handles this step',
  '      type: stage': '# Multi-agent stage — multiple agents collaborate',
  '      agent:': '# Agent config to use (from configs/agents/)',
  '      depends_on:': '# Run after these stages complete (creates execution order)',
  '      strategy:': '# How agents collaborate: parallel, sequential, leader',
  '      condition:': '# Only run if this condition is true (skip otherwise)',
  '        source:': '# What to check: stage_name.structured.field or stage_name.output',
  '        operator:': '# Comparison: equals, not_equals, contains, in, exists',
  '        value:': '# Expected value to compare against',
  '      input_map:': '# Wire specific data from upstream stages to this stage\'s input',
  '      outputs:': '# Declare named output fields (extracted from agent JSON response)',
  '  description:': '',
  '  error_handling:': '# What happens when a stage fails',
  '    on_stage_failure:': '# halt = stop workflow, continue = skip and proceed',
};

/** Inline comments for agent YAML fields */
const AGENT_COMMENTS: Record<string, string> = {
  'agent:': '',
  '  name:': '# Agent identifier — referenced by workflow nodes',
  '  type:': '# Agent type: llm (LLM-based), script (code execution)',
  '  system_prompt:': '# System message — defines the agent\'s persona and behavior',
  '  task_template:': '# User message template — use {{ var }} for Jinja2 variables',
  '  max_iterations:': '# Max tool-calling loop iterations (prevents runaway)',
  '  token_budget:': '# Max prompt tokens before truncation kicks in',
  '  tools:': '# Tools this agent can use (from registered tool classes)',
  '  provider:': '# Override the workflow default provider',
  '  model:': '# Override the workflow default model',
  '  temperature:': '# LLM sampling temperature (0 = deterministic, 1 = creative)',
  '  max_tokens:': '# Max response tokens',
  '  memory:': '# Memory configuration for cross-run recall',
  '    enabled:': '# Enable memory recall and storage',
  '    recall_limit:': '# Max memories to inject into prompt',
};

function annotateWorkflowYaml(yamlStr: string): string {
  return annotateYaml(yamlStr, WF_COMMENTS);
}

function annotateAgentYaml(yamlStr: string): string {
  return annotateYaml(yamlStr, AGENT_COMMENTS);
}

function annotateYaml(yamlStr: string, comments: Record<string, string>): string {
  const lines = yamlStr.split('\n');
  const result: string[] = [];
  for (const line of lines) {
    // Check if this line matches a comment pattern
    const trimmed = line.trimEnd();
    let matched = false;
    for (const [pattern, comment] of Object.entries(comments)) {
      if (trimmed.startsWith(pattern) && comment) {
        // Add comment on the line above
        const indent = line.match(/^(\s*)/)?.[1] ?? '';
        result.push(`${indent}${comment}`);
        matched = true;
        break;
      }
    }
    // For input_map entries that look like "key: source.reference"
    if (!matched && /^\s+\w+:\s+\w+\.\w+/.test(trimmed) && !trimmed.includes('#')) {
      const parts = trimmed.split(':');
      if (parts.length === 2) {
        const source = parts[1].trim();
        if (source.includes('.structured.')) {
          result.push(line + `  # ← structured field from upstream JSON output`);
          continue;
        } else if (source.includes('.output')) {
          result.push(line + `  # ← full text output from upstream stage`);
          continue;
        }
      }
    }
    result.push(line);
  }
  return result.join('\n');
}

function TabButton({ active, onClick, label }: { active: boolean; onClick: () => void; label: string }) {
  return (
    <button
      onClick={onClick}
      className={`text-xs px-2 py-1 rounded shrink-0 transition-colors ${
        active
          ? 'bg-temper-accent/15 text-temper-accent font-medium'
          : 'text-temper-text-muted hover:text-temper-text hover:bg-temper-surface/50'
      }`}
    >
      {label}
    </button>
  );
}
