/**
 * Route entry for /library — renders the My Library component.
 */
import { MyLibrary } from '@/components/studio/MyLibrary';
import { useDocumentTitle } from '@/hooks/useDocumentTitle';

export function LibraryView() {
  useDocumentTitle('Library');
  return <MyLibrary />;
}
