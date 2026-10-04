import { useState, useEffect } from 'react';
import { Link, useLocation } from 'react-router-dom';
import {
  LayoutDashboard,
  PenTool,
  BookOpen,
  FileText,
  Settings,
  Sun,
  Moon,
  PanelLeftClose,
  PanelLeftOpen,
} from 'lucide-react';
import { TemperSymbol } from '@/components/shared/TemperBrand';
import { getActiveTheme, toggleTheme } from '@/lib/theme';
import { cn } from '@/lib/utils';

const STORAGE_KEY = 'temper-sidebar-collapsed';

const NAV_ITEMS = [
  { label: 'Workflows', icon: LayoutDashboard, to: '/', match: (p: string) => p === '/' || p.startsWith('/workflow/') },
  { label: 'Studio', icon: PenTool, to: '/studio', match: (p: string) => p.startsWith('/studio') },
  { label: 'Library', icon: BookOpen, to: '/library', match: (p: string) => p.startsWith('/library') },
  { label: 'Docs', icon: FileText, to: '/docs', match: (p: string) => p.startsWith('/docs') },
  { label: 'Settings', icon: Settings, to: '/settings', match: (p: string) => p.startsWith('/settings') },
] as const;

export function AppSidebar() {
  const location = useLocation();
  const [collapsed, setCollapsed] = useState(() => {
    try { return localStorage.getItem(STORAGE_KEY) === 'true'; } catch { return false; }
  });
  const [theme, setTheme] = useState<'light' | 'dark'>(getActiveTheme);

  useEffect(() => {
    try { localStorage.setItem(STORAGE_KEY, String(collapsed)); } catch {}
  }, [collapsed]);

  function handleThemeToggle() {
    const next = toggleTheme();
    setTheme(next);
  }

  return (
    <aside
      className={cn(
        'flex flex-col h-full bg-temper-panel border-r border-temper-border shrink-0 transition-[width] duration-200 overflow-hidden',
        collapsed ? 'w-14' : 'w-[200px]',
      )}
    >
      {/* Brand: the Temper symbol, with the name when there is room. The
          symbol's own file keeps the glyph off its edges; the padding and
          gap add the rest of the quarter-box clear space. */}
      <div
        className={cn(
          'flex items-center gap-2.5 py-4 border-b border-temper-border shrink-0',
          collapsed ? 'justify-center px-0' : 'px-3',
        )}
        data-testid="sidebar-brand"
      >
        <TemperSymbol size={32} label={collapsed ? 'Temper AI' : ''} />
        {!collapsed && (
          <span className="text-base font-semibold text-temper-text whitespace-nowrap">Temper AI</span>
        )}
      </div>

      {/* Nav links */}
      <nav className="flex flex-col gap-1 px-2 py-3 flex-1" aria-label="Main navigation">
        {NAV_ITEMS.map((item) => {
          const active = item.match(location.pathname);
          return (
            <Link
              key={item.to}
              to={item.to}
              // Active: a quiet surface, the brand bar on the left and
              // semibold text, so the state never rests on colour alone.
              className={cn(
                'flex items-center gap-2.5 px-2.5 py-2 rounded-md text-sm transition-colors border-l-[3px]',
                active
                  ? 'bg-temper-surface border-temper-accent text-temper-text font-semibold'
                  : 'border-transparent text-temper-text-muted hover:text-temper-text hover:bg-temper-surface',
              )}
              aria-current={active ? 'page' : undefined}
              aria-label={collapsed ? item.label : undefined}
              title={collapsed ? item.label : undefined}
            >
              <item.icon className="w-4 h-4 shrink-0" />
              {!collapsed && <span className="truncate">{item.label}</span>}
            </Link>
          );
        })}
      </nav>

      {/* Bottom controls */}
      <div className="flex flex-col gap-1 px-2 py-3 border-t border-temper-border">
        <button
          onClick={handleThemeToggle}
          className="flex items-center gap-2.5 px-2.5 py-2 rounded-md text-sm text-temper-text-muted hover:text-temper-text hover:bg-temper-surface transition-colors"
          aria-label={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
          title={collapsed ? (theme === 'dark' ? 'Light mode' : 'Dark mode') : undefined}
        >
          {theme === 'dark' ? <Sun className="w-4 h-4 shrink-0" /> : <Moon className="w-4 h-4 shrink-0" />}
          {!collapsed && <span>{theme === 'dark' ? 'Light mode' : 'Dark mode'}</span>}
        </button>
        <button
          onClick={() => setCollapsed((c) => !c)}
          className="flex items-center gap-2.5 px-2.5 py-2 rounded-md text-sm text-temper-text-muted hover:text-temper-text hover:bg-temper-surface transition-colors"
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          title={collapsed ? 'Expand' : undefined}
        >
          {collapsed ? <PanelLeftOpen className="w-4 h-4 shrink-0" /> : <PanelLeftClose className="w-4 h-4 shrink-0" />}
          {!collapsed && <span>Collapse</span>}
        </button>
      </div>
    </aside>
  );
}
