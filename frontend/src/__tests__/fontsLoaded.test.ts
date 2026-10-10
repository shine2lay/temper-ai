/**
 * The page's ready point (Design D80) waits for the face of every character
 * the page draws: the two Source Sans Pro files, and the two small faces with
 * the four symbols Source Sans Pro lacks (index.css; Design rm-753d7aa4 (b)).
 * `fonts.load` fetches only the faces whose unicode-range holds a character
 * of its text, a single space by default, so the symbols are in that text.
 * (The browser check team-glance-words.spec.ts reads index.css's faces as the
 * browser parsed them, and the fonts each symbol is drawn with.)
 *
 * Happy path, as the owner's test rule asks (bp-be8d76b9): both weights are
 * asked for with that text before the page counts as measured; it measures,
 * reports 'loaded' once, measures again when more fonts land, and stops
 * listening when cleaned up.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';

import { onFontsLoaded, PAGE_FACES, PAGE_TEXT } from '@/lib/fontsLoaded';

afterEach(() => {
  Reflect.deleteProperty(document, 'fonts');
});

describe('onFontsLoaded', () => {
  it('asks for both weights with a space and the four symbols, measures, reports loaded, and measures again as fonts land', async () => {
    const listeners = new Map<string, () => void>();
    const fonts = {
      load: vi.fn<(face: string, text?: string) => Promise<FontFace[]>>(() => Promise.resolve([])),
      ready: Promise.resolve(),
      addEventListener: vi.fn((type: string, listener: () => void) => listeners.set(type, listener)),
      removeEventListener: vi.fn((type: string) => listeners.delete(type)),
    };
    Object.defineProperty(document, 'fonts', { value: fonts, configurable: true });
    const measure = vi.fn();
    const done = vi.fn();
    const stop = onFontsLoaded(measure, done);

    // The text: a space for the page's own files, and the right and down arrows, play and warning signs.
    expect(Array.from(PAGE_TEXT)).toEqual([' ', '\u2192', '\u2193', '\u25B6', '\u26A0']);
    // Both weights, each with that text, before the page counts as measured.
    expect(PAGE_FACES).toEqual(['400 16px "Source Sans Pro"', '600 16px "Source Sans Pro"']);
    expect(fonts.load.mock.calls).toEqual(PAGE_FACES.map((face) => [face, PAGE_TEXT]));
    expect(done).not.toHaveBeenCalled();
    await vi.waitFor(() => expect(done).toHaveBeenCalledWith('loaded'));
    expect(done).toHaveBeenCalledTimes(1);
    expect(measure).toHaveBeenCalled();
    expect(measure.mock.invocationCallOrder[0]).toBeLessThan(done.mock.invocationCallOrder[0]);

    // A later load measures again; after the clean-up nothing listens.
    const measured = measure.mock.calls.length;
    listeners.get('loadingdone')?.();
    expect(measure).toHaveBeenCalledTimes(measured + 1);
    stop();
    expect(fonts.removeEventListener).toHaveBeenCalledWith('loadingdone', expect.any(Function));
    expect(listeners.size).toBe(0);
    expect(done).toHaveBeenCalledTimes(1);
  });
});
