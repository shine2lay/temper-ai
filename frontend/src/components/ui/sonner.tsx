import { Toaster as Sonner } from 'sonner';

export function Toaster() {
  return (
    <Sonner
      theme="dark"
      position="bottom-right"
      toastOptions={{
        className: 'bg-temper-panel border-temper-border text-temper-text',
      }}
    />
  );
}
