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
