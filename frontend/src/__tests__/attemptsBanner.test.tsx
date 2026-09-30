/**
 * What the run page says about a run that ran more than once.
 *
 * The point of the banner is that a resumed run does not look like a fresh one: a reader
 * seeing steps from two attempts merged into one tree should be told why, and told when it
 * was temper that picked the run back up rather than a person.
 */
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { AttemptsBanner } from '@/components/layout/AttemptsBanner';
import type { RunAttempt } from '@/types';

function attempt(over: Partial<RunAttempt> = {}): RunAttempt {
  return {
    attempt: 1,
    event_id: 'ev-1',
    start_time: '2026-09-28T01:20:00Z',
    status: 'interrupted',
    is_current: false,
    picked_up_by_temper: false,
    ...over,
  };
}

describe('AttemptsBanner', () => {
  it('says nothing about a run that ran once', () => {
    const { container } = render(<AttemptsBanner attempts={[attempt({ is_current: true })]} />);

    expect(container).toBeEmptyDOMElement();
  });

  it('says nothing when the server does not send attempts', () => {
    const { container } = render(<AttemptsBanner attempts={null} />);

    expect(container).toBeEmptyDOMElement();
  });

  it('names temper when temper picked the run back up', () => {
    render(
      <AttemptsBanner
        attempts={[
          attempt({ attempt: 1, picked_up_by_temper: true }),
          attempt({ attempt: 2, event_id: 'ev-2', status: 'completed', is_current: true }),
        ]}
      />,
    );

    expect(screen.getByText(/temper picked this run back up after a restart/)).toBeInTheDocument();
    expect(screen.getByText(/picked back up by temper/)).toBeInTheDocument();
  });

  it('says only that it was resumed when a person pressed Resume', () => {
    render(
      <AttemptsBanner
        attempts={[
          attempt({ attempt: 1, status: 'failed' }),
          attempt({ attempt: 2, event_id: 'ev-2', status: 'running', is_current: true }),
        ]}
      />,
    );

    expect(screen.getByText(/started again from where it stopped/)).toBeInTheDocument();
    expect(screen.queryByText(/picked back up by temper/)).not.toBeInTheDocument();
  });

  it('keeps the earlier attempt readable, with how it ended', () => {
    render(
      <AttemptsBanner
        attempts={[
          attempt({ attempt: 1, status: 'interrupted', error: 'the server restarted' }),
          attempt({ attempt: 2, event_id: 'ev-2', status: 'completed', is_current: true }),
        ]}
      />,
    );

    const banner = screen.getByTestId('attempts-banner');
    expect(banner.textContent).toContain('#1');
    expect(banner.textContent).toContain('interrupted');
    expect(banner.textContent).toContain('the server restarted');
    expect(banner.textContent).toContain('#2');
    expect(banner.textContent).toContain('this one');
  });
});
