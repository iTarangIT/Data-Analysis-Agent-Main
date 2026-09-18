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
    # The account (`users.id`) that started the run. Not a foreign key, so removing a person
    # never has to rewrite or orphan their organisation's history.
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
    # The stages the run went through and each query it tried, with row counts but never rows.
    # NULL for every run that predates the column.
    trace: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    """A person who signs in. Identity only: what they may do is `role`, read from this row.

    Supabase holds the credentials and the session; this row holds which tenant the person
    belongs to. `auth_user_id` is the Supabase user id (the token's `sub`) and is the only
    thing a request is matched on. Reading the tenant and role from here, rather than from the
    token, means a demotion or a deactivation takes effect on the very next request.
    """

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    # Null for an account from before Supabase, until its owner signs in with that address
    # verified and adopts it.
    auth_user_id: Mapped[str | None] = mapped_column(
        String(36), unique=True, index=True, nullable=True
    )
    # Unique across the service, not per tenant: an address resolves to exactly one account,
    # which is what makes adopting an older account by its email unambiguous.
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    role: Mapped[str] = mapped_column(String(20), default="owner")
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    tenant: Mapped[Tenant] = relationship(back_populates="users")
