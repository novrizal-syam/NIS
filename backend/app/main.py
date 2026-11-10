"""FastAPI application factory."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app import models as _models  # noqa: F401  (register every model before the first request)
from app.audit.router import router as audit_router
from app.auth.email_admin import router as email_admin_router
from app.auth.onboarding import router as onboarding_router
from app.auth.roles_router import router as roles_router
from app.auth.router import router as auth_router
from app.auth.users_router import router as users_router
from app.billing.router import router as billing_router
from app.capex.router import router as capex_router
from app.contract.router import router as contract_router
from app.core import openapi_meta
from app.core.config import get_settings
from app.core.db import get_session, session_scope, use_session_provider
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging, request_logging_middleware
from app.crm.quotation_router import router as quotation_router
from app.crm.router import router as crm_router
from app.demo.router import router as demo_router
from app.dms.docs_router import public_router as dms_public_router
from app.dms.docs_router import router as dms_docs_router
from app.dms.router import router as dms_router
from app.finance.ledger_router import router as ledger_router
from app.finance.router import router as finance_router
from app.integrations.router import router as integrations_router
from app.inventory.router import router as inventory_router
from app.letters.router import router as letters_router
from app.lms.router import router as lms_router
from app.maintenance.router import router as maintenance_router
from app.master.router import router as master_router
from app.notifications.router import router as notifications_router
from app.operations.router import router as operations_router
from app.payroll.router import router as payroll_router
from app.portal.router import router as portal_router
from app.procurement.po_router import router as po_router
from app.procurement.router import router as procurement_router
from app.project.budget_router import router as budget_router
from app.project.router import router as project_router
from app.qhse.router import router as qhse_router
from app.reporting.access_review import router as reports_router
from app.reporting.dashboard_router import router as dashboard_router
from app.services.storage import get_storage, use_storage_provider
from app.setup import service as setup_service
from app.setup.router import router as setup_router
from app.sod.router import router as sod_router
from app.tax.router import close_router
from app.tax.router import router as tax_router
from app.tender.router import router as tender_router
from app.treasury.router import router as treasury_router
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
        description=openapi_meta.DESCRIPTION,
        openapi_tags=openapi_meta.openapi_tags(),
        # Interactive docs only outside production; the spec is exported to docs/api/.
        docs_url=None if settings.is_production else "/api/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/api/openapi.json",
    )
    install_error_handlers(app)
    # Background tasks and middleware resolve sessions like endpoints (overridable in tests).
    use_session_provider(lambda: app.dependency_overrides.get(get_session, get_session))
    use_storage_provider(lambda: app.dependency_overrides.get(get_storage, get_storage))

    @app.middleware("http")
    async def setup_guard(request: Request, call_next: Any) -> Any:
        """Until first-run setup is finished only health, setup and sign-in answer (sign-in
        lets the setup admin resume the wizard after a reload)."""
        path = request.url.path
        open_paths = ("/api/health", "/api/setup", "/api/auth/")
        if path.startswith("/api/") and not path.startswith(open_paths):
            async with session_scope() as session:
                completed = await setup_service.is_completed(session)
            if not completed:
                return JSONResponse(
                    {"code": "SETUP_REQUIRED", "message": "Penyiapan awal belum selesai."}, 423
                )
        return await call_next(request)

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
    api.include_router(onboarding_router)
    api.include_router(email_admin_router)
    api.include_router(users_router)
    api.include_router(roles_router)
    api.include_router(workflow_router)
    api.include_router(master_router)
    api.include_router(audit_router)
    api.include_router(dms_router)
    api.include_router(notifications_router)
    api.include_router(demo_router)
    api.include_router(setup_router)
    api.include_router(sod_router)
    api.include_router(reports_router)
    api.include_router(crm_router)
    api.include_router(quotation_router)
    api.include_router(contract_router)
    api.include_router(project_router)
    api.include_router(tender_router)
    api.include_router(budget_router)
    api.include_router(procurement_router)
    api.include_router(po_router)
    api.include_router(inventory_router)
    api.include_router(finance_router)
    api.include_router(operations_router)
    api.include_router(maintenance_router)
    api.include_router(qhse_router)
    api.include_router(billing_router)
    api.include_router(ledger_router)
    api.include_router(treasury_router)
    api.include_router(payroll_router)
    api.include_router(tax_router)
    api.include_router(close_router)
    api.include_router(capex_router)
    api.include_router(dms_docs_router)
    api.include_router(dms_public_router)
    api.include_router(letters_router)
    api.include_router(lms_router)
    api.include_router(dashboard_router)
    api.include_router(integrations_router)
    api.include_router(portal_router)
    app.include_router(api)
    return app


app = create_app()
