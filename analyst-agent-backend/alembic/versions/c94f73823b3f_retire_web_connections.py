"""retire web connections

The dashboard source was removed, so nothing can build a connector for a `kind='web'` row any
more and a run naming one would fail as a 500. Each is retired the way `delete_connection`
retires a row: soft-deleted, so the runs that reference it keep a valid foreign key and history
still names the source, and with its credential blanked, because the dashboard password must
not outlive the feature.

The downgrade is a no-op. A blanked secret cannot be restored, and un-deleting a row with no
credential would only bring back the 500.

Revision ID: c94f73823b3f
Revises: 6df29aa84fda
Create Date: 2026-09-15 12:05:19.746208

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = 'c94f73823b3f'
down_revision: str | None = '6df29aa84fda'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE connections SET deleted_at = now(), secret_enc = '' "
            "WHERE kind = 'web' AND deleted_at IS NULL"
        )
    )


def downgrade() -> None:
    pass
