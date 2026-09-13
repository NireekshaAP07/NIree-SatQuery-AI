"""
Shared pytest fixtures for SatQuery AI integration & unit tests.

Database strategy: TRANSACTION ROLLBACK ISOLATION
  - A single real Postgres connection is checked out at the start of each test.
  - Every ORM operation in the test runs inside a SAVEPOINT.
  - After the test completes (pass or fail), the outer transaction is rolled back,
    leaving the DB in its original state — no cleanup SQL required.
  - This means tests run against the real schema (PostGIS, enums, FK constraints)
    without polluting the database.

Storage strategy:
  - All tests are forced to use LocalStorageBackend pointing at a temp directory.
  - The temp directory is wiped after each test.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Force local storage and safe test env before importing app modules
os.environ.setdefault("STORAGE_BACKEND", "local")
os.environ.setdefault("APP_ENV", "development")

from app.main import app
from app.core.database import Base, get_db
from app.core.config import get_settings


# ─── Storage Fixture ───────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_storage_root(tmp_path):
    """A fresh temp directory used as the local storage root for each test."""
    root = tmp_path / "storage"
    for subdir in ("raw", "derived", "tiles", "reports", "tmp"):
        (root / subdir).mkdir(parents=True, exist_ok=True)
    yield root
    shutil.rmtree(root, ignore_errors=True)


@pytest.fixture(autouse=True)
def patch_storage(tmp_storage_root):
    """
    Auto-used for every test: redirects get_storage() to a temp local backend.
    Prevents any test from touching data/ or MinIO.
    """
    from app.core.storage import LocalStorageBackend

    fake_backend = LocalStorageBackend(root=tmp_storage_root)
    with patch("app.core.storage.get_storage", return_value=fake_backend), \
         patch("app.routers.assets.get_storage", return_value=fake_backend), \
         patch("app.routers.reports.get_storage", return_value=fake_backend):
        yield fake_backend


# ─── Database Fixtures (Transaction Rollback) ──────────────────────────────────

@pytest_asyncio.fixture()
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Yields an AsyncSession whose writes are rolled back after the test.

    Uses nested transactions (SAVEPOINT) so each test starts with a clean slate
    without dropping or recreating tables.
    """
    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False)

    connection = await engine.connect()
    # Begin outer transaction — everything inside will be rolled back
    trans = await connection.begin()

    session_factory = async_sessionmaker(
        bind=connection,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
    )
    session = session_factory()

    try:
        yield session
    finally:
        await session.close()
        await trans.rollback()
        await connection.close()
        await engine.dispose()


# ─── FastAPI Test Client ────────────────────────────────────────────────────────

@pytest_asyncio.fixture()
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """
    Yields an async HTTPX client wired to the FastAPI ASGI app.
    Overrides the get_db dependency so API calls use the same rolled-back session.
    """
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c
    app.dependency_overrides.clear()


# ─── Sample File Helpers ────────────────────────────────────────────────────────

@pytest.fixture()
def sample_tif_bytes() -> bytes:
    """Returns the raw bytes of the sample optical GeoTIFF from sample_data/."""
    path = "sample_data/isro_optical_2026.tif"
    try:
        with open(path, "rb") as f:
            return f.read()
    except FileNotFoundError:
        # If run outside the project root, return a minimal 1-pixel TIFF stub
        # so pure unit tests don't need the real file.
        import io
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (1, 1), color=(128, 128, 128)).save(buf, format="TIFF")
        return buf.getvalue()
