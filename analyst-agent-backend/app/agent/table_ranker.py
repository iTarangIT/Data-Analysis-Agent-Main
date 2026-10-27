"""Which tables a question needs, when every table of a database is in play.

Describing every table in full would put tens of thousands of tokens in front of the model on
every call, so a run instead spells out the few tables its question most likely needs and lists
the rest in a one-line index (see schema_context.render_index). Choosing those few has to be
cheap and must never touch the customer's database, so it is a lexical ranking over what the
catalog already holds: table and column names, and their comments. No model call, no rows.

A miss costs one `describe_tables` call, not a wrong answer: every table stays queryable, and
the index tells the model it exists.
"""

import math
import re
from collections import Counter

from app.catalog.types import Catalog, CatalogTable, Relationship

# How strongly each part of a table speaks for it, and how much a long part is discounted
# (BM25F: each field is normalised by its own length). A table's own name says most about what
# it holds; its comment is what a person wrote to say so. Columns say something, but a wide
# table has a hundred of them, so they are discounted hard by length: otherwise the main table
# of a database, always the widest, loses to every narrow side table sharing a word with it.
FIELDS = {
    # field: (weight, length discount b)
    "name": (3.0, 0.3),
    "comment": (2.0, 0.5),
    "columns": (1.0, 0.9),
}
COLUMN_COMMENT_WEIGHT = 0.5

# Earlier questions in the thread count for less than the one being asked, so "and by dealer?"
# keeps the tables of the question before it without crowding out what is new.
PRIOR_QUESTION_WEIGHT = 0.5

_K1 = 1.2

_STOPWORDS = frozenset(
    [
        "a",
        "an",
        "the",
        "of",
        "in",
        "on",
        "at",
        "to",
        "for",
        "by",
        "with",
        "from",
        "and",
        "or",
        "not",
        "no",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "do",
        "does",
        "did",
        "how",
        "many",
        "much",
        "what",
        "which",
        "who",
        "whom",
        "whose",
        "when",
        "where",
        "why",
        "show",
        "give",
        "list",
        "tell",
        "me",
        "my",
        "our",
        "we",
        "us",
        "i",
        "this",
        "that",
        "these",
        "those",
        "it",
        "its",
        "per",
        "each",
        "every",
        "all",
        "any",
        "some",
        "there",
        "their",
        "them",
        "than",
        "then",
        "as",
        "into",
        "over",
        "under",
        "between",
        "last",
        "next",
        "this",
        "past",
        "current",
        "month",
        "months",
        "week",
        "weeks",
        "day",
        "days",
        "year",
        "years",
        "today",
        "yesterday",
        "trend",
        "total",
        "count",
        "number",
        "sum",
        "average",
        "avg",
        "top",
        "most",
        "least",
        "more",
        "less",
        "get",
        "find",
        "please",
        "data",
        "table",
        "tables",
    ]
)

# Business words people use that the schema spells differently. Kept to plain sales and
# operations vocabulary; anything specific to one customer belongs in their table comments.
SYNONYMS: dict[str, tuple[str, ...]] = {
    "revenue": ("invoice", "sale", "amount"),
    "turnover": ("invoice", "sale", "amount"),
    "billing": ("invoice",),
    "billed": ("invoice",),
    "sold": ("sale", "invoice"),
    "selling": ("sale", "invoice"),
    "bill": ("invoice",),
    "payment": ("invoice", "receipt", "paid"),
    "collection": ("invoice", "receipt", "paid"),
    "customer": ("dealer", "account", "client"),
    "client": ("dealer", "account", "customer"),
    "distributor": ("dealer",),
    "prospect": ("lead",),
    "enquiry": ("lead",),
    "inquiry": ("lead",),
    "converted": ("status", "conversion", "won"),
    "conversion": ("status", "converted", "won"),
    "won": ("status", "deal"),
    "lost": ("status", "lost_reason"),
    "pipeline": ("lead", "deal", "stage"),
    "opportunity": ("deal",),
    "rep": ("staff", "user", "assigned"),
    "salesperson": ("staff", "user", "assigned"),
    "employee": ("staff", "user"),
    "executive": ("staff", "user"),
    "team": ("staff", "user"),
    "owner": ("staff", "owner", "assigned"),
    "call": ("call", "dialer"),
    "dialled": ("call", "dialer"),
    "dialed": ("call", "dialer"),
    "phone": ("call",),
    "campaign": ("campaign", "dialer"),
    "stock": ("inventory",),
    "warehouse": ("inventory",),
    "unit": ("inventory", "unit"),
    "spend": ("expense",),
    "cost": ("expense", "cost"),
    "goal": ("target",),
    "quota": ("target",),
    "region": ("state", "city", "territory", "region"),
    "location": ("state", "city"),
    "visit": ("visit",),
    "order": ("order", "purchase"),
    "product": ("product", "item"),
    "item": ("product", "item"),
}


def _stem(word: str) -> str:
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith(("ches", "shes", "sses", "xes")):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def tokens(text: str | None) -> list[str]:
    """Words of a name, comment or question: snake_case and camelCase split, plurals folded."""
    if not text:
        return []
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    words = re.split(r"[^A-Za-z0-9]+", spaced.lower())
    return [_stem(w) for w in words if len(w) > 1 and not w.isdigit()]


def _document(table: CatalogTable) -> dict[str, Counter[str]]:
    """A table as words, field by field."""
    d = table.definition
    columns: Counter[str] = Counter()
    for column in d.columns:
        for word in tokens(column.name):
            columns[word] += 1.0
        for word in tokens(column.comment):
            columns[word] += COLUMN_COMMENT_WEIGHT
    return {
        "name": Counter(tokens(d.name)),
        "comment": Counter(tokens(d.comment)),
        "columns": columns,
    }


def _query(question: str, prior: list[str]) -> Counter[str]:
    """The words a question asks with, its synonyms at half weight, earlier questions less."""
    query: Counter[str] = Counter()

    def add(text: str, weight: float) -> None:
        for word in tokens(text):
            if word in _STOPWORDS:
                continue
            query[word] = max(query[word], weight)
            for alias in SYNONYMS.get(word, ()):
                for part in tokens(alias):
                    query[part] = max(query[part], weight * 0.5)

    for text in prior:
        add(text, PRIOR_QUESTION_WEIGHT)
    add(question, 1.0)
    return query


def scores(catalog: Catalog, question: str, prior: list[str] | None = None) -> dict[str, float]:
    """BM25F of each table against the question. Zero for a table the question shares no word
    with."""
    docs = {t.definition.name: _document(t) for t in catalog.tables}
    if not docs:
        return {}
    query = _query(question, prior or [])
    n = len(docs)
    mean = {
        field: (sum(sum(doc[field].values()) for doc in docs.values()) / n) or 1.0
        for field in FIELDS
    }
    holding = Counter(
        word for doc in docs.values() for word in set().union(*(doc[f] for f in FIELDS))
    )

    out: dict[str, float] = {}
    for name, doc in docs.items():
        lengths = {field: sum(doc[field].values()) for field in FIELDS}
        score = 0.0
        for word, weight in query.items():
            tf = sum(
                w * doc[field][word] / (1 - b + b * lengths[field] / mean[field])
                for field, (w, b) in FIELDS.items()
                if doc[field][word]
            )
            if not tf:
                continue
            idf = math.log(1 + (n - holding[word] + 0.5) / (holding[word] + 0.5))
            score += weight * idf * tf * (_K1 + 1) / (tf + _K1)
        out[name] = score
    return out


def _neighbours(name: str, relationships: list[Relationship]) -> list[str]:
    """Tables one join away, declared joins first."""
    found: list[tuple[int, str]] = []
    for r in relationships:
        rank = 0 if r.origin == "declared" else 1
        if r.from_table == name and r.to_table != name:
            found.append((rank, r.to_table))
        elif r.to_table == name and r.from_table != name:
            found.append((rank, r.from_table))
    return [t for _, t in sorted(found)]


def _size(table: CatalogTable) -> int:
    stats = table.stats or {}
    return int(stats.get("rows_approx") or 0)


def rank(catalog: Catalog, question: str, k: int, prior: list[str] | None = None) -> list[str]:
    """The `k` tables to describe in full for this question, best first.

    Three quarters of the places go to the best-scoring tables, then to the tables one join
    away from the top three, so a question about leads by salesperson carries the staff table
    its join needs. Any place left goes back to score. A question that matches nothing, such as
    "give me an overview", gets the largest non-empty tables rather than nothing.
    """
    scored = scores(catalog, question, prior)
    by_score = [name for name, s in sorted(scored.items(), key=lambda x: (-x[1], x[0])) if s > 0]
    if not by_score:
        sized = sorted(catalog.tables, key=lambda t: (-_size(t), t.definition.name))
        return [t.definition.name for t in sized[:k]]

    picked: list[str] = by_score[: max(1, math.ceil(k * 0.75))]
    for name in by_score[:3]:
        for neighbour in _neighbours(name, catalog.relationships):
            if len(picked) >= k:
                break
            if neighbour not in picked and neighbour in scored:
                picked.append(neighbour)
    for name in by_score:
        if len(picked) >= k:
            break
        if name not in picked:
            picked.append(name)
    return picked[:k]


def focus(
    catalog: Catalog, question: str, k: int, limit: int, prior: list[str] | None = None
) -> Catalog:
    """The catalog for one run: unchanged when every table fits in `limit`, otherwise with the
    `k` tables this question most likely needs marked for full description."""
    if len(catalog.tables) <= limit:
        return catalog
    return catalog.model_copy(update={"focus": rank(catalog, question, k, prior)})
