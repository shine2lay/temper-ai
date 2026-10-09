import { useState, useEffect, useRef, type KeyboardEvent } from 'react';
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
  Users,
} from 'lucide-react';
import { TemperSymbol } from '@/components/shared/TemperBrand';
import { useTeamStatus } from '@/hooks/useTeamStatus';
import { getActiveTheme, toggleTheme } from '@/lib/theme';
import { useIsNarrow } from '@/lib/useMediaQuery';
import { cn } from '@/lib/utils';

const STORAGE_KEY = 'temper-sidebar-collapsed';

const NAV_ITEMS = [
  { label: 'Workflows', icon: LayoutDashboard, to: '/', match: (p: string) => p === '/' || p.startsWith('/workflow/') },
  { label: 'Studio', icon: PenTool, to: '/studio', match: (p: string) => p.startsWith('/studio') },
  { label: 'Library', icon: BookOpen, to: '/library', match: (p: string) => p.startsWith('/library') },
  { label: 'Docs', icon: FileText, to: '/docs', match: (p: string) => p.startsWith('/docs') },
  { label: 'Settings', icon: Settings, to: '/settings', match: (p: string) => p.startsWith('/settings') },
] as const;

/** Shown after Workflows only while the server's Team switch is on. */
const TEAM_ITEM = { label: 'Team', icon: Users, to: '/team', match: (p: string) => p === '/team' || p.startsWith('/team/') };

/** What the keyboard can reach in the sidebar. */
const FOCUSABLE = 'a[href], button:not([disabled])';

/**
 * On a phone-width screen (under 768 px) the sidebar starts as the icon
 * rail on every load, whatever was chosen on a wider screen, so the page
 * keeps the room. Expand opens it as a drawer over the page (Design
 * rm-a79c1512, fix B): the page stays where it is under a scrim, focus
 * moves to the first link and stays in the drawer, and choosing a link,
 * Esc, a tap outside or Collapse closes it, focus back on the toggle.
 * Wider screens keep the choice saved in localStorage.
 */
export function AppSidebar() {
  const location = useLocation();
  const narrow = useIsNarrow();
  const [wideCollapsed, setWideCollapsed] = useState(() => {
    try { return localStorage.getItem(STORAGE_KEY) === 'true'; } catch { return false; }
  });
  // The page the drawer was opened on, on a phone; null while it is the rail.
  // Going to another page (a link, Back) closes it with no extra step.
  const [openOn, setOpenOn] = useState<string | null>(null);
  const drawer = narrow && openOn === location.pathname;
  const collapsed = narrow ? !drawer : wideCollapsed;
  const toggleRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const [theme, setTheme] = useState<'light' | 'dark'>(getActiveTheme);
  const team = useTeamStatus();
  const navItems = team.on ? [NAV_ITEMS[0], TEAM_ITEM, ...NAV_ITEMS.slice(1)] : NAV_ITEMS;

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, String(wideCollapsed));
    } catch {
      // Storage can be off: the choice then lasts until the page reloads.
    }
  }, [wideCollapsed]);

  // The drawer opened: focus moves in, to its first link.
  useEffect(() => {
    if (drawer) panelRef.current?.querySelector<HTMLElement>('a[href]')?.focus();
  }, [drawer]);

  // Esc closes the drawer from anywhere on the page.
  useEffect(() => {
    if (!drawer) return;
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      event.preventDefault();
      setOpenOn(null);
      toggleRef.current?.focus();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [drawer]);

  function closeDrawer() {
    setOpenOn(null);
    toggleRef.current?.focus();
  }

  function handleCollapseToggle() {
    if (narrow) setOpenOn(drawer ? null : location.pathname);
    else setWideCollapsed((c) => !c);
  }

  // While the drawer is open, Tab and Shift+Tab go round inside it.
  function keepFocusIn(event: KeyboardEvent<HTMLDivElement>) {
    if (!drawer || event.key !== 'Tab') return;
    const items = Array.from(event.currentTarget.querySelectorAll<HTMLElement>(FOCUSABLE));
    if (items.length === 0) return;
    const first = items[0];
    const last = items[items.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  function handleThemeToggle() {
    const next = toggleTheme();
    setTheme(next);
  }

  return (
    <>
      {drawer && (
        <>
          {/* The rail's room stays, so the page doesn't move under the drawer. */}
          <div aria-hidden="true" className="w-14 shrink-0" data-sidebar-placeholder />
          {/* A tap outside closes the drawer (Esc does the same from the keyboard). */}
          <div aria-hidden="true" className="fixed inset-0 z-40 bg-black/50" onClick={closeDrawer} data-sidebar-scrim />
        </>
      )}
      <aside
        className={cn(
          'flex flex-col h-full bg-temper-panel border-r border-temper-border shrink-0 transition-[width] duration-200 overflow-hidden',
          collapsed ? 'w-14' : 'w-[200px]',
          drawer && 'fixed inset-y-0 left-0 z-50 shadow-xl',
        )}
      >
        <div
          ref={panelRef}
          role={drawer ? 'dialog' : undefined}
          aria-modal={drawer ? true : undefined}
          aria-label={drawer ? 'Main menu' : undefined}
          onKeyDown={keepFocusIn}
          className="flex h-full min-h-0 flex-col"
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
            {navItems.map((item) => {
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
                  // In the drawer, choosing a link closes it, even the page you are on.
                  onClick={drawer ? closeDrawer : undefined}
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
              ref={toggleRef}
              onClick={handleCollapseToggle}
              className="flex items-center gap-2.5 px-2.5 py-2 rounded-md text-sm text-temper-text-muted hover:text-temper-text hover:bg-temper-surface transition-colors"
              aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
              title={collapsed ? 'Expand' : undefined}
            >
              {collapsed ? <PanelLeftOpen className="w-4 h-4 shrink-0" /> : <PanelLeftClose className="w-4 h-4 shrink-0" />}
              {!collapsed && <span>Collapse</span>}
            </button>
          </div>
        </div>
      </aside>
    </>
  );
}
