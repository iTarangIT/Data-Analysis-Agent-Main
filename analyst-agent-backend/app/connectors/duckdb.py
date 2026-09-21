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
import pandas as pd
from pandas.tseries.api import guess_datetime_format

from app.catalog.types import Column, TableDef
from app.connectors import storage
from app.connectors.pg_stats import row_bucket, row_magnitude
from app.services.errors import DomainError

# The table name is interpolated into CREATE TABLE, so it is derived from a validated pattern
# rather than escaped. Deriving is what stays safe when someone edits this later.
TABLE_NAME = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
KEYWORDS = frozenset(
    name
    for (name,) in duckdb.sql(
        "SELECT keyword_name FROM duckdb_keywords() WHERE keyword_category <> 'unreserved'"
    ).fetchall()
)
TOTAL_ROW = r"(grand\s+)?total"


@dataclass(frozen=True)
class FileSource:
    table: str
    path: str
    file: str
    origin: str
    profile: dict[str, Any]
    sheet: str = ""


@dataclass(frozen=True)
class Part:
    table: str
    file: str
    origin: str
    storage_key: str
    sha256: str
    profile: dict[str, Any]
    sheet: str = ""


def _column_type(types: list[str]) -> str:
    if len(set(types)) == 1:
        return types[0]
    if set(types) == {"BIGINT", "DOUBLE"}:
        return "DOUBLE"
    return "VARCHAR"


def _slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9_]+", "_", name.strip().lower()).strip("_")[:63]
    if not slug or not slug[0].isalpha():
        slug = f"t_{slug}"[:63]
    if slug in KEYWORDS:
        slug = f"{slug}_"
    return slug


def _unique(slug: str, taken: set[str]) -> str:
    if slug not in taken:
        return slug
    n = 2
    while (candidate := f"{slug[: 62 - len(str(n))]}_{n}") in taken:
        n += 1
    return candidate


def _header_row(probe: pd.DataFrame) -> int:
    filled = probe.notna()
    number = probe.apply(pd.to_numeric, errors="coerce").notna()
    text = filled & ~number & probe.map(lambda value: isinstance(value, str))
    mix = pd.DataFrame(
        {
            "text": text.any(axis=1),
            "number": number.any(axis=1),
            "other": (filled & ~number & ~text).any(axis=1),
        }
    )
    below = mix.shift(-1, fill_value=False)
    header = (
        (text.sum(axis=1) >= 0.7 * filled.sum(axis=1))
        & filled.any(axis=1)
        & below.any(axis=1)
        & mix.ne(below).any(axis=1)
    )
    return int(header.idxmax()) if header.any() else 0


def _dates(column: pd.Series) -> pd.Series:
    candidates = column.where(pd.to_numeric(column, errors="coerce").isna())
    start = candidates.first_valid_index()
    if start is None:
        return column
    first = str(candidates[start])
    fmt = guess_datetime_format(first, dayfirst=not first[:4].isdigit())
    if fmt is None or "%d" not in fmt or ("%Y" not in fmt and "%y" not in fmt):
        return column
    parsed = pd.to_datetime(candidates, format=fmt, errors="coerce")
    return parsed if parsed.notna().sum() >= 0.9 * column.notna().sum() else column


def _harden(frame: pd.DataFrame, header_row: int) -> tuple[pd.DataFrame, dict[str, Any]]:
    blank = frame.columns.astype(str).str.startswith("Unnamed:") & frame.isna().all().to_numpy()
    frame = frame.loc[:, ~blank]

    first_cell = frame.bfill(axis=1).iloc[:, 0].astype(str).str.strip()
    trailing = first_cell.str.fullmatch(TOTAL_ROW, case=False)[::-1].cummin()[::-1]
    frame = frame[~trailing]

    taken: set[str] = set()
    columns: dict[str, str] = {}
    for original in frame.columns.astype(str):
        slug = _unique(_slug(original), taken)
        taken.add(slug)
        columns[slug] = original
    frame = frame.set_axis(list(columns), axis=1)

    for name in frame.select_dtypes(include=["object", "str"]).columns:
        frame[name] = _dates(frame[name])

    dates = frame.select_dtypes(include=["datetime", "datetimetz"]).dropna(axis=1, how="all")
    profile = {
        "row_count": len(frame),
        "header_row": header_row,
        "dropped_total_rows": int(trailing.sum()),
        "columns": columns,
        "date_range": {
            name: [low.isoformat(), high.isoformat()]
            for name, low, high in zip(dates.columns, dates.min(), dates.max(), strict=True)
        },
    }
    return frame, profile


def _read(
    con: duckdb.DuckDBPyConnection, src: Path, suffix: str
) -> dict[str, tuple[int, pd.DataFrame]]:
    if suffix == ".xlsx":
        frames: dict[str, tuple[int, pd.DataFrame]] = {}
        with pd.ExcelFile(src) as book:
            for sheet in book.sheet_names:
                header = _header_row(book.parse(sheet, header=None, nrows=10))
                frames[str(sheet)] = (header, book.parse(sheet, header=header))
        return frames
    if suffix == ".parquet":
        return {"": (0, con.read_parquet(str(src)).df())}
    [(sep,)] = con.execute("SELECT Delimiter FROM sniff_csv(?)", [str(src)]).fetchall()
    header = _header_row(pd.read_csv(src, sep=sep, header=None, nrows=10))
    return {"": (header, pd.read_csv(src, sep=sep, header=header))}


def ingest_upload(src: Path, dest_dir: Path, filename: str, taken: set[str]) -> list[FileSource]:
    """Convert an upload into one Parquet file per table.

    `src` is where the bytes were staged; `filename` is what the customer called the file, and
    is what the table is named after. They differ because an upload lands in a temp file first,
    and naming the table after that would show the model `tmplr333xb5` instead of `q3_sales`.

    A spreadsheet routinely has several sheets, and answering from the first one silently would
    be the worst available failure, so each sheet becomes its own table.
    """
    suffix = Path(filename).suffix.lower()
    stem = Path(filename).stem
    dest_dir.mkdir(parents=True, exist_ok=True)
    sources: list[FileSource] = []

    con = duckdb.connect()
    try:
        tables: dict[str, tuple[pd.DataFrame, dict[str, Any]]] = {}
        for sheet, (header_row, raw) in _read(con, src, suffix).items():
            if raw.empty:
                continue
            frame, profile = _harden(raw, header_row)
            if not frame.empty:
                tables[sheet] = (frame, profile)

        for sheet, (frame, profile) in tables.items():
            table = _unique(_slug(f"{stem}__{sheet}" if len(tables) > 1 else stem), taken)
            taken.add(table)
            path = dest_dir / f"{table}.parquet"
            # Written through DuckDB rather than pandas.to_parquet, which needs pyarrow.
            con.from_df(frame).write_parquet(str(path))
            described = con.execute("DESCRIBE SELECT * FROM read_parquet(?)", [str(path)])
            profile["types"] = {name: type_ for name, type_, *_ in described.fetchall()}
            sources.append(
                FileSource(
                    table=table,
                    path=str(path),
                    file=filename,
                    origin="upload",
                    profile=profile,
                    sheet=sheet,
                )
            )
    finally:
        con.close()

    if not sources:
        raise DomainError(f"{filename} has no readable rows")
    return sources


class Dataset:
    kind = "file"

    def __init__(self, tenant_id: str, parts: list[Part]) -> None:
        self.tenant_id = tenant_id
        self.parts = parts

    def list_tables(self) -> list[str]:
        return sorted({part.table for part in self.parts})

    def read_tables(self, names: list[str]) -> list[TableDef]:
        wanted = set(names)
        types: dict[str, dict[str, list[str]]] = {}
        for part in self.parts:
            if part.table in wanted:
                for column, type_ in part.profile["types"].items():
                    types.setdefault(part.table, {}).setdefault(column, []).append(type_)
        return [
            TableDef(
                name=table,
                columns=[Column(name=name, type=_column_type(t)) for name, t in columns.items()],
            )
            for table, columns in sorted(types.items())
        ]

    def table_stats(self, names: list[str]) -> dict[str, dict[str, Any]]:
        wanted = set(names)
        rows: dict[str, int] = {}
        for part in self.parts:
            if part.table in wanted:
                rows[part.table] = rows.get(part.table, 0) + part.profile["row_count"]
        stats: dict[str, dict[str, Any]] = {}
        for name, count in rows.items():
            stats[name] = {"rows": row_bucket(count)}
            if stats[name]["rows"] != "few":
                stats[name]["rows_approx"] = row_magnitude(count)
        return stats

    def open(self, names: set[str]) -> "DuckDBConnector":
        return DuckDBConnector(
            self.tenant_id,
            [
                FileSource(
                    table=part.table,
                    path=str(storage.local(part.storage_key, part.sha256)),
                    file=part.file,
                    origin=part.origin,
                    profile=part.profile,
                    sheet=part.sheet,
                )
                for part in self.parts
                if part.table in names
            ],
        )


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
        paths: dict[str, list[str]] = {}
        for source in sources:
            if not TABLE_NAME.match(source.table):
                raise ValueError(f"unsafe table name {source.table!r}")
            paths.setdefault(source.table, []).append(source.path)
        self.con = duckdb.connect()
        # One tenant's query must not eat the box, and single-threaded is the fairness knob.
        self.con.execute("SET memory_limit='512MB'")
        self.con.execute("SET threads=1")
        self.con.execute("SET temp_directory=''")
        for table, files in paths.items():
            self.con.execute(
                f"CREATE TABLE {table} AS SELECT * FROM read_parquet(?, union_by_name = true)",
                [files],
            )
        self.con.execute("SET enable_external_access=false")
        self.con.execute("SET lock_configuration=true")

    def run_select(self, sql: str, max_rows: int) -> tuple[list[str], list[tuple]]:
        cursor = self.con.execute(sql)
        cols = [d[0] for d in cursor.description]
        return cols, cursor.fetchmany(max_rows)
