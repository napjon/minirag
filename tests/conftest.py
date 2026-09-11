from __future__ import annotations

import os

import pytest
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("MODEL_PROVIDER", "fixture")
os.environ.setdefault("AUTH_MODE", "demo")
os.environ.setdefault("DEPLOYMENT_PROFILE", "hosted")

TEST_DATABASE_URL = "postgresql+asyncpg://marketdesk:marketdesk@127.0.0.1:5432/marketdesk_test"
TEST_ADMIN_DATABASE_URL = "postgresql+asyncpg://postgres:devpassword@127.0.0.1:5432/postgres"
TEST_ADMIN_DATABASE_URL_TARGET = (
    "postgresql+asyncpg://postgres:devpassword@127.0.0.1:5432/marketdesk_test"
)

if not os.environ.get("MARKETDESK_KEEP_DEV_DB"):
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL
    os.environ["DATABASE_ADMIN_URL"] = TEST_ADMIN_DATABASE_URL_TARGET

from backend.config import get_settings  # noqa: E402
from backend.db import init_db, reset_engine  # noqa: E402
from backend.main import create_app  # noqa: E402
from backend.seed import seed  # noqa: E402


async def isolate_test_database() -> None:
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL
    import asyncpg

    conn = await asyncpg.connect(
        TEST_ADMIN_DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    )
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = 'marketdesk_test'")
        if not exists:
            await conn.execute("CREATE DATABASE marketdesk_test")
    finally:
        await conn.close()

    admin = await asyncpg.connect(
        TEST_ADMIN_DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://").replace(
            ":5432/postgres", ":5432/marketdesk_test"
        )
    )
    try:
        await admin.execute("GRANT USAGE ON SCHEMA public TO marketdesk")
        await admin.execute(
            "ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public "
            "GRANT ALL ON TABLES TO marketdesk"
        )
        await admin.execute(
            "ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public "
            "GRANT ALL ON SEQUENCES TO marketdesk"
        )
        await admin.execute("GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO marketdesk")
        await admin.execute("GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO marketdesk")
    finally:
        await admin.close()


@pytest.fixture(scope="session")
async def app():
    await isolate_test_database()
    get_settings.cache_clear()
    await reset_engine()
    await init_db(get_settings())
    await seed()
    application = create_app()
    yield application
    await reset_engine()


@pytest.fixture(scope="session")
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def login(client: AsyncClient, email: str = "analyst@marketdesk.test") -> str:
    response = await client.post("/v1/auth/demo", json={"email": email, "workspace": "harbor"})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]
