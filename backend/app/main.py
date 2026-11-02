"""FastAPI application factory."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app import models as _models  # noqa: F401  (register every model before the first request)
from app.audit.router import router as audit_router
from app.auth.router import router as auth_router
from app.auth.users_router import router as users_router
from app.core.config import get_settings
from app.core.db import get_session
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging, request_logging_middleware
from app.demo.router import router as demo_router
from app.dms.router import router as dms_router
from app.master.router import router as master_router
from app.notifications.router import router as notifications_router
from app.workflow.jobs import scheduler_loop
from app.workflow.router import router as workflow_router

log = logging.getLogger("app")


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        task = None
        if settings.scheduler_enabled:
            task = asyncio.create_task(scheduler_loop(settings.scheduler_interval_seconds))
        yield
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    app = FastAPI(
        lifespan=lifespan,
        title=settings.app_name,
        version="0.1.0",
        docs_url=None if settings.is_production else "/api/docs",
        openapi_url=None if settings.is_production else "/api/openapi.json",
    )
    install_error_handlers(app)
    app.middleware("http")(request_logging_middleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["x-request-id"],
    )

    api = APIRouter(prefix="/api")

    @api.get("/health", tags=["system"])
    async def health(
        response: Response,
        session: AsyncSession = Depends(get_session),  # noqa: B008
    ) -> dict[str, Any]:
        try:
            await session.execute(text("SELECT 1"))
        except Exception:
            log.exception("health_db_failed")
            response.status_code = 503
            return {"status": "degraded", "db": "error", "version": app.version}
        return {"status": "ok", "db": "ok", "version": app.version}

    api.include_router(auth_router)
    api.include_router(users_router)
    api.include_router(workflow_router)
    api.include_router(master_router)
    api.include_router(audit_router)
    api.include_router(dms_router)
    api.include_router(notifications_router)
    api.include_router(demo_router)
    app.include_router(api)
    return app


app = create_app()
