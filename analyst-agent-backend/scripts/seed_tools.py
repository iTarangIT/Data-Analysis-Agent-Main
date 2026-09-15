"""Give an organisation the database this deployment answers from.

    python scripts/seed_tools.py you@example.com

Reads `IOT_RO_DSN`, which is already in `.env`. Nothing is typed at the command line, so no
credential lands in a shell history.

Goes through `conn_svc.create_connection` rather than writing rows, which means the source is
opened and smoke-tested before it is stored, and the secret is encrypted by the one vault path.

Idempotent: an existing Postgres source is updated in place rather than duplicated.
"""

import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv()

from app.db.models import User  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.security import vault  # noqa: E402
from app.services import connections as conn_svc  # noqa: E402
from app.services import tables  # noqa: E402

DATABASE_NAME = "IoT database"


def _tenant_of(db, email: str) -> str:
    user = db.query(User).filter(User.email == email.lower()).one_or_none()
    if user is None:
        sys.exit(f"no account for {email}. Register in the app first, then run this again.")
    return user.tenant_id


def _upsert(db, tenant_id: str, dsn: str) -> str:
    existing = [c for c in conn_svc.list_connections(db, tenant_id) if c.kind == "postgres"]

    if not existing:
        created = conn_svc.create_connection(db, tenant_id, DATABASE_NAME, "postgres", {"dsn": dsn})
        return f"created {DATABASE_NAME} {created.id}"

    keep, *extra = sorted(existing, key=lambda c: (c.created_at, c.id))

    # Re-encrypt rather than edit: `secret_enc` is opaque, and this is the same vault call
    # `create_connection` makes. What was read from the old source is forgotten because the
    # credential may now point somewhere else entirely; the tables are listed again on next use.
    keep.name = DATABASE_NAME
    keep.secret_enc = vault.encrypt({"dsn": dsn})
    tables.forget(db, keep)

    for duplicate in extra:
        conn_svc.delete_connection(db, tenant_id, duplicate.id)

    db.commit()
    dropped = f", retired {len(extra)} duplicate(s)" if extra else ""
    return f"updated {DATABASE_NAME} {keep.id}{dropped}"


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__.strip().splitlines()[2].strip())

    dsn = os.getenv("IOT_RO_DSN")
    if not dsn:
        sys.exit("IOT_RO_DSN is not set in the environment or .env")

    db = SessionLocal()
    try:
        tenant_id = _tenant_of(db, sys.argv[1])
        print(f"organisation {tenant_id}")
        print(" ", _upsert(db, tenant_id, dsn))
    finally:
        db.close()


if __name__ == "__main__":
    main()
