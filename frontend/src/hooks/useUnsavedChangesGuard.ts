import { useEffect } from 'react';
import { useBlocker } from 'react-router-dom';

/**
 * Warn before leaving a screen with unsaved edits.
 *
 * Studio guarded its canvas this way, but the Library editors did not: typing
 * into an agent's prompt and clicking any nav link threw the edit away with no
 * warning at all. Covers both in-app navigation and closing/reloading the tab.
 */
export function useUnsavedChangesGuard(isDirty: boolean, message?: string) {
  useBlocker(({ currentLocation, nextLocation }) => {
    if (!isDirty) return false;
    if (currentLocation.pathname === nextLocation.pathname) return false;
    return !window.confirm(
      message ?? 'You have unsaved changes. Are you sure you want to leave?',
    );
  });

  useEffect(() => {
    const handler = (e: BeforeUnloadEvent) => {
      if (isDirty) e.preventDefault();
    };
    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [isDirty]);
}
