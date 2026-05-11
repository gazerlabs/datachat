"""Polling-loop scheduler for report email sends.

A single asyncio task wakes every POLL_INTERVAL_SECONDS, finds report_schedules
where enabled=true and next_send_at <= utcnow(), and dispatches send_report_now
for each. Run state is in the DB — restarts pick up where they left off.

When the backend runs as more than one replica (multiple processes against the
same Postgres DB), each replica's scheduler loop would otherwise process the
same due schedules and send duplicate emails. A Postgres session-scoped
advisory lock around each tick collapses concurrent workers to one. SQLite
deployments are single-process by definition, so the lock is skipped there.
"""

import asyncio
import logging
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.report import ReportSchedule
from app.services import report_service

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 60

# Stable 64-bit key for pg_try_advisory_lock. Picked once and burned in — if
# another part of the app ever uses advisory locks, give that one a different
# key. Hash of "datachat:scheduler:report-tick" trimmed to a signed int.
_SCHEDULER_LOCK_KEY = 7_242_517_309_521_837_241

_task: asyncio.Task | None = None
_stopping = asyncio.Event()


def _try_acquire_scheduler_lock(db: Session) -> bool:
    """Best-effort cross-process lock for one scheduler tick.

    Returns True if this replica owns the tick (do the work), False if another
    replica is already in the tick (skip). Held until the session is closed
    because we use session-scoped pg_try_advisory_lock, which makes
    leak-on-crash a non-issue.
    """
    if db.bind is None or db.bind.dialect.name != "postgresql":
        # SQLite path: single-process by definition, no lock needed.
        return True
    try:
        got = db.execute(
            text("SELECT pg_try_advisory_lock(:key)"),
            {"key": _SCHEDULER_LOCK_KEY},
        ).scalar()
        return bool(got)
    except Exception:
        # If the lock query itself errored (e.g. DB momentarily unavailable),
        # fail closed and skip this tick — we'd rather miss one cycle than
        # send the email twice.
        logger.exception("Scheduler: pg_try_advisory_lock failed; skipping tick")
        return False


async def _process_due_schedules() -> None:
    """One pass: find due schedules, send each, log failures and continue."""
    db: Session = SessionLocal()
    try:
        if not _try_acquire_scheduler_lock(db):
            logger.debug(
                "Scheduler: another replica holds the advisory lock; skipping tick",
            )
            return

        now = datetime.utcnow()
        due = (
            db.query(ReportSchedule)
            .filter(ReportSchedule.enabled.is_(True))
            .filter(ReportSchedule.next_send_at.isnot(None))
            .filter(ReportSchedule.next_send_at <= now)
            .all()
        )
        if not due:
            return
        logger.info("Scheduler: %d due schedule(s) to process", len(due))
        for schedule in due:
            try:
                await report_service.send_report_now(db, report_id=schedule.report_id)
            except Exception:
                logger.exception(
                    "Scheduler: failed to send report %s; advancing next_send_at to avoid hot-looping",
                    schedule.report_id,
                )
                # Advance next_send_at even on failure so we don't retry every poll.
                schedule.next_send_at = report_service.compute_next_send_at(
                    schedule, after=now,
                )
                db.commit()
    finally:
        # Closing the session releases the advisory lock automatically.
        db.close()


async def _scheduler_loop() -> None:
    logger.info("Report scheduler started (poll interval %ds)", POLL_INTERVAL_SECONDS)
    try:
        while not _stopping.is_set():
            try:
                await _process_due_schedules()
            except Exception:
                logger.exception("Scheduler tick failed; continuing")
            try:
                await asyncio.wait_for(_stopping.wait(), timeout=POLL_INTERVAL_SECONDS)
            except asyncio.TimeoutError:
                pass
    finally:
        logger.info("Report scheduler stopped")


def start_scheduler() -> None:
    global _task
    if _task is not None and not _task.done():
        return
    _stopping.clear()
    _task = asyncio.create_task(_scheduler_loop(), name="report-scheduler")


async def stop_scheduler() -> None:
    global _task
    _stopping.set()
    if _task is not None:
        try:
            await _task
        except Exception:
            pass
        _task = None
