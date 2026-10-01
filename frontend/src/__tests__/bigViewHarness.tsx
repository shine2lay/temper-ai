/**
 * Opening the big view the way a reader does, for the unit tests.
 *
 * A test should click what the reader clicks — select the thing, let the view
 * open, then open the fold or the arrow it wants to read. These helpers keep
 * that one line long so the tests stay about what the view *shows*.
 */
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { useExecutionStore } from '@/store/executionStore';
import { BigView } from '@/components/bigview/BigView';
import type { Selection } from '@/types';

/** Selects a thing and renders the big view on it. */
export function openBigView(type: Selection['type'], id: string) {
  const result = render(<BigView />);
  act(() => {
    useExecutionStore.getState().select(type, id);
  });
  return result;
}

/** The view's own root, so a test can scope its queries to it. */
export function view(): HTMLElement {
  return screen.getByTestId('big-view');
}

/** Opens one of the middle box's folds by its key, e.g. 'prompt'. */
export function openFold(key: string) {
  act(() => {
    fireEvent.click(screen.getByTestId(`bv-fold-${key}-trigger`));
  });
}

/** Opens the left arrow (what went in) or the right one (what came out). */
export function openArrow(side: 'in' | 'out') {
  act(() => {
    fireEvent.click(screen.getByTestId(`bv-${side}-toggle`));
  });
  return screen.getByTestId(`bv-${side}-body`);
}

/** Opens the nth row of the timeline and returns its body. */
export function openRow(index: number): HTMLElement {
  const rows = screen.getAllByTestId('bv-row');
  act(() => {
    fireEvent.click(within(rows[index]).getByTestId('bv-row-trigger'));
  });
  return within(rows[index]).getByTestId('bv-row-body');
}

/** Every fold key the middle box is currently offering. */
export function foldKeys(): string[] {
  return Array.from(view().querySelectorAll('[data-testid^="bv-fold-"]'))
    .map((el) => el.getAttribute('data-testid') ?? '')
    .filter((id) => id.endsWith('-trigger') === false)
    .map((id) => id.replace('bv-fold-', ''));
}

/** The facts on the top strip, as "label value" pairs. */
export function facts(): string[] {
  return Array.from(screen.getByTestId('bv-facts').children).map((el) =>
    (el.textContent ?? '').trim(),
  );
}
