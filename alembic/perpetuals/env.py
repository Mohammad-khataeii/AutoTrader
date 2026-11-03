"""Migration stream for the perpetuals worker; leaves alembic_version alone."""
from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

from autotrader.perpetuals.models import Base

url = make_url(context.config.attributes["database_url"])
drivers = {"postgresql+asyncpg": "postgresql+psycopg", "sqlite+aiosqlite": "sqlite"}
engine = create_engine(url.set(drivername=drivers[url.drivername]), poolclass=NullPool)
try:
    with engine.connect() as connection:
        if connection.dialect.name == "postgresql":
            connection.exec_driver_sql("SELECT pg_advisory_lock(3400496)")
            connection.commit()
        context.configure(connection=connection, target_metadata=Base.metadata,
                          version_table="paper_perp_schema_version")
        with context.begin_transaction():
            context.run_migrations()
finally:
    engine.dispose()
