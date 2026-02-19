import { Toaster as Sonner } from 'sonner';

export function Toaster() {
  return (
    <Sonner
      theme="dark"
      position="bottom-right"
      toastOptions={{
        className: 'bg-maf-panel border-maf-border text-maf-text',
      }}
    />
  );
}
