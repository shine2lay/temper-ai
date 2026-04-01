import { useEffect, useRef, useCallback } from 'react';
import { useExecutionStore } from '@/store/executionStore';
import type { WSMessage } from '@/types';
import {
  WS_INITIAL_DELAY_MS,
  WS_MAX_DELAY_MS,
  WS_BACKOFF_MULTIPLIER,
  WS_MAX_RECONNECT_ATTEMPTS,
  WS_CLOSE_WORKFLOW_TERMINAL,
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
      setWSStatus({ connected: true, reconnectAttempt: 0, wsError: null });
    };

    ws.onmessage = (event) => {
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
