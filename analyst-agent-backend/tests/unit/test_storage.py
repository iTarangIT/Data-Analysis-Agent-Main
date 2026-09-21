import hashlib
from pathlib import Path

import pytest

from app.connectors import storage
from app.services.errors import DomainError, SourceUnavailable

KEY = "t_a/c1/f1/sales-0123456789ab.parquet"


def _staged(tmp_path: Path, body: bytes = b"PAR1 parquet bytes PAR1") -> tuple[Path, str]:
    path = tmp_path / "staging" / "sales.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return path, hashlib.sha256(body).hexdigest()


@pytest.fixture
def local_store(tmp_path, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "file_store_dir", str(tmp_path), raising=False)
    return tmp_path


def test_a_local_object_lives_at_its_key(local_store):
    path, digest = _staged(local_store)

    storage.put(path, KEY, digest)

    assert storage.local(KEY, digest) == local_store / KEY
    assert (local_store / KEY).read_bytes() == b"PAR1 parquet bytes PAR1"
    assert not path.exists()


def test_deleting_a_local_object_removes_it(local_store):
    path, digest = _staged(local_store)
    storage.put(path, KEY, digest)

    storage.delete([{"storage_key": KEY, "sha256": digest}])

    assert not (local_store / KEY).exists()


def test_the_client_sends_the_secret_key_as_apikey_only(supabase_storage):
    client = storage._client()

    assert client.headers["apikey"] == "sb_secret_test"
    assert "authorization" not in client.headers
    assert str(client.base_url).endswith("/storage/v1/")


def test_an_upload_goes_to_the_bucket_and_stays_in_the_cache(supabase_storage, tmp_path):
    path, digest = _staged(tmp_path)

    storage.put(path, KEY, digest)

    assert supabase_storage.objects == {KEY: b"PAR1 parquet bytes PAR1"}
    assert storage.local(KEY, digest) == tmp_path / "cache" / f"{digest}.parquet"
    assert [method for method, _ in supabase_storage.requests] == ["POST"]


def test_a_cache_miss_downloads_once(supabase_storage, tmp_path):
    path, digest = _staged(tmp_path)
    storage.put(path, KEY, digest)
    (tmp_path / "cache" / f"{digest}.parquet").unlink()

    first = storage.local(KEY, digest)
    second = storage.local(KEY, digest)

    assert first == second
    assert first.read_bytes() == b"PAR1 parquet bytes PAR1"
    assert [method for method, _ in supabase_storage.requests] == ["POST", "GET"]


def test_a_damaged_download_is_refused_and_not_cached(supabase_storage, tmp_path):
    path, digest = _staged(tmp_path)
    storage.put(path, KEY, digest)
    (tmp_path / "cache" / f"{digest}.parquet").unlink()
    supabase_storage.objects[KEY] = b"something else"

    with pytest.raises(SourceUnavailable, match="damaged"):
        storage.local(KEY, digest)

    assert list((tmp_path / "cache").iterdir()) == []


def test_deleting_removes_the_object_and_the_cache_entry(supabase_storage, tmp_path):
    path, digest = _staged(tmp_path)
    storage.put(path, KEY, digest)

    storage.delete([{"storage_key": KEY, "sha256": digest}])

    assert supabase_storage.objects == {}
    assert not (tmp_path / "cache" / f"{digest}.parquet").exists()


def test_deletes_are_sent_in_batches_of_a_thousand(supabase_storage):
    parts = [{"storage_key": f"t_a/c1/f{i}/t.parquet", "sha256": f"{i:064x}"} for i in range(1001)]

    storage.delete(parts)

    assert [method for method, _ in supabase_storage.requests] == ["DELETE", "DELETE"]


def test_storage_that_is_down_is_a_503_not_a_crash(supabase_storage, tmp_path):
    path, digest = _staged(tmp_path)
    supabase_storage.down = True

    with pytest.raises(SourceUnavailable, match="could not be reached"):
        storage.put(path, KEY, digest)


def test_an_object_too_large_to_store_is_refused_plainly(supabase_storage, tmp_path, monkeypatch):
    import httpx

    path, digest = _staged(tmp_path)
    monkeypatch.setattr(
        storage._client(), "_transport", httpx.MockTransport(lambda r: httpx.Response(413))
    )

    with pytest.raises(DomainError, match="larger than file storage accepts"):
        storage.put(path, KEY, digest)
