import { useState } from 'react';
import { getActiveTheme, toggleTheme } from '@/lib/theme';

export function ThemeToggle() {
  const [theme, setTheme] = useState(getActiveTheme);

  return (
    <button
      onClick={() => setTheme(toggleTheme())}
      className="w-7 h-7 flex items-center justify-center rounded text-temper-text-dim hover:text-temper-text hover:bg-temper-surface transition-colors text-sm"
      title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
    >
      {theme === 'dark' ? '\u2600' : '\u263E'}
    </button>
  );
}
