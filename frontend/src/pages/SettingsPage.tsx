import { useState } from 'react';
import { useDocumentTitle } from '@/hooks/useDocumentTitle';
import { getActiveTheme, toggleTheme } from '@/lib/theme';
import { cn } from '@/lib/utils';
import { Sun, Moon, Monitor } from 'lucide-react';

export function SettingsPage() {
  useDocumentTitle('Settings');
  const [currentTheme, setCurrentTheme] = useState(getActiveTheme());

  function handleThemeChange() {
    const next = toggleTheme();
    setCurrentTheme(next);
  }

  return (
    <div className="flex-1 overflow-auto bg-temper-bg text-temper-text">
      <div className="max-w-2xl mx-auto px-6 py-8">
        <h1 className="text-3xl font-bold mb-8 text-temper-text">Settings</h1>

        {/* Theme Section */}
        <div className="bg-temper-panel border border-temper-border rounded-lg p-6 mb-6">
          <h2 className="text-lg font-semibold mb-4 text-temper-text">Appearance</h2>

          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-temper-text mb-3">
                Theme
              </label>
              <p className="text-sm text-temper-text-muted mb-4">
                Current theme: <span className="font-semibold capitalize">{currentTheme}</span>
              </p>

              <button
                onClick={handleThemeChange}
                className={cn(
                  'flex items-center gap-3 px-4 py-3 rounded-lg border-2 transition-colors',
                  currentTheme === 'dark'
                    ? 'border-temper-accent bg-temper-accent/10 text-temper-accent'
                    : 'border-temper-border bg-temper-surface text-temper-text-muted hover:text-temper-text',
                )}
              >
                {currentTheme === 'dark' ? (
                  <>
                    <Moon className="w-5 h-5" />
                    <span>Dark Mode (Active)</span>
                  </>
                ) : (
                  <>
                    <Sun className="w-5 h-5" />
                    <span>Light Mode (Active)</span>
                  </>
                )}
              </button>

              <p className="text-xs text-temper-text-dim mt-3">
                Your preference is saved locally and will persist across sessions.
              </p>
            </div>

            {/* System Preference Info */}
            <div className="mt-6 p-4 bg-temper-surface rounded border border-temper-border-light">
              <div className="flex items-start gap-3">
                <Monitor className="w-5 h-5 text-temper-accent-dim mt-0.5 shrink-0" />
                <div className="text-sm">
                  <p className="font-medium text-temper-text mb-1">System Preference</p>
                  <p className="text-temper-text-muted">
                    When no preference is set, the app uses your system's color scheme setting.
                  </p>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Color Palette Preview */}
        <div className="bg-temper-panel border border-temper-border rounded-lg p-6">
          <h2 className="text-lg font-semibold mb-4 text-temper-text">Color Palette</h2>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {[
              { name: 'Background', var: '--temper-bg' },
              { name: 'Panel', var: '--temper-panel' },
              { name: 'Border', var: '--temper-border' },
              { name: 'Accent', var: '--temper-accent' },
              { name: 'Text', var: '--temper-text' },
              { name: 'Text Muted', var: '--temper-text-muted' },
              { name: 'Completed', var: '--temper-completed' },
              { name: 'Running', var: '--temper-running' },
            ].map((color) => (
              <div key={color.var} className="space-y-2">
                <div
                  className="w-full h-16 rounded-lg border border-temper-border"
                  style={{
                    backgroundColor: `var(${color.var})`,
                  }}
                />
                <p className="text-xs font-medium text-temper-text-muted">{color.name}</p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
