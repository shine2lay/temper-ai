/**
 * The glance page's tone colours, ring styles and answer names. Colour never
 * works alone: each state also has an icon and a word.
 */
import type { GlanceTone, RingStyle } from '@/lib/teamGlance';
import type { TeamAnswerOption } from '@/types/team';

/** Text colour of a tone (the StatusBadge colours, 4.5:1 on the panel in both themes). */
export const toneText: Record<GlanceTone, string> = {
  blue: 'text-[var(--badge-running-text)]',
  yellow: 'text-[var(--badge-waiting-text)]',
  grey: 'text-temper-text-muted',
  green: 'text-[var(--badge-completed-text)]',
  red: 'text-[var(--badge-failed-text)]',
};

/**
 * The page's type (SPEC 12: 28 / 26 / 22 / 20 / 18 / 17 / 16 / 15 / 14 px, nothing smaller than 14). These
 * replace the app's 12 px upper-case label on this page only; the other Team pages keep theirs.
 */
/** A card's head, an h2: "Team now", "Shared work", "Latest", "All activity", "Message a member" (SPEC 5: 20 px). */
export const glanceCardHead = 'm-0 text-xl font-semibold text-temper-text';
/** A band cell's label, Now / You / Spend (SPEC 4: 14 px muted; on a phone 1.2 line height, as the reference). */
export const glanceBandLabel = 'm-0 text-sm font-normal text-temper-text-muted max-md:leading-[1.2]';

/**
 * The page's frame, shared with the loading and error views so nothing moves when the first reply lands. Under
 * 768 px it takes the reference's phone spacing (D9, so the band ends on the first screen, D84): 14 px sides and gaps,
 * no rule under the header.
 */
export const glanceHeaderBox =
  'flex flex-col gap-1.5 border-temper-border px-[14px] pt-[14px] md:gap-2 md:border-b md:px-6 md:pt-4 md:pb-4';
export const glanceBodyBox = 'flex min-w-0 flex-col gap-[14px] px-[14px] pt-[14px] pb-8 md:gap-4 md:px-6 md:pt-4';
/** The header's two buttons (SPEC 3): 44 px tall; on a phone they share one row, 8 px sides (D9). */
export const glanceHeadButton = 'min-h-11 max-md:flex-[1_1_auto] max-md:px-2';

/** The ring around a member's initial (glance.css draws each style). */
export function ringAttr(ring: RingStyle): { 'data-ring': RingStyle } {
  return { 'data-ring': ring };
}

/** "A" for a member's ring: its first letter, upper case. */
export function initialOf(name: string): string {
  return (name.trim()[0] ?? '?').toUpperCase();
}

/** How the You cell names an answer on its button (what is sent is always Temper's word). */
export function glanceAnswerLabel(option: Pick<TeamAnswerOption, 'answer' | 'needs_text'>): string {
  const named: Record<string, string> = {
    continue: 'Continue',
    guide: 'Guide',
    stop: 'Stop',
    nudge: 'Nudge',
    'go on': 'Go on',
    reply: 'Reply',
  };
  const word = named[option.answer] ?? option.answer.charAt(0).toUpperCase() + option.answer.slice(1);
  return option.needs_text === 'required' && option.answer !== 'stop' ? `${word}\u2026` : word;
}
