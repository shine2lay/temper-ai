/**
 * Class names the Team page shares, from Design's boards (team.css), on the
 * app's own tokens. The global :focus-visible rule gives every control the
 * 2 px accent ring with a 2 px offset.
 */

const BTN = 'inline-flex items-center justify-center gap-2 rounded-md border font-semibold whitespace-nowrap no-underline transition-colors cursor-pointer disabled:cursor-not-allowed disabled:opacity-55';

export const teamBtn = {
  primary: `${BTN} min-h-8 px-3 text-sm bg-temper-accent text-temper-on-accent border-transparent hover:bg-temper-accent-dim`,
  secondary: `${BTN} min-h-8 px-3 text-sm bg-temper-surface text-temper-text border-temper-control hover:bg-temper-accent/10`,
  ghostXs: `${BTN} min-h-7 px-2.5 text-xs bg-transparent text-temper-text border-transparent hover:bg-temper-surface`,
  secondaryXs: `${BTN} min-h-7 px-2.5 text-xs bg-temper-surface text-temper-text border-temper-control hover:bg-temper-accent/10`,
} as const;

/** A card: panel colour, border, 8 px corners. */
export const teamCard = 'rounded-lg border border-temper-border bg-temper-panel';

/** A card's small heading (an h2): 12 px, upper case, muted. */
export const teamLabel = 'm-0 mb-2 text-xs font-semibold uppercase tracking-[0.06em] text-temper-text-muted';

/** A chip: small, bordered, 6 px corners. */
export const teamChip = 'inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-xs leading-[18px] whitespace-nowrap';

export const teamChipTone = {
  neutral: 'border-temper-control text-temper-text bg-transparent',
  running: 'bg-[var(--badge-running-bg)] text-[var(--badge-running-text)] border-[var(--badge-running-border)]',
  done: 'bg-[var(--badge-completed-bg)] text-[var(--badge-completed-text)] border-[var(--badge-completed-border)]',
  waiting: 'bg-[var(--badge-waiting-bg)] text-[var(--badge-waiting-text)] border-[var(--badge-waiting-border)]',
  failed: 'bg-[var(--badge-failed-bg)] text-[var(--badge-failed-text)] border-[var(--badge-failed-border)]',
} as const;

/** An underlined text link with at least a 24 px target. */
export const teamLink = 'inline-flex min-h-6 items-center gap-1 text-temper-text underline underline-offset-2 decoration-temper-control hover:decoration-temper-text';
