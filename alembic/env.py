from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from autotrader.persistence.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _migration_url() -> str:
    x_args = context.get_x_argument(as_dictionary=True)
    url = x_args.get("dburl") or os.getenv("DATABASE_URL") or config.get_main_option("sqlalchemy.url")
    return url.replace("sqlite+aiosqlite://", "sqlite://").replace("postgresql+asyncpg://", "postgresql+psycopg://")


def run_migrations_offline() -> None:
    url = _migration_url()
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _migration_url()
    connectable = engine_from_config(configuration, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        if connection.dialect.name == "postgresql":
            # Serialize API/worker startup migrations using a session advisory lock.
            connection.exec_driver_sql("SELECT pg_advisory_lock(3400000)")
            connection.commit()
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
