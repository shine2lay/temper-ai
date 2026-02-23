"""DBConfigLoader: load workflow/stage/agent configs from DB instead of filesystem.

Used in multi-tenant server mode as a drop-in replacement for ConfigLoader.
"""

import logging
from typing import Any

from sqlmodel import col, select

from temper_ai.storage.database.manager import get_session
from temper_ai.storage.database.models_tenancy import (
    AgentConfigDB,
    StageConfigDB,
    WorkflowConfigDB,
)

logger = logging.getLogger(__name__)

_CONFIG_TYPE_DB_MODEL: dict[str, Any] = {
    "workflow": WorkflowConfigDB,
    "stage": StageConfigDB,
    "agent": AgentConfigDB,
}


def _load_config(tenant_id: str, db_model_cls: Any, name: str) -> dict[str, Any]:
    """Query DB for a config record and return config_data.

    Raises FileNotFoundError if not found.
    """
    with get_session() as session:
        statement = select(db_model_cls).where(
            col(db_model_cls.tenant_id) == tenant_id,
            col(db_model_cls.name) == name,
        )
        record = session.exec(statement).first()

    if record is None:
        label = db_model_cls.__tablename__.rstrip("s")  # e.g. "workflow_config"
        raise FileNotFoundError(f"{label} '{name}' not found for tenant '{tenant_id}'.")
    return dict(record.config_data)


def _list_names(tenant_id: str, db_model_cls: Any) -> list[str]:
    """Return list of config names for a tenant."""
    with get_session() as session:
        statement = select(col(db_model_cls.name)).where(
            col(db_model_cls.tenant_id) == tenant_id
        )
        rows = session.exec(statement).all()
    return list(rows)


class DBConfigLoader:
    """Load workflow/stage/agent configs from DB instead of filesystem.

    Used in multi-tenant server mode.
    """

    def __init__(self, tenant_id: str) -> None:
        self._tenant_id = tenant_id

    def load_workflow(self, name: str) -> dict[str, Any]:
        """Load workflow config from DB by name.

        Raises FileNotFoundError if not found.
        """
        return _load_config(self._tenant_id, WorkflowConfigDB, name)

    def load_stage(self, name: str, validate: bool = True) -> dict[str, Any]:
        """Load stage config from DB by name.

        Raises FileNotFoundError if not found.
        The validate parameter is accepted for interface compatibility.
        """
        return _load_config(self._tenant_id, StageConfigDB, name)

    def load_agent(self, name: str, validate: bool = True) -> dict[str, Any]:
        """Load agent config from DB by name.

        Raises FileNotFoundError if not found.
        The validate parameter is accepted for interface compatibility.
        """
        return _load_config(self._tenant_id, AgentConfigDB, name)

    def list_configs(self, config_type: str) -> list[str]:
        """List config names of the given type for this tenant.

        Returns list of name strings.
        Raises ValueError for unknown config_type.
        """
        db_model_cls = _CONFIG_TYPE_DB_MODEL.get(config_type)
        if db_model_cls is None:
            raise ValueError(
                f"Unknown config_type '{config_type}'. "
                f"Must be one of: {sorted(_CONFIG_TYPE_DB_MODEL)}"
            )
        return _list_names(self._tenant_id, db_model_cls)
