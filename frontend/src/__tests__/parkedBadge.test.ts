/**
 * "waiting for allowance, back around 14:20".
 *
 * The time is the whole badge. Without it the words read like another way of
 * saying stuck, which is exactly what a parked run must not look like -- so
 * the one piece with any logic in it is worth pinning down: the server's
 * timestamps, and what a bad one does.
 */
import { describe, it, expect } from 'vitest';
import { formatClock } from '@/lib/utils';

describe('formatClock', () => {
  it('reads a UTC moment as a clock time', () => {
    // Rendered in the reader's own zone -- the clock on the wall next to the
    // screen -- so the test asks what that zone makes of it rather than
    // hard-coding an offset it would only pass in one country.
    const iso = '2026-09-26T14:20:00Z';
    const expected = new Date(iso).toLocaleTimeString([], {
      hour: '2-digit', minute: '2-digit', hour12: false,
    });

    expect(formatClock(iso)).toBe(expected);
  });

  it('treats a timestamp without a zone as UTC, as the server means it', () => {
    // The API hands back naive ISO strings. Read as local, a 14:20 park shows
    // as 14:20 in Tokyo and 14:20 in Berlin -- both wrong for someone.
    expect(formatClock('2026-09-26T14:20:00')).toBe(formatClock('2026-09-26T14:20:00Z'));
  });

  it('says nothing when there is no time to say', () => {
    // The badge falls back to "waiting for allowance" on its own.
    expect(formatClock(null)).toBe('');
    expect(formatClock(undefined)).toBe('');
    expect(formatClock('')).toBe('');
  });

  it('says nothing rather than "Invalid Date"', () => {
    expect(formatClock('soon')).toBe('');
  });

  it('pads the hour, so times line up down a list', () => {
    expect(formatClock('2026-09-26T04:05:00Z')).toMatch(/^\d{2}:\d{2}$/);
  });
});
