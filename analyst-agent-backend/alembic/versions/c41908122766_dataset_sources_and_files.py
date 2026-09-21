"""dataset sources and files

Revision ID: c41908122766
Revises: 62162b953aa7
Create Date: 2026-09-21 10:36:25.643389

"""
import hashlib
import shutil
import uuid
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import duckdb
from alembic import op
import sqlalchemy as sa

from app.config import get_settings
from app.security import vault


revision: str = 'c41908122766'
down_revision: str | None = '62162b953aa7'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LOST = "file lost, re-upload it"

connections = sa.table(
    "connections",
    sa.column("id", sa.String),
    sa.column("tenant_id", sa.String),
    sa.column("kind", sa.String),
    sa.column("secret_enc", sa.Text),
    sa.column("deleted_at", sa.DateTime(timezone=True)),
)
sources = sa.table(
    "dataset_sources",
    sa.column("id", sa.String),
    sa.column("connection_id", sa.String),
    sa.column("origin", sa.String),
    sa.column("label", sa.String),
    sa.column("combine", sa.Boolean),
    sa.column("status", sa.String),
)
files = sa.table(
    "dataset_files",
    sa.column("id", sa.String),
    sa.column("source_id", sa.String),
    sa.column("connection_id", sa.String),
    sa.column("remote_id", sa.String),
    sa.column("name", sa.String),
    sa.column("status", sa.String),
    sa.column("reason", sa.Text),
    sa.column("parts", sa.JSON),
    sa.column("synced_at", sa.DateTime(timezone=True)),
)
connection_tables = sa.table(
    "connection_tables", sa.column("connection_id", sa.String), sa.column("name", sa.String)
)


def _move(root: Path, tenant_id: str, connection_id: str, file_id: str, source: dict) -> dict:
    src = Path(source["path"])
    with src.open("rb") as f:
        digest = hashlib.file_digest(f, "sha256").hexdigest()
    with duckdb.connect() as con:
        types = {
            name: type_
            for name, type_, *_ in con.execute(
                "DESCRIBE SELECT * FROM read_parquet(?)", [str(src)]
            ).fetchall()
        }
        (rows,) = con.execute("SELECT count(*) FROM read_parquet(?)", [str(src)]).fetchone()
    key = f"{tenant_id}/{connection_id}/{file_id}/{source['table']}-{digest[:12]}.parquet"
    dest = root / key
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(src, dest)
    profile = source.get("profile") or {
        "row_count": rows,
        "header_row": 0,
        "dropped_total_rows": 0,
        "columns": {name: name for name in types},
        "date_range": {},
    }
    return {
        "sheet": "",
        "table": source["table"],
        "storage_key": key,
        "sha256": digest,
        "bytes": dest.stat().st_size,
        "profile": {**profile, "types": types},
    }


def _move_dataset(root: Path, connection_id: str, tenant_id: str, secret: str) -> None:
    bind = op.get_bind()
    held = vault.decrypt(secret)["sources"]
    by_file: dict[str, list[dict]] = defaultdict(list)
    for source in held:
        by_file[source.get("file") or Path(source["path"]).name].append(source)

    source_id = str(uuid.uuid4())
    rows, kept = [], set()
    for name, parts in by_file.items():
        file_id = str(uuid.uuid4())
        row = {
            "id": file_id,
            "source_id": source_id,
            "connection_id": connection_id,
            "remote_id": name,
            "name": name,
            "synced_at": datetime.now(UTC),
        }
        if all(Path(p["path"]).exists() for p in parts):
            moved = [_move(root, tenant_id, connection_id, file_id, p) for p in parts]
            rows.append({**row, "status": "ready", "reason": None, "parts": moved})
            kept |= {p["table"] for p in parts}
        else:
            rows.append({**row, "status": "failed", "reason": LOST, "parts": []})

    op.bulk_insert(
        sources,
        [
            {
                "id": source_id,
                "connection_id": connection_id,
                "origin": "upload",
                "label": "Uploads",
                "combine": False,
                "status": "active",
            }
        ],
    )
    if rows:
        op.bulk_insert(files, rows)
    bind.execute(
        sa.delete(connection_tables).where(
            connection_tables.c.connection_id == connection_id,
            connection_tables.c.name.not_in(kept),
        )
    )
    bind.execute(
        sa.update(connections)
        .where(connections.c.id == connection_id)
        .values(secret_enc=vault.encrypt({}))
    )
    for batch in {Path(s["path"]).parent for s in held}:
        if batch.is_dir() and not any(batch.iterdir()):
            batch.rmdir()


def upgrade() -> None:
    op.create_table('dataset_sources',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('connection_id', sa.String(length=36), nullable=False),
    sa.Column('origin', sa.String(length=20), nullable=False),
    sa.Column('remote_id', sa.String(length=200), nullable=True),
    sa.Column('resource_key', sa.String(length=200), nullable=True),
    sa.Column('label', sa.String(length=500), nullable=False),
    sa.Column('rules', sa.JSON(), nullable=True),
    sa.Column('combine', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('seen_folders', sa.JSON(), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['connection_id'], ['connections.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_dataset_sources_connection_id'), 'dataset_sources', ['connection_id'], unique=False)
    op.create_index('uq_dataset_sources_upload', 'dataset_sources', ['connection_id'], unique=True, postgresql_where=sa.text("origin = 'upload'"))
    op.create_table('dataset_files',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('source_id', sa.String(length=36), nullable=False),
    sa.Column('connection_id', sa.String(length=36), nullable=False),
    sa.Column('remote_id', sa.String(length=1000), nullable=False),
    sa.Column('name', sa.String(length=1000), nullable=False),
    sa.Column('mime', sa.String(length=200), nullable=True),
    sa.Column('remote_version', sa.String(length=100), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('bytes', sa.BigInteger(), nullable=True),
    sa.Column('parts', sa.JSON(), nullable=False),
    sa.Column('synced_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['connection_id'], ['connections.id'], ),
    sa.ForeignKeyConstraint(['source_id'], ['dataset_sources.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('source_id', 'remote_id', name='uq_dataset_files_source_id_remote_id')
    )
    op.create_index(op.f('ix_dataset_files_connection_id'), 'dataset_files', ['connection_id'], unique=False)
    op.add_column('connections', sa.Column('sync_status', sa.String(length=20), nullable=True))
    op.add_column('connections', sa.Column('synced_at', sa.DateTime(timezone=True), nullable=True))

    root = Path(get_settings().file_store_dir)
    datasets = op.get_bind().execute(
        sa.select(connections.c.id, connections.c.tenant_id, connections.c.secret_enc).where(
            connections.c.kind == "file", connections.c.deleted_at.is_(None)
        )
    ).all()
    for connection_id, tenant_id, secret in datasets:
        _move_dataset(root, connection_id, tenant_id, secret)


def downgrade() -> None:
    bind = op.get_bind()
    root = Path(get_settings().file_store_dir)
    held: dict[str, list[dict]] = defaultdict(list)
    ready = bind.execute(
        sa.select(files.c.connection_id, files.c.name, files.c.parts)
        .join(sources, sources.c.id == files.c.source_id)
        .where(sources.c.origin == "upload", files.c.status == "ready")
    ).all()
    for connection_id, name, parts in ready:
        held[connection_id] += [
            {
                "table": p["table"],
                "path": str(root / p["storage_key"]),
                "file": name,
                "origin": "upload",
                "profile": p["profile"],
            }
            for p in parts
        ]
    datasets = bind.execute(
        sa.select(connections.c.id).where(
            connections.c.kind == "file", connections.c.deleted_at.is_(None)
        )
    ).scalars().all()
    for connection_id in datasets:
        bind.execute(
            sa.update(connections)
            .where(connections.c.id == connection_id)
            .values(secret_enc=vault.encrypt({"sources": held[connection_id]}))
        )

    op.drop_column('connections', 'synced_at')
    op.drop_column('connections', 'sync_status')
    op.drop_index(op.f('ix_dataset_files_connection_id'), table_name='dataset_files')
    op.drop_table('dataset_files')
    op.drop_index('uq_dataset_sources_upload', table_name='dataset_sources', postgresql_where=sa.text("origin = 'upload'"))
    op.drop_index(op.f('ix_dataset_sources_connection_id'), table_name='dataset_sources')
    op.drop_table('dataset_sources')
