/**
 * Floating canvas overlay card for workflow settings.
 * Compact view shows 4 key settings; expanded view shows all settings with inline editing.
 * Expanded view organized into important (always-visible) and advanced (collapsible) sections.
 */
import { useState, useCallback } from 'react';
import { useDesignStore, defaultMeta, type WorkflowMeta } from '@/store/designStore';
import type { DesignState } from '@/store/designTypes';
import { InlineEdit, InlineSelect, InlineToggle } from './InlineEdit';
import {
  SectionHeader,
  CollapsibleSection,
  ExpandedField,
  CompactArrayEditor,
  CompactOutputsEditor,
} from './shared';

const failureOptions = [
  { value: 'halt', label: 'halt' },
  { value: 'continue', label: 'continue' },
  { value: 'skip', label: 'skip' },
  { value: 'retry', label: 'retry' },
];

const safetyOptions = [
  { value: 'execute', label: 'execute' },
  { value: 'monitor', label: 'monitor' },
  { value: 'audit', label: 'audit' },
];

const budgetActionOptions = [
  { value: 'halt', label: 'halt' },
  { value: 'continue', label: 'continue' },
  { value: 'notify', label: 'notify' },
];

const consoleModeOptions = [
  { value: 'minimal', label: 'minimal' },
  { value: 'standard', label: 'standard' },
  { value: 'verbose', label: 'verbose' },
];

const productTypeOptions = [
  { value: '', label: 'none' },
  { value: 'web_app', label: 'web_app' },
  { value: 'mobile_app', label: 'mobile_app' },
  { value: 'api', label: 'api' },
  { value: 'data_product', label: 'data_product' },
  { value: 'data_pipeline', label: 'data_pipeline' },
  { value: 'cli_tool', label: 'cli_tool' },
];

/* ---------- Non-default detection ---------- */

/** Single source of truth — derived from the store's defaultMeta(). */
const DEFAULTS = defaultMeta() as unknown as Record<string, unknown>;

function isNonDefault(meta: WorkflowMeta, key: string): boolean {
  if (!(key in DEFAULTS)) return false;
  const val = meta[key as keyof WorkflowMeta];
  const def = DEFAULTS[key];
  return val !== def;
}

function accentIf(meta: WorkflowMeta, key: string): string {
  return isNonDefault(meta, key) ? 'text-temper-accent' : '';
}

/* ---------- Main component ---------- */

function EdgeToggle({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex items-center gap-1 cursor-pointer select-none" title={`Toggle ${label} edges`}>
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="w-3 h-3 rounded accent-temper-accent cursor-pointer"
      />
      <span className="text-[9px] text-temper-text-dim">{label}</span>
    </label>
  );
}

export function WorkflowSettingsOverlay() {
  const [mode, setMode] = useState<'minimized' | 'compact' | 'expanded'>('compact');
  const meta = useDesignStore((s) => s.meta);
  const setMeta = useDesignStore((s) => s.setMeta);
  const showDepEdges = useDesignStore((s) => s.showDepEdges);
  const showWireEdges = useDesignStore((s) => s.showWireEdges);
  const setShowDepEdges = useDesignStore((s) => s.setShowDepEdges);
  const setShowWireEdges = useDesignStore((s) => s.setShowWireEdges);
  const handlePointerDown = useCallback((e: React.PointerEvent) => {
    e.stopPropagation();
  }, []);

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    e.stopPropagation();
  }, []);

  const inputCount = meta.required_inputs.length + meta.optional_inputs.length;
  const outputCount = meta.outputs.length;

  // Minimized: just a gear icon
  if (mode === 'minimized') {
    return (
      <button
        onPointerDown={handlePointerDown}
        onMouseDown={handleMouseDown}
        onClick={() => setMode('compact')}
        className="w-8 h-8 rounded-lg border border-temper-border bg-temper-panel shadow-lg flex items-center justify-center text-temper-text-muted hover:text-temper-text hover:bg-temper-surface transition-colors"
        title="Open workflow settings"
      >
        <span className="text-sm">{'\u2699'}</span>
      </button>
    );
  }

  return (
    <div
      onPointerDown={handlePointerDown}
      onMouseDown={handleMouseDown}
      className={`${mode === 'expanded' ? 'w-[440px]' : 'w-[280px]'} rounded-lg border border-temper-border bg-temper-panel shadow-xl`}
    >
      {/* Header */}
      <div className="px-3 py-2 border-b border-temper-border/50 flex items-center gap-2">
        <span className="text-xs font-semibold text-temper-text flex-1">Workflow Settings</span>
        <EdgeToggle label="Flow" checked={showDepEdges} onChange={setShowDepEdges} />
        <EdgeToggle label="I/O" checked={showWireEdges} onChange={setShowWireEdges} />
        <button
          onClick={() => setMode(mode === 'expanded' ? 'compact' : 'expanded')}
          className="w-5 h-5 flex items-center justify-center rounded text-temper-text-muted hover:text-temper-text hover:bg-temper-surface transition-colors text-[10px]"
          title={mode === 'expanded' ? 'Collapse' : 'Expand'}
        >
          {mode === 'expanded' ? '\u25B2' : '\u25BC'}
        </button>
        <button
          onClick={() => setMode('minimized')}
          className="w-5 h-5 flex items-center justify-center rounded text-temper-text-muted hover:text-temper-text hover:bg-temper-surface transition-colors text-[10px]"
          title="Minimize"
        >
          &times;
        </button>
      </div>

      {mode === 'expanded' ? (
        <ExpandedView meta={meta} setMeta={setMeta} />
      ) : (
        <CompactView meta={meta} setMeta={setMeta} inputCount={inputCount} outputCount={outputCount} />
      )}
    </div>
  );
}

/* ---------- Compact View ---------- */

function CompactView({
  meta,
  setMeta,
  inputCount,
  outputCount,
}: {
  meta: WorkflowMeta;
  setMeta: (partial: Partial<WorkflowMeta>) => void;
  inputCount: number;
  outputCount: number;
}) {
  return (
    <>
      {/* Default LLM provider/model — most important settings */}
      <div className="px-3 py-2 grid grid-cols-2 gap-x-4 gap-y-1.5 border-b border-temper-border/30">
        <CompactField label="provider">
          <InlineEdit
            value={meta.default_provider}
            onChange={(v) => setMeta({ default_provider: String(v ?? '') })}
            emptyLabel="not set"
            placeholder="vllm"
            tooltip="Default LLM provider for all agents (e.g., vllm, openai, anthropic)"
            className={meta.default_provider ? 'text-temper-accent font-medium' : ''}
          />
        </CompactField>

        <CompactField label="model">
          <InlineEdit
            value={meta.default_model}
            onChange={(v) => setMeta({ default_model: String(v ?? '') })}
            emptyLabel="not set"
            placeholder="qwen3-next"
            tooltip="Default model for all agents (agents can override individually)"
            className={meta.default_model ? 'text-temper-accent font-medium' : ''}
          />
        </CompactField>
      </div>

      <div className="px-3 py-2 grid grid-cols-2 gap-x-4 gap-y-1.5">
        <CompactField label="timeout">
          <InlineEdit
            value={meta.timeout_seconds}
            onChange={(v) => setMeta({ timeout_seconds: Number(v) || 0 })}
            type="number"
            tooltip="Max workflow duration in seconds"
            className={accentIf(meta, 'timeout_seconds')}
            min={0}
          />
          <span className="text-[9px] text-temper-text-dim ml-0.5">s</span>
        </CompactField>

        <CompactField label="failure">
          <InlineSelect
            value={meta.on_stage_failure}
            options={failureOptions}
            onChange={(v) => setMeta({ on_stage_failure: v as WorkflowMeta['on_stage_failure'] })}
            tooltip="Behavior when a stage fails"
            className={accentIf(meta, 'on_stage_failure')}
          />
        </CompactField>

        <CompactField label="safety">
          <InlineSelect
            value={meta.global_safety_mode}
            options={safetyOptions}
            onChange={(v) => setMeta({ global_safety_mode: v as WorkflowMeta['global_safety_mode'] })}
            tooltip="Global safety mode"
            className={accentIf(meta, 'global_safety_mode')}
          />
        </CompactField>

        <CompactField label="cost">
          <InlineEdit
            value={meta.max_cost_usd}
            onChange={(v) => setMeta({ max_cost_usd: v != null && v !== '' ? Number(v) : null })}
            type="number"
            emptyLabel="--"
            tooltip="Max LLM cost in USD"
            className={accentIf(meta, 'max_cost_usd')}
            min={0}
            step={0.01}
          />
        </CompactField>
      </div>

      {/* Footer: I/O summary */}
      <div className="px-3 py-1.5 border-t border-temper-border/30 text-[10px] text-temper-text-dim">
        {inputCount} input{inputCount !== 1 ? 's' : ''} &middot; {outputCount} output{outputCount !== 1 ? 's' : ''}
      </div>
    </>
  );
}

function CompactField({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-1.5">
      <span className="text-[10px] text-temper-text-dim w-12 shrink-0">{label}</span>
      <div className="flex items-center gap-0">{children}</div>
    </div>
  );
}

/* ---------- Expanded View ---------- */

function ExpandedView({
  meta,
  setMeta,
}: {
  meta: WorkflowMeta;
  setMeta: (partial: Partial<WorkflowMeta>) => void;
}) {
  return (
    <div className="max-h-[60vh] overflow-y-auto">
      {/* General */}
      <div className="px-3 py-2 border-b border-temper-border/30">
        <SectionHeader title="General" tooltip={"Workflow identity.\n\nName: unique identifier used in CLI commands and cross-workflow references.\nDescription: human-readable summary shown in listings and DAG visualizations.\nVersion: semver string for tracking config changes across deploys.\nType: product classification (web_app, api, cli_tool, etc.) — used by lifecycle auto-classification and project scaffolding."} />
        <ExpandedField label="Name" tip="Unique identifier used in CLI commands (e.g. temper-ai run <name>) and cross-workflow references. Must be a valid YAML key.">
          <InlineEdit
            value={meta.name}
            onChange={(v) => setMeta({ name: String(v ?? '') })}
            placeholder="my_workflow"
            emptyLabel="untitled"
            className="w-full"
          />
        </ExpandedField>
        <ExpandedField label="Desc" tip="Human-readable summary displayed in workflow listings, DAG headers, and dashboard cards. Helps others understand what this workflow does at a glance.">
          <InlineEdit
            value={meta.description}
            onChange={(v) => setMeta({ description: String(v ?? '') })}
            type="textarea"
            placeholder="What does this workflow do?"
            emptyLabel="no description"
            className="w-full"
          />
        </ExpandedField>
        <ExpandedField label="Version" tip="Semver string (e.g. 1.0, 2.3) for tracking config changes. Shown in logs and used by lifecycle to compare across deploys.">
          <InlineEdit
            value={meta.version}
            onChange={(v) => setMeta({ version: String(v ?? '1.0') })}
            placeholder="1.0"
            className={accentIf(meta, 'version')}
          />
        </ExpandedField>
        <ExpandedField label="Type" tip="Classifies the project this workflow targets (web_app, api, cli_tool, etc.). Used by lifecycle auto-classification and scaffolding templates. Leave empty if not applicable.">
          <InlineSelect
            value={meta.product_type ?? ''}
            options={productTypeOptions}
            onChange={(v) => setMeta({ product_type: v || null })}
            tooltip="Product type classification"
            className={accentIf(meta, 'product_type')}
          />
        </ExpandedField>
      </div>

      {/* Execution & Budget */}
      <div className="px-3 py-2 border-b border-temper-border/30">
        <SectionHeader title="Execution &amp; Budget" tooltip={"Controls how the workflow runs and what it can spend.\n\nTimeout: hard wall-clock limit — the workflow is killed after this many seconds.\nMax iterations: cap on how many times the DAG scheduler can re-enter the stage graph (prevents infinite loops).\nCost / Token limits: when hit, the budget action fires (halt, continue, or notify).\nConvergence: stop early if stage outputs stabilize between iterations.\nTool cache: cache read-only tool results so identical calls skip re-execution.\nPredecessor injection: stages receive only their DAG parents' outputs instead of the full shared state."} />
        <ExpandedField label="Timeout" tip="Hard wall-clock limit in seconds. The entire workflow is killed after this duration, regardless of which stage is running. Set high for long-running pipelines (e.g. 14400 = 4 hours).">
          <InlineEdit
            value={meta.timeout_seconds}
            onChange={(v) => setMeta({ timeout_seconds: Number(v) || 0 })}
            type="number"
            tooltip="Max workflow duration in seconds"
            className={accentIf(meta, 'timeout_seconds')}
            min={0}
          />
          <span className="text-[9px] text-temper-text-dim ml-1">seconds</span>
        </ExpandedField>
        <ExpandedField label="Max iters" tip="Maximum times the DAG scheduler can cycle through the stage graph. Prevents infinite loops when stages have loop-back edges. Each pass through the full graph counts as one iteration.">
          <InlineEdit
            value={meta.max_iterations}
            onChange={(v) => setMeta({ max_iterations: Number(v) || 1 })}
            type="number"
            tooltip="Max stage iterations"
            className={accentIf(meta, 'max_iterations')}
            min={1}
          />
        </ExpandedField>
        <ExpandedField label="Cost limit" tip="Maximum LLM spend in USD across all stages. Tracks cumulative cost from all provider API calls. When reached, the 'on exceed' action fires. Leave empty for unlimited.">
          <InlineEdit
            value={meta.max_cost_usd}
            onChange={(v) => setMeta({ max_cost_usd: v != null && v !== '' ? Number(v) : null })}
            type="number"
            emptyLabel="no limit"
            tooltip="Max LLM cost in USD"
            className={accentIf(meta, 'max_cost_usd')}
            min={0}
            step={0.01}
          />
        </ExpandedField>
        <ExpandedField label="Token limit" tip="Maximum total tokens (input + output) across all LLM calls in the workflow. Useful for capping context-heavy workflows. Leave empty for unlimited.">
          <InlineEdit
            value={meta.max_tokens}
            onChange={(v) => setMeta({ max_tokens: v != null && v !== '' ? Number(v) : null })}
            type="number"
            emptyLabel="no limit"
            tooltip="Max total tokens"
            className={accentIf(meta, 'max_tokens')}
            min={0}
          />
        </ExpandedField>
        <ExpandedField label="On exceed" tip="What happens when cost or token limit is hit. Halt: stop the workflow immediately. Continue: log a warning and keep going. Notify: send an alert but continue execution.">
          <InlineSelect
            value={meta.budget_action_on_exceed}
            options={budgetActionOptions}
            onChange={(v) => setMeta({ budget_action_on_exceed: v as WorkflowMeta['budget_action_on_exceed'] })}
            tooltip="Action when budget exceeded"
            className={accentIf(meta, 'budget_action_on_exceed')}
          />
        </ExpandedField>
        <ExpandedField label="Convergence" tip="Stop early when stage outputs stabilize between iterations. The engine compares consecutive outputs and halts if the diff falls below a threshold. Saves cost on iterative workflows.">
          <InlineToggle
            value={meta.convergence_detection}
            onChange={(v) => setMeta({ convergence_detection: v })}
            tooltip="Enable convergence detection"
            className={accentIf(meta, 'convergence_detection')}
          />
        </ExpandedField>
        <ExpandedField label="Tool cache" tip="Cache results from read-only tools (e.g. file reads, web fetches) so identical calls within the same run skip re-execution. Reduces latency and cost for repetitive tool usage.">
          <InlineToggle
            value={meta.tool_cache_enabled}
            onChange={(v) => setMeta({ tool_cache_enabled: v })}
            tooltip="Cache read-only tool results"
            className={accentIf(meta, 'tool_cache_enabled')}
          />
        </ExpandedField>
        <ExpandedField label="Predecessor" tip="When on, each stage receives only its direct DAG parents' outputs instead of the full shared state. Reduces prompt size and prevents data leakage between unrelated branches.">
          <InlineToggle
            value={meta.predecessor_injection}
            onChange={(v) => setMeta({ predecessor_injection: v })}
            tooltip="Inject only DAG predecessor outputs"
            className={accentIf(meta, 'predecessor_injection')}
          />
        </ExpandedField>
      </div>

      {/* Error Handling */}
      <div className="px-3 py-2 border-b border-temper-border/30">
        <SectionHeader title="Error Handling" tooltip={"What happens when a stage fails.\n\nOn failure: halt stops the entire workflow, skip moves to the next stage, retry re-runs the failed stage, continue marks it failed but keeps going.\nMax retries: how many times a failed stage is retried before the failure policy takes over.\nEscalation: the policy module invoked when retries are exhausted (e.g. GracefulDegradation reduces scope instead of hard-failing).\nRollback: when enabled, the engine automatically reverts side-effects (tool actions, state changes) of the failed stage."} />
        <ExpandedField label="On failure" tip="What happens when a stage fails after exhausting retries. Halt: stop the entire workflow. Skip: mark the stage as failed and proceed to the next. Retry: re-run the stage. Continue: log the failure and keep going.">
          <InlineSelect
            value={meta.on_stage_failure}
            options={failureOptions}
            onChange={(v) => setMeta({ on_stage_failure: v as WorkflowMeta['on_stage_failure'] })}
            tooltip="Behavior when a stage fails"
            className={accentIf(meta, 'on_stage_failure')}
          />
        </ExpandedField>
        <ExpandedField label="Max retries" tip="How many times a failed stage is re-attempted before the failure policy kicks in. Set to 0 to never retry. Each retry re-runs the full stage including all its agents.">
          <InlineEdit
            value={meta.max_stage_retries}
            onChange={(v) => setMeta({ max_stage_retries: Number(v) || 0 })}
            type="number"
            tooltip="Max stage retry attempts"
            className={accentIf(meta, 'max_stage_retries')}
            min={0}
          />
        </ExpandedField>
        <ExpandedField label="Escalation" tip="Policy module invoked when retries are exhausted. GracefulDegradation reduces scope and continues. Other options include FullHalt and ManualReview. This is a Python module reference.">
          <InlineEdit
            value={meta.escalation_policy}
            onChange={(v) => setMeta({ escalation_policy: String(v ?? 'GracefulDegradation') })}
            tooltip="Escalation policy module"
            className={accentIf(meta, 'escalation_policy')}
          />
        </ExpandedField>
        <ExpandedField label="Rollback" tip="When enabled, a failed stage's side-effects (tool actions, file writes, state mutations) are automatically reverted. Disable if your stages have external side-effects that can't be undone.">
          <InlineToggle
            value={meta.enable_rollback}
            onChange={(v) => setMeta({ enable_rollback: v })}
            tooltip="Enable automatic rollback on failure"
            className={accentIf(meta, 'enable_rollback')}
          />
        </ExpandedField>
      </div>

      {/* Safety */}
      <div className="px-3 py-2 border-b border-temper-border/30">
        <SectionHeader title="Safety" tooltip={"Guards that control what agents are allowed to do.\n\nMode: execute runs actions for real, monitor logs but blocks side-effects, audit requires human approval before every action.\nComposition: when agents in a stage have different safety modes, this decides the effective mode (MostRestrictive picks the strictest).\nApproval stages: specific stages that always require human sign-off regardless of global mode.\nDry-run stages: stages that simulate execution without performing real actions — useful for testing pipelines safely."} />
        <ExpandedField label="Mode" tip="Global safety mode applied to all stages unless overridden. Execute: run actions for real. Monitor: log actions but block side-effects. Audit: require human approval before every tool action.">
          <InlineSelect
            value={meta.global_safety_mode}
            options={safetyOptions}
            onChange={(v) => setMeta({ global_safety_mode: v as WorkflowMeta['global_safety_mode'] })}
            tooltip="Global safety mode"
            className={accentIf(meta, 'global_safety_mode')}
          />
        </ExpandedField>
        <ExpandedField label="Composition" tip="When agents in a stage have different safety modes, this decides the effective mode. MostRestrictive picks the strictest agent's mode. Other strategies: LeastRestrictive, StageOverride.">
          <InlineEdit
            value={meta.safety_composition_strategy}
            onChange={(v) => setMeta({ safety_composition_strategy: String(v ?? 'MostRestrictive') })}
            tooltip="How agent safety modes compose"
            className={accentIf(meta, 'safety_composition_strategy')}
          />
        </ExpandedField>
        <ExpandedField label="Approval" tip="Stages listed here always require human sign-off before execution, regardless of the global safety mode. Add stage names to force manual review on sensitive steps.">
          <CompactArrayEditor
            values={meta.approval_required_stages}
            onChange={(v) => setMeta({ approval_required_stages: v })}
            placeholder="stage name"
          />
        </ExpandedField>
        <ExpandedField label="Dry-run" tip="Stages listed here simulate execution without performing real actions. Tool calls are logged but not executed. Useful for testing new pipeline stages safely before going live.">
          <CompactArrayEditor
            values={meta.dry_run_stages}
            onChange={(v) => setMeta({ dry_run_stages: v })}
            placeholder="stage name"
          />
        </ExpandedField>
      </div>

      {/* Inputs / Outputs */}
      <div className="px-3 py-2 border-b border-temper-border/30">
        <SectionHeader title="Inputs / Outputs" tooltip={"Data flowing in and out of the workflow.\n\nRequired inputs: variables that must be provided at runtime (e.g. workspace_path). The workflow refuses to start without them.\nOptional inputs: variables that enhance behavior but aren't mandatory — stages check for their presence at runtime.\nOutputs: named values extracted from stage results when the workflow completes. Each output maps a name to a source (stage_name.output_key)."} />
        <ExpandedField label="Required" tip="Variables that must be provided when running the workflow (via --input YAML or API). The workflow refuses to start if any are missing. Referenced in stage prompts as {{ variable_name }}.">
          <CompactArrayEditor
            values={meta.required_inputs}
            onChange={(v) => setMeta({ required_inputs: v })}
            placeholder="e.g., user_prompt"
          />
        </ExpandedField>
        <ExpandedField label="Optional" tip="Variables that enhance behavior but aren't required. Stages can check for their presence with Jinja conditionals ({% if variable_name %}). Useful for optional context or configuration.">
          <CompactArrayEditor
            values={meta.optional_inputs}
            onChange={(v) => setMeta({ optional_inputs: v })}
            placeholder="e.g., context"
          />
        </ExpandedField>
        <ExpandedField label="Outputs" tip="Named values extracted from stage results when the workflow completes. Each output maps a name to a source in the form stage_name.output_key. These are returned to the caller and shown in the dashboard.">
          <CompactOutputsEditor
            outputs={meta.outputs}
            onChange={(v) => setMeta({ outputs: v })}
          />
        </ExpandedField>
      </div>

      {/* --- Advanced sections (collapsed by default) --- */}

      <CollapsibleSection title="Rate Limiting" tooltip={"Throttle LLM API calls to stay within provider limits.\n\nEnabled: turn rate limiting on/off for this workflow.\nMax RPM: maximum requests per minute across all stages. Exceeding this either blocks or errors depending on the block setting.\nBlock on limit: when true, requests queue and wait instead of failing immediately.\nMax wait: how long a blocked request will wait (in seconds) before timing out with an error."}>
        <ExpandedField label="Enabled" tip="Turn rate limiting on for this workflow. When off, LLM calls fire as fast as the provider allows. Enable this to avoid 429 errors from providers with strict rate limits.">
          <InlineToggle
            value={meta.rate_limit_enabled}
            onChange={(v) => setMeta({ rate_limit_enabled: v })}
            tooltip="Enable rate limiting"
            className={accentIf(meta, 'rate_limit_enabled')}
          />
        </ExpandedField>
        <ExpandedField label="Max RPM" tip="Maximum LLM API requests per minute across all stages combined. Set this below your provider's rate limit to leave headroom. Parallel stages share this budget.">
          <InlineEdit
            value={meta.rate_limit_max_rpm}
            onChange={(v) => setMeta({ rate_limit_max_rpm: Number(v) || 1 })}
            type="number"
            tooltip="Max requests per minute"
            className={accentIf(meta, 'rate_limit_max_rpm')}
            min={1}
          />
        </ExpandedField>
        <ExpandedField label="Block" tip="When on, requests that exceed the rate limit queue and wait instead of failing immediately. When off, exceeding the limit raises an error that triggers the stage's error handling policy.">
          <InlineToggle
            value={meta.rate_limit_block_on_limit}
            onChange={(v) => setMeta({ rate_limit_block_on_limit: v })}
            tooltip="Block when rate limit hit"
            className={accentIf(meta, 'rate_limit_block_on_limit')}
          />
        </ExpandedField>
        <ExpandedField label="Max wait" tip="How long a blocked request waits (in seconds) before timing out with an error. Only applies when 'Block' is on. Set higher for bursty workloads.">
          <InlineEdit
            value={meta.rate_limit_max_wait_seconds}
            onChange={(v) => setMeta({ rate_limit_max_wait_seconds: Number(v) || 1 })}
            type="number"
            tooltip="Max wait time when blocked (seconds)"
            className={accentIf(meta, 'rate_limit_max_wait_seconds')}
            min={1}
          />
          <span className="text-[9px] text-temper-text-dim ml-1">s</span>
        </ExpandedField>
      </CollapsibleSection>

      <CollapsibleSection title="Planning Pass" tooltip={"Run an LLM planning step before the workflow executes.\n\nWhen enabled, a planner agent analyzes the workflow DAG and inputs, then generates a high-level execution plan that guides stage ordering and resource allocation.\nProvider/Model: which LLM to use for planning (can differ from stage agents).\nTemperature: controls randomness — lower values (0.1-0.3) produce more deterministic plans, higher values explore creative strategies.\nMax tokens: cap on the planning response length."}>
        <ExpandedField label="Enabled" tip="Run a planning step before the main workflow executes. The planner analyzes the DAG and inputs, then generates an execution strategy. The plan is injected into each stage's context. Use --plan flag in CLI.">
          <InlineToggle
            value={meta.planning_enabled}
            onChange={(v) => setMeta({ planning_enabled: v })}
            tooltip="Enable planning pass before execution"
            className={accentIf(meta, 'planning_enabled')}
          />
        </ExpandedField>
        <ExpandedField label="Provider" tip="LLM provider for the planning step. Can differ from your stage agents — e.g. use a cheaper model for planning (openai, anthropic, ollama, vllm, custom).">
          <InlineEdit
            value={meta.planning_provider}
            onChange={(v) => setMeta({ planning_provider: String(v ?? 'openai') })}
            tooltip="LLM provider for planning"
            className={accentIf(meta, 'planning_provider')}
          />
        </ExpandedField>
        <ExpandedField label="Model" tip="Specific model ID for the planner (e.g. gpt-4o-mini, claude-3-haiku, qwen3-next). Smaller models work well here since planning is a structured task.">
          <InlineEdit
            value={meta.planning_model}
            onChange={(v) => setMeta({ planning_model: String(v ?? 'gpt-4o-mini') })}
            tooltip="Model for planning"
            className={accentIf(meta, 'planning_model')}
          />
        </ExpandedField>
        <ExpandedField label="Temp" tip="Sampling temperature (0 to 2). Lower values (0.1-0.3) produce deterministic, focused plans. Higher values explore creative strategies. Default 0.3 is a good balance for planning.">
          <InlineEdit
            value={meta.planning_temperature}
            onChange={(v) => setMeta({ planning_temperature: Number(v) || 0 })}
            type="number"
            tooltip="Temperature (0-2)"
            className={accentIf(meta, 'planning_temperature')}
            min={0}
            max={2}
            step={0.1}
          />
        </ExpandedField>
        <ExpandedField label="Max tokens" tip="Maximum tokens the planning response can use. Plans are usually 500-2000 tokens. Set higher if your workflow has many stages or complex dependencies.">
          <InlineEdit
            value={meta.planning_max_tokens}
            onChange={(v) => setMeta({ planning_max_tokens: Number(v) || 1 })}
            type="number"
            tooltip="Max tokens for planning"
            className={accentIf(meta, 'planning_max_tokens')}
            min={1}
          />
        </ExpandedField>
      </CollapsibleSection>

      <CollapsibleSection title="Observability" tooltip={"Control what the workflow logs, traces, and exports.\n\nConsole mode: minimal shows only errors, standard shows stage transitions and summaries, verbose shows full agent prompts and responses.\nTrace all: emit detailed trace spans for every LLM call and tool invocation (useful for debugging, adds overhead).\nDAG visualization: generate an ASCII or Mermaid DAG diagram at the start of each run.\nWaterfall: show a timeline waterfall of stage durations in the console after completion.\nExport formats: where traces are persisted — json (files), sqlite (queryable DB), or both."}>
        <ExpandedField label="Console" tip="Controls console output verbosity. Minimal: only errors and final result. Standard: stage transitions, summaries, and timing. Verbose: full agent prompts, LLM responses, and tool call details.">
          <InlineSelect
            value={meta.observability_console_mode}
            options={consoleModeOptions}
            onChange={(v) => setMeta({ observability_console_mode: v as WorkflowMeta['observability_console_mode'] })}
            tooltip="Console output verbosity"
            className={accentIf(meta, 'observability_console_mode')}
          />
        </ExpandedField>
        <ExpandedField label="Trace all" tip="Emit detailed trace spans for every LLM call, tool invocation, and decision point. Essential for debugging but adds overhead and storage. Traces are exported in the formats below.">
          <InlineToggle
            value={meta.observability_trace_everything}
            onChange={(v) => setMeta({ observability_trace_everything: v })}
            tooltip="Trace all decisions"
            className={accentIf(meta, 'observability_trace_everything')}
          />
        </ExpandedField>
        <ExpandedField label="DAG viz" tip="Print an ASCII or Mermaid diagram of the stage DAG at the start of each run. Useful for confirming the pipeline structure before execution begins.">
          <InlineToggle
            value={meta.observability_dag_visualization}
            onChange={(v) => setMeta({ observability_dag_visualization: v })}
            tooltip="Generate DAG visualization"
            className={accentIf(meta, 'observability_dag_visualization')}
          />
        </ExpandedField>
        <ExpandedField label="Waterfall" tip="Show a timeline waterfall of stage durations in the console after the workflow completes. Makes it easy to spot bottleneck stages and understand parallel execution.">
          <InlineToggle
            value={meta.observability_waterfall}
            onChange={(v) => setMeta({ observability_waterfall: v })}
            tooltip="Show waterfall in console"
            className={accentIf(meta, 'observability_waterfall')}
          />
        </ExpandedField>
        <ExpandedField label="Export" tip="Formats for persisting traces and metrics. json: structured JSON files (human-readable). sqlite: queryable database (use with dashboard). Add both for maximum flexibility.">
          <CompactArrayEditor
            values={meta.observability_export_format}
            onChange={(v) => setMeta({ observability_export_format: v })}
            placeholder="json"
          />
        </ExpandedField>
      </CollapsibleSection>

      <CollapsibleSection title="Autonomous Loop" tooltip={"Makes the workflow self-improving across runs.\n\nEnabled: activate the autonomous feedback loop.\nLearning: mine patterns from past runs to improve future performance (e.g. which prompts work best).\nGoals: propose and track high-level improvement objectives based on run history.\nPortfolio: analyze component-level performance and suggest architectural changes.\nAuto-apply learning/goals: automatically apply recommendations without human review (use with caution).\nPrompt optimization: run DSPy-based prompt compilation to optimize agent prompts between runs.\nAgent memory sync: after each run, push learnings to persistent agents so they benefit across workflows."}>
        <ExpandedField label="Enabled" tip="Activate the autonomous feedback loop. When on, the workflow runs repeatedly with --autonomous, collecting metrics and applying improvements between iterations.">
          <InlineToggle
            value={meta.autonomous_enabled}
            onChange={(v) => setMeta({ autonomous_enabled: v })}
            tooltip="Enable autonomous loop"
            className={accentIf(meta, 'autonomous_enabled')}
          />
        </ExpandedField>
        <ExpandedField label="Learning" tip="Mine patterns from past runs — which prompts produce better output, which tool strategies are more reliable. Learnings are stored and surfaced as recommendations for future runs.">
          <InlineToggle
            value={meta.autonomous_learning}
            onChange={(v) => setMeta({ autonomous_learning: v })}
            tooltip="Enable learning subsystem"
            className={accentIf(meta, 'autonomous_learning')}
          />
        </ExpandedField>
        <ExpandedField label="Goals" tip="Propose and track high-level improvement objectives (e.g. 'reduce code stage latency by 20%'). Goals are derived from run metrics and reviewed via the dashboard or CLI.">
          <InlineToggle
            value={meta.autonomous_goals}
            onChange={(v) => setMeta({ autonomous_goals: v })}
            tooltip="Enable goals subsystem"
            className={accentIf(meta, 'autonomous_goals')}
          />
        </ExpandedField>
        <ExpandedField label="Portfolio" tip="Analyze component-level performance across stages and agents. Identifies weak links, suggests architectural changes, and tracks improvement over time via a knowledge graph.">
          <InlineToggle
            value={meta.autonomous_portfolio}
            onChange={(v) => setMeta({ autonomous_portfolio: v })}
            tooltip="Enable portfolio subsystem"
            className={accentIf(meta, 'autonomous_portfolio')}
          />
        </ExpandedField>
        <ExpandedField label="Auto learn" tip="Automatically apply learning recommendations (prompt tweaks, parameter adjustments) without human review. Only applies changes above a confidence threshold. Use with caution in production.">
          <InlineToggle
            value={meta.autonomous_auto_apply_learning}
            onChange={(v) => setMeta({ autonomous_auto_apply_learning: v })}
            tooltip="Auto-apply learning recommendations"
            className={accentIf(meta, 'autonomous_auto_apply_learning')}
          />
        </ExpandedField>
        <ExpandedField label="Auto goals" tip="Automatically apply goal-derived changes (e.g. switch to a faster model if latency goal is unmet) without human review. Same confidence threshold as auto-learn.">
          <InlineToggle
            value={meta.autonomous_auto_apply_goals}
            onChange={(v) => setMeta({ autonomous_auto_apply_goals: v })}
            tooltip="Auto-apply goal recommendations"
            className={accentIf(meta, 'autonomous_auto_apply_goals')}
          />
        </ExpandedField>
        <ExpandedField label="Prompt opt" tip="Run DSPy-based prompt compilation between autonomous iterations. Collects input/output examples from past runs and optimizes agent prompts using bootstrap or MIPRO strategies.">
          <InlineToggle
            value={meta.autonomous_prompt_optimization}
            onChange={(v) => setMeta({ autonomous_prompt_optimization: v })}
            tooltip="Enable prompt optimization"
            className={accentIf(meta, 'autonomous_prompt_optimization')}
          />
        </ExpandedField>
        <ExpandedField label="Agent sync" tip="After each run, push workflow learnings to persistent agents (registered via temper-ai agent register). Lets agents benefit from improvements discovered in any workflow they participate in.">
          <InlineToggle
            value={meta.autonomous_agent_memory_sync}
            onChange={(v) => setMeta({ autonomous_agent_memory_sync: v })}
            tooltip="Sync learnings to persistent agents"
            className={accentIf(meta, 'autonomous_agent_memory_sync')}
          />
        </ExpandedField>
      </CollapsibleSection>

      <CollapsibleSection title="Lifecycle" tooltip={"Adapt workflow behavior based on the project's maturity and type.\n\nEnabled: activate lifecycle-aware adaptations.\nProfile: a named set of rules that adjust timeouts, retry counts, and safety levels based on project characteristics (e.g. lean_small_projects uses shorter timeouts and fewer retries).\nAuto-classify: automatically detect project type from the codebase (language, framework, size) and select an appropriate profile. Disable to use the exact profile you specify."}>
        <ExpandedField label="Enabled" tip="Activate lifecycle-aware adaptations. When on, the engine adjusts timeouts, retry counts, and safety levels based on the project's type and maturity stage.">
          <InlineToggle
            value={meta.lifecycle_enabled}
            onChange={(v) => setMeta({ lifecycle_enabled: v })}
            tooltip="Enable lifecycle management"
            className={accentIf(meta, 'lifecycle_enabled')}
          />
        </ExpandedField>
        <ExpandedField label="Profile" tip="A named set of adaptation rules. Examples: lean_small_projects (shorter timeouts, fewer retries), enterprise (strict safety, longer timeouts). Leave empty to rely on auto-classification.">
          <InlineEdit
            value={meta.lifecycle_profile}
            onChange={(v) => setMeta({ lifecycle_profile: v != null && v !== '' ? String(v) : null })}
            emptyLabel="none"
            tooltip="Named lifecycle profile"
            className={accentIf(meta, 'lifecycle_profile')}
          />
        </ExpandedField>
        <ExpandedField label="Auto-classify" tip="Automatically detect project characteristics (language, framework, codebase size) and select an appropriate lifecycle profile. Turn off to use exactly the profile you specify above.">
          <InlineToggle
            value={meta.lifecycle_auto_classify}
            onChange={(v) => setMeta({ lifecycle_auto_classify: v })}
            tooltip="Auto-detect project characteristics"
            className={accentIf(meta, 'lifecycle_auto_classify')}
          />
        </ExpandedField>
      </CollapsibleSection>

      <CollapsibleSection title="Metadata" tooltip={"Organizational metadata for filtering and access control.\n\nTags: free-form labels for categorizing workflows in listings and dashboards (e.g. vcs, code-generation, production).\nOwner: the person or team responsible for this workflow — shown in dashboard listings and used by notification routing."}>
        <ExpandedField label="Tags" tip="Free-form labels for filtering and organizing workflows. Shown in dashboard listings, CLI list output, and used for search. Examples: vcs, production, code-generation, experimental.">
          <CompactArrayEditor
            values={meta.tags}
            onChange={(v) => setMeta({ tags: v })}
            placeholder="tag"
          />
        </ExpandedField>
        <ExpandedField label="Owner" tip="Person or team responsible for this workflow. Displayed in dashboard listings, used by notification routing, and shown in audit trails. Use email or team name.">
          <InlineEdit
            value={meta.owner}
            onChange={(v) => setMeta({ owner: v != null && v !== '' ? String(v) : null })}
            emptyLabel="none"
            tooltip="Workflow owner"
            className={accentIf(meta, 'owner')}
          />
        </ExpandedField>
      </CollapsibleSection>
    </div>
  );
}
