"""Profile registry for lifecycle adaptation.

Merges YAML file profiles with database-stored profiles and matches
profiles to project characteristics.
"""

import logging
from pathlib import Path
from typing import List, Optional

import yaml

from src.lifecycle._schemas import (
    AdaptationRule,
    LifecycleProfile,
    ProjectCharacteristics,
)
from src.lifecycle.store import LifecycleStore

logger = logging.getLogger(__name__)

YAML_GLOB = "*.yaml"


class ProfileRegistry:
    """Registry that merges YAML and DB lifecycle profiles."""

    def __init__(
        self,
        config_dir: Path,
        store: Optional[LifecycleStore] = None,
    ) -> None:
        self._config_dir = config_dir
        self._store = store
        self._yaml_profiles: dict[str, LifecycleProfile] = {}
        self._load_yaml_profiles()

    def _load_yaml_profiles(self) -> None:
        """Load all YAML profile files from config directory."""
        if not self._config_dir.exists():
            logger.info(
                "Lifecycle config dir not found: %s", self._config_dir
            )
            return

        for path in sorted(self._config_dir.glob(YAML_GLOB)):
            try:
                profile = _load_profile_yaml(path)
                if profile is not None:
                    self._yaml_profiles[profile.name] = profile
            except Exception:  # noqa: BLE001 -- skip invalid files
                logger.warning(
                    "Failed to load profile: %s", path, exc_info=True
                )

        logger.info(
            "Loaded %d YAML lifecycle profiles", len(self._yaml_profiles)
        )

    def list_profiles(self) -> List[LifecycleProfile]:
        """List all profiles from YAML and DB sources."""
        profiles = dict(self._yaml_profiles)

        if self._store is not None:
            for record in self._store.list_profiles():
                db_profile = _record_to_profile(record)
                if db_profile.name not in profiles:
                    profiles[db_profile.name] = db_profile

        return list(profiles.values())

    def get_profile(self, name: str) -> Optional[LifecycleProfile]:
        """Get a profile by name. YAML takes priority over DB."""
        if name in self._yaml_profiles:
            return self._yaml_profiles[name]

        if self._store is not None:
            record = self._store.get_profile(name)
            if record is not None:
                return _record_to_profile(record)

        return None

    def match_profiles(
        self,
        characteristics: ProjectCharacteristics,
        workflow_name: str = "",
    ) -> List[LifecycleProfile]:
        """Return profiles matching the given characteristics.

        A profile matches if:
        - It is enabled
        - Its product_types list is empty (matches all) or contains
          the characteristics' product_type
        """
        matched: List[LifecycleProfile] = []

        for profile in self.list_profiles():
            if not profile.enabled:
                continue
            if not _matches_product_type(
                profile, characteristics.product_type
            ):
                continue
            matched.append(profile)

        logger.info(
            "Matched %d profiles for %s (product_type=%s)",
            len(matched),
            workflow_name,
            characteristics.product_type,
        )
        return matched


def _matches_product_type(
    profile: LifecycleProfile, product_type: Optional[str]
) -> bool:
    """Check if a profile matches a product type."""
    if not profile.product_types:
        return True  # Empty = matches all
    if product_type is None:
        return True  # No product type = accept all profiles
    return product_type in profile.product_types


def _load_profile_yaml(path: Path) -> Optional[LifecycleProfile]:
    """Load a single profile from a YAML file."""
    with open(path) as f:
        data = yaml.safe_load(f)

    if not data or "name" not in data:
        return None

    # Parse rules
    raw_rules = data.get("rules", [])
    rules = [AdaptationRule(**r) for r in raw_rules]

    return LifecycleProfile(
        name=data["name"],
        description=data.get("description", ""),
        version=data.get("version", "1.0"),
        product_types=data.get("product_types", []),
        rules=rules,
        enabled=data.get("enabled", True),
        source=data.get("source", "manual"),
        confidence=data.get("confidence", 1.0),
        min_autonomy_level=data.get("min_autonomy_level", 0),
        requires_approval=data.get("requires_approval", True),
    )


def _record_to_profile(record: object) -> LifecycleProfile:
    """Convert a LifecycleProfileRecord to a LifecycleProfile."""
    rules = [AdaptationRule(**r) for r in getattr(record, "rules", [])]
    return LifecycleProfile(
        name=record.name,  # type: ignore[attr-defined]
        description=record.description,  # type: ignore[attr-defined]
        version=record.version,  # type: ignore[attr-defined]
        product_types=record.product_types,  # type: ignore[attr-defined]
        rules=rules,
        enabled=record.enabled,  # type: ignore[attr-defined]
        source=record.source,  # type: ignore[attr-defined]
        confidence=record.confidence,  # type: ignore[attr-defined]
        min_autonomy_level=record.min_autonomy_level,  # type: ignore[attr-defined]
        requires_approval=record.requires_approval,  # type: ignore[attr-defined]
    )
