"""Bounded shadow registry; ledgers remain in independent PostgreSQL databases."""
import sqlalchemy as sa
from alembic import op

revision = '0011_v42_shadow_isolation'
down_revision = '0010_v41_ai_quotas'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('shadow_experiments',
        sa.Column('experiment_id',sa.String(64),primary_key=True),
        sa.Column('request_id',sa.String(64),nullable=False,unique=True),
        sa.Column('name',sa.String(128),nullable=False),
        sa.Column('state',sa.String(32),nullable=False),
        sa.Column('database_name',sa.String(63),nullable=False,unique=True),
        sa.Column('manifest_json',sa.Text(),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False))
    op.create_table('shadow_identity',sa.Column('singleton',sa.Integer(),primary_key=True),
        sa.Column('manifest_hash',sa.String(64),nullable=False),sa.Column('manifest_json',sa.Text(),nullable=False),
        sa.CheckConstraint('singleton = 1',name='shadow_identity_singleton'))
    if op.get_bind().dialect.name != 'postgresql':
        return
    # A domain marker may never be retargeted after funding.
    op.execute("""CREATE FUNCTION protect_shadow_identity() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN RAISE EXCEPTION 'Shadow domain identity is immutable'; END $$""")
    op.execute('CREATE TRIGGER shadow_identity_immutable BEFORE UPDATE OR DELETE ON shadow_identity FOR EACH ROW EXECUTE FUNCTION protect_shadow_identity()')
    op.execute("""CREATE FUNCTION protect_shadow_registry() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'Shadow history cannot be deleted'; END IF;
      IF ROW(NEW.experiment_id,NEW.request_id,NEW.name,NEW.database_name,NEW.manifest_json,NEW.created_at)
         IS DISTINCT FROM ROW(OLD.experiment_id,OLD.request_id,OLD.name,OLD.database_name,OLD.manifest_json,OLD.created_at)
      THEN RAISE EXCEPTION 'Shadow experiment configuration is frozen'; END IF;
      RETURN NEW;
    END $$""")
    op.execute('CREATE TRIGGER shadow_registry_immutable BEFORE UPDATE OR DELETE ON shadow_experiments FOR EACH ROW EXECUTE FUNCTION protect_shadow_registry()')
    import os
    if os.getenv('AUTOTRADER_V42_MIGRATION_FAILPOINT') == 'after_ddl':
        raise RuntimeError('Injected V4.2 migration failure after DDL')


def downgrade():
    connection=op.get_bind()
    if connection.scalar(sa.text('SELECT count(*) FROM shadow_experiments')) or connection.scalar(sa.text('SELECT count(*) FROM shadow_identity')):
        raise RuntimeError('Shadow records exist; destructive downgrade forbidden. Retain databases and use compatible rollback images.')
    op.drop_table('shadow_identity')
    if connection.dialect.name == 'postgresql':
        op.execute('DROP FUNCTION protect_shadow_identity()')
    op.drop_table('shadow_experiments')
    if connection.dialect.name == 'postgresql':
        op.execute('DROP FUNCTION protect_shadow_registry()')
