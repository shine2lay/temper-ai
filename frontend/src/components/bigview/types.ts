/**
 * The shape of one thing on the run page.
 *
 * Everything the big view can open — the run, a stage, an agent, a script
 * agent, a model call, a tool call — is described by one `ViewShape`. The
 * frame (top strip, in-arrow, box, out-arrow, timeline) is written once
 * against this type; `shape.ts` is the only place that knows what each kind
 * puts in it.
 *
 * Nothing here is a rendered string: a `ContentValue` carries the raw value
 * and the renderer decides how to show it, so opening a 126-agent run never
 * stringifies anything the reader has not asked to see.
 */
import type { ExecutionStatus, LLMCall, ToolCall } from '@/types';

export type BigViewKind =
  | 'workflow'
  | 'stage'
  | 'agent'
  | 'scriptAgent'
  | 'llmCall'
  | 'toolCall';

/** One fact on the top strip. Short enough to sit on a single line. */
export interface Fact {
  label: string;
  value: string;
  /** `status` renders a StatusBadge; the rest are plain tones. */
  tone?: 'status' | 'accent' | 'muted' | 'warn' | 'danger' | 'money';
  title?: string;
}

/**
 * A ready-made piece of the page that is not text: the run's cost bars, an
 * agent's tool chips, a stage's collaboration events. Naming it rather than
 * holding a React node keeps the shape plain data, so a test can assert on
 * it and `shape.ts` stays free of JSX.
 */
export type WidgetName =
  | 'cost-breakdown'
  | 'tool-names'
  | 'declared-io'
  | 'collaboration'
  | 'links';

/** A piece of content, still in its native form. */
export type ContentValue =
  | { kind: 'auto'; text: string }
  | { kind: 'markdown'; text: string }
  | { kind: 'code'; text: string }
  | { kind: 'json'; data: unknown }
  | { kind: 'messages'; messages: unknown }
  | { kind: 'stream'; agentId: string }
  /** A script agent's saved log, read page by page (components/scriptlog/ScriptLogView.tsx). */
  | { kind: 'scriptLog'; attemptId: string }
  | { kind: 'thinking'; text: string }
  | { kind: 'widget'; name: WidgetName; data?: unknown }
  | { kind: 'empty'; note: string }
  | { kind: 'group'; parts: { label?: string; value: ContentValue }[] };

/** One fold inside the middle box. */
export interface CoreBlock {
  key: string;
  title: string;
  value: ContentValue;
  defaultOpen?: boolean;
  /** Small chip next to the title, e.g. "4 tools". */
  badge?: string;
}

/** One row of the merged model/tool stream. */
export interface TimelineRow {
  id: string;
  type: 'llm' | 'tool';
  /** Epoch ms, for ordering. Rows with no time keep their arrival order. */
  at: number;
  title: string;
  status: ExecutionStatus;
  /** Short facts shown on the closed row. */
  chips: string[];
  thinking: boolean;
  /** For tool rows, so the row can show where the call went. */
  origin?: Pick<ToolCall, 'transport' | 'server' | 'executed_by'>;
  /** The call itself. Its panes are derived only when the row opens. */
  source: LLMCall | ToolCall;
  error?: string;
}

/** A link out of this thing: its parent, a sibling run, a child. */
export interface ShapeLink {
  id: string;
  label: string;
  status?: ExecutionStatus;
  meta?: string;
  active?: boolean;
  open: () => void;
}

export interface ViewShape {
  kind: BigViewKind;
  /** Stable id of the thing shown, so folds reset when it changes. */
  id: string;
  title: string;
  status: ExecutionStatus;
  /** What this kind is called, for the frame's label. */
  kindLabel: string;
  facts: Fact[];
  /** A way back up: the stage an agent belongs to, the agent a call came from. */
  parent?: ShapeLink;
  /** Other runs of the same thing — an agent's rounds, a stage's iterations. */
  siblings: ShapeLink[];
  /** What sits inside: a stage's agents, the run's stages. */
  children: { label: string; items: ShapeLink[] };
  /** The folds in the middle box. */
  core: CoreBlock[];
  in: { label: string; value: ContentValue };
  out: { label: string; value: ContentValue };
  /**
   * The stream of model and tool calls under this thing, in the order they
   * happened. Left out by a kind that cannot have one (a single model call,
   * a single tool call): the section is then not drawn at all, rather than
   * standing empty on a full screen.
   */
  timeline?: TimelineRow[];
  error?: string;
  /** Shown under the top strip when the page only has a summary. */
  note?: string;
}

export function isEmptyContent(value: ContentValue): boolean {
  switch (value.kind) {
    case 'empty':
      return true;
    case 'json':
      if (value.data == null) return true;
      if (typeof value.data === 'object') return Object.keys(value.data as object).length === 0;
      return false;
    case 'group':
      return value.parts.every((p) => isEmptyContent(p.value));
    case 'messages':
      return value.messages == null || (Array.isArray(value.messages) && value.messages.length === 0);
    case 'widget':
      return Array.isArray(value.data) && value.data.length === 0;
    case 'stream':
    case 'scriptLog':
      return false;
    default:
      return !value.text;
  }
}
