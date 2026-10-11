import { Square } from 'lucide-react';
import { cn } from '@/lib/utils';
import { stopAnswerRunList, stopAnswerWords } from '@/lib/teamOutcome';
import type { TeamWait } from '@/types/team';
import { TeamDialog, TeamDialogCancel, TeamDialogLabel } from '../TeamDialog';
import { OwnerWords } from '../TeamQuote';
import { teamBtn } from '../teamUi';

/**
 * The stop-answer confirm (Design's O1c): shown when stop is picked in the
 * needs-you card and Send is pressed. Its words are Design's (spec 5.8):
 * the team ends, then one sentence on what the run list will say, by the
 * kind of question being answered. At the settings check (O1e) it says
 * the held answer is dropped.
 */
export function StopAnswerDialog({
  open,
  onOpenChange,
  waitTitle,
  waitKind,
  answerLabel = 'stop',
  words,
  onConfirm,
  projectContext = false,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  waitTitle: string;
  waitKind: TeamWait['kind'];
  /** How the card names the stop answer ("Stop the team" at the settings check). */
  answerLabel?: string;
  words: string;
  onConfirm: () => void;
  /** D123: leave legacy callers unchanged. */
  projectContext?: boolean;
}) {
  const listWords = stopAnswerRunList(waitKind);
  const runList = projectContext ? listWords?.replace('like Stop run', 'like Stop project') : listWords;
  const legacy = stopAnswerWords(waitKind);
  const { title, ends } = projectContext ? {
    title: waitKind === 'settings' ? 'Stop this project at the settings check?' : 'Stop this project at this question?',
    ends: waitKind === 'settings' ? 'The project ends here, before anything runs with the new settings. Your last answer is not applied, and nothing more is spent.' : 'The project ends here and nothing more is spent.',
  } : legacy;
  return (
    <TeamDialog
      open={open}
      onOpenChange={onOpenChange}
      testId="team-stop-answer-dialog"
      projectActions={projectContext}
      title={title}
      subtitle="Your answer: stop"
      hint="You can't undo this."
      buttons={
        <>
          <TeamDialogCancel className={cn(teamBtn.secondaryMd, projectContext && 'min-h-11 min-w-11 whitespace-normal py-2')}>{projectContext ? 'Cancel' : 'Keep the team'}</TeamDialogCancel>
          <button type="button" className={cn(teamBtn.dangerMd, projectContext && 'min-h-11 min-w-11 whitespace-normal py-2')} onClick={onConfirm}>
            <Square className="h-4 w-4" aria-hidden="true" />
            <span>{projectContext ? 'Stop project' : 'Stop the team'}</span>
          </button>
        </>
      }
    >
      <TeamDialogLabel>You answer</TeamDialogLabel>
      <p className="m-0 text-sm text-temper-text">
        <b className="font-semibold">{answerLabel}</b> to &ldquo;{waitTitle}&rdquo;
      </p>
      <TeamDialogLabel>What happens</TeamDialogLabel>
      <ul className="m-0 flex list-disc flex-col gap-1 pl-5 text-sm text-temper-text">
        <li>{ends}</li>
        {runList && <li>{runList}</li>}
      </ul>
      {words.trim() !== '' && (
        <OwnerWords by="owner" words={words} labelClassName="mb-2 uppercase tracking-[0.06em]" />
      )}
    </TeamDialog>
  );
}
