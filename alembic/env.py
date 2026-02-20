import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# Ensure project root is on sys.path for model imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Import all SQLModel models so metadata is populated
from sqlmodel import SQLModel
import temper_ai.observability.models  # noqa: F401
import temper_ai.experimentation.models  # noqa: F401
import temper_ai.interfaces.server.models  # noqa: F401
import temper_ai.learning.models  # noqa: F401
import temper_ai.lifecycle.models  # noqa: F401
import temper_ai.goals.models  # noqa: F401
import temper_ai.portfolio.models  # noqa: F401
import temper_ai.safety.autonomy.models  # noqa: F401
import temper_ai.memory.adapters.pg_adapter  # noqa: F401

# M9 models
from temper_ai.storage.database.models_registry import AgentRegistryDB  # noqa: F401
from temper_ai.events.models import EventLog, EventSubscription  # noqa: F401

target_metadata = SQLModel.metadata

# Allow URL override via -x sqlalchemy.url=... or TEMPER_DATABASE_URL env var
url_override = context.get_x_argument(as_dictionary=True).get("sqlalchemy.url")
if not url_override:
    url_override = os.environ.get("TEMPER_DATABASE_URL")
if url_override:
    config.set_main_option("sqlalchemy.url", url_override)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
