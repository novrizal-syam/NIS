"""FastAPI application factory."""

import logging
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_session
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging, request_logging_middleware

log = logging.getLogger("app")


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
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

    app.include_router(api)
    return app


app = create_app()
