"""Reading tables' structure out of the Postgres catalog, and never their rows.

It serves a picker listing a whole database and a refresh of up to a dozen selected tables, so
it costs a fixed handful of catalog statements however many tables are read, never a round trip
per table.
"""

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

from app.catalog.types import Column, ForeignKey, TableDef

SCHEMA = "public"

_TABLES = text(
    """
    SELECT c.relname
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'public'
       AND c.relkind IN ('r', 'p')
       AND NOT c.relispartition
     ORDER BY c.relname
    """
)

# Not the Inspector's reflected types: those render timestamptz as TIMESTAMP, dropping the time
# zone a correct date filter depends on, and reflect extension types as NullType.
_COLUMNS = text(
    """
    SELECT c.relname AS table_name,
           a.attname AS name,
           format_type(a.atttypid, a.atttypmod) AS type,
           NOT a.attnotnull AS nullable,
           col_description(c.oid, a.attnum) AS comment
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
      JOIN pg_attribute a ON a.attrelid = c.oid
     WHERE n.nspname = 'public'
       AND c.relname = ANY(:names)
       AND a.attnum > 0
       AND NOT a.attisdropped
     ORDER BY c.relname, a.attnum
    """
)


def list_tables(conn: Connection) -> list[str]:
    """Ordinary and partitioned tables in `public`, never partition children.

    `Inspector.get_table_names` returns children too. On the iTarang IoT database that is 100
    weekly partitions against 15 real tables. Views are excluded with them: the only ones present
    belong to pg_stat_statements.
    """
    return [r.relname for r in conn.execute(_TABLES)]


def _unique_sets(constraints: list[dict], indexes: list[dict]) -> list[list[str]]:
    """Unique constraints, plus unique indexes that could stand in for one.

    A constraint is backed by an index that reflects as a duplicate of it, and a partial or
    expression index does not make its columns unique across the table, so neither counts.
    """
    sets = [c["column_names"] for c in constraints]
    for ix in indexes:
        if (
            ix["unique"]
            and "duplicates_constraint" not in ix
            and not ix.get("dialect_options", {}).get("postgresql_where")
            and None not in ix["column_names"]
            and ix["column_names"] not in sets
        ):
            sets.append(ix["column_names"])
    return sets


def read_tables(conn: Connection, names: list[str]) -> list[TableDef]:
    """The structure of each named table, sorted by name. A name that is not a listed table is
    skipped, which is how a caller learns that a selected table has gone."""
    visible = set(list_tables(conn))
    wanted = sorted(set(names) & visible)
    if not wanted:
        return []

    columns: dict[str, list[Column]] = {}
    for row in conn.execute(_COLUMNS, {"names": wanted}):
        columns.setdefault(row.table_name, []).append(
            Column(name=row.name, type=row.type, nullable=row.nullable, comment=row.comment)
        )

    insp = inspect(conn)
    scope = {"schema": SCHEMA, "filter_names": wanted}
    pks = insp.get_multi_pk_constraint(**scope)
    # Without ignoring the search path, a key into `public` reflects with no schema at all.
    fks = insp.get_multi_foreign_keys(postgresql_ignore_search_path=True, **scope)
    uniques = insp.get_multi_unique_constraints(**scope)
    indexes = insp.get_multi_indexes(**scope)
    checks = insp.get_multi_check_constraints(**scope)
    comments = insp.get_multi_table_comment(**scope)

    tables = []
    for name in wanted:
        key = (SCHEMA, name)
        tables.append(
            TableDef(
                name=name,
                comment=comments.get(key, {}).get("text"),
                columns=columns.get(name, []),
                primary_key=pks.get(key, {}).get("constrained_columns") or [],
                uniques=_unique_sets(uniques.get(key, []), indexes.get(key, [])),
                foreign_keys=[
                    ForeignKey(
                        columns=fk["constrained_columns"],
                        ref_table=fk["referred_table"],
                        ref_columns=fk["referred_columns"],
                    )
                    for fk in fks.get(key, [])
                    # A key referencing a partitioned table also reflects once per partition.
                    # Partitions are never listed, so keeping listed targets drops the copies.
                    if fk["referred_schema"] == SCHEMA and fk["referred_table"] in visible
                ],
                checks=[c["sqltext"] for c in checks.get(key, [])],
            )
        )
    return tables
