import { useEffect, useRef, useCallback } from 'react';
import { useExecutionStore } from '@/store/executionStore';
import type { WSMessage } from '@/types';
import { getApiKey } from '@/lib/authFetch';
import {
  WS_INITIAL_DELAY_MS,
  WS_MAX_DELAY_MS,
  WS_BACKOFF_MULTIPLIER,
  WS_MAX_RECONNECT_ATTEMPTS,
  WS_CLOSE_WORKFLOW_TERMINAL,
  WS_STALE_AFTER_MS,
} from '@/lib/constants';

/**
 * WebSocket hook — connects to the workflow event stream.
 * No auth required in v1 — connects directly.
 */
export function useWorkflowWebSocket(workflowId: string | undefined): void {
  const socketRef = useRef<WebSocket | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const delayRef = useRef(WS_INITIAL_DELAY_MS);
  const unmountedRef = useRef(false);
  /** When the server was last heard from — a dropped network does not
   *  always close the socket, so silence is the only signal. */
  const lastSeenRef = useRef<number>(Date.now());

  const applySnapshot = useExecutionStore((s) => s.applySnapshot);
  const applyEvent = useExecutionStore((s) => s.applyEvent);
  const setWSStatus = useExecutionStore((s) => s.setWSStatus);

  const connect = useCallback(() => {
    if (unmountedRef.current || !workflowId) return;

    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    // A browser cannot set headers on a WebSocket handshake, so the token
    // rides in the query string (the server accepts either).
    const token = getApiKey();
    const query = token ? `?token=${encodeURIComponent(token)}` : '';
    const url = `${protocol}//${location.host}/ws/${workflowId}${query}`;
    const ws = new WebSocket(url);
    socketRef.current = ws;

    ws.onopen = () => {
      delayRef.current = WS_INITIAL_DELAY_MS;
      lastSeenRef.current = Date.now();
      setWSStatus({ connected: true, reconnectAttempt: 0, wsError: null });
    };

    ws.onmessage = (event) => {
      lastSeenRef.current = Date.now();
      let msg: WSMessage;
      try {
        msg = JSON.parse(event.data) as WSMessage;
      } catch {
        return;
      }

      switch (msg.type) {
        case 'snapshot':
          applySnapshot(msg.workflow);
          break;
        case 'event':
          applyEvent(msg);
          break;
        case 'heartbeat':
          setWSStatus({ lastHeartbeat: msg.timestamp });
          break;
      }
    };

    ws.onclose = (event) => {
      if (unmountedRef.current) return;

      setWSStatus({ connected: false });

      if (event.code === WS_CLOSE_WORKFLOW_TERMINAL || event.code === 1000) {
        setWSStatus({ reconnectAttempt: 0 });
        return;
      }

      // Don't reconnect if workflow is terminal
      const wfStatus = useExecutionStore.getState().workflow?.status;
      if (wfStatus === 'completed' || wfStatus === 'failed') {
        setWSStatus({ reconnectAttempt: 0 });
        return;
      }

      const attempt = useExecutionStore.getState().wsStatus.reconnectAttempt + 1;
      if (attempt > WS_MAX_RECONNECT_ATTEMPTS) {
        setWSStatus({ wsError: 'max_retries', reconnectAttempt: attempt });
        return;
      }

      setWSStatus({ reconnectAttempt: attempt });
      const delay = delayRef.current;
      delayRef.current = Math.min(delay * WS_BACKOFF_MULTIPLIER, WS_MAX_DELAY_MS);
      timerRef.current = setTimeout(connect, delay);
    };

    ws.onerror = () => {};
  }, [workflowId, applySnapshot, applyEvent, setWSStatus]);

  // A network that vanishes mid-run often leaves the socket open with no
  // close event, so the dashboard went on reporting "Connected" while
  // receiving nothing. The server heartbeats every 30s; silence well past
  // that means the connection is gone, so drop it and let the existing
  // backoff reconnect.
  // The browser knows immediately when the network goes away; the
  // heartbeat check below is the backstop for a connection that dies
  // without the browser noticing (a server that stops answering, a
  // silently dropped tunnel).
  useEffect(() => {
    const onOffline = () => {
      setWSStatus({ connected: false });
      try {
        socketRef.current?.close();
      } catch {
        /* already gone */
      }
    };
    const onOnline = () => {
      lastSeenRef.current = Date.now();
      if (!unmountedRef.current) connect();
    };
    window.addEventListener('offline', onOffline);
    window.addEventListener('online', onOnline);
    return () => {
      window.removeEventListener('offline', onOffline);
      window.removeEventListener('online', onOnline);
    };
  }, [connect, setWSStatus]);

  useEffect(() => {
    const check = setInterval(() => {
      if (unmountedRef.current) return;
      if (!useExecutionStore.getState().wsStatus.connected) return;
      if (Date.now() - lastSeenRef.current < WS_STALE_AFTER_MS) return;
      setWSStatus({ connected: false });
      const ws = socketRef.current;
      if (ws) {
        try {
          ws.close();
        } catch {
          /* already gone */
        }
      }
    }, 5000);
    return () => clearInterval(check);
  }, [setWSStatus]);

  useEffect(() => {
    unmountedRef.current = false;
    connect();

    return () => {
      unmountedRef.current = true;
      if (timerRef.current !== null) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
      const ws = socketRef.current;
      if (ws) {
        ws.onclose = null;
        ws.close();
        socketRef.current = null;
      }
      setWSStatus({ connected: false });
    };
  }, [connect, setWSStatus]);
}
