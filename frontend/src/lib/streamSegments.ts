/**
 * Streamed agent output split into plain text, thinking and tool lines.
 *
 * Thinking reaches the page two ways. The Claude Code provider writes it
 * into the text as `<thinking>...</thinking>`; other models use
 * `<think>...</think>`. Providers with a thinking stream send it as chunks of
 * their own (chunk_type "thinking"), kept apart in StreamEntry.thinking with
 * marks saying where in the text each piece arrived.
 */
import type { StreamEntry } from '@/types';

export type StreamSegmentType = 'text' | 'thinking' | 'tool_call';

export interface StreamSegment {
  type: StreamSegmentType;
  content: string;
}

const THINK_TAGS: ReadonlyArray<readonly [string, string]> = [
  ['<thinking>', '</thinking>'],
  ['<think>', '</think>'],
];

const TOOL_LINE = '\n🔧';

/** Whether text holds a `<think>` or `<thinking>` block. */
export function hasThinkingTags(text: string): boolean {
  return text.includes('<think>') || text.includes('<thinking>');
}

/** Remove `<think>` and `<thinking>` blocks, keeping the rest of the text. */
export function stripThinkingTags(text: string): string {
  return text.replace(/<(think|thinking)>[\s\S]*?<\/\1>/g, '').trim();
}

function pushSegment(out: StreamSegment[], type: StreamSegmentType, content: string): void {
  if (!content) return;
  const last = out[out.length - 1];
  if (last && last.type === type && type !== 'tool_call') {
    last.content += content;
  } else {
    out.push({ type, content });
  }
}

/**
 * Split text at its thinking blocks (both tag styles) and, when asked, at
 * its 🔧 tool lines. A block still open at the end is thinking in progress.
 */
export function parseStreamText(text: string, opts: { toolLines?: boolean } = {}): StreamSegment[] {
  const out: StreamSegment[] = [];
  splitInto(out, text, !!opts.toolLines);
  return tidyAroundThinking(out);
}

function splitInto(out: StreamSegment[], text: string, toolLines: boolean): void {
  let i = 0;
  while (i < text.length) {
    let next = -1;
    let tag: readonly [string, string] | null = null;
    for (const pair of THINK_TAGS) {
      const at = text.indexOf(pair[0], i);
      if (at !== -1 && (next === -1 || at < next)) {
        next = at;
        tag = pair;
      }
    }
    const toolAt = toolLines ? text.indexOf(TOOL_LINE, i) : -1;
    if (toolAt !== -1 && (next === -1 || toolAt < next)) {
      pushSegment(out, 'text', text.slice(i, toolAt));
      const lineEnd = text.indexOf('\n', toolAt + 1);
      const line = lineEnd === -1 ? text.slice(toolAt) : text.slice(toolAt, lineEnd);
      out.push({ type: 'tool_call', content: line.trim() });
      i = lineEnd === -1 ? text.length : lineEnd;
      continue;
    }
    if (next === -1 || !tag) {
      pushSegment(out, 'text', text.slice(i));
      break;
    }
    pushSegment(out, 'text', text.slice(i, next));
    const start = next + tag[0].length;
    const end = text.indexOf(tag[1], start);
    if (end === -1) {
      pushSegment(out, 'thinking', text.slice(start));
      break;
    }
    pushSegment(out, 'thinking', text.slice(start, end));
    i = end + tag[1].length;
  }
}

/**
 * Drop the one line break on each side of a thinking block: the block is
 * drawn as a box of its own, and the break around `<thinking>` (which the
 * Claude Code provider always writes) left an empty line above and below it.
 */
function tidyAroundThinking(segments: StreamSegment[]): StreamSegment[] {
  for (let k = 0; k < segments.length; k++) {
    if (segments[k].type !== 'thinking') continue;
    const before = segments[k - 1];
    if (before?.type === 'text' && before.content.endsWith('\n')) {
      before.content = before.content.slice(0, -1);
    }
    const after = segments[k + 1];
    if (after?.type === 'text' && after.content.startsWith('\n')) {
      after.content = after.content.slice(1);
    }
  }
  return segments.filter((s) => s.content !== '');
}

/**
 * An agent's stream as the live strip shows it: its text with thinking and
 * tool lines split out, and the separately streamed thinking put back where
 * it arrived.
 */
export function buildStreamSegments(entry: Pick<StreamEntry, 'content' | 'thinking' | 'thinkingMarks'>): StreamSegment[] {
  // Thinking with no marks came before any text it led to.
  const marks = entry.thinkingMarks
    ?? (entry.thinking ? [{ at: 0, from: 0, to: entry.thinking.length }] : []);
  const out: StreamSegment[] = [];
  let at = 0;
  for (const mark of marks) {
    const upTo = Math.min(Math.max(mark.at, at), entry.content.length);
    splitInto(out, entry.content.slice(at, upTo), true);
    pushSegment(out, 'thinking', entry.thinking.slice(mark.from, mark.to));
    at = upTo;
  }
  splitInto(out, entry.content.slice(at), true);
  return tidyAroundThinking(out);
}

/**
 * The newest `maxLines` lines of a stream, cut across segments: a thinking
 * block the cut falls in keeps its newest lines and stays a thinking block.
 */
export function tailLines(segments: StreamSegment[], maxLines: number): StreamSegment[] {
  const out: StreamSegment[] = [];
  let budget = maxLines;
  for (let k = segments.length - 1; k >= 0 && budget > 0; k--) {
    const seg = segments[k];
    if (seg.type === 'tool_call') {
      out.unshift(seg);
      budget -= 1;
      continue;
    }
    let start = 0;
    let end = seg.content.length;
    // A segment ending in a line break has an empty last line: skip it
    // rather than spend a line of the budget on it.
    if (seg.content.endsWith('\n')) end -= 1;
    while (end > 0) {
      const nl = seg.content.lastIndexOf('\n', end - 1);
      if (nl < 0) break;
      budget -= 1;
      if (budget <= 0) {
        start = nl + 1;
        break;
      }
      end = nl;
    }
    const kept = seg.content.slice(start);
    if (kept.trim()) out.unshift({ type: seg.type, content: kept });
    if (start > 0) break;
    budget -= 1; // the segment's first line
  }
  return out;
}
