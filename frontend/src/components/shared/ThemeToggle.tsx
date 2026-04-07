import { useState } from 'react';
import { Sun, Moon } from 'lucide-react';
import { getActiveTheme, toggleTheme } from '@/lib/theme';

export function ThemeToggle() {
  const [theme, setTheme] = useState(getActiveTheme);

  return (
    <button
      onClick={() => setTheme(toggleTheme())}
      className="w-7 h-7 flex items-center justify-center rounded text-temper-text-dim hover:text-temper-text hover:bg-temper-surface transition-colors"
      title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
      aria-label={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
    >
      {theme === 'dark' ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
    </button>
  );
}
