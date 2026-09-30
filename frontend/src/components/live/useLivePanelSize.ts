/**
 * How tall the live panel is, and how dragging changes it.
 *
 * The height is kept as a share of the page, so it looks the same on a
 * laptop and on a wide screen, and it is remembered between visits. Beside
 * the dragged height there is one button height: full page. Which of the two
 * you chose is remembered as well, so the panel opens the way you left it.
 */
import { useCallback, useEffect, useRef, useState } from 'react';

const HEIGHT_KEY = 'temper-live-panel-share';
const FOLDED_KEY = 'temper-live-panel-folded';
const EXPANDED_KEY = 'temper-live-panel-expanded';

/** Where it starts: a little under half the page. */
export const DEFAULT_SHARE = 0.4;
/** Folded, only the header bar shows. */
export const BAR_HEIGHT = 34;
/** Dragged below this, the panel folds to its bar. */
export const MIN_SHARE = 0.12;

function readShare(): number {
  try {
    const raw = localStorage.getItem(HEIGHT_KEY);
    const value = raw == null ? NaN : Number.parseFloat(raw);
    if (Number.isFinite(value) && value >= MIN_SHARE && value <= 1) return value;
  } catch {
    /* no storage (private window): the default is fine */
  }
  return DEFAULT_SHARE;
}

function readFolded(): boolean {
  try {
    return localStorage.getItem(FOLDED_KEY) === '1';
  } catch {
    return false;
  }
}

function readExpanded(): boolean {
  try {
    return localStorage.getItem(EXPANDED_KEY) === '1';
  } catch {
    return false;
  }
}

function remember(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* nothing to do: the size just won't be remembered */
  }
}

export interface LivePanelSize {
  /** Share of the page the panel takes, 0..1. */
  share: number;
  folded: boolean;
  /** Opened to the full page by the button, whatever the dragged share is. */
  expanded: boolean;
  dragging: boolean;
  /** What to give the panel's `height`: a bar, the whole page, or the share. */
  height: string;
  setFolded: (folded: boolean) => void;
  /** Full page ↔ the height you dragged. Expanding also unfolds. */
  setExpanded: (expanded: boolean) => void;
  /** Put on the drag handle. */
  onHandlePointerDown: (event: React.PointerEvent) => void;
  /** Put on the panel itself: its parent is what the share is measured against. */
  panelRef: React.RefObject<HTMLDivElement | null>;
}

export function useLivePanelSize(): LivePanelSize {
  const [share, setShare] = useState(readShare);
  const [folded, setFoldedState] = useState(readFolded);
  const [expanded, setExpandedState] = useState(readExpanded);
  const [dragging, setDragging] = useState(false);
  const panelRef = useRef<HTMLDivElement | null>(null);

  const setFolded = useCallback((next: boolean) => {
    setFoldedState(next);
    remember(FOLDED_KEY, next ? '1' : '0');
  }, []);

  const setExpanded = useCallback((next: boolean) => {
    setExpandedState(next);
    remember(EXPANDED_KEY, next ? '1' : '0');
    // Opening it to the full page while it is folded would show nothing:
    // the button that opens it wide opens it.
    if (next) {
      setFoldedState(false);
      remember(FOLDED_KEY, '0');
    }
  }, []);

  const onHandlePointerDown = useCallback(
    (event: React.PointerEvent) => {
      event.preventDefault();
      const box = panelRef.current?.parentElement?.getBoundingClientRect();
      if (!box || box.height <= 0) return;
      setDragging(true);
      (event.target as Element).setPointerCapture?.(event.pointerId);

      // A drag says what height you want: the full-page button steps aside.
      setExpandedState(false);
      remember(EXPANDED_KEY, '0');

      const move = (e: PointerEvent) => {
        const next = (box.bottom - e.clientY) / box.height;
        if (next < MIN_SHARE) {
          setFoldedState(true);
          return;
        }
        setFoldedState(false);
        setShare(Math.min(1, next));
      };
      const up = () => {
        setDragging(false);
        window.removeEventListener('pointermove', move);
        window.removeEventListener('pointerup', up);
        setShare((current) => {
          remember(HEIGHT_KEY, String(current));
          return current;
        });
        setFoldedState((current) => {
          remember(FOLDED_KEY, current ? '1' : '0');
          return current;
        });
      };
      window.addEventListener('pointermove', move);
      window.addEventListener('pointerup', up);
    },
    [],
  );

  useEffect(() => () => setDragging(false), []);

  const height = folded
    ? `${BAR_HEIGHT}px`
    : expanded
      ? '100%'
      : `${Math.round(share * 100)}%`;

  return {
    share,
    folded,
    expanded,
    dragging,
    height,
    setFolded,
    setExpanded,
    onHandlePointerDown,
    panelRef,
  };
}
