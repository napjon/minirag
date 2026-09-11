from __future__ import annotations

import os

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from backend.api.router import router
from backend.config import get_settings
from backend.db import get_engine, init_db
from backend.jobs.service import IdempotencyConflict


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.web_origin, "http://127.0.0.1:3130", "http://localhost:3130"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)

    @app.exception_handler(IdempotencyConflict)
    async def _idempotency_conflict(_request: Request, exc: IdempotencyConflict) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.on_event("startup")
    async def _startup() -> None:
        if os.environ.get("MARKETDESK_MIGRATE_ON_START") == "1":
            await init_db(settings)
            return
        engine = get_engine(settings)
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    return app


app = create_app()


def run() -> None:
    settings = get_settings()
    uvicorn.run("backend.main:app", host=settings.api_host, port=settings.api_port, reload=False)
