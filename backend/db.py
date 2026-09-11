from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.config import Settings, get_settings
from backend.domain.models import Base

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine(settings: Settings | None = None) -> AsyncEngine:
    global _engine, _sessionmaker
    settings = settings or get_settings()
    if _engine is None:
        _engine = create_async_engine(settings.database_url, pool_pre_ping=True)
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    if _sessionmaker is None:
        get_engine()
    assert _sessionmaker is not None
    return _sessionmaker


async def reset_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None


async def session_scope() -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as session:
        yield session


async def init_db(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    # Extension creation, schema creation, and RLS policy management require the
    # migration owner. The request-time DATABASE_URL must remain a restricted
    # runtime role and must never be promoted to perform bootstrap DDL.
    admin_engine = create_async_engine(settings.admin_database_url)
    try:
        async with admin_engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await conn.run_sync(Base.metadata.create_all)
            # The repository ships an initial Alembic revision, while local
            # bootstrap uses SQLAlchemy metadata so tests and first-run seed
            # remain self-contained. Stamp only an empty version table: future
            # revisions still run normally through `alembic upgrade head`.
            await conn.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL)"
                )
            )
            version = await conn.scalar(text("SELECT version_num FROM alembic_version LIMIT 1"))
            if version is None:
                await conn.execute(
                    text("INSERT INTO alembic_version (version_num) VALUES (:version)"),
                    {"version": "0001_initial"},
                )
            await conn.execute(
                text(
                    """
                    DO $$
                    DECLARE t text;
                    BEGIN
                      FOR t IN
                        SELECT unnest(ARRAY[
                          'sources','documents','document_versions','chunks','products',
                          'price_observations','spend_records','order_records','sourcing_events',
                          'detection_findings','drafts','draft_revisions','review_decisions',
                          'jobs','interactions','feedback','outbox_events','audit_events','memberships'
                        ])
                      LOOP
                        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
                        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
                        EXECUTE format(
                          'DROP POLICY IF EXISTS workspace_isolation ON %I', t
                        );
                        EXECUTE format(
                          'CREATE POLICY workspace_isolation ON %I
                           USING (workspace_id =
                             NULLIF(current_setting(''app.workspace_id'', true), '''')::uuid)
                           WITH CHECK (workspace_id =
                             NULLIF(current_setting(''app.workspace_id'', true), '''')::uuid)',
                          t
                        );
                      END LOOP;
                    END $$;
                    """
                )
            )
    finally:
        await admin_engine.dispose()


async def apply_rls(session: AsyncSession, workspace_id: str, principal_id: str) -> None:
    await session.execute(
        text("SELECT set_config('app.workspace_id', :ws, true)"), {"ws": workspace_id}
    )
    await session.execute(
        text("SELECT set_config('app.principal_id', :pid, true)"), {"pid": principal_id}
    )
