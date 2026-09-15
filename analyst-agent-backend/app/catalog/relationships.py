"""How a set of tables joins, worked out from their keys.

Declared foreign keys are taken as given. Analytics databases often declare none, so two
conservative name matches stand in for them, and every edge those produce is labelled
`inferred` so that neither the model nor a person mistakes it for a constraint.

Only tables inside the set are considered. The set is what a person selected and the guard
rejects everything else, so an edge leading out of it would only teach the model a join it
cannot run.
"""

from collections.abc import Iterator

from app.catalog.types import Column, Relationship, TableDef

# Types a join key plausibly has. Dates, times, booleans and floating-point measurements are left
# out on purpose: two tables that both carry a `day` or a `value` column are rarely related.
_FAMILY = {
    **dict.fromkeys(
        (
            "smallint",
            "integer",
            "bigint",
            "int",
            "int2",
            "int4",
            "int8",
            "tinyint",
            "hugeint",
            "utinyint",
            "usmallint",
            "uinteger",
            "ubigint",
        ),
        "integer",
    ),
    **dict.fromkeys(
        ("text", "character varying", "varchar", "character", "char", "bpchar", "string"), "text"
    ),
    "uuid": "uuid",
}


def _family(type_: str) -> str | None:
    return _FAMILY.get(type_.lower().split("(")[0].strip())


def _plural_forms(noun: str) -> set[str]:
    forms = {noun, f"{noun}s", f"{noun}es"}
    if noun.endswith("y"):
        forms.add(f"{noun[:-1]}ies")
    return forms


def _cardinality(table: TableDef, columns: list[str]) -> str:
    keys = [table.primary_key, *table.uniques]
    return "one_to_one" if any(k and set(columns) == set(k) for k in keys) else "many_to_one"


def _single_keys(table: TableDef) -> set[str]:
    """Columns that identify a row on their own: a one-column primary key, or UNIQUE NOT NULL."""
    not_null = {c.name for c in table.columns if not c.nullable}
    keys = set(table.primary_key) if len(table.primary_key) == 1 else set()
    return keys | {u[0] for u in table.uniques if len(u) == 1 and u[0] in not_null}


def _inferred_targets(
    source: TableDef, column: Column, tables: list[TableDef]
) -> Iterator[tuple[TableDef, str]]:
    family = _family(column.type)
    # A table's own whole key is what other tables point at, not a pointer itself. Without this
    # `countries.code` and `currencies.code` would be joined for sharing a name.
    if family is None or source.primary_key == [column.name]:
        return

    for target in tables:
        if target is source:
            continue
        types = {c.name: c.type for c in target.columns}

        if (
            column.name != "id"
            and column.name in _single_keys(target)
            and _family(types[column.name]) == family
        ):
            yield target, column.name

        if (
            column.name.endswith("_id")
            and target.name in _plural_forms(column.name.removesuffix("_id"))
            and target.primary_key == ["id"]
            and _family(types["id"]) == family
        ):
            yield target, "id"


def map_relationships(tables: list[TableDef]) -> list[Relationship]:
    names = {t.name for t in tables}
    declared: list[Relationship] = []
    joined: set[frozenset[str]] = set()

    for table in tables:
        for fk in table.foreign_keys:
            if fk.ref_table not in names:
                continue
            joined.add(frozenset((table.name, fk.ref_table)))
            declared.append(
                Relationship(
                    from_table=table.name,
                    from_columns=fk.columns,
                    to_table=fk.ref_table,
                    to_columns=fk.ref_columns,
                    origin="declared",
                    cardinality=_cardinality(table, fk.columns),
                )
            )

    inferred = [
        Relationship(
            from_table=source.name,
            from_columns=[column.name],
            to_table=target.name,
            to_columns=[target_column],
            origin="inferred",
            cardinality=_cardinality(source, [column.name]),
        )
        for source in tables
        for column in source.columns
        for target, target_column in _inferred_targets(source, column, tables)
        if frozenset((source.name, target.name)) not in joined
    ]

    ordered = sorted(
        declared + inferred,
        key=lambda r: (r.from_table, r.from_columns, r.to_table, r.to_columns),
    )

    # Two unique columns matching each other are found from both ends. They are one relationship,
    # so the end that sorts first is kept.
    seen: set[frozenset[tuple[str, tuple[str, ...]]]] = set()
    result = []
    for edge in ordered:
        ends = frozenset(
            ((edge.from_table, tuple(edge.from_columns)), (edge.to_table, tuple(edge.to_columns)))
        )
        if edge.cardinality == "one_to_one" and edge.origin == "inferred":
            if ends in seen:
                continue
            seen.add(ends)
        result.append(edge)
    return result
