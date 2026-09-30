/**
 * The find bar above the run graph.
 *
 * Type part of a name to light the nodes that match and dim the rest, step
 * through them with Enter or `n`, jump straight to whatever went wrong, or
 * narrow the run to what is running, failed, or waiting on a person.
 *
 * Nothing here decides anything: the rules are in lib/runSearch.ts and the
 * wiring is in hooks/useRunFind.ts.
 */
import type { RunFind } from '@/hooks/useRunFind';
import type { StatusFilter } from '@/lib/runSearch';

const STATUS_CHOICES: { key: StatusFilter; label: string; title: string }[] = [
  { key: 'all', label: 'All', title: 'Show the whole run' },
  { key: 'running', label: 'Running', title: 'Only what is running now' },
  { key: 'failed', label: 'Failed', title: 'Only what failed' },
  { key: 'waiting', label: 'Waiting', title: 'Only what is waiting on a person' },
];

const TROUBLE_TITLE: Record<RunFind['trouble'], string> = {
  failed: 'Go to the first thing that failed — press again for the next',
  running: 'Nothing failed — go to what is running now',
  waiting: 'Nothing failed — go to what is waiting on a person',
  none: 'Nothing failed and nothing is running',
};

export function RunFindBar({ find }: { find: RunFind }) {
  const searching = find.query.trim().length > 0;

  return (
    <div
      className="flex items-center gap-1.5"
      data-testid="run-find-bar"
      // Typing must not reach the graph's own key handling: Enter in the box
      // steps to the next match, it does not open a node. Only the box's own
      // keys are held back; a key pressed on a button here still reaches the
      // page, or Escape would do nothing while a filter button has focus.
      onKeyDown={(e) => {
        if (e.target === find.inputRef.current) e.stopPropagation();
      }}
    >
      <div className="flex items-center gap-1 px-1.5 py-0.5 rounded bg-temper-surface border border-temper-border focus-within:border-temper-accent">
        <span aria-hidden className="text-temper-text-dim text-[11px] leading-none">
          ⌕
        </span>
        <input
          ref={find.inputRef}
          type="search"
          value={find.query}
          onChange={(e) => find.setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault();
              find.step(e.shiftKey ? -1 : 1);
            } else if (e.key === 'Escape') {
              e.preventDefault();
              find.clear();
            }
          }}
          placeholder="Find a stage, agent or model…"
          aria-label="Find a stage, agent or model by name"
          data-testid="run-find-input"
          className="w-48 py-0.5 text-xs bg-transparent text-temper-text placeholder:text-temper-text-dim focus:outline-none"
        />
        {searching && (
          <span
            data-testid="run-find-count"
            className={`text-[10px] whitespace-nowrap tabular-nums ${
              find.matches.length === 0 ? 'text-temper-text-dim' : 'text-temper-text-muted'
            }`}
          >
            {find.matches.length === 0
              ? 'none'
              : `${find.position} of ${find.matches.length}`}
          </span>
        )}
      </div>

      <div className="flex items-center rounded border border-temper-border overflow-hidden">
        <button
          type="button"
          onClick={() => find.step(-1)}
          disabled={find.matches.length === 0}
          title="Previous match (shift+n)"
          aria-label="Previous match"
          data-testid="run-find-prev"
          className="px-1.5 py-1 text-[11px] leading-none text-temper-text-muted bg-temper-surface hover:text-temper-text hover:bg-temper-panel disabled:opacity-40 disabled:hover:text-temper-text-muted"
        >
          ‹
        </button>
        <button
          type="button"
          onClick={() => find.step(1)}
          disabled={find.matches.length === 0}
          title="Next match (n)"
          aria-label="Next match"
          data-testid="run-find-next"
          className="px-1.5 py-1 text-[11px] leading-none text-temper-text-muted bg-temper-surface border-l border-temper-border hover:text-temper-text hover:bg-temper-panel disabled:opacity-40 disabled:hover:text-temper-text-muted"
        >
          ›
        </button>
      </div>

      <button
        type="button"
        onClick={find.jumpToTrouble}
        disabled={find.trouble === 'none'}
        title={TROUBLE_TITLE[find.trouble]}
        aria-label="Go to the trouble"
        data-testid="run-find-trouble"
        data-trouble={find.trouble}
        className={`px-2 py-1 rounded border text-[10px] leading-none whitespace-nowrap transition-colors disabled:opacity-40 ${
          find.trouble === 'failed'
            ? 'border-[var(--color-temper-failed)]/60 text-[var(--color-temper-failed)] bg-[var(--color-temper-failed)]/10 hover:bg-[var(--color-temper-failed)]/20'
            : 'border-temper-border text-temper-text-muted bg-temper-surface hover:text-temper-text'
        }`}
      >
        {find.trouble === 'failed' ? '⚑ Trouble' : '⚑ Now'}
      </button>

      <div className="flex items-center rounded border border-temper-border overflow-hidden">
        {STATUS_CHOICES.map((choice) => (
          <button
            key={choice.key}
            type="button"
            onClick={() => find.setStatus(choice.key)}
            title={choice.title}
            aria-pressed={find.status === choice.key}
            data-testid={`run-find-status-${choice.key}`}
            className={`px-1.5 py-1 text-[10px] leading-none border-l first:border-l-0 border-temper-border transition-colors ${
              find.status === choice.key
                ? 'bg-temper-accent/20 text-temper-accent'
                : 'bg-temper-surface text-temper-text-muted hover:text-temper-text hover:bg-temper-panel'
            }`}
          >
            {choice.label}
          </button>
        ))}
      </div>
    </div>
  );
}
