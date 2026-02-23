import { useEffect, useRef, useCallback } from 'react';
import { useExecutionStore } from '@/store/executionStore';
import { getApiKey, authFetch } from '@/lib/authFetch';
import type { WSMessage } from '@/types';
import {
  WS_INITIAL_DELAY_MS,
  WS_MAX_DELAY_MS,
  WS_BACKOFF_MULTIPLIER,
} from '@/lib/constants';

/**
 * Fetch a short-lived WebSocket ticket from the server.
 * Returns the ticket string, or null if no API key is configured
 * or the request fails.
 */
async function fetchWsTicket(): Promise<string | null> {
  const apiKey = getApiKey();
  if (!apiKey) return null;
  try {
    const res = await authFetch('/api/auth/ws-ticket', { method: 'POST' });
    if (!res.ok) return null;
    const data = await res.json() as { ticket?: string };
    return data.ticket ?? null;
  } catch {
    return null;
  }
}

/**
 * WebSocket hook that connects to the workflow event stream.
 * Handles snapshot/event/heartbeat messages and reconnects with
 * exponential backoff on disconnection.
 *
 * Uses short-lived tickets (/api/auth/ws-ticket) instead of sending
 * API keys directly in the WebSocket query string to prevent key
 * leakage into server logs, browser history, and proxy logs.
 */
export function useWorkflowWebSocket(workflowId: string | undefined): void {
  const socketRef = useRef<WebSocket | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const delayRef = useRef(WS_INITIAL_DELAY_MS);
  const unmountedRef = useRef(false);

  const applySnapshot = useExecutionStore((s) => s.applySnapshot);
  const applyEvent = useExecutionStore((s) => s.applyEvent);
  const setWSStatus = useExecutionStore((s) => s.setWSStatus);

  const connect = useCallback(async () => {
    if (unmountedRef.current || !workflowId) return;

    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    let url = `${protocol}//${location.host}/ws/${workflowId}`;
    const ticket = await fetchWsTicket();
    if (ticket) url += `?ticket=${encodeURIComponent(ticket)}`;
    const ws = new WebSocket(url);
    socketRef.current = ws;

    ws.onopen = () => {
      delayRef.current = WS_INITIAL_DELAY_MS;
      setWSStatus({ connected: true, reconnectAttempt: 0 });
    };

    ws.onmessage = (event) => {
      let msg: WSMessage;
      try {
        msg = JSON.parse(event.data) as WSMessage;
      } catch {
        return; // silently ignore malformed messages
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

    ws.onclose = () => {
      if (unmountedRef.current) return;

      setWSStatus({ connected: false });
      setWSStatus({
        reconnectAttempt:
          useExecutionStore.getState().wsStatus.reconnectAttempt + 1,
      });

      // Schedule reconnect with exponential backoff
      const delay = delayRef.current;
      delayRef.current = Math.min(
        delay * WS_BACKOFF_MULTIPLIER,
        WS_MAX_DELAY_MS,
      );
      timerRef.current = setTimeout(connect, delay);
    };

    ws.onerror = () => {
      // onclose fires after onerror; let onclose handle reconnect
    };
  }, [workflowId, applySnapshot, applyEvent, setWSStatus]);

  useEffect(() => {
    unmountedRef.current = false;
    connect();

    return () => {
      unmountedRef.current = true;

      // Cancel pending reconnect
      if (timerRef.current !== null) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }

      // Null out onclose before closing to prevent zombie reconnects
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
