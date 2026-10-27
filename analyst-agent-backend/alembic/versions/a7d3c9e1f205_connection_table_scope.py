"""connection table scope

A database connection no longer needs a person to choose its tables: every table its login can
read is in play, and each question is given the ones it needs. Existing database connections
move to that; file connections keep the picker.

Revision ID: a7d3c9e1f205
Revises: c41908122766
Create Date: 2026-10-27 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = 'a7d3c9e1f205'
down_revision: str | None = 'c41908122766'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "connections",
        sa.Column("table_scope", sa.String(length=10), server_default="selected", nullable=False),
    )
    op.execute("UPDATE connections SET table_scope = 'all' WHERE kind = 'postgres'")


def downgrade() -> None:
    op.drop_column("connections", "table_scope")
