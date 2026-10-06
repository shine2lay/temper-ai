import { Square } from 'lucide-react';
import { stopAnswerRunList } from '@/lib/teamOutcome';
import type { TeamWait } from '@/types/team';
import { TeamDialog, TeamDialogCancel, TeamDialogLabel } from '../TeamDialog';
import { OwnerWords } from '../TeamQuote';
import { teamBtn } from '../teamUi';

/**
 * The stop-answer confirm (Design's O1c): shown when stop is picked in the
 * needs-you card and Send is pressed. Its words are Design's (spec 5.8):
 * the team ends, then one sentence on what the run list will say, by the
 * kind of question being answered.
 */
export function StopAnswerDialog({
  open,
  onOpenChange,
  waitTitle,
  waitKind,
  words,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  waitTitle: string;
  waitKind: TeamWait['kind'];
  words: string;
  onConfirm: () => void;
}) {
  const runList = stopAnswerRunList(waitKind);
  return (
    <TeamDialog
      open={open}
      onOpenChange={onOpenChange}
      testId="team-stop-answer-dialog"
      title="Stop the team at this question?"
      subtitle="Your answer: stop"
      hint="You can't undo this."
      buttons={
        <>
          <TeamDialogCancel className={teamBtn.secondaryMd}>Keep the team</TeamDialogCancel>
          <button type="button" className={teamBtn.dangerMd} onClick={onConfirm}>
            <Square className="h-4 w-4" aria-hidden="true" />
            <span>Stop the team</span>
          </button>
        </>
      }
    >
      <TeamDialogLabel>You answer</TeamDialogLabel>
      <p className="m-0 text-sm text-temper-text">
        <b className="font-semibold">stop</b> to &ldquo;{waitTitle}&rdquo;
      </p>
      <TeamDialogLabel>What happens</TeamDialogLabel>
      <ul className="m-0 flex list-disc flex-col gap-1 pl-5 text-sm text-temper-text">
        <li>The team ends here and nothing more is spent.</li>
        {runList && <li>{runList}</li>}
      </ul>
      {words.trim() !== '' && (
        <OwnerWords by="owner" words={words} labelClassName="mb-2 uppercase tracking-[0.06em]" />
      )}
    </TeamDialog>
  );
}
