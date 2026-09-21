import hashlib
import os
import tempfile
from functools import lru_cache
from pathlib import Path

import httpx

from app.config import get_settings
from app.logging import log
from app.services.errors import DomainError, SourceUnavailable

DELETE_BATCH = 1000


@lru_cache
def _client() -> httpx.Client:
    settings = get_settings()
    if settings.supabase_secret_key is None:
        raise RuntimeError("FILE_STORE_BACKEND=supabase needs SUPABASE_SECRET_KEY")
    return httpx.Client(
        base_url=f"{settings.supabase_url}/storage/v1",
        headers={"apikey": settings.supabase_secret_key.get_secret_value()},
        timeout=httpx.Timeout(60.0, connect=10.0),
    )


def _root() -> Path:
    return Path(get_settings().file_store_dir)


def _cached(sha256: str) -> Path:
    return _root() / "cache" / f"{sha256}.parquet"


def _unreachable(e: httpx.HTTPError) -> SourceUnavailable:
    log.warning("storage.unreachable", error=str(e))
    return SourceUnavailable("file storage could not be reached just now - try again")


def put(path: Path, key: str, sha256: str) -> None:
    settings = get_settings()
    if settings.file_store_backend == "local":
        target = _root() / key
        target.parent.mkdir(parents=True, exist_ok=True)
        path.replace(target)
        return
    try:
        with path.open("rb") as body:
            response = _client().post(
                f"/object/{settings.storage_bucket}/{key}",
                content=body,
                headers={"content-type": "application/octet-stream", "x-upsert": "true"},
            )
        if response.status_code == 413:
            raise DomainError("a converted file is larger than file storage accepts")
        response.raise_for_status()
    except httpx.HTTPError as e:
        raise _unreachable(e) from e
    cached = _cached(sha256)
    cached.parent.mkdir(parents=True, exist_ok=True)
    path.replace(cached)


def local(key: str, sha256: str) -> Path:
    settings = get_settings()
    if settings.file_store_backend == "local":
        return _root() / key
    cached = _cached(sha256)
    if cached.exists():
        return cached
    cached.parent.mkdir(parents=True, exist_ok=True)
    fd, partial = tempfile.mkstemp(dir=cached.parent, suffix=".part")
    digest = hashlib.sha256()
    try:
        with (
            os.fdopen(fd, "wb") as out,
            _client().stream("GET", f"/object/authenticated/{settings.storage_bucket}/{key}") as r,
        ):
            r.raise_for_status()
            for chunk in r.iter_bytes():
                digest.update(chunk)
                out.write(chunk)
        if digest.hexdigest() != sha256:
            log.warning("storage.corrupt", key=key)
            raise SourceUnavailable("a stored file came back damaged - try again")
        os.replace(partial, cached)
    except httpx.HTTPError as e:
        raise _unreachable(e) from e
    finally:
        Path(partial).unlink(missing_ok=True)
    return cached


def delete(parts: list[dict]) -> None:
    settings = get_settings()
    for part in parts:
        _cached(part["sha256"]).unlink(missing_ok=True)
    if settings.file_store_backend == "local":
        for part in parts:
            (_root() / part["storage_key"]).unlink(missing_ok=True)
        return
    keys = [part["storage_key"] for part in parts]
    try:
        for start in range(0, len(keys), DELETE_BATCH):
            _client().request(
                "DELETE",
                f"/object/{settings.storage_bucket}",
                json={"prefixes": keys[start : start + DELETE_BATCH]},
            ).raise_for_status()
    except httpx.HTTPError as e:
        raise _unreachable(e) from e
