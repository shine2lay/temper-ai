import { useEffect } from 'react';

/**
 * Set `document.title` for the current page.
 *
 * Every route used to keep the title baked into index.html ("Temper AI -
 * Execution View"), so browser tabs, history and bookmarks were all
 * indistinguishable.
 */
export function useDocumentTitle(title: string | null | undefined) {
  useEffect(() => {
    if (!title) return;
    const previous = document.title;
    document.title = `Temper AI — ${title}`;
    return () => {
      document.title = previous;
    };
  }, [title]);
}
