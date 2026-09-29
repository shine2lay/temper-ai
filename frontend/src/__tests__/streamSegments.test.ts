/**
 * Thinking in the live strip: both ways it reaches the page, in the order it
 * came, and cut to the newest lines without losing what is thinking.
 */
import { describe, it, expect } from 'vitest';
import {
  buildStreamSegments,
  hasThinkingTags,
  parseStreamText,
  stripThinkingTags,
  tailLines,
} from '@/lib/streamSegments';

const entry = (content: string, thinking = '', thinkingMarks?: { at: number; from: number; to: number }[]) => ({
  content,
  thinking,
  thinkingMarks,
});

describe('parseStreamText', () => {
  it('splits out <thinking> blocks the way the Claude Code provider writes them', () => {
    const text = 'Reading the spec.\n<thinking>The spec wants two pages.</thinking>\nWriting the first page.';
    expect(parseStreamText(text)).toEqual([
      { type: 'text', content: 'Reading the spec.' },
      { type: 'thinking', content: 'The spec wants two pages.' },
      { type: 'text', content: 'Writing the first page.' },
    ]);
  });

  it('still splits out <think> blocks', () => {
    expect(parseStreamText('<think>hmm</think>answer')).toEqual([
      { type: 'thinking', content: 'hmm' },
      { type: 'text', content: 'answer' },
    ]);
  });

  it('shows a block still being written as thinking', () => {
    expect(parseStreamText('ok\n<thinking>first I will')).toEqual([
      { type: 'text', content: 'ok' },
      { type: 'thinking', content: 'first I will' },
    ]);
  });

  it('splits tool lines only when asked', () => {
    const text = 'start\n🔧 read_file(a.py)\nnext';
    expect(parseStreamText(text)).toEqual([{ type: 'text', content: text }]);
    expect(parseStreamText(text, { toolLines: true })).toEqual([
      { type: 'text', content: 'start' },
      { type: 'tool_call', content: '🔧 read_file(a.py)' },
      { type: 'text', content: '\nnext' },
    ]);
  });

  it('knows both tag styles when checking and stripping', () => {
    expect(hasThinkingTags('a <thinking>b</thinking>')).toBe(true);
    expect(hasThinkingTags('a <think>b</think>')).toBe(true);
    expect(hasThinkingTags('plain')).toBe(false);
    expect(stripThinkingTags('<thinking>x</thinking>kept <think>y</think>too')).toBe('kept too');
  });
});

describe('buildStreamSegments', () => {
  it('puts streamed thinking (chunk_type thinking) where it arrived in the text', () => {
    // thinking "plan A", text "Doing A. ", thinking "then B", text "Done."
    const segs = buildStreamSegments(entry('Doing A. Done.', 'plan Athen B', [
      { at: 0, from: 0, to: 6 },
      { at: 9, from: 6, to: 12 },
    ]));
    expect(segs).toEqual([
      { type: 'thinking', content: 'plan A' },
      { type: 'text', content: 'Doing A. ' },
      { type: 'thinking', content: 'then B' },
      { type: 'text', content: 'Done.' },
    ]);
  });

  it('shows streamed thinking with no marks before the text', () => {
    expect(buildStreamSegments(entry('answer', 'reasoning'))).toEqual([
      { type: 'thinking', content: 'reasoning' },
      { type: 'text', content: 'answer' },
    ]);
  });

  it('shows thinking that has no text yet', () => {
    expect(buildStreamSegments(entry('', 'still thinking', [{ at: 0, from: 0, to: 14 }]))).toEqual([
      { type: 'thinking', content: 'still thinking' },
    ]);
  });

  it('shows both styles together', () => {
    const segs = buildStreamSegments(entry('x\n<thinking>tagged</thinking>\ny', 'streamed', [
      { at: 0, from: 0, to: 8 },
    ]));
    expect(segs.filter((s) => s.type === 'thinking').map((s) => s.content)).toEqual(['streamed', 'tagged']);
  });
});

describe('tailLines', () => {
  it('keeps the newest lines and keeps a thinking block that began further up as thinking', () => {
    const thinking = Array.from({ length: 10 }, (_, i) => `thought ${i + 1}`).join('\n');
    const segs = parseStreamText(`intro\n<thinking>${thinking}`);
    const tail = tailLines(segs, 3);
    expect(tail).toEqual([{ type: 'thinking', content: 'thought 8\nthought 9\nthought 10' }]);
  });

  it('keeps lines across segments, newest last', () => {
    const segs = parseStreamText('a\nb\n<thinking>c\nd</thinking>\ne\nf');
    expect(tailLines(segs, 4)).toEqual([
      { type: 'thinking', content: 'c\nd' },
      { type: 'text', content: 'e\nf' },
    ]);
    expect(tailLines(segs, 3)).toEqual([
      { type: 'thinking', content: 'd' },
      { type: 'text', content: 'e\nf' },
    ]);
  });

  it('returns everything when it fits', () => {
    const segs = parseStreamText('one\n<thinking>two</thinking>\nthree');
    expect(tailLines(segs, 6)).toEqual(segs);
  });
});
