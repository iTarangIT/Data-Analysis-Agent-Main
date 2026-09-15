"""The selected tables, and how they join, written out for the query tool's description.

This text is the whole of what the model knows about a customer's database. It states only what
the catalog holds: columns, types and keys; what each table holds, as the catalog measured it;
and each relationship, with whether a constraint declares it or a column name suggested it.
"""

from typing import Any

from app.agent.prompts import NO_RELATIONSHIPS
from app.catalog.types import Catalog, Relationship, TableDef

_ROW_PHRASE = {
    "empty": "EMPTY, holds no rows at all",
    "few": "a few rows",
    "nonempty": "has rows, how many is not known",
    "unknown": "row count not known",
}


def _stats_line(stats: dict[str, Any]) -> str:
    """What the table holds, in words the model can act on.

    Deliberately vague about size and exact about emptiness. A bucket is all the model needs
    to judge whether a query will survive the statement timeout, whereas an exact-looking
    count invites it to answer "there are 45,899,998 readings" without querying anything.
    """
    rows = stats.get("rows", "unknown")
    if rows in _ROW_PHRASE:
        said = _ROW_PHRASE[rows]
    else:
        approx = stats.get("rows_approx")
        said = f"about {approx:,} rows" if approx else "row count not known"
        if stats.get("rows_at_least"):
            said = said.replace("about", "at least about")

    if covered := stats.get("covered_to"):
        said += f"; its newest data sits in a partition ending {covered}"
    return said


def _table(definition: TableDef, stats: dict[str, Any] | None) -> str:
    header = f"TABLE {definition.name}"
    if stats:
        header += f"  -- {_stats_line(stats)}"
    lines = [header]
    if definition.comment:
        lines.append(f"  -- {definition.comment}")

    # A key over one column is marked on the column; a key over several is stated once below.
    single_pk = definition.primary_key if len(definition.primary_key) == 1 else []
    single_unique = {u[0] for u in definition.uniques if len(u) == 1}
    for column in definition.columns:
        line = f"  {column.name} {column.type}"
        if column.name in single_pk:
            line += " PRIMARY KEY"
        elif not column.nullable:
            line += " NOT NULL"
        if column.name in single_unique:
            line += " UNIQUE"
        if column.comment:
            line += f"  -- {column.comment}"
        lines.append(line)

    if len(definition.primary_key) > 1:
        lines.append(f"  PRIMARY KEY ({', '.join(definition.primary_key)})")
    lines += [f"  UNIQUE ({', '.join(u)})" for u in definition.uniques if len(u) > 1]
    lines += [f"  CHECK ({check})" for check in definition.checks]
    return "\n".join(lines)


def render_tables(catalog: Catalog) -> str:
    return "\n\n".join(_table(t.definition, t.stats) for t in catalog.tables)


def _end(table: str, columns: list[str]) -> str:
    return f"{table}.{columns[0]}" if len(columns) == 1 else f"{table}.({', '.join(columns)})"


def _relationship(r: Relationship) -> str:
    kind = r.cardinality.replace("_", "-")
    if r.origin == "inferred":
        kind += ", inferred from matching column names"
    return f"  {_end(r.from_table, r.from_columns)} -> {_end(r.to_table, r.to_columns)}  ({kind})"


def render_relationships(catalog: Catalog) -> str:
    if not catalog.relationships:
        return NO_RELATIONSHIPS
    return "\n".join(_relationship(r) for r in catalog.relationships)
