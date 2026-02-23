import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { OutputDisplay } from '@/components/shared/OutputDisplay';

const SAMPLE_DATA: Record<string, unknown> = {
  output: '# Analysis\n\nThe market shows strong growth in Q4 with significant improvements across all sectors.',
  structured: { sentiment: 'positive', confidence: 0.92 },
  stage_status: 'completed',
  agent_metrics: { tokens: 500 },
};

describe('OutputDisplay', () => {
  it('renders markdown content for long text fields', () => {
    render(<OutputDisplay data={SAMPLE_DATA} />);
    expect(screen.getByText('Analysis')).toBeInTheDocument();
    expect(screen.getByText(/The market shows/)).toBeInTheDocument();
  });

  it('renders structured fields as a table', () => {
    render(<OutputDisplay data={SAMPLE_DATA} />);
    expect(screen.getByText('Structured Data')).toBeInTheDocument();
    expect(screen.getByText('Sentiment')).toBeInTheDocument();
    expect(screen.getByText('positive')).toBeInTheDocument();
  });

  it('renders metadata in collapsed Raw Data section', () => {
    render(<OutputDisplay data={SAMPLE_DATA} />);
    expect(screen.getByText('Raw Data')).toBeInTheDocument();
  });

  it('shows "No data" for empty object', () => {
    render(<OutputDisplay data={{}} />);
    expect(screen.getByText('No data')).toBeInTheDocument();
  });

  it('shows expand/collapse toggle', () => {
    render(<OutputDisplay data={SAMPLE_DATA} />);
    expect(screen.getByText('Show more')).toBeInTheDocument();
  });

  it('toggles between collapsed and expanded', () => {
    render(<OutputDisplay data={SAMPLE_DATA} />);
    fireEvent.click(screen.getByText('Show more'));
    expect(screen.getByText('Show less')).toBeInTheDocument();

    fireEvent.click(screen.getByText('Show less'));
    expect(screen.getByText('Show more')).toBeInTheDocument();
  });

  it('treats whitespace-only content keys as metadata', () => {
    render(<OutputDisplay data={{ output: '   ', status: 'done' }} />);
    expect(screen.getByText('Raw Data')).toBeInTheDocument();
  });
});
