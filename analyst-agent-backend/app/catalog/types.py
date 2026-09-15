"""The structure of a customer's tables, as far as the agent is allowed to know it.

Nothing here can hold a row. These are what the schema readers return, what the App DB stores
for each selected table, and what the query tool's description is rendered from. The package
imports nothing from `app`, so connectors, services, the agent and the API can all depend on it.
"""

from typing import Any, Literal

from pydantic import BaseModel


class Column(BaseModel):
    name: str
    type: str
    nullable: bool = True
    comment: str | None = None


class ForeignKey(BaseModel):
    columns: list[str]
    ref_table: str
    ref_columns: list[str]


class TableDef(BaseModel):
    name: str
    comment: str | None = None
    columns: list[Column]
    primary_key: list[str] = []
    # Unique constraints, plus unique indexes that are neither partial nor on an expression.
    uniques: list[list[str]] = []
    foreign_keys: list[ForeignKey] = []
    checks: list[str] = []


class Relationship(BaseModel):
    from_table: str
    from_columns: list[str]
    to_table: str
    to_columns: list[str]
    # `inferred` is a column-name match with no constraint behind it.
    origin: Literal["declared", "inferred"]
    cardinality: Literal["many_to_one", "one_to_one"]


class CatalogTable(BaseModel):
    definition: TableDef
    stats: dict[str, Any] | None = None


class Catalog(BaseModel):
    tables: list[CatalogTable]
    relationships: list[Relationship] = []

    @property
    def table_names(self) -> set[str]:
        return {t.definition.name for t in self.tables}
