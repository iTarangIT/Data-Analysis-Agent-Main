"""Which of a connection's tables the agent may use, and what is known of their structure.

Every table the source exposes gets a row, so the picker can list them all. A definition and
statistics are held only while a table is selected, and neither is ever a row of that table.

A source's first listing chooses every table when there are no more than the cap allows, which
keeps a small database or a spreadsheet answering without a visit to the picker. Past the cap
nothing is chosen, and a run is refused until a person has chosen.
"""

import asyncio
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.catalog.relationships import map_relationships
from app.catalog.types import Catalog, CatalogTable, Relationship, TableDef
from app.config import get_settings
from app.connectors.base import SqlConnector
from app.connectors.registry import connector_for
from app.db.models import Connection, ConnectionTable
from app.logging import log
from app.services.errors import DomainError, SourceUnavailable

# Structure rarely changes, but what a table holds does, and the model reads both: a table that
# emptied or a partition that stopped filling must reach the prompt without anyone refreshing.
REFRESH_AFTER = timedelta(hours=6)


def _rows(db: Session, connection_id: str) -> list[ConnectionTable]:
    return list(
        db.scalars(
            select(ConnectionTable)
            .where(ConnectionTable.connection_id == connection_id)
            .order_by(ConnectionTable.name)
        )
    )


def _add(db: Session, connection_id: str, names: list[str], selected: bool) -> None:
    if not names:
        return
    # Two runs can be first to reach a connection at the same moment. The unique key lets both
    # proceed rather than failing one of them.
    db.execute(
        insert(ConnectionTable)
        .values(
            [
                {
                    "id": str(uuid.uuid4()),
                    "connection_id": connection_id,
                    "name": n,
                    "selected": selected,
                }
                for n in names
            ]
        )
        .on_conflict_do_nothing(index_elements=["connection_id", "name"])
    )


def _first_listing(db: Session, conn: Connection, names: list[str]) -> list[ConnectionTable]:
    _add(db, conn.id, names, selected=len(names) <= get_settings().max_agent_tables)
    return _rows(db, conn.id)


@contextmanager
def _reachable(conn: Connection) -> Iterator[None]:
    """Turn a source that is down into an answer rather than a crash.

    The driver's message names host, port and user, so it is logged and a plain sentence goes
    back instead. Without this a dropped tunnel reaches the browser as a 500, and the picker
    shows a runtime error where it should show a line saying to try again.
    """
    try:
        yield
    except DomainError:
        raise
    except Exception as e:
        log.warning("tables.source_unreachable", connection_id=conn.id, error=str(e))
        raise SourceUnavailable(
            "could not reach that database just now - check it is running and try again"
        ) from e


def _introspect(
    connector: SqlConnector, names: list[str]
) -> tuple[list[TableDef], dict[str, dict[str, Any]]]:
    if not names:
        return [], {}
    return connector.read_tables(names), connector.table_stats(names)


def _apply(
    conn: Connection,
    selected: list[ConnectionTable],
    definitions: list[TableDef],
    stats: dict[str, dict[str, Any]],
) -> None:
    """Record what was read. A selected table the source no longer has is left without a
    definition, which keeps it out of every run until a refresh removes it."""
    read = {d.name: d for d in definitions}
    for row in selected:
        definition = read.get(row.name)
        row.definition = definition.model_dump() if definition else None
        row.stats = stats.get(row.name) if definition else None
    conn.relationships = [r.model_dump() for r in map_relationships(definitions)]
    conn.catalog_refreshed_at = datetime.now(UTC)


def ensure_listed(db: Session, conn: Connection) -> None:
    """List a source's tables the first time they are asked about. A no-op after that."""
    if db.scalar(select(ConnectionTable.id).where(ConnectionTable.connection_id == conn.id)):
        return
    connector = connector_for(conn)
    with _reachable(conn):
        selected = [r for r in _first_listing(db, conn, connector.list_tables()) if r.selected]
        _apply(conn, selected, *_introspect(connector, [r.name for r in selected]))
    db.commit()


def view(db: Session, conn: Connection) -> dict[str, Any]:
    files = (
        {p["table"]: f.name for f in conn.files if f.status == "ready" for p in f.parts}
        if conn.kind == "file"
        else {}
    )
    return {
        "max_selected": get_settings().max_agent_tables,
        "refreshed_at": conn.catalog_refreshed_at,
        "tables": [
            {
                "name": r.name,
                "file": files.get(r.name),
                "selected": r.selected,
                "definition": r.definition,
                "stats": r.stats,
            }
            for r in _rows(db, conn.id)
        ],
        "relationships": conn.relationships or [],
    }


def save_selection(db: Session, conn: Connection, names: list[str]) -> dict[str, Any]:
    ensure_listed(db, conn)
    rows = _rows(db, conn.id)
    wanted = set(names)

    unknown = sorted(wanted - {r.name for r in rows})
    if unknown:
        raise DomainError(f"this connection has no table named {', '.join(unknown)}")
    cap = get_settings().max_agent_tables
    if len(wanted) > cap:
        raise DomainError(f"choose at most {cap} tables")

    for row in rows:
        row.selected = row.name in wanted
        if not row.selected:
            row.definition = row.stats = None
    selected = [r for r in rows if r.selected]
    with _reachable(conn):
        _apply(conn, selected, *_introspect(connector_for(conn), [r.name for r in selected]))
    db.commit()
    return view(db, conn)


def refresh(db: Session, conn: Connection) -> dict[str, Any]:
    """Re-list the source and re-read the selection. A new table arrives unselected; a vanished
    one is dropped, selected or not."""
    ensure_listed(db, conn)
    connector = connector_for(conn)
    with _reachable(conn):
        present = set(connector.list_tables())
    rows = _rows(db, conn.id)
    known = {r.name for r in rows}
    added, removed = sorted(present - known), sorted(known - present)

    for row in rows:
        if row.name not in present:
            db.delete(row)
    _add(db, conn.id, added, selected=False)

    selected = [r for r in rows if r.selected and r.name in present]
    with _reachable(conn):
        _apply(conn, selected, *_introspect(connector, [r.name for r in selected]))
    db.commit()
    return {**view(db, conn), "added": added, "removed": removed}


def counts(db: Session, connection_ids: list[str]) -> dict[str, tuple[int, int]]:
    """Selected and total tables per connection, in one statement for a whole list."""
    rows = db.execute(
        select(
            ConnectionTable.connection_id,
            func.count().filter(ConnectionTable.selected),
            func.count(),
        )
        .where(ConnectionTable.connection_id.in_(connection_ids))
        .group_by(ConnectionTable.connection_id)
    ).all()
    return {connection_id: (chosen, total) for connection_id, chosen, total in rows}


def forget(db: Session, conn: Connection) -> None:
    """Drop everything read from a source that is gone, or that a credential now points
    somewhere else. The caller commits."""
    db.execute(delete(ConnectionTable).where(ConnectionTable.connection_id == conn.id))
    conn.relationships = None
    conn.catalog_refreshed_at = None


async def load_for_run(db: Session, conn: Connection, connector: SqlConnector) -> Catalog:
    """The chosen tables for one run, re-read first when the last reading has gone stale.

    A run only ever updates the rows of tables already chosen, or inserts a first listing that
    the unique key makes safe to race. Tables arriving or vanishing wait for a refresh a person
    asks for. The customer's database is read off the event loop; the Session stays on it.
    """
    rows = _rows(db, conn.id)
    if not rows:
        with _reachable(conn):
            rows = _first_listing(db, conn, await asyncio.to_thread(connector.list_tables))
    selected = [r for r in rows if r.selected]

    stale = (
        conn.catalog_refreshed_at is None
        or datetime.now(UTC) - conn.catalog_refreshed_at > REFRESH_AFTER
    )
    if selected and stale:
        with _reachable(conn):
            read = await asyncio.to_thread(_introspect, connector, [r.name for r in selected])
        _apply(conn, selected, *read)

    catalog = Catalog(
        tables=[
            CatalogTable(definition=TableDef.model_validate(r.definition), stats=r.stats)
            for r in selected
            if r.definition
        ],
        relationships=[Relationship.model_validate(r) for r in conn.relationships or []],
    )
    db.commit()
    if not catalog.tables:
        raise DomainError("choose which tables the agent may use for this connection first")
    return catalog
