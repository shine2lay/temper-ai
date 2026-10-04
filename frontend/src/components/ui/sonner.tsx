import { useEffect, useState } from 'react';
import { Toaster as Sonner } from 'sonner';

/** The app's theme is the `dark` class on <html> (lib/theme.ts); follow it. */
function useHtmlTheme(): 'light' | 'dark' {
  const read = () => (document.documentElement.classList.contains('dark') ? 'dark' : 'light');
  const [theme, setTheme] = useState<'light' | 'dark'>(read);
  useEffect(() => {
    const observer = new MutationObserver(() => setTheme(read()));
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });
    return () => observer.disconnect();
  }, []);
  return theme;
}

export function Toaster() {
  const theme = useHtmlTheme();
  return (
    <Sonner
      theme={theme}
      position="bottom-right"
      toastOptions={{
        className: 'bg-temper-panel border-temper-border text-temper-text',
      }}
    />
  );
}
