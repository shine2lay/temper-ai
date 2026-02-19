import { useEffect } from 'react';
import { useExecutionStore } from '@/store/executionStore';

interface ShortcutActions {
  onSwitchTab?: (tab: string) => void;
}

export function useKeyboardShortcuts(actions: ShortcutActions = {}) {
  const clearSelection = useExecutionStore((s) => s.clearSelection);
  const selection = useExecutionStore((s) => s.selection);

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      // Don't capture when typing in inputs
      if (
        e.target instanceof HTMLInputElement ||
        e.target instanceof HTMLTextAreaElement
      ) {
        return;
      }

      switch (e.key) {
        case 'Escape':
          if (selection) {
            clearSelection();
            e.preventDefault();
          }
          break;
        case '1':
          actions.onSwitchTab?.('dag');
          break;
        case '2':
          actions.onSwitchTab?.('timeline');
          break;
        case '3':
          actions.onSwitchTab?.('eventlog');
          break;
        case '?':
          console.info('Keyboard shortcuts: Esc=close panel, 1=DAG, 2=Timeline, 3=EventLog');
          break;
      }
    }

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [selection, clearSelection, actions]);
}
