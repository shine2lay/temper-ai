/**
 * The run page before its first reply (SPEC 10). Until Temper answers the
 * page can't tell a free-flowing team from a round run, so both kinds share
 * these two views [D53].
 */
import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { RefreshCw } from 'lucide-react';
import { cn } from '@/lib/utils';
import { TeamGuardBanner } from '@/components/team/TeamGuardBanner';
import { teamBtn, teamCard } from '@/components/team/teamUi';
import type { TeamGuardMode } from '@/types/team';
import { GlanceCrumbs } from './GlanceRunView';
import { GIcon } from './glanceUi';
import { glanceBodyBox, glanceHeaderBox, toneText } from './glanceStyle';
import { StatusBandSkeleton } from './StatusBand';
import './glance.css';

function Page({ header, children, testId }: { header: ReactNode; children: ReactNode; testId: string }) {
  return (
    <div className="glance-root flex h-full flex-col overflow-auto bg-temper-bg" data-testid={testId}>
      <header className={glanceHeaderBox}>
        <GlanceCrumbs />
        {header}
      </header>
      <div className={glanceBodyBox}>{children}</div>
    </div>
  );
}

/**
 * Loading: one page heading for screen readers, "Team run" [D7, D53], with
 * skeleton bars standing in for the title; the band's labels over skeletons
 * in the loaded band's shape [D70]; then the words.
 */
export function GlanceLoading({ guardMode }: { guardMode?: TeamGuardMode }) {
  const bar = 'rounded-md bg-temper-surface';
  return (
    <Page
      testId="glance-loading"
      header={
        <div className="flex min-w-0 flex-col gap-1">
          <h1 className="sr-only">Team run</h1>
          <div className={cn(bar, 'h-7 w-[80%] max-w-[420px]')} aria-hidden="true" />
          <div className={cn(bar, 'h-4 w-[60%] max-w-[300px]')} aria-hidden="true" />
        </div>
      }
    >
      <TeamGuardBanner mode={guardMode} textScale="glance" />
      <StatusBandSkeleton />
      <p role="status" className="m-0 text-sm text-temper-text-muted">
        Loading the project from Temper…
      </p>
    </Page>
  );
}

/**
 * The first read failed: nothing to show yet. The page keeps reading every
 * 5 s (useTeamRun), so it comes back by itself once Temper answers.
 */
export function GlanceReadError({ onRetry }: { onRetry: () => void }) {
  return (
    <Page
      testId="glance-read-failed"
      header={
        <h1 className="m-0 text-xl font-semibold text-balance break-words text-temper-text">
          This project couldn&apos;t be read
        </h1>
      }
    >
      <div
        role="alert"
        className={cn(teamCard, 'glance-edge-left flex min-w-0 flex-col gap-2 p-4')}
        data-tone="red"
        data-testid="glance-read-error"
      >
        <p className={cn('m-0 flex items-start gap-2 text-xl leading-7 font-semibold', toneText.red)}>
          <GIcon name="alert" className="mt-1 h-5 w-5 shrink-0" />
          <span className="min-w-0 break-words">Temper didn&apos;t answer</span>
        </p>
        <p className="m-0 text-base break-words text-temper-text">
          The page asked Temper for this project and got no answer. Nothing was changed. It may be restarting.
        </p>
        <div className="flex flex-wrap gap-2.5">
          <button type="button" className={teamBtn.primary} onClick={onRetry}>
            <RefreshCw className="h-4 w-4" aria-hidden="true" />
            <span>Try again</span>
          </button>
          <Link to="/team" className={teamBtn.secondary}>
            Back to Projects
          </Link>
        </div>
      </div>
    </Page>
  );
}
