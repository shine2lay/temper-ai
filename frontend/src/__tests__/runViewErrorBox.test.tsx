/**
 * One broken part of the run view must not blank the page.
 *
 * Before this, a single bad list anywhere under the run view threw while
 * React was drawing, React unmounted the whole tree, and the page went
 * white in the middle of a run — exactly when you are watching it.
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, cleanup, screen } from '@testing-library/react';

import { ErrorBoundary } from '@/components/shared/ErrorBoundary';

function Broken(): React.ReactElement {
  throw new Error('calls is not iterable');
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('a broken part of the run view', () => {
  it('shows a small box and leaves the rest of the page alone', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});

    render(
      <div>
        <ErrorBoundary label="The live panel">
          <Broken />
        </ErrorBoundary>
        <div data-testid="the-rest">the run's picture, still here</div>
      </div>,
    );

    expect(screen.getByRole('alert')).toHaveTextContent('The live panel stopped drawing');
    expect(screen.getByRole('alert')).toHaveTextContent('calls is not iterable');
    expect(screen.getByRole('alert')).toHaveTextContent('the rest of the page still works');
    expect(screen.getByTestId('the-rest')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Reload' })).toBeInTheDocument();
  });

  it('clears itself when the page moves to another run', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});

    const view = render(
      <ErrorBoundary label="The live panel" resetKey="run-1">
        <Broken />
      </ErrorBoundary>,
    );
    expect(screen.getByRole('alert')).toBeInTheDocument();

    view.rerender(
      <ErrorBoundary label="The live panel" resetKey="run-2">
        <div data-testid="fine">drawing again</div>
      </ErrorBoundary>,
    );
    expect(screen.queryByRole('alert')).toBeNull();
    expect(screen.getByTestId('fine')).toBeInTheDocument();
  });
});
