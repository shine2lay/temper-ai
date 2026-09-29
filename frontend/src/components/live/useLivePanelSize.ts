/**
 * How tall the live panel is, and how dragging changes it.
 *
 * The height is kept as a share of the page, so it looks the same on a
 * laptop and on a wide screen, and it is remembered between visits.
 */
import { useCallback, useEffect, useRef, useState } from 'react';

const HEIGHT_KEY = 'temper-live-panel-share';
const FOLDED_KEY = 'temper-live-panel-folded';

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
  dragging: boolean;
  setFolded: (folded: boolean) => void;
  /** Put on the drag handle. */
  onHandlePointerDown: (event: React.PointerEvent) => void;
  /** Put on the panel itself: its parent is what the share is measured against. */
  panelRef: React.RefObject<HTMLDivElement | null>;
}

export function useLivePanelSize(): LivePanelSize {
  const [share, setShare] = useState(readShare);
  const [folded, setFoldedState] = useState(readFolded);
  const [dragging, setDragging] = useState(false);
  const panelRef = useRef<HTMLDivElement | null>(null);

  const setFolded = useCallback((next: boolean) => {
    setFoldedState(next);
    remember(FOLDED_KEY, next ? '1' : '0');
  }, []);

  const onHandlePointerDown = useCallback(
    (event: React.PointerEvent) => {
      event.preventDefault();
      const box = panelRef.current?.parentElement?.getBoundingClientRect();
      if (!box || box.height <= 0) return;
      setDragging(true);
      (event.target as Element).setPointerCapture?.(event.pointerId);

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

  return { share, folded, dragging, setFolded, onHandlePointerDown, panelRef };
}
