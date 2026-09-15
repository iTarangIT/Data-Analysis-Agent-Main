"""What a Postgres table actually holds, read from the catalog rather than by scanning.

This exists because the agent could not tell an empty table from a filter that matched
nothing from a period falling after the data ends, and so answered all three with a shrug.
On the customer's IoT database 7 of 15 tables hold no rows and the telemetry pipeline stopped
in early July, which makes that distinction most of the product.

Two rules govern everything here, and both are about not inventing anything:

`reltuples` is a planner estimate, not a count. It is -1 for a table that has never been
analysed and 0 for one analysed while empty and bulk-loaded since, so neither value proves a
table is empty. Emptiness is settled by an `EXISTS` probe or reported as unknown; it is never
inferred from statistics.

A partition's upper bound is not the newest row. Partitions are routinely created weeks
ahead of the data, so the newest bound would advertise coverage the table does not have.
Only the newest *non-empty* child's bound is reported.
"""

import re
from typing import Any

import structlog
from sqlalchemy import text

log = structlog.get_logger(__name__)

# Two seconds, not the connection's eight. Introspection runs inside POST /runs, before the
# stream opens, and a probe that hangs would hold the request open rather than fail cleanly.
PROBE_TIMEOUT_MS = 2000

# Bounds the generated SQL for a table with many partitions. Beyond this the coverage date is
# reported as unknown rather than guessed at from a subset.
MAX_PROBED_PARTITIONS = 60

_BOUND = re.compile(r"^FOR VALUES FROM \((?P<lo>.+)\) TO \((?P<hi>.+)\)$")
_TS_TYPES = ("'date'::regtype", "'timestamp'::regtype", "'timestamptz'::regtype")

_COUNTS = """
WITH RECURSIVE roots AS (
    SELECT c.oid, c.relname, c.relkind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'public'
       AND c.relkind IN ('r', 'p')
       AND NOT c.relispartition
),
tree AS (
    SELECT r.oid AS root, r.oid AS rel FROM roots r
    UNION ALL
    SELECT t.root, ch.oid
      FROM tree t
      JOIN pg_inherits i ON i.inhparent = t.rel
      JOIN pg_class ch ON ch.oid = i.inhrelid
)
SELECT r.relname,
       count(*) FILTER (WHERE c.relkind <> 'p' AND c.reltuples < 0) AS unanalysed,
       coalesce(sum(GREATEST(c.reltuples, 0))
                FILTER (WHERE c.relkind <> 'p'), 0)::bigint AS approx_rows
  FROM roots r
  JOIN tree t ON t.root = r.oid
  JOIN pg_class c ON c.oid = t.rel
 GROUP BY r.relname
"""

# Only single-column RANGE partitioning on a date or timestamp. A LIST or HASH key, or a
# composite one, says nothing about time, and its bound string has a different shape.
_RANGE_PARENTS = f"""
SELECT c.relname
  FROM pg_partitioned_table pt
  JOIN pg_class c ON c.oid = pt.partrelid
  JOIN pg_namespace n ON n.oid = c.relnamespace
  JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = pt.partattrs[0]
 WHERE n.nspname = 'public'
   AND NOT c.relispartition
   AND pt.partstrat = 'r'
   AND array_length(pt.partattrs, 1) = 1
   AND a.atttypid IN ({", ".join(_TS_TYPES)})
"""

_CHILDREN = """
SELECT p.relname AS parent,
       ch.relname AS child,
       ch.reltuples::bigint AS approx_rows,
       pg_get_expr(ch.relpartbound, ch.oid) AS bound
  FROM pg_class p
  JOIN pg_namespace n ON n.oid = p.relnamespace
  JOIN pg_inherits i ON i.inhparent = p.oid
  JOIN pg_class ch ON ch.oid = i.inhrelid
 WHERE n.nspname = 'public'
   AND p.relkind = 'p'
   AND NOT p.relispartition
   AND ch.relpartbound IS NOT NULL
"""


def _bucket(approx_rows: int) -> str:
    if approx_rows < 1_000:
        return "few"
    if approx_rows < 1_000_000:
        return "thousands"
    return "millions"


def _magnitude(approx_rows: int) -> int:
    """Two significant figures.

    `reltuples` is a float4, so 45.9 million carries about seven significant digits and the
    last of them is noise. Printing it whole would put a number in the prompt that looks
    counted, and the model would repeat it as one. Rounding also keeps the tool description
    stable while autovacuum re-analyses underneath it, which the eval cassettes fingerprint.
    """
    digits = len(str(approx_rows))
    step = 10 ** max(digits - 2, 0)
    return round(approx_rows / step) * step


def _has_rows(conn, tables: list[str]) -> dict[str, bool]:
    """One statement for every table in doubt, so they share a single timeout budget.

    `EXISTS` stops at the first live tuple, so a populated table costs one page and an empty
    one costs nothing. Names come from the catalog, which is the same trust boundary the
    existing sample-row query already sits on.
    """
    if not tables:
        return {}
    # `tbl`, not `t`: SQLAlchemy's Row exposes `.t` as a synonym for `.tuple()`, which
    # shadows a column of that name and hands back the whole row instead of the value.
    union = "\nUNION ALL ".join(
        f'SELECT {_literal(t)} AS tbl, EXISTS (SELECT 1 FROM public."{t}") AS has_rows'
        for t in tables
    )
    return {row.tbl: row.has_rows for row in conn.execute(text(union))}


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _upper_bound(bound: str | None) -> str | None:
    """The upper edge of a RANGE partition, or None for anything not shaped like one.

    DEFAULT partitions, MAXVALUE and composite keys all land here and are all refused: a
    bound that cannot be read exactly is worth nothing, and a guess at one is worth less.
    """
    if not bound:
        return None
    m = _BOUND.match(bound.strip())
    if not m:
        return None
    hi = m.group("hi").strip()
    if "," in hi or not hi.startswith("'") or not hi.endswith("'"):
        return None
    value = hi[1:-1].replace("''", "'")
    return value.removesuffix(" 00:00:00+00")


def _coverage(conn, parent: str, children: list[Any]) -> str | None:
    """The upper bound of the newest partition that actually holds rows.

    Walking down from the newest rather than taking the first is the whole point. A pipeline
    that stopped in July leaves months of empty partitions created ahead of it, and reporting
    their bound would claim coverage that does not exist.
    """
    if any((c.bound or "").strip() == "DEFAULT" for c in children):
        # A default partition catches rows outside every range, so the highest range bound
        # stops describing where the data ends.
        return None

    dated = [(ub, c) for c in children if (ub := _upper_bound(c.bound))]
    if not dated:
        return None
    dated.sort(key=lambda pair: pair[0], reverse=True)

    ahead = []
    for upper, child in dated:
        if child.approx_rows > 0:
            return upper
        ahead.append((upper, child))
        if len(ahead) > MAX_PROBED_PARTITIONS:
            log.info("stats.coverage_unknown", table=parent, unanalysed=len(ahead))
            return None

    probed = _has_rows(conn, [c.child for _, c in ahead])
    for upper, child in ahead:
        if probed.get(child.child):
            return upper
    return None


def collect(conn, tables: list[str]) -> dict[str, dict[str, Any]]:
    """Per-table row bucket and coverage date, for the tables the connector already shows.

    Every query here reads the catalog or stops at one row. Nothing scans a table, because
    the tables this matters most for are the ones that cannot be scanned inside the timeout.
    """
    conn.execute(text(f"SET LOCAL statement_timeout = {PROBE_TIMEOUT_MS}"))
    # `pg_get_expr` renders a timestamptz bound in the session's zone, which on a native
    # Windows server is the machine's. Pinning it keeps the parsed date right and the
    # rendered description byte-stable between machines.
    conn.execute(text("SET LOCAL TimeZone = 'UTC'"))

    wanted = set(tables)
    counts = {r.relname: r for r in conn.execute(text(_COUNTS)) if r.relname in wanted}

    ambiguous = [name for name, r in counts.items() if r.approx_rows == 0]
    known = _has_rows(conn, ambiguous)

    range_parents = {r.relname for r in conn.execute(text(_RANGE_PARENTS))} & wanted
    children: dict[str, list[Any]] = {}
    if range_parents:
        for row in conn.execute(text(_CHILDREN)):
            if row.parent in range_parents:
                children.setdefault(row.parent, []).append(row)

    stats: dict[str, dict[str, Any]] = {}
    for name in tables:
        row = counts.get(name)
        if row is None:
            continue

        if row.approx_rows == 0:
            has = known.get(name)
            if has is None:
                entry: dict[str, Any] = {"rows": "unknown"}
            elif has:
                # Proven to hold rows, but never analysed, so how many is not known. That is
                # a different fact from not knowing whether it holds any, and the model can
                # act on it: query the table, but do not assume it is small.
                entry = {"rows": "nonempty"}
            else:
                stats[name] = {"rows": "empty"}
                continue
        else:
            entry = {"rows": _bucket(row.approx_rows)}
            if entry["rows"] != "few":
                entry["rows_approx"] = _magnitude(row.approx_rows)
            if row.unanalysed:
                # Some partitions have never been analysed, so the sum is a floor.
                entry["rows_at_least"] = True

        if name in children:
            covered = _coverage(conn, name, children[name])
            if covered:
                entry["covered_to"] = covered
        stats[name] = entry

    return stats
