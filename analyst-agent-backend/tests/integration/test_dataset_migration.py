from pathlib import Path

import duckdb
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

pytestmark = pytest.mark.integration

BEFORE = "62162b953aa7"


def _parquet(path: Path, sql: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    duckdb.sql(f"COPY ({sql}) TO '{path.as_posix()}' (FORMAT parquet)")
    return str(path)


@pytest.fixture
def alembic_config() -> Config:
    config = Config()
    config.set_main_option("script_location", "alembic")
    return config


@pytest.fixture
def root(tmp_path, monkeypatch) -> Path:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "file_store_dir", str(tmp_path), raising=False)
    return tmp_path


@pytest.fixture
def seeded(clean_app_db, alembic_config, root):
    from app.security import vault
    from app.services.connections import ensure_tenant

    ensure_tenant(clean_app_db, "t_test")
    command.downgrade(alembic_config, BEFORE)
    batch = root / "t_test" / "c1"
    sources = [
        {
            "table": "sales",
            "path": _parquet(batch / "b1" / "sales.parquet", "SELECT 1 AS units UNION ALL SELECT 2"),
            "file": "sales.csv",
            "origin": "upload",
            "profile": {"row_count": 2},
        },
        {"table": "ledger", "path": _parquet(batch / "ledger.parquet", "SELECT 'a' AS name")},
        {
            "table": "gone",
            "path": str(batch / "b2" / "gone.parquet"),
            "file": "gone.csv",
            "origin": "upload",
            "profile": {"row_count": 1},
        },
    ]
    clean_app_db.execute(
        text(
            "INSERT INTO connections (id, tenant_id, name, kind, secret_enc) "
            "VALUES ('c1', 't_test', 'July', 'file', :secret)"
        ),
        {"secret": vault.encrypt({"sources": sources})},
    )
    clean_app_db.execute(
        text(
            "INSERT INTO connection_tables (id, connection_id, name, selected) VALUES "
            "('ct1', 'c1', 'sales', true), ('ct2', 'c1', 'ledger', true), "
            "('ct3', 'c1', 'gone', true)"
        )
    )
    clean_app_db.commit()
    try:
        yield clean_app_db
    finally:
        clean_app_db.rollback()
        command.upgrade(alembic_config, "head")


def _secret(db) -> dict:
    from app.security import vault

    db.rollback()
    return vault.decrypt(db.execute(text("SELECT secret_enc FROM connections")).scalar_one())


def test_the_upgrade_moves_every_dataset_into_rows(seeded, alembic_config, root):
    command.upgrade(alembic_config, "head")

    rows = seeded.execute(
        text("SELECT name, status, reason, parts FROM dataset_files ORDER BY name")
    ).all()
    tables = seeded.execute(text("SELECT name FROM connection_tables")).scalars().all()

    assert [(name, status, reason) for name, status, reason, _ in rows] == [
        ("gone.csv", "failed", "file lost, re-upload it"),
        ("ledger.parquet", "ready", None),
        ("sales.csv", "ready", None),
    ]
    parts = {part["table"]: part for *_, held in rows for part in held}
    assert set(parts) == {"ledger", "sales"}
    assert all((root / part["storage_key"]).exists() for part in parts.values())
    assert not (root / "t_test" / "c1" / "b1").exists()
    assert parts["ledger"]["profile"]["row_count"] == 1
    assert parts["ledger"]["profile"]["types"] == {"name": "VARCHAR"}
    assert sorted(tables) == ["ledger", "sales"]
    assert _secret(seeded) == {}


def test_the_downgrade_rebuilds_the_file_list(seeded, alembic_config):
    command.upgrade(alembic_config, "head")
    seeded.rollback()

    command.downgrade(alembic_config, BEFORE)

    sources = _secret(seeded)["sources"]
    assert sorted((s["table"], s["file"]) for s in sources) == [
        ("ledger", "ledger.parquet"),
        ("sales", "sales.csv"),
    ]
    assert all(Path(s["path"]).exists() for s in sources)
