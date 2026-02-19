import { useEffect, useRef, useCallback } from 'react';
import { useExecutionStore } from '@/store/executionStore';
import type { WSMessage } from '@/types';
import {
  WS_INITIAL_DELAY_MS,
  WS_MAX_DELAY_MS,
  WS_BACKOFF_MULTIPLIER,
} from '@/lib/constants';

/**
 * WebSocket hook that connects to the workflow event stream.
 * Handles snapshot/event/heartbeat messages and reconnects with
 * exponential backoff on disconnection.
 */
export function useWorkflowWebSocket(workflowId: string | undefined): void {
  const socketRef = useRef<WebSocket | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const delayRef = useRef(WS_INITIAL_DELAY_MS);
  const unmountedRef = useRef(false);

  const applySnapshot = useExecutionStore((s) => s.applySnapshot);
  const applyEvent = useExecutionStore((s) => s.applyEvent);
  const setWSStatus = useExecutionStore((s) => s.setWSStatus);

  const connect = useCallback(() => {
    if (unmountedRef.current || !workflowId) return;

    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = `${protocol}//${location.host}/ws/${workflowId}`;
    const ws = new WebSocket(url);
    socketRef.current = ws;

    ws.onopen = () => {
      delayRef.current = WS_INITIAL_DELAY_MS;
      setWSStatus({ connected: true, reconnectAttempt: 0 });
    };

    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data) as WSMessage;

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
