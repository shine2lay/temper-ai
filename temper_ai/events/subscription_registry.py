"""Registry for managing persistent event subscriptions."""

import logging
import uuid
from typing import Any

logger = logging.getLogger(__name__)


class SubscriptionRegistry:
    """Manages persistent event subscriptions stored in the database."""

    def __init__(self, session_factory: Any | None = None) -> None:
        """Initialize the registry.

        Args:
            session_factory: Callable returning a context manager yielding a DB session.
        """
        self._session_factory = session_factory

    def register(
        self,
        agent_id: str | None,
        event_type: str,
        handler_ref: str | None = None,
        workflow_to_trigger: str | None = None,
        source_workflow_filter: str | None = None,
        payload_filter: Any | None = None,
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
