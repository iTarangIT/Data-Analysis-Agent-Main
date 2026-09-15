"""Answering questions about an uploaded spreadsheet, with DuckDB as the query engine.

Uploads are converted to Parquet once, at ingest, and the connector only ever reads Parquet.
That removes the Excel extension, which DuckDB would have to download at first use and cannot
once external access is off. It also moves CSV type sniffing out of the query path, so a
column cannot change type between runs and make the cached schema a lie.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb

from app.catalog.types import Column, TableDef
from app.services.errors import DomainError

# The table name is interpolated into CREATE TABLE, so it is derived from a validated pattern
# rather than escaped. Deriving is what stays safe when someone edits this later.
TABLE_NAME = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


@dataclass(frozen=True)
class FileSource:
    table: str
    path: str


def _slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9_]+", "_", name.strip().lower()).strip("_")[:63]
    if not slug or not slug[0].isalpha():
        slug = f"t_{slug}"[:63]
    return slug


def _unique(slug: str, taken: set[str]) -> str:
    if slug not in taken:
        return slug
    n = 2
    while f"{slug}_{n}" in taken:
        n += 1
    return f"{slug}_{n}"


def ingest_upload(src: Path, dest_dir: Path, filename: str) -> list[FileSource]:
    """Convert an upload into one Parquet file per table.

    `src` is where the bytes were staged; `filename` is what the customer called the file, and
    is what the table is named after. They differ because an upload lands in a temp file first,
    and naming the table after that would show the model `tmplr333xb5` instead of `q3_sales`.

    A spreadsheet routinely has several sheets, and answering from the first one silently would
    be the worst available failure, so each sheet becomes its own table.
    """
    suffix = Path(filename).suffix.lower()
    dest_dir.mkdir(parents=True, exist_ok=True)
    sources: list[FileSource] = []
    taken: set[str] = set()

    con = duckdb.connect()
    try:
        if suffix == ".xlsx":
            import pandas as pd

            # Written through DuckDB rather than pandas.to_parquet, which needs pyarrow.
            for sheet, frame in pd.read_excel(src, sheet_name=None).items():
                if frame.empty:
                    continue
                table = _unique(_slug(sheet), taken)
                taken.add(table)
                path = dest_dir / f"{table}.parquet"
                con.from_df(frame).write_parquet(str(path))
                sources.append(FileSource(table=table, path=str(path)))
        else:
            table = _unique(_slug(Path(filename).stem), taken)
            taken.add(table)
            path = dest_dir / f"{table}.parquet"
            reader = con.read_parquet if suffix == ".parquet" else con.read_csv
            reader(str(src)).write_parquet(str(path))
            sources.append(FileSource(table=table, path=str(path)))
    finally:
        con.close()

    if not sources:
        raise DomainError("that file has no readable rows")
    return sources


class DuckDBConnector:
    """A tenant's uploaded file, queried in memory.

    The construction order below is the security property. Every source is materialised as a
    real table first, and only then is the filesystem taken away, so afterwards no query can
    read a path however it is written. That is the engine layer, the direct analogue of the
    `analyst_ro` role on Postgres; the guard's table allowlist is the second.

    What the lockdown does not stop is `CREATE TABLE ... AS SELECT` against this in-memory
    database, which the guard rejects. Its blast radius is a copy that is discarded when the
    run ends, while the Parquet on disk is unreachable.
    """

    kind = "file"
    dialect = "duckdb"

    def __init__(self, tenant_id: str, sources: list[FileSource]) -> None:
        self.tenant_id = tenant_id
        self.tables = [s.table for s in sources]
        self.con = duckdb.connect()
        # One tenant's query must not eat the box, and single-threaded is the fairness knob.
        self.con.execute("SET memory_limit='512MB'")
        self.con.execute("SET threads=1")
        for source in sources:
            if not TABLE_NAME.match(source.table):
                raise ValueError(f"unsafe table name {source.table!r}")
            self.con.execute(
                f"CREATE TABLE {source.table} AS SELECT * FROM read_parquet(?)", [source.path]
            )
        self.con.execute("SET enable_external_access=false")
        self.con.execute("SET lock_configuration=true")

    def list_tables(self) -> list[str]:
        return sorted(self.tables)

    def read_tables(self, names: list[str]) -> list[TableDef]:
        """Columns only. A spreadsheet has no keys, so it has no relationships to report."""
        wanted = set(names) & set(self.tables)
        columns: dict[str, list[Column]] = {}
        rows = self.con.execute(
            "SELECT table_name, column_name, data_type, is_nullable = 'YES' "
            "FROM information_schema.columns WHERE table_schema = 'main' "
            "ORDER BY table_name, ordinal_position"
        ).fetchall()
        for table, name, type_, nullable in rows:
            if table in wanted:
                columns.setdefault(table, []).append(
                    Column(name=name, type=type_, nullable=nullable)
                )
        return [TableDef(name=table, columns=columns[table]) for table in sorted(wanted)]

    def table_stats(self, names: list[str]) -> dict[str, dict[str, Any]]:
        """Nothing to report. An upload is small, never partitioned and held whole in memory, so
        neither a size bucket nor a coverage date would change the query the model writes."""
        return {}

    def run_select(self, sql: str, max_rows: int) -> tuple[list[str], list[tuple]]:
        cursor = self.con.execute(sql)
        cols = [d[0] for d in cursor.description]
        return cols, cursor.fetchmany(max_rows)
