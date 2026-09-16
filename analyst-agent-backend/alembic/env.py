from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context
from app.agent.store import owned_by_alembic
from app.config import get_settings
from app.db.models import Base

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", str(get_settings().app_db_url))
target_metadata = Base.metadata

def include_object(object_, name, type_, reflected, compare_to):
    """The agent's long-term memory lives in this database but is created by LangGraph, not by
    us. Without this, autogenerate writes a migration dropping it."""
    return owned_by_alembic(name, type_)


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
