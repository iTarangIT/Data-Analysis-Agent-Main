"""Give an organisation the two sources this deployment answers from.

    python scripts/seed_tools.py you@example.com

Reads `IOT_RO_DSN` for the database and `INTELLICAR_URL` / `INTELLICAR_ID` /
`INTELLICAR_PASSWORD` for the dashboard, all of which are already in `.env`. Nothing is typed
at the command line, so no credential lands in a shell history.

Goes through `conn_svc.create_connection` rather than writing rows, which means the Postgres
source is opened and smoke-tested before it is stored, and both secrets are encrypted by the
one vault path. A web source is not testable this way -- the agent does not smoke-test one at
creation either, because it costs a browser session -- so a wrong dashboard password surfaces
on the first live question instead.

Idempotent: a source of the same kind is updated in place rather than duplicated. That matters
because the router resolves a kind to one connection, and two Postgres rows would make which
one answers depend on row order.
"""

import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv()

from app.db.models import Connection, User  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.security import vault  # noqa: E402
from app.services import connections as conn_svc  # noqa: E402

# The names are what the router reads, so they say what the source is rather than what it is
# implemented with.
DATABASE_NAME = "IoT database"
DASHBOARD_NAME = "Live dashboard"


def _require(*names: str) -> list[str]:
    values = []
    for name in names:
        value = os.getenv(name)
        if not value:
            sys.exit(f"{name} is not set in the environment or .env")
        values.append(value)
    return values


def _tenant_of(db, email: str) -> str:
    user = db.query(User).filter(User.email == email.lower()).one_or_none()
    if user is None:
        sys.exit(f"no account for {email}. Register in the app first, then run this again.")
    return user.tenant_id


def _upsert(db, tenant_id: str, name: str, kind: str, secret: dict) -> str:
    existing = [
        c
        for c in conn_svc.list_connections(db, tenant_id)
        if c.kind == kind and c.deleted_at is None
    ]

    if not existing:
        created = conn_svc.create_connection(db, tenant_id, name, kind, secret)
        return f"created {name} ({kind}) {created.id}"

    keep, *extra = sorted(existing, key=lambda c: (c.created_at, c.id))

    # Re-encrypt rather than edit: `secret_enc` is opaque, and this is the same vault call
    # `create_connection` makes. The schema cache is dropped because the credential may now
    # point somewhere else entirely.
    keep.name = name
    keep.secret_enc = vault.encrypt(secret)
    keep.schema_cache = None
    keep.schema_cached_at = None

    for duplicate in extra:
        conn_svc.delete_connection(db, tenant_id, duplicate.id)

    db.commit()
    dropped = f", retired {len(extra)} duplicate(s)" if extra else ""
    return f"updated {name} ({kind}) {keep.id}{dropped}"


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__.strip().splitlines()[2].strip())

    dsn, url, username, password = _require(
        "IOT_RO_DSN", "INTELLICAR_URL", "INTELLICAR_ID", "INTELLICAR_PASSWORD"
    )

    db = SessionLocal()
    try:
        tenant_id = _tenant_of(db, sys.argv[1])
        print(f"organisation {tenant_id}")

        # Postgres first: it is the one that gets smoke-tested, so a bad DSN fails before the
        # dashboard row is written and the tree is left in a half-seeded state.
        print(" ", _upsert(db, tenant_id, DATABASE_NAME, "postgres", {"dsn": dsn}))
        print(
            " ",
            _upsert(
                db,
                tenant_id,
                DASHBOARD_NAME,
                "web",
                {"url": url, "username": username, "password": password},
            ),
        )

        rows = db.query(Connection).filter_by(tenant_id=tenant_id, deleted_at=None)
        print(f"  sources now: {', '.join(sorted(c.name for c in rows))}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
