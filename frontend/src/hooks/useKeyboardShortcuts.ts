import { useEffect, useRef } from 'react';
import { useExecutionStore } from '@/store/executionStore';

interface ShortcutActions {
  onSwitchTab?: (tab: string) => void;
  onShowHelp?: () => void;
}

export function useKeyboardShortcuts(actions: ShortcutActions = {}) {
  const clearSelection = useExecutionStore((s) => s.clearSelection);
  const selection = useExecutionStore((s) => s.selection);

  // Keep a stable ref so the effect doesn't re-register on every render
  const actionsRef = useRef(actions);
  actionsRef.current = actions;

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      // Don't capture when typing in inputs
      if (
        e.target instanceof HTMLInputElement ||
        e.target instanceof HTMLTextAreaElement ||
        (e.target instanceof HTMLElement && e.target.isContentEditable)
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
          actionsRef.current.onSwitchTab?.('dag');
          break;
        case '2':
          actionsRef.current.onSwitchTab?.('timeline');
          break;
        case '3':
          actionsRef.current.onSwitchTab?.('eventlog');
          break;
        case '4':
          actionsRef.current.onSwitchTab?.('llmcalls');
          break;
        case '5':
          actionsRef.current.onSwitchTab?.('checkpoints');
          break;
        case '?':
          actionsRef.current.onShowHelp?.();
          break;
      }
    }

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [selection, clearSelection]);
}
