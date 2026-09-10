import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text, func
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


class Connection(Base):
    """A customer data source. `secret_enc` holds the Fernet-encrypted DSN or login JSON."""

    __tablename__ = "connections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20))
    secret_enc: Mapped[str] = mapped_column(Text)
    schema_cache: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    schema_cached_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    tenant: Mapped[Tenant] = relationship(back_populates="connections")


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
    status: Mapped[str] = mapped_column(String(20), default="running")
    tool: Mapped[str | None] = mapped_column(String(20), nullable=True)
    sql: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The model the provider actually resolved, which is not always the one configured.
    model: Mapped[str | None] = mapped_column(String(60), nullable=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    rows_returned: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
