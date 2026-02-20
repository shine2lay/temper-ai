"""Event bus module for persistent events and subscriptions."""


def __getattr__(name):  # type: ignore[no-untyped-def]
    if name == "TemperEventBus":
        from temper_ai.events.event_bus import TemperEventBus

        return TemperEventBus
    if name == "SubscriptionRegistry":
        from temper_ai.events.subscription_registry import SubscriptionRegistry

        return SubscriptionRegistry
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
