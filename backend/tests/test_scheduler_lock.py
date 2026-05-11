"""Tests for the scheduler advisory-lock helper.

The lock collapses concurrent replicas to a single tick. The implementation
short-circuits to True on SQLite (single-process by definition) and calls
pg_try_advisory_lock on Postgres.
"""

from unittest.mock import MagicMock

import pytest


class TestTryAcquireSchedulerLock:
    def test_sqlite_always_acquires(self):
        from app.services.scheduler_service import _try_acquire_scheduler_lock

        db = MagicMock()
        db.bind.dialect.name = "sqlite"
        assert _try_acquire_scheduler_lock(db) is True
        # No SQL should have been issued — SQLite path short-circuits.
        db.execute.assert_not_called()

    def test_postgres_acquired(self):
        from app.services.scheduler_service import (
            _SCHEDULER_LOCK_KEY,
            _try_acquire_scheduler_lock,
        )

        db = MagicMock()
        db.bind.dialect.name = "postgresql"
        scalar_result = MagicMock()
        scalar_result.scalar.return_value = True
        db.execute.return_value = scalar_result

        assert _try_acquire_scheduler_lock(db) is True
        # Verify the right key was used (passed positionally as the 2nd arg).
        args, _ = db.execute.call_args
        assert args[1] == {"key": _SCHEDULER_LOCK_KEY}

    def test_postgres_lock_held_by_another_returns_false(self):
        from app.services.scheduler_service import _try_acquire_scheduler_lock

        db = MagicMock()
        db.bind.dialect.name = "postgresql"
        scalar_result = MagicMock()
        scalar_result.scalar.return_value = False
        db.execute.return_value = scalar_result

        assert _try_acquire_scheduler_lock(db) is False

    def test_postgres_lock_query_error_returns_false(self):
        """If the lock query itself errors, fail closed (skip the tick) — we'd
        rather miss one cycle than double-send."""
        from app.services.scheduler_service import _try_acquire_scheduler_lock

        db = MagicMock()
        db.bind.dialect.name = "postgresql"
        db.execute.side_effect = Exception("connection lost")

        assert _try_acquire_scheduler_lock(db) is False

    def test_no_bind_returns_true(self):
        """Defensive: if db.bind is None somehow, treat as single-process."""
        from app.services.scheduler_service import _try_acquire_scheduler_lock

        db = MagicMock()
        db.bind = None
        assert _try_acquire_scheduler_lock(db) is True
