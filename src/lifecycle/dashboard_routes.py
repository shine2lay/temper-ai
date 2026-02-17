"""Dashboard API routes for lifecycle adaptation.

Provides 4 endpoints:
- GET /api/lifecycle/adaptations - List recent adaptations
- GET /api/lifecycle/profiles - List all profiles
- GET /api/lifecycle/experiments - List experiment results
- GET /api/lifecycle/metrics - Get lifecycle metrics summary
"""

import logging
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

DEFAULT_LIFECYCLE_DB = "sqlite:///./lifecycle.db"
DEFAULT_LIFECYCLE_CONFIG_DIR = "configs/lifecycle"
DEFAULT_LIMIT = 50
_METHOD_GET = "GET"


def get_lifecycle_routes() -> List[Dict[str, Any]]:
    """Return route definitions for lifecycle dashboard endpoints."""
    return [
        {
            "path": "/api/lifecycle/adaptations",
            "method": _METHOD_GET,
            "handler": handle_list_adaptations,
        },
        {
            "path": "/api/lifecycle/profiles",
            "method": _METHOD_GET,
            "handler": handle_list_profiles,
        },
        {
            "path": "/api/lifecycle/experiments",
            "method": _METHOD_GET,
            "handler": handle_list_experiments,
        },
        {
            "path": "/api/lifecycle/metrics",
            "method": _METHOD_GET,
            "handler": handle_metrics,
        },
    ]


def handle_list_adaptations(
    db_url: str = DEFAULT_LIFECYCLE_DB,
    limit: int = DEFAULT_LIMIT,
) -> Dict[str, Any]:
    """List recent lifecycle adaptations."""
    try:
        from src.lifecycle.store import LifecycleStore

        store = LifecycleStore(database_url=db_url)
        adaptations = store.list_adaptations(limit=limit)
        return {
            "adaptations": [
                {
                    "id": a.id,
                    "workflow_id": a.workflow_id,
                    "profile_name": a.profile_name,
                    "rules_applied": a.rules_applied,
                    "stages_original": a.stages_original,
                    "stages_adapted": a.stages_adapted,
                    "created_at": str(a.created_at),
                }
                for a in adaptations
            ]
        }
    except Exception as exc:  # noqa: BLE001 -- API error handling
        logger.warning("Failed to list adaptations: %s", exc)
        return {"adaptations": [], "error": str(exc)}


def handle_list_profiles(
    db_url: str = DEFAULT_LIFECYCLE_DB,
    config_dir: str = DEFAULT_LIFECYCLE_CONFIG_DIR,
) -> Dict[str, Any]:
    """List all lifecycle profiles."""
    try:
        from src.lifecycle.profiles import ProfileRegistry
        from src.lifecycle.store import LifecycleStore

        store = LifecycleStore(database_url=db_url)
        registry = ProfileRegistry(
            config_dir=Path(config_dir), store=store
        )
        profiles = registry.list_profiles()
        return {
            "profiles": [
                {
                    "name": p.name,
                    "description": p.description,
                    "source": p.source,
                    "enabled": p.enabled,
                    "rules_count": len(p.rules),
                    "min_autonomy_level": p.min_autonomy_level,
                    "confidence": p.confidence,
                }
                for p in profiles
            ]
        }
    except Exception as exc:  # noqa: BLE001 -- API error handling
        logger.warning("Failed to list profiles: %s", exc)
        return {"profiles": [], "error": str(exc)}


def handle_list_experiments(
    db_url: str = DEFAULT_LIFECYCLE_DB,
) -> Dict[str, Any]:
    """List lifecycle experiment results."""
    try:
        from src.lifecycle.store import LifecycleStore

        store = LifecycleStore(database_url=db_url)
        adaptations = store.list_adaptations(limit=DEFAULT_LIMIT)
        experiments: Dict[str, list] = {}
        for a in adaptations:
            if a.experiment_id:
                if a.experiment_id not in experiments:
                    experiments[a.experiment_id] = []
                experiments[a.experiment_id].append(a.experiment_variant)

        return {
            "experiments": [
                {"id": eid, "variants": variants}
                for eid, variants in experiments.items()
            ]
        }
    except Exception as exc:  # noqa: BLE001 -- API error handling
        logger.warning("Failed to list experiments: %s", exc)
        return {"experiments": [], "error": str(exc)}


def handle_metrics(
    db_url: str = DEFAULT_LIFECYCLE_DB,
) -> Dict[str, Any]:
    """Get lifecycle adaptation metrics summary."""
    try:
        from src.lifecycle.store import LifecycleStore

        store = LifecycleStore(database_url=db_url)
        adaptations = store.list_adaptations()
        profiles = store.list_profiles()

        profile_usage: Dict[str, int] = {}
        for a in adaptations:
            profile_usage[a.profile_name] = (
                profile_usage.get(a.profile_name, 0) + 1
            )

        return {
            "total_adaptations": len(adaptations),
            "total_profiles": len(profiles),
            "profile_usage": profile_usage,
        }
    except Exception as exc:  # noqa: BLE001 -- API error handling
        logger.warning("Failed to get metrics: %s", exc)
        return {"error": str(exc)}
