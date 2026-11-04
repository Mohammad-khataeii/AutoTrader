"""Independent migration stream; invoked explicitly, never at application startup."""
from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool
from autotrader.perpetuals.multi.models import Base

url = make_url(context.config.attributes['database_url'])
drivers = {'postgresql+asyncpg':'postgresql+psycopg', 'sqlite+aiosqlite':'sqlite'}
engine = create_engine(url.set(drivername=drivers.get(url.drivername, url.drivername)), poolclass=NullPool)
try:
    with engine.connect() as connection:
        if connection.dialect.name == 'postgresql':
            connection.exec_driver_sql('SELECT pg_advisory_lock(3400498)');connection.commit()
        context.configure(connection=connection, target_metadata=Base.metadata,
                          version_table='paper_multi_schema_version')
        with context.begin_transaction():context.run_migrations()
finally:
    engine.dispose()
