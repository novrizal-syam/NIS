"""Background jobs. Run on a schedule (cron / compose) or let the API run them in-process
when SCHEDULER_ENABLED=true:

    python -m app.workflow.jobs escalate
"""

import asyncio
import logging
import sys

from app import models as _models  # noqa: F401  (register every model)
from app.core.db import SessionLocal
from app.workflow import engine

log = logging.getLogger("app.jobs")


async def run_escalation() -> int:
    async with SessionLocal() as session:
        count = await engine.escalate_overdue(session)
        await session.commit()
    if count:
        log.info("escalated", extra={"steps": count})
    return count


async def scheduler_loop(interval_seconds: int = 900) -> None:
    while True:
        try:
            await run_escalation()
        except Exception:
            log.exception("escalation_job_failed")
        await asyncio.sleep(interval_seconds)


if __name__ == "__main__":
    if sys.argv[1:] != ["escalate"]:
        sys.exit("usage: python -m app.workflow.jobs escalate")
    print(f"Tahap yang dieskalasi: {asyncio.run(run_escalation())}")
