"""Background jobs. Run on a schedule (cron) or let the API run them in-process when
SCHEDULER_ENABLED=true:

    python -m app.workflow.jobs escalate | expiry | email | all
"""

import asyncio
import logging
import sys
import time
from collections.abc import Awaitable, Callable

from app import models as _models  # noqa: F401  (register every model)
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.notifications import service as notifications
from app.workflow import engine

log = logging.getLogger("app.jobs")


async def _in_session(fn: Callable[..., Awaitable[int]]) -> int:
    async with SessionLocal() as session:
        count = await fn(session)
        await session.commit()
    return count


async def run_escalation() -> int:
    return await _in_session(engine.escalate_overdue)


async def run_expiry_alerts() -> int:
    return await _in_session(notifications.run_expiry_alerts)


async def run_email_outbox() -> int:
    return await _in_session(notifications.deliver_email_outbox)


JOBS: dict[str, Callable[[], Awaitable[int]]] = {
    "escalate": run_escalation,
    "expiry": run_expiry_alerts,
    "email": run_email_outbox,
}


async def scheduler_loop(interval_seconds: int = 900) -> None:
    """Email outbox every EMAIL_INTERVAL_SECONDS; escalation and expiry every interval."""
    email_every = get_settings().email_interval_seconds
    last_slow = 0.0
    while True:
        jobs = ["email"]
        if time.monotonic() - last_slow >= interval_seconds:
            jobs += ["escalate", "expiry"]
            last_slow = time.monotonic()
        for name in jobs:
            try:
                count = await JOBS[name]()
                if count:
                    log.info("job_done", extra={"job": name, "count": count})
            except Exception:
                log.exception("job_failed", extra={"job": name})
        await asyncio.sleep(email_every)


async def _run(names: list[str]) -> None:
    for name in names:
        print(f"{name}: {await JOBS[name]()}")


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg not in (*JOBS, "all"):
        sys.exit("usage: python -m app.workflow.jobs escalate|expiry|email|all")
    asyncio.run(_run(list(JOBS) if arg == "all" else [arg]))
