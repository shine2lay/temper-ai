import { useId, useState } from 'react';
import { RefreshCw, Send } from 'lucide-react';
import { cn } from '@/lib/utils';
import { DEFAULT_MESSAGE_MAX_CHARS } from '@/lib/teamMessage';
import type { MessageResult, TeamMessageSender } from '@/hooks/useTeamMessage';
import type { TeamRun } from '@/types/team';
import { TeamCharCount } from '../TeamCharCount';
import { TeamNote } from '../TeamNote';
import { teamBtn, teamCard, teamField, teamLabel } from '../teamUi';

const NO_ANSWER = "Temper didn't answer. Trying again is safe: the same request counts once.";

/** What Temper said to the last message (SPEC 5.6). */
function MessageResultNote({
  result,
  paused,
  sending,
  onRetry,
}: {
  result: MessageResult;
  paused: boolean;
  sending: boolean;
  onRetry: () => void;
}) {
  const { outcome } = result;
  if (outcome.kind === 'sent') {
    return (
      <TeamNote tone="ok">
        {outcome.held ? (
          <>
            <b className="font-semibold">Sent: held until you answer the open question.</b>
            {paused && <> The team is paused, so no member takes a turn until then.</>}
          </>
        ) : (
          <>
            <b className="font-semibold">Sent.</b> {outcome.to} gets it at its next turn.
          </>
        )}
      </TeamNote>
    );
  }
  if (outcome.kind === 'refused') {
    return (
      <TeamNote tone="bad">
        <b className="font-semibold">Temper refused:</b> <span data-engine-words="">{outcome.words}</span>{' '}
        Your text is kept.
      </TeamNote>
    );
  }
  return (
    <TeamNote
      tone="bad"
      action={
        <button type="button" className={teamBtn.secondary} onClick={onRetry} disabled={sending}>
          <RefreshCw className="h-4 w-4" aria-hidden="true" />
          <span>Try again</span>
        </button>
      }
    >
      {NO_ANSWER}
    </TeamNote>
  );
}

/**
 * "Message a member" (SPEC 5.6, boards O2 and O6r): a message reaches the
 * member at its next turn, or is held while a question waits for the
 * owner. Only Temper checks it: an empty or too long message, or a member
 * who has left, comes back as Temper's own words, with the text kept.
 */
export function MessageComposer({
  run,
  limit,
  sender,
}: {
  run: TeamRun;
  limit: number | undefined;
  sender: TeamMessageSender;
}) {
  const ids = useId();
  const titleId = `${ids}-title`;
  const toId = `${ids}-to`;
  const bodyId = `${ids}-body`;
  const countId = `${ids}-count`;
  const helpId = `${ids}-help`;
  const names = run.members.map((m) => m.name);
  const leader = run.trial.leader;
  const [to, setTo] = useState(() => (names.includes(leader) ? leader : (names[0] ?? '')));
  const [body, setBody] = useState('');
  const waitOpen = run.open_waits.length > 0;
  const max = limit ?? DEFAULT_MESSAGE_MAX_CHARS;
  const { sending, result } = sender;

  async function send() {
    const done = await sender.send(to, body);
    // Sent: the box empties, unless the owner has written something else meanwhile.
    if (done.outcome.kind === 'sent') setBody((b) => (b === done.sent.body ? '' : b));
  }

  async function retry() {
    const done = await sender.retry();
    if (done && done.outcome.kind === 'sent') setBody((b) => (b === done.sent.body ? '' : b));
  }

  return (
    <section data-card="composer" aria-labelledby={titleId} className={cn(teamCard, 'flex flex-col gap-3 p-4')}>
      <h2 id={titleId} className={cn(teamLabel, 'mb-0')}>
        Message a member
      </h2>
      <div className="flex flex-wrap items-center gap-2">
        <label htmlFor={toId} className="text-sm text-temper-text-muted">
          To
        </label>
        <select
          id={toId}
          value={to}
          onChange={(e) => setTo(e.target.value)}
          className={cn(teamField, 'min-h-9 w-auto min-w-[10rem] py-1.5')}
        >
          {names.map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>
        <TeamCharCount id={countId} className="ml-auto" text={body} limit={max} />
      </div>
      <label htmlFor={bodyId} className="sr-only">
        Message
      </label>
      <textarea
        id={bodyId}
        value={body}
        onChange={(e) => setBody(e.target.value)}
        placeholder="Write to a member…"
        rows={4}
        aria-describedby={`${countId} ${helpId}`}
        className={cn(teamField, 'min-h-[88px] resize-y')}
      />
      {/* One live region that stays, so every new result is read out (SPEC 6: polite). */}
      <div aria-live="polite" data-testid="team-message-result" className="empty:hidden">
        {result && (
          <MessageResultNote
            key={result.seq}
            result={result}
            paused={run.state === 'paused'}
            sending={sending}
            onRetry={() => void retry()}
          />
        )}
      </div>
      <div className="flex flex-wrap items-center justify-end gap-3">
        <p id={helpId} className="m-0 flex-1 text-xs text-temper-text-muted">
          {waitOpen ? 'Held until you answer the open question.' : 'Reaches the member at its next turn.'}
        </p>
        {/* While a question waits, Send answer is the page's main action (O2). */}
        <button
          type="button"
          className={waitOpen ? teamBtn.secondaryMd : teamBtn.primaryMd}
          onClick={() => void send()}
          disabled={sending}
          aria-busy={sending || undefined}
        >
          {!sending && <Send className="h-4 w-4" aria-hidden="true" />}
          <span>{sending ? 'Sending…' : 'Send message'}</span>
        </button>
      </div>
    </section>
  );
}
