"""Pick which source answers a question, before the agent is built.

This deployment has two sources that never change: a Postgres database holding everything
already recorded, and a web dashboard showing only the present moment. Choosing between them
is mechanical -- live now, or already happened -- so it is not a decision to put in front of
a person on every question.

Routing here rather than inside the agent is deliberate. Binding both tool sets to one agent
would merge two schemas into the SQL guard's allowlist, make `WEB_CAPABILITY`'s promise that
there is no SQL here into a lie, and pay for a browser login before a purely historic question
could start. Choosing first keeps a run bound to exactly one connection, which is what every
layer below this already assumes.

The model call is the only impure part, and it is injected in tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import structlog

from app.agent.prompts import ROUTER_SYSTEM
from app.db.models import Connection
from app.llm import get_llm

log = structlog.get_logger(__name__)

LIVE = "live"
HISTORIC = "historic"

# The dashboard is the only live source. Everything else has already been written down.
LIVE_KINDS = ("web",)


@dataclass(frozen=True)
class Route:
    connection: Connection
    # `live` or `historic`, or the reason a model was never asked. Logged, never shown.
    reason: str


def _newest_first(connections: list[Connection]) -> list[Connection]:
    """`list_connections` has no ORDER BY, so row order is whatever Postgres felt like.

    Nothing stops a tenant holding two Postgres connections either, so "the database one" has
    to be resolved deterministically rather than by taking whichever came back first.
    """
    return sorted(connections, key=lambda c: (c.created_at, c.id), reverse=True)


def pick(connections: list[Connection], live: bool) -> Connection | None:
    wanted = [c for c in _newest_first(connections) if (c.kind in LIVE_KINDS) == live]
    return wanted[0] if wanted else None


def classify(question: str) -> str:
    """Ask the model whether a question is about now or about what has been recorded.

    Any failure answers `historic`. That is the safer default in both directions: the database
    answers far more kinds of question than the dashboard does, and it cannot fail on a cold
    browser session.
    """
    prompt = ROUTER_SYSTEM.format(today=date.today().isoformat())
    try:
        reply = get_llm().invoke([("system", prompt), ("human", question)])
    except Exception as e:
        log.warning("router.failed", error=str(e))
        return HISTORIC

    # Gemini 3 returns content blocks rather than a string, so read `.text`, which flattens
    # both shapes. `.content` would give back a Python repr.
    answer = (reply.text or "").strip().lower()
    return LIVE if answer.startswith(LIVE) else HISTORIC


def choose_source(question: str, connections: list[Connection]) -> Route:
    """Route one question. Raises nothing: a caller with no connections gets no route.

    With only one source there is nothing to decide and no reason to spend a model call on it.
    """
    usable = [c for c in connections if c.deleted_at is None]
    if not usable:
        raise ValueError("no connections to route between")

    if len(usable) == 1:
        return Route(connection=usable[0], reason="only source")

    verdict = classify(question)
    chosen = pick(usable, live=verdict == LIVE)

    if chosen is None:
        # The model asked for a kind this tenant does not have. Fall back rather than refuse:
        # a question answered from the wrong-but-available source still beats an error.
        chosen = _newest_first(usable)[0]
        log.info("router.no_source_of_kind", verdict=verdict, chosen=chosen.kind)
        return Route(connection=chosen, reason=f"{verdict}, no source of that kind")

    log.info("router.chose", verdict=verdict, kind=chosen.kind, connection_id=chosen.id)
    return Route(connection=chosen, reason=verdict)
