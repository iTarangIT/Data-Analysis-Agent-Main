"""What the agent remembers between runs, and how that is laid out in the store.

Every namespace starts with the tenant, so the isolation the rest of the service enforces at the
JWT holds here too: a read built from one tenant's context cannot name another tenant's key.
Glossary, queries and corrections are per connection as well, because a definition or a proven
join means nothing against a different customer's schema.

A thread record keeps the question, the SQL and the answer. It never keeps result rows: those are
the customer's data, and this database holds the structure of their tables and not their contents.
"""

import hashlib
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from langgraph.store.base import BaseStore

from app.agent.context import RunContext
from app.agent.prompts import MEMORY_BLOCK, NO_MEMORY

GLOSSARY = "glossary"
QUERIES = "queries"
CORRECTIONS = "corrections"
PREFERENCES = "preferences"
THREADS = "threads"

# Each recalled query costs a question and a SELECT in every prompt on this connection, against
# the same budget `max_agent_tables` already spends on table structure.
RECALLED_QUERIES = 5
RECALLED_TERMS = 20


def _digest(text: str) -> str:
    return hashlib.sha256(" ".join(text.lower().split()).encode()).hexdigest()[:16]


def _connection_ns(ctx: RunContext, kind: str) -> tuple[str, ...]:
    return (ctx.tenant_id, ctx.connection_id, kind)


def _tenant_ns(ctx: RunContext, kind: str) -> tuple[str, ...]:
    return (ctx.tenant_id, kind)


def recall(store: BaseStore, ctx: RunContext) -> str:
    """Everything worth putting in front of the model, rendered once per run."""
    terms = store.search(_connection_ns(ctx, GLOSSARY), limit=RECALLED_TERMS)
    queries = store.search(_connection_ns(ctx, QUERIES), limit=RECALLED_QUERIES)
    stored = store.get(_tenant_ns(ctx, PREFERENCES), ctx.tenant_id)
    prefs = stored.value if stored else {}

    if not (terms or queries or prefs):
        return NO_MEMORY

    return MEMORY_BLOCK.format(
        terms=_lines(f"{i.value['term']}: {i.value['definition']}" for i in terms),
        queries=_lines(f"{i.value['question']}\n  {i.value['sql']}" for i in queries),
        preferences=_lines(f"{k}: {v}" for k, v in prefs.items()),
    )


def _lines(entries: Iterable[str]) -> str:
    return "\n".join(f"- {e}" for e in entries) or "  None."


def remember_definition(store: BaseStore, ctx: RunContext, term: str, definition: str) -> None:
    store.put(
        _connection_ns(ctx, GLOSSARY),
        _digest(term),
        {"term": term, "definition": definition, "at": datetime.now(UTC).isoformat()},
    )


def remember_query(store: BaseStore, ctx: RunContext, question: str, sql: str) -> None:
    """Keyed on the question, so asking the same thing again overwrites rather than accumulates."""
    store.put(
        _connection_ns(ctx, QUERIES),
        _digest(question),
        {"question": question, "sql": sql, "at": datetime.now(UTC).isoformat()},
    )


def remember_correction(
    store: BaseStore, ctx: RunContext, rejected: str, reason: str, corrected: str
) -> None:
    store.put(
        _connection_ns(ctx, CORRECTIONS),
        _digest(rejected),
        {"rejected": rejected, "reason": reason, "corrected": corrected},
    )


def recall_correction(store: BaseStore, ctx: RunContext, rejected: str) -> dict[str, Any] | None:
    item = store.get(_connection_ns(ctx, CORRECTIONS), _digest(rejected))
    return item.value if item else None


def remember_thread(
    store: BaseStore, ctx: RunContext, question: str, sql: str | None, answer: str
) -> None:
    store.put(
        _tenant_ns(ctx, THREADS),
        ctx.thread_id,
        {
            "question": question,
            "sql": sql,
            "answer": answer,
            "at": datetime.now(UTC).isoformat(),
        },
    )


def set_preference(store: BaseStore, ctx: RunContext, key: str, value: str) -> None:
    namespace = _tenant_ns(ctx, PREFERENCES)
    stored = store.get(namespace, ctx.tenant_id)
    store.put(namespace, ctx.tenant_id, {**(stored.value if stored else {}), key: value})
