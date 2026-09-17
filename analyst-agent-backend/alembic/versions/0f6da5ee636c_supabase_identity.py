"""supabase identity

Supabase Auth now holds every credential and session. A user row keeps only which tenant a
person belongs to, matched on `auth_user_id`, the Supabase user id.

`password_hash` and `refresh_tokens` are dropped: no code reads them any more, and keeping a
password hash nobody can use is a liability, not a record. Existing users keep their `id`, so
their runs stay theirs; each is adopted by the first Supabase sign-in that proves the same
email address.

The downgrade recreates both empty and `password_hash` nullable. Nobody can sign in to the
previous code with a password again, which is the honest outcome of going back.

Revision ID: 0f6da5ee636c
Revises: 5b7e2d9a41c3
Create Date: 2026-09-17 18:00:00.000000

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = '0f6da5ee636c'
down_revision: str | None = '5b7e2d9a41c3'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('users', sa.Column('auth_user_id', sa.String(length=36), nullable=True))
    op.create_index(op.f('ix_users_auth_user_id'), 'users', ['auth_user_id'], unique=True)
    op.drop_column('users', 'password_hash')

    op.drop_index(op.f('ix_refresh_tokens_user_id'), table_name='refresh_tokens')
    op.drop_index(op.f('ix_refresh_tokens_token_hash'), table_name='refresh_tokens')
    op.drop_index(op.f('ix_refresh_tokens_family_id'), table_name='refresh_tokens')
    op.drop_index(op.f('ix_refresh_tokens_expires_at'), table_name='refresh_tokens')
    op.drop_table('refresh_tokens')


def downgrade() -> None:
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

    op.add_column('users', sa.Column('password_hash', sa.String(length=255), nullable=True))
    op.drop_index(op.f('ix_users_auth_user_id'), table_name='users')
    op.drop_column('users', 'auth_user_id')
