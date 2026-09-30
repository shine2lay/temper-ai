/**
 * The run page's find bar, wired to the graph.
 *
 * It holds what the bar needs — the matches, which one you are on, what stays
 * bright — and the three moves it offers: step to the next match, jump to the
 * trouble, and clear. The rules themselves are plain functions in
 * lib/runSearch.ts; this only joins them to the store, the canvas and the
 * keyboard.
 *
 * The word and the status filter live in the store, so the live panel narrows
 * with the graph instead of keeping its own idea of what you are looking for.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useReactFlow } from '@xyflow/react';
import type { Node } from '@xyflow/react';

import { useExecutionStore } from '@/store/executionStore';
import { useDebounce } from '@/hooks/useDebounce';
import {
  buildFindEntries,
  findMatches,
  litIds,
  matchPosition,
  stepMatch,
  troubleKind,
  troubleOrder,
  type FindEntry,
  type StatusFilter,
} from '@/lib/runSearch';

/** How long typing settles before the graph dims and the view moves. */
const TYPING_SETTLE_MS = 120;

export interface RunFind {
  query: string;
  setQuery: (query: string) => void;
  status: StatusFilter;
  setStatus: (status: StatusFilter) => void;
  /** Every node the word finds, in graph order. */
  matches: string[];
  /** Which match you are on, from 1; 0 when on none. */
  position: number;
  /** The node the view is on: the one wearing the ring. */
  focusedId: string | null;
  /** The ids to keep bright, or null when nothing narrows the view. */
  lit: Set<string> | null;
  /** True while a word or a filter is narrowing the run. */
  narrowed: boolean;
  /** What the trouble button would take you to. */
  trouble: 'failed' | 'running' | 'waiting' | 'none';
  step: (direction: 1 | -1) => void;
  jumpToTrouble: () => void;
  clear: () => void;
  /** The search box, so `/` can put the cursor in it. */
  inputRef: React.RefObject<HTMLInputElement | null>;
  entries: FindEntry[];
}

export function useRunFind(nodes: Node[]): RunFind {
  const query = useExecutionStore((s) => s.findQuery);
  const status = useExecutionStore((s) => s.findStatus);
  const setFindQuery = useExecutionStore((s) => s.setFindQuery);
  const setStatus = useExecutionStore((s) => s.setFindStatus);
  const { fitView } = useReactFlow();

  const [focusedId, setFocusedId] = useState<string | null>(null);
  const troubleAt = useRef<string | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  const entries = useMemo(() => buildFindEntries(nodes as unknown as Parameters<typeof buildFindEntries>[0]), [nodes]);

  // Typing settles first: on a run of eighty nodes every keystroke would
  // otherwise re-dim the canvas and drag the view along with it.
  const settled = useDebounce(query, TYPING_SETTLE_MS);
  const matches = useMemo(
    () => findMatches(entries, settled, status),
    [entries, settled, status],
  );
  const lit = useMemo(() => litIds(entries, settled, status), [entries, settled, status]);
  const trouble = useMemo(() => troubleKind(entries), [entries]);

  // A new word lands you on its first match; one that still matches keeps
  // you where you are, so a slower typist is not thrown about.
  useEffect(() => {
    if (!settled.trim()) return;
    setFocusedId((current) =>
      current && matches.includes(current) ? current : matches[0] ?? null,
    );
  }, [settled, matches]);

  // Whatever put the focus on a node — typing, `n`, the trouble button —
  // the view goes there.
  useEffect(() => {
    if (!focusedId) return;
    fitView({ nodes: [{ id: focusedId }], duration: 320, padding: 1.6, maxZoom: 1.1 });
  }, [focusedId, fitView]);

  const setQuery = useCallback(
    (next: string) => {
      setFindQuery(next);
      // Emptying the box is as good as clearing it: nothing is found, so
      // nothing wears the ring.
      if (!next.trim()) setFocusedId(null);
    },
    [setFindQuery],
  );

  const step = useCallback(
    (direction: 1 | -1) => {
      const next = stepMatch(matches, focusedId, direction);
      if (next) setFocusedId(next);
    },
    [matches, focusedId],
  );

  const jumpToTrouble = useCallback(() => {
    const order = troubleOrder(entries);
    if (order.length === 0) return;
    // Pressing again goes to the next one, and round again at the end.
    const next = stepMatch(order, troubleAt.current, 1);
    troubleAt.current = next;
    if (next) setFocusedId(next);
  }, [entries]);

  const clear = useCallback(() => {
    setFindQuery('');
    setStatus('all');
    setFocusedId(null);
    troubleAt.current = null;
    inputRef.current?.blur();
    // Back to the whole run, which is what "clear" means on a graph.
    fitView({ padding: 0.1, duration: 320 });
  }, [setFindQuery, setStatus, fitView]);

  return {
    query,
    setQuery,
    status,
    setStatus,
    matches,
    position: matchPosition(matches, focusedId),
    focusedId,
    lit,
    narrowed: settled.trim().length > 0 || status !== 'all',
    trouble,
    step,
    jumpToTrouble,
    clear,
    inputRef,
    entries,
  };
}
