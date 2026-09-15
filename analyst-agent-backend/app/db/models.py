import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _uuid() -> str:
    return str(uuid.uuid4())


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200))
    plan: Mapped[str] = mapped_column(String(50), default="free")
    daily_token_budget: Mapped[int] = mapped_column(Integer, default=200_000)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    connections: Mapped[list["Connection"]] = relationship(back_populates="tenant")
    users: Mapped[list["User"]] = relationship(back_populates="tenant")


class Connection(Base):
    """A customer data source. `secret_enc` holds the Fernet-encrypted DSN or file sources."""

    __tablename__ = "connections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20))
    secret_enc: Mapped[str] = mapped_column(Text)
    # How the selected tables join, mapped when their structure was last read.
    relationships: Mapped[list | None] = mapped_column(JSON, nullable=True)
    catalog_refreshed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Soft delete, because runs reference this row and they are the ledger we price from.
    # Deleting also blanks secret_enc, so a deleted connection holds no customer credential.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    tenant: Mapped[Tenant] = relationship(back_populates="connections")


class ConnectionTable(Base):
    """One table a connection's source exposes, and whether the agent may use it.

    `definition` and `stats` are held only while the table is selected, and neither is ever a
    row: a definition is columns and keys, and stats are a size bucket and a partition bound.
    """

    __tablename__ = "connection_tables"
    # Also serves every lookup of one connection's tables, so connection_id needs no index.
    __table_args__ = (
        UniqueConstraint("connection_id", "name", name="uq_connection_tables_connection_id_name"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    connection_id: Mapped[str] = mapped_column(ForeignKey("connections.id"))
    name: Mapped[str] = mapped_column(String(200))
    selected: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    definition: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    stats: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class Run(Base):
    """One question answered for one tenant. Doubles as the usage ledger we price from."""

    __tablename__ = "runs"
    # Every read of this table is "one tenant, recent rows": the budget check, the rate limits
    # and the usage rollup. On tenant_id alone they scan the tenant's whole history.
    __table_args__ = (Index("ix_runs_tenant_created", "tenant_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"))
    connection_id: Mapped[str] = mapped_column(ForeignKey("connections.id"))
    thread_id: Mapped[str] = mapped_column(String(100), index=True)
    question: Mapped[str] = mapped_column(Text)
    # The `sub` claim of the token that started the run. Deliberately not a foreign key: the
    # eval harness and the test fixtures hand-mint tokens for users that have no row.
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="running")
    tool: Mapped[str | None] = mapped_column(String(20), nullable=True)
    sql: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The narrative the model wrote. NULL means not recorded, which every run predating this
    # column is, and is why it is not defaulted to the empty string.
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The model the provider actually resolved, which is not always the one configured.
    model: Mapped[str | None] = mapped_column(String(60), nullable=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    rows_returned: Mapped[int] = mapped_column(Integer, default=0)
    # So a past run can be re-rendered without re-running the customer's query.
    chart: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    """A person who signs in. Identity only: what they may do is `role`, read from this row.

    `role` is deliberately absent from the JWT. TenantContext is a frozen two-field dataclass
    that every route already depends on, and reading the role from the database means a
    demotion takes effect at once rather than at the next refresh.
    """

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    # Unique across the service, not per tenant: sign-in takes an email and a password with no
    # tenant selector, so an address has to resolve to exactly one account.
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="owner")
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    tenant: Mapped[Tenant] = relationship(back_populates="users")


class RefreshToken(Base):
    """One row per issued refresh token, so a session can be listed and revoked individually.

    A column on `users` would hold one token, so signing in on a phone would silently sign the
    laptop out, and rotation would have nowhere to record what replaced what.
    """

    __tablename__ = "refresh_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # Every token rotated from one sign-in shares this. Presenting an already-rotated token
    # revokes the whole family in one statement, which is the theft response.
    family_id: Mapped[str] = mapped_column(String(36), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    replaced_by_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # Audit only. Behind the Next.js proxy these record the proxy unless it forwards the
    # originating address, so do not authorise on them.
    user_agent: Mapped[str | None] = mapped_column(String(200), nullable=True)
    ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
