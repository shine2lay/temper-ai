/** D123 caller-scoped words and classes. Legacy callers remain the default. */
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { StopAnswerDialog } from '@/components/team/run/StopAnswerDialog';
import { StopRunDialog } from '@/components/team/run/StopRunDialog';

// A string name in getByRole already matches the whole accessible name.
afterEach(cleanup);
describe('D123: no shared global replacement', () => {
  it.each([false, true])('header projectContext=%s preserves workflow and cancel sends nothing', (projectContext) => {
    const closed = vi.fn();
    const stopped = vi.fn();
    render(<StopRunDialog open onOpenChange={closed} executionId="fixture" workflow="actual-workflow" reasonLimit={100} onStopped={stopped} projectContext={projectContext} />);
    expect(screen.getByRole('alertdialog')).toHaveTextContent(projectContext ? 'Stop this project?' : 'Stop run: actual-workflow');
    expect(screen.getByRole('alertdialog')).toHaveTextContent('actual-workflow');
    expect(screen.getByRole('alertdialog')).toHaveTextContent(projectContext ? 'Ends this project and cancels its run.' : 'Ends the team and cancels the run.');
    const confirm = screen.getByRole('button', { name: projectContext ? 'Stop project' : 'Stop run' });
    expect(confirm.className.includes('min-h-11')).toBe(projectContext);
    expect(confirm).not.toHaveFocus();
    fireEvent.click(screen.getByRole('button', { name: projectContext ? 'Cancel' : 'Keep running' }));
    expect(closed).toHaveBeenCalledWith(false);
    expect(stopped).not.toHaveBeenCalled();
  });
  it.each(['pause', 'settings', 'recovery'] as const)('question kind %s preserves operational result, supplied text and cancel', (waitKind) => {
    const confirm = vi.fn();
    const close = vi.fn();
    render(<StopAnswerDialog open onOpenChange={close} waitTitle="Keep the exact question?" waitKind={waitKind} words="Exact owner words." onConfirm={confirm} projectContext />);
    const d = screen.getByRole('alertdialog');
    expect(d).toHaveTextContent(waitKind === 'settings' ? 'Stop this project at the settings check?' : 'Stop this project at this question?');
    expect(d).toHaveTextContent('Your answer: stop');
    expect(d).toHaveTextContent('Keep the exact question?');
    expect(d).toHaveTextContent('Exact owner words.');
    expect(d).toHaveTextContent(waitKind === 'recovery' ? 'will show this run as failed' : 'will show this run as cancelled, like Stop project');
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(close).toHaveBeenCalledWith(false);
    expect(confirm).not.toHaveBeenCalled();
  });
  it('legacy question callers retain Team and Stop run copy and 36px defaults', () => {
    render(<StopAnswerDialog open onOpenChange={vi.fn()} waitTitle="Keep the exact question?" waitKind="settings" words="" onConfirm={vi.fn()} />);
    expect(screen.getByRole('alertdialog')).toHaveTextContent('Stop the team at the settings check?');
    expect(screen.getByRole('alertdialog')).toHaveTextContent('like Stop run');
    expect(screen.getByRole('button', { name: 'Stop the team' }).className).not.toContain('min-h-11');
    expect(screen.getByRole('button', { name: 'Keep the team' })).toBeInTheDocument();
  });
});
