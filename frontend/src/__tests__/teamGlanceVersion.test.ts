/**
 * Design's D88-D99 and D111-D113 word helpers (Frontend task #27): Now's two
 * version lines from Temper's work.latest (D97), a share note cut to the room
 * left (D111), "No one is working until you answer." (D112) and the busy rows
 * a phone lists (D111, D113). Pure functions only: nothing renders.
 */
import { describe, expect, it } from 'vitest';

import {
  cutNote,
  nobodyWorksUntilYouAnswer,
  versionLines,
  workingNow,
  type GlanceRun,
  type GlanceShare,
} from '@/lib/teamGlance';

const NOW = Date.parse('2026-10-10T12:00:00Z');

function share(over: Partial<GlanceShare> = {}): GlanceShare {
  return {
    versionNo: 6,
    commitShort: 'a1b2c3d',
    by: 'Backend',
    at: '2026-10-10T11:56:00Z',
    note: 'Export button and CSV writer; tests pass.',
    filesChanged: 3,
    filesTotal: 12,
    ...over,
  };
}

describe('Now: the latest version in two lines (D97)', () => {
  it('names the version, who shared it and when, then the note on its own', () => {
    expect(versionLines(share(), NOW)).toEqual({
      versionNo: 6,
      by: 'Backend',
      ago: '4 min ago',
      note: 'Export button and CSV writer; tests pass.',
      files: null,
    });
  });

  it('a note keeps one line: its line breaks become spaces; a blank note is none', () => {
    expect(versionLines(share({ note: '  First line\n\nsecond   line ' }), NOW)?.note).toBe('First line second line');
    expect(versionLines(share({ note: ' \n ' }), NOW)).toMatchObject({ note: null, files: '3 files changed' });
  });

  it('with no note it counts the files changed, as Temper counted them', () => {
    expect(versionLines(share({ note: null }), NOW)).toMatchObject({ note: null, files: '3 files changed' });
    expect(versionLines(share({ note: null, filesChanged: 1 }), NOW)?.files).toBe('1 file changed');
    // No count from Temper: nothing made up.
    expect(versionLines(share({ note: null, filesChanged: null }), NOW)).toMatchObject({ note: null, files: null });
  });

  it('says nothing about a time it does not know; nothing at all before a share', () => {
    expect(versionLines(share({ at: null }), NOW)?.ago).toBeNull();
    expect(versionLines(share(), null)?.ago).toBeNull();
    expect(versionLines(share({ by: null }), NOW)?.by).toBeNull();
    expect(versionLines(null, NOW)).toBeNull();
  });
});

describe('a share note cut to the room left (D97, D111)', () => {
  const note = 'Export button and CSV writer, tests pass';

  it('keeps the whole note in quotes when it fits', () => {
    expect(cutNote(note, note.length)).toBe('\u201cExport button and CSV writer, tests pass\u201d');
    expect(cutNote(note, 999)).toBe('\u201cExport button and CSV writer, tests pass\u201d');
  });

  it('never splits an emoji, combining accent, skin-tone or ZWJ sequence (item 14)', () => {
    expect(cutNote('CSV 😀 ready', 5)).toBe('“CSV…”');
    expect(cutNote('CSV 😀 ready', 6)).toBe('“CSV 😀…”');
    expect(cutNote('Cafe\u0301 ready', 4)).toBe('“Caf…”');
    expect(cutNote('Cafe\u0301 ready', 5)).toBe('“Cafe\u0301…”');
    const emoji = '👩🏽‍💻';
    for (let keep = 4; keep < 4 + emoji.length; keep++) expect(cutNote(`CSV ${emoji} ready`, keep)).toBe('“CSV…”');
    expect(cutNote(`CSV ${emoji} ready`, 4 + emoji.length)).toBe(`“CSV ${emoji}…”`);
  });

  it('cuts with an ellipsis inside the closing quote, never after a space or a comma', () => {
    expect(cutNote(note, 10)).toBe('\u201cExport but\u2026\u201d');
    // "Export button and CSV writer," -> the comma goes, the quote closes.
    expect(cutNote(note, 29)).toBe('\u201cExport button and CSV writer\u2026\u201d');
    expect(cutNote(note, 7)).toBe('\u201cExport\u2026\u201d');
    expect(cutNote(note, 0)).toBe('\u201c\u2026\u201d');
  });
});

/** Just what the two helpers read. */
function band(phase: Partial<GlanceRun['phase']>, counts: Partial<GlanceRun['counts']>): GlanceRun {
  return {
    phase: { name: 'waiting_for_owner', asked: false, running: 0, ...phase },
    counts: { working: 0, workingSupplied: true, ...counts },
  } as unknown as GlanceRun;
}

describe('"No one is working until you answer." (D112)', () => {
  it('only while the owner is asked and Temper counts no one working', () => {
    for (const name of ['waiting_for_owner', 'quiet', 'settings'] as const) {
      expect(nobodyWorksUntilYouAnswer(band({ name }, {})), name).toBe(true);
    }
    for (const name of ['check_in', 'limit'] as const) {
      expect(nobodyWorksUntilYouAnswer(band({ name, asked: true }, {})), name).toBe(true);
      // Not asked yet: the team waits on Temper, not on the owner.
      expect(nobodyWorksUntilYouAnswer(band({ name, asked: false }, {})), name).toBe(false);
    }
  });

  it('a member still working, a turn still running or a count Temper did not send keeps the phase sentence', () => {
    expect(nobodyWorksUntilYouAnswer(band({}, { working: 1 }))).toBe(false);
    expect(nobodyWorksUntilYouAnswer(band({ running: 1 }, {}))).toBe(false);
    expect(nobodyWorksUntilYouAnswer(band({}, { workingSupplied: false }))).toBe(false);
    for (const name of ['working', 'draining', 'closing', 'done', 'stopped'] as const) {
      expect(nobodyWorksUntilYouAnswer(band({ name }, {})), name).toBe(false);
    }
  });
});

describe('the busy rows Now lists (D84, D111, D113)', () => {
  const members = ['lead', 'builder', 'checker', 'writer'].map((name, i) => ({
    name,
    state: 'working',
    since: `2026-10-10T11:5${i}:00Z`,
    retryOf: null,
    on: { kind: 'work_request', text: `${name} part`, to: null },
  }));
  const run = { members, phase: { name: 'working', asked: false, running: 4 } } as unknown as GlanceRun;

  it('a phone lists one row and counts the rest; none leaves the count to the count line', () => {
    expect(workingNow(run, 1)).toMatchObject({ more: 3 });
    expect(workingNow(run, 1).rows).toHaveLength(1);
    // D113: with no row (the stale note shows), "and N more working" has nothing to sit under; StatusBand shows none.
    expect(workingNow(run, 0)).toMatchObject({ rows: [], more: 4 });
    expect(workingNow(run, 3).rows).toHaveLength(3);
  });
});
