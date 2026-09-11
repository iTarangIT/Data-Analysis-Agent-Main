"""users and refresh tokens

Real sign-in, plus the three columns the history and connection screens need.

Nothing is backfilled. Every tenant that exists today was conjured by `ensure_tenant` from a
hand-minted JWT and has no person behind it; a migration must not invent an account with a
password nobody can reset. `scripts/create_owner.py` adopts such a tenant instead.

`runs.user_id` is intentionally not a foreign key. The eval harness and the test fixtures sign
tokens for subjects that have no users row, and a constraint would reject their runs.

All four added columns are nullable with no default, so Postgres adds them as metadata only
and does not rewrite either table.

Revision ID: 6df29aa84fda
Revises: 0fe15064cf2d
Create Date: 2026-09-11 11:59:52.561711

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = '6df29aa84fda'
down_revision: str | None = '0fe15064cf2d'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('users',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('tenant_id', sa.String(length=36), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('role', sa.String(length=20), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)
    op.create_index(op.f('ix_users_tenant_id'), 'users', ['tenant_id'], unique=False)
    op.create_table('refresh_tokens',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('family_id', sa.String(length=36), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('issued_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('replaced_by_id', sa.String(length=36), nullable=True),
    sa.Column('user_agent', sa.String(length=200), nullable=True),
    sa.Column('ip', sa.String(length=45), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_refresh_tokens_expires_at'), 'refresh_tokens', ['expires_at'], unique=False)
    op.create_index(op.f('ix_refresh_tokens_family_id'), 'refresh_tokens', ['family_id'], unique=False)
    op.create_index(op.f('ix_refresh_tokens_token_hash'), 'refresh_tokens', ['token_hash'], unique=True)
    op.create_index(op.f('ix_refresh_tokens_user_id'), 'refresh_tokens', ['user_id'], unique=False)
    op.add_column('connections', sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('runs', sa.Column('user_id', sa.String(length=36), nullable=True))
    op.add_column('runs', sa.Column('answer', sa.Text(), nullable=True))
    op.create_index(op.f('ix_runs_user_id'), 'runs', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_runs_user_id'), table_name='runs')
    op.drop_column('runs', 'answer')
    op.drop_column('runs', 'user_id')
    op.drop_column('connections', 'deleted_at')
    op.drop_index(op.f('ix_refresh_tokens_user_id'), table_name='refresh_tokens')
    op.drop_index(op.f('ix_refresh_tokens_token_hash'), table_name='refresh_tokens')
    op.drop_index(op.f('ix_refresh_tokens_family_id'), table_name='refresh_tokens')
    op.drop_index(op.f('ix_refresh_tokens_expires_at'), table_name='refresh_tokens')
    op.drop_table('refresh_tokens')
    op.drop_index(op.f('ix_users_tenant_id'), table_name='users')
    op.drop_index(op.f('ix_users_email'), table_name='users')
    op.drop_table('users')
