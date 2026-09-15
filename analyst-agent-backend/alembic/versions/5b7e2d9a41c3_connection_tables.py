"""connection tables

Which of a connection's tables the agent may use, and the structure of the ones it may.

`connection_tables` holds a row for every table the source exposes, so the picker can list them
all, but a definition and statistics only while a table is selected. How the selected tables
join sits on the connection, beside the time their structure was last read.

`schema_cache` and `schema_cached_at` are dropped. They were a six-hour cache of every table's
structure, which the catalog replaces, and a cache is not data: the downgrade recreates both
empty and the previous code fills them again on its next run.

Stop any arq worker before upgrading. A worker still running the previous code reads
`schema_cache` and fails on the first run it picks up.

Revision ID: 5b7e2d9a41c3
Revises: c94f73823b3f
Create Date: 2026-09-15 13:00:00.000000

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = '5b7e2d9a41c3'
down_revision: str | None = 'c94f73823b3f'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('connection_tables',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('connection_id', sa.String(length=36), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('selected', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('definition', sa.JSON(), nullable=True),
    sa.Column('stats', sa.JSON(), nullable=True),
    sa.ForeignKeyConstraint(['connection_id'], ['connections.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('connection_id', 'name', name='uq_connection_tables_connection_id_name')
    )
    op.add_column('connections', sa.Column('relationships', sa.JSON(), nullable=True))
    op.add_column('connections', sa.Column('catalog_refreshed_at', sa.DateTime(timezone=True), nullable=True))
    op.drop_column('connections', 'schema_cached_at')
    op.drop_column('connections', 'schema_cache')


def downgrade() -> None:
    op.add_column('connections', sa.Column('schema_cache', sa.JSON(), nullable=True))
    op.add_column('connections', sa.Column('schema_cached_at', sa.DateTime(timezone=True), nullable=True))
    op.drop_column('connections', 'catalog_refreshed_at')
    op.drop_column('connections', 'relationships')
    op.drop_table('connection_tables')
