"""Registry for managing persistent event subscriptions."""

import logging
import uuid
from typing import Any, List, Optional

from sqlmodel import select

logger = logging.getLogger(__name__)


class SubscriptionRegistry:
    """Manages persistent event subscriptions stored in the database."""

    def __init__(self, session_factory: Optional[Any] = None) -> None:
        """Initialize the registry.

        Args:
            session_factory: Callable returning a context manager yielding a DB session.
        """
        self._session_factory = session_factory

    def register(
        self,
        agent_id: Optional[str],
        event_type: str,
        handler_ref: Optional[str] = None,
        workflow_to_trigger: Optional[str] = None,
        source_workflow_filter: Optional[str] = None,
        payload_filter: Optional[Any] = None,
    ) -> str:
        """Create and persist an event subscription.

        Returns:
            The new subscription ID.
        """
        from temper_ai.events.models import EventSubscription

        sub_id = str(uuid.uuid4())

        if handler_ref:
            from temper_ai.events._subscription_helpers import _HANDLER_REGISTRY

            if handler_ref not in _HANDLER_REGISTRY:
                logger.warning(
                    "Handler '%s' not yet registered; subscription created but handler won't fire until registered",
                    handler_ref,
                )

        subscription = EventSubscription(
            id=sub_id,
            agent_id=agent_id,
            event_type=event_type,
            handler_ref=handler_ref,
            workflow_to_trigger=workflow_to_trigger,
            source_workflow_filter=source_workflow_filter,
            payload_filter=payload_filter,
            active=True,
        )

        if self._session_factory is None:
            logger.warning("No session_factory; subscription not persisted: %s", sub_id)
            return sub_id

        with self._session_factory() as session:
            session.add(subscription)

        return sub_id

    def unregister(self, subscription_id: str) -> bool:
        """Deactivate a subscription.

        Args:
            subscription_id: ID of the subscription to deactivate.

        Returns:
            True if found and deactivated, False otherwise.
        """
        from temper_ai.events.models import EventSubscription

        if self._session_factory is None:
            return False

        with self._session_factory() as session:
            sub = session.get(EventSubscription, subscription_id)
            if sub is None:
                return False
            sub.active = False
            session.add(sub)

        return True

    def get_for_event(
        self,
        event_type: str,
        source_workflow_id: Optional[str] = None,
    ) -> List[Any]:
        """Get active subscriptions matching an event type and optional source.

        Args:
            event_type: The event type to filter by.
            source_workflow_id: Optional source workflow ID filter.

        Returns:
            List of matching EventSubscription records.
        """
        from temper_ai.events.models import EventSubscription

        if self._session_factory is None:
            return []

        with self._session_factory() as session:
            stmt = select(EventSubscription).where(
                EventSubscription.event_type == event_type,
                EventSubscription.active == True,  # noqa: E712
            )
            if source_workflow_id:
                stmt = stmt.where(
                    EventSubscription.source_workflow_filter == source_workflow_id
                )
            return session.exec(stmt).all()

    def load_active(self) -> List[Any]:
        """Load all currently active subscriptions.

        Returns:
            List of all active EventSubscription records.
        """
        from temper_ai.events.models import EventSubscription

        if self._session_factory is None:
            return []

        with self._session_factory() as session:
            stmt = select(EventSubscription).where(
                EventSubscription.active == True  # noqa: E712
            )
            return session.exec(stmt).all()

    def get_by_id(self, subscription_id: str) -> Optional[Any]:
        """Retrieve a subscription by its ID.

        Args:
            subscription_id: The subscription UUID string.

        Returns:
            EventSubscription or None.
        """
        from temper_ai.events.models import EventSubscription

        if self._session_factory is None:
            return None

        with self._session_factory() as session:
            return session.get(EventSubscription, subscription_id)
