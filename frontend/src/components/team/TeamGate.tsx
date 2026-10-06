import { Suspense, type ReactNode } from 'react';
import { NotFound } from '@/components/shared/NotFound';
import { useTeamStatus } from '@/hooks/useTeamStatus';

/**
 * Team pages exist only while the server's Team switch is on. Until the
 * status answer is in, nothing renders (no flash of either page); then the
 * page itself, loaded on demand, or the app's own "Page not found".
 */
export function TeamGate({ children }: { children: ReactNode }) {
  const { on, settled } = useTeamStatus({ poll: true });
  if (!settled) return null;
  if (!on) return <NotFound />;
  return <Suspense fallback={null}>{children}</Suspense>;
}
