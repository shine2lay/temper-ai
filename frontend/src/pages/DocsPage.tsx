import { ConfigDocs } from '@/components/docs/ConfigDocs';
import { useDocumentTitle } from '@/hooks/useDocumentTitle';

export function DocsPage() {
  useDocumentTitle('Docs');
  return <ConfigDocs />;
}
