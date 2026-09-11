"""The safety boundary between a language model and a customer's database.

Pure sqlglot. This module must never call a model: it is the one place where a mistake becomes
a breach rather than a wrong answer. It is also only the third of three independent read-only
layers, the others being the `analyst_ro` role and the connector's connect_args.

Called from `app.agent.tools`, which every model-issued query must pass through.
"""

import sqlglot
from sqlglot import exp

# Anything that writes, changes structure or changes permissions. `Into` is here because
# `SELECT ... INTO t` parses as an ordinary Select yet creates a table. `Copy`, `Attach` and
# `Install` cannot appear inside a Select and so are already unreachable, but on duckdb they are
# how a query would write a file, open another database or fetch an extension, and this list is
# where someone looks to check that.
FORBIDDEN = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.Alter,
    exp.Create,
    exp.Command,
    exp.Merge,
    exp.TruncateTable,
    exp.Grant,
    exp.Into,
    exp.Copy,
    exp.Attach,
    exp.Install,
)


def _local_aliases(tree: exp.Expression) -> set[str]:
    """Names that resolve inside the query itself: CTE and derived-table aliases.

    Without this, `WITH recent AS (...) SELECT * FROM recent` is rejected because `recent`
    is not in the customer's schema.
    """
    aliases = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    aliases |= {
        sub.alias_or_name.lower() for sub in tree.find_all(exp.Subquery) if sub.alias_or_name
    }
    return aliases


def _with_row_cap(tree: exp.Expression, max_rows: int) -> exp.Expression:
    limit = tree.args.get("limit")
    if limit is not None:
        try:
            if int(limit.expression.this) <= max_rows:
                return tree
        except (AttributeError, TypeError, ValueError):
            pass  # A non-literal limit, such as a parameter, is not a cap we can trust.
    return tree.limit(max_rows)


def validate_sql(
    sql: str, allowed_tables: set[str], max_rows: int, dialect: str = "postgres"
) -> tuple[str, str | None]:
    """Return (safe_sql, None) if `sql` is a single read-only SELECT over allowed tables.

    Otherwise return (sql, reason). The reason is fed back to the SQL generator as a retry hint,
    so it names what was wrong rather than merely saying no.
    """
    try:
        statements = sqlglot.parse(sql, read=dialect)
    except sqlglot.errors.ParseError as e:
        return sql, f"parse error: {e}"

    statements = [s for s in statements if s is not None]
    if len(statements) != 1:
        return sql, f"exactly one statement is allowed, got {len(statements)}"

    tree = statements[0]
    if not isinstance(tree, exp.Select | exp.SetOperation):
        return sql, f"only SELECT statements are allowed, got {type(tree).__name__.upper()}"

    for node in tree.walk():
        if isinstance(node, FORBIDDEN):
            return sql, f"forbidden operation: {type(node).__name__}"

    # A table function such as read_csv_auto('...') is a Table node with an empty name, so the
    # allowlist already rejects it. Naming it in the message matters: the reason is fed back as a
    # retry hint, and "tables not allowed: ['']" tells the model nothing, so it reissues the same
    # query until the tool budget runs out.
    used = {t.name.lower() or t.sql(dialect=dialect) for t in tree.find_all(exp.Table)}
    unknown = used - {t.lower() for t in allowed_tables} - _local_aliases(tree)
    if unknown:
        return sql, f"tables not allowed: {sorted(unknown)}"

    return _with_row_cap(tree, max_rows).sql(dialect=dialect), None
