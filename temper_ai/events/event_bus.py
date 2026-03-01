"""Persistent event bus wrapping ObservabilityEventBus via composition."""

import logging
import threading
from datetime import datetime
from typing import Any

from temper_ai.events._bus_helpers import (
    convert_to_observability_event,
    evaluate_subscriptions,
    persist_event,
)
from temper_ai.events._cross_workflow import CrossWorkflowTrigger
from temper_ai.events._subscription_helpers import register_handler, resolve_handler
from temper_ai.events.constants import (
    DEFAULT_TRIGGER_TIMEOUT_SECONDS,
    MAX_SUBSCRIPTION_HANDLERS,
)
from temper_ai.events.subscription_registry import SubscriptionRegistry

logger = logging.getLogger(__name__)


class TemperEventBus:
    """Persistent event bus with cross-workflow triggers.

    Wraps ObservabilityEventBus via composition.
    Events can be persisted to the database and subscriptions are
    stored for durable, cross-restart delivery.
    """

    def __init__(
        self,
        observability_bus: Any | None = None,
        session_factory: Any | None = None,
        persist: bool = True,
    ) -> None:
        """Initialize the TemperEventBus.

        Args:
            observability_bus: Optional ObservabilityEventBus. Created if None.
            session_factory: Callable returning a session context manager.
            persist: Whether to persist events to the database.
        """
        if observability_bus is None:
            from temper_ai.observability.event_bus import ObservabilityEventBus

            observability_bus = ObservabilityEventBus()

        self._obs_bus = observability_bus
        self._session_factory = session_factory
        self._persist = persist
        self._registry = SubscriptionRegistry(session_factory=session_factory)
        self._trigger = CrossWorkflowTrigger()
        self._wait_events: dict[str, threading.Event] = {}
        self._execution_service: Any | None = None
        self._wait_payloads: dict[str, dict[str, Any] | None] = {}
        self._wait_lock = threading.Lock()

    def set_execution_service(self, execution_service: Any) -> None:
        """Inject execution service into the cross-workflow trigger.

        Two-phase init to break circular dependency: event_bus creates
        trigger, but execution_service needs event_bus.
        """
        self._execution_service = execution_service
        self._trigger = CrossWorkflowTrigger(execution_service=execution_service)

    def subscribe(self, callback: Any) -> str:
        """Subscribe a callback to the inner ObservabilityEventBus.

        Delegates to the wrapped ObservabilityEventBus so that callers
        (e.g. WorkflowRunner, DashboardDataService) can subscribe
        regardless of whether they hold a TemperEventBus or a raw
        ObservabilityEventBus.

        Args:
            callback: Callable invoked for each ObservabilityEvent.

        Returns:
            Subscription ID string for later unsubscribe.
        """
        return self._obs_bus.subscribe(callback)

    def unsubscribe(self, subscription_id: str) -> None:
        """Unsubscribe a callback from the inner ObservabilityEventBus.

        Args:
            subscription_id: ID returned by subscribe().
        """
        self._obs_bus.unsubscribe(subscription_id)

    def emit(
        self,
        event_type: Any,
        payload: dict[str, Any] | None = None,
        source_workflow_id: str | None = None,
        source_stage_name: str | None = None,
        agent_id: str | None = None,
    ) -> None:
        """Emit an event, persisting and forwarding to subscribers.

        Accepts either decomposed arguments (event_type string + payload dict)
        or a single ObservabilityEvent object (as emitted by ExecutionTracker).

        Args:
            event_type: The event type string, or an ObservabilityEvent object.
            payload: Optional event payload dict.
            source_workflow_id: Originating workflow ID.
            source_stage_name: Originating stage name.
            agent_id: Originating agent ID.
        """
        # Handle ObservabilityEvent objects passed directly by ExecutionTracker
        if hasattr(event_type, "event_type") and hasattr(event_type, "data"):
            obs_event = event_type
            self._obs_bus.emit(obs_event)
            evt_str = obs_event.event_type
            self._evaluate_subscriptions(
                evt_str, obs_event.data, getattr(obs_event, "workflow_id", None)
            )
            self._notify_waiters(
                evt_str, obs_event.data, getattr(obs_event, "workflow_id", None)
            )
            return

        if self._persist and self._session_factory is not None:
            self._persist_and_emit(
                event_type, payload, source_workflow_id, source_stage_name, agent_id
            )
        else:
            self._forward_to_obs_bus(event_type, payload, source_workflow_id, agent_id)
            self._evaluate_subscriptions(event_type, payload, source_workflow_id)

        self._notify_waiters(event_type, payload, source_workflow_id)

    def subscribe_persistent(
        self,
        agent_id: str | None,
        event_type: str,
        handler_ref: str | None = None,
        workflow_to_trigger: str | None = None,
        source_workflow_filter: str | None = None,
        payload_filter: dict[str, Any] | None = None,
    ) -> str:
        """Register a persistent subscription stored in the database.

        Args:
            agent_id: Agent registering the subscription.
            event_type: Event type to subscribe to.
            handler_ref: Dotted module path to handler callable.
            workflow_to_trigger: Workflow path to trigger on event.
            source_workflow_filter: Only receive events from this workflow.
            payload_filter: Dict of key/value pairs that must match the payload.

        Returns:
            Subscription ID string.
        """
        return self._registry.register(
            agent_id=agent_id,
            event_type=event_type,
            handler_ref=handler_ref,
            workflow_to_trigger=workflow_to_trigger,
            source_workflow_filter=source_workflow_filter,
            payload_filter=payload_filter,
        )

    def wait_for_event(
        self,
        event_type: str,
        timeout_seconds: int = DEFAULT_TRIGGER_TIMEOUT_SECONDS,
        source_workflow_filter: str | None = None,
    ) -> dict[str, Any] | None:
        """Block until a matching event is emitted or timeout occurs.

        Args:
            event_type: Event type to wait for.
            timeout_seconds: Maximum wait time.
            source_workflow_filter: Optional source workflow ID to filter on.

        Returns:
            Event payload dict if event received, None on timeout.
        """
        wait_key = self._build_wait_key(event_type, source_workflow_filter)
        event_flag = threading.Event()
        with self._wait_lock:
            self._wait_events[wait_key] = event_flag
            self._wait_payloads[wait_key] = None

        try:
            triggered = event_flag.wait(timeout=timeout_seconds)
            if not triggered:
                return None
            with self._wait_lock:
                return self._wait_payloads.get(wait_key)
        finally:
            with self._wait_lock:
                self._wait_events.pop(wait_key, None)
                self._wait_payloads.pop(wait_key, None)

    def replay_events(
        self,
        event_type: str | None = None,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[Any]:
        """Query past events from the database.

        Args:
            event_type: Filter by event type.
            since: Return events after this timestamp.
            limit: Maximum number of events to return.

        Returns:
            List of EventLog records.
        """
        if self._session_factory is None:
            return []

        from sqlmodel import col, select

        from temper_ai.events.models import EventLog

        with self._session_factory() as session:
            stmt = select(EventLog)
            if event_type:
                stmt = stmt.where(EventLog.event_type == event_type)
            if since:
                stmt = stmt.where(EventLog.timestamp >= since)
            stmt = stmt.order_by(col(EventLog.timestamp).desc()).limit(limit)
            return session.exec(stmt).all()

    # -- Private helpers --------------------------------------------------------

    def _persist_and_emit(
        self,
        event_type: str,
        payload: dict[str, Any] | None,
        source_workflow_id: str | None,
        source_stage_name: str | None,
        agent_id: str | None,
    ) -> None:
        """Persist event to DB then forward to observability bus."""
        try:
            with self._session_factory() as session:  # type: ignore[misc]
                persist_event(
                    session,
                    event_type,
                    payload,
                    source_workflow_id,
                    source_stage_name,
                    agent_id,
                )
                subs = evaluate_subscriptions(
                    session, event_type, payload, source_workflow_id
                )
        except Exception as exc:
            logger.warning("Event persistence failed for %s: %s", event_type, exc)
            subs = []

        self._forward_to_obs_bus(event_type, payload, source_workflow_id, agent_id)
        self._dispatch_subscriptions(subs, event_type, payload, source_workflow_id)

    def _forward_to_obs_bus(
        self,
        event_type: str,
        payload: dict[str, Any] | None,
        source_workflow_id: str | None,
        agent_id: str | None,
    ) -> None:
        """Convert and forward event to ObservabilityEventBus."""
        obs_event = convert_to_observability_event(
            event_type, payload, source_workflow_id, agent_id
        )
        try:
            self._obs_bus.emit(obs_event)
        except Exception as exc:
            logger.warning("ObservabilityEventBus emit failed: %s", exc)

    def _evaluate_subscriptions(
        self,
        event_type: str,
        payload: dict[str, Any] | None,
        source_workflow_id: str | None,
    ) -> None:
        """Evaluate subscriptions for the non-persist emit path."""
        if self._session_factory is None:
            return
        try:
            with self._session_factory() as session:
                subs = evaluate_subscriptions(
                    session, event_type, payload, source_workflow_id
                )
            self._dispatch_subscriptions(subs, event_type, payload, source_workflow_id)
        except Exception as exc:
            logger.warning("Subscription evaluation failed: %s", exc)

    def _dispatch_subscriptions(
        self,
        subs: list[Any],
        event_type: str,
        payload: dict[str, Any] | None,
        source_workflow_id: str | None,
    ) -> None:
        """Dispatch event to matching subscriptions (up to max)."""
        for sub in subs[:MAX_SUBSCRIPTION_HANDLERS]:
            if sub.handler_ref:
                handler = resolve_handler(sub.handler_ref)
                if handler is not None:
                    try:
                        handler(event_type, payload)
                    except Exception as exc:
                        logger.warning(
                            "Subscription handler error (%s): %s", sub.id, exc
                        )
            if sub.workflow_to_trigger:
                self._trigger.trigger(sub.workflow_to_trigger, inputs=payload or {})

    def _notify_waiters(
        self,
        event_type: str,
        payload: dict[str, Any] | None,
        source_workflow_id: str | None,
    ) -> None:
        """Signal any threads blocked in wait_for_event."""
        with self._wait_lock:
            keys_to_notify = [
                self._build_wait_key(event_type, None),
                self._build_wait_key(event_type, source_workflow_id),
            ]
            for key in keys_to_notify:
                if key in self._wait_events:
                    self._wait_payloads[key] = payload
                    self._wait_events[key].set()

    @staticmethod
    def _build_wait_key(event_type: str, source_workflow_filter: str | None) -> str:
        """Build a unique key for the wait_for_event lookup."""
        return f"{event_type}::{source_workflow_filter or ''}"


# Module-level re-export so callers can use temper_ai.events.event_bus.register_handler
__all__ = ["TemperEventBus", "register_handler"]
