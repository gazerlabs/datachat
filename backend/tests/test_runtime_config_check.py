"""Tests for the startup config sanity check in app.main._check_runtime_config.

The check is loud-but-non-fatal: it logs WARN-level messages when it detects
operational footguns (SQLite under apparent production, relative
LOCAL_DUCKDB_DIR) so the operator sees them on first boot.
"""

import logging
from unittest.mock import patch

import pytest


def _run_check():
    from app.main import _check_runtime_config
    _check_runtime_config()


class TestSqliteWarning:
    def test_sqlite_with_auth_enabled_warns(self, caplog):
        with caplog.at_level(logging.WARNING, logger="app.main"):
            with patch("app.main.DATABASE_URL", "sqlite:///./datachat.db"), \
                 patch("app.main.DISABLE_AUTH", False), \
                 patch("app.main.LOCAL_DUCKDB_DIR", "/data/local_duckdb"):
                _run_check()

        msgs = [r.getMessage() for r in caplog.records]
        assert any("SQLite" in m and "Postgres" in m for m in msgs)

    def test_sqlite_with_disable_auth_quiet(self, caplog):
        with caplog.at_level(logging.WARNING, logger="app.main"):
            with patch("app.main.DATABASE_URL", "sqlite:///./datachat.db"), \
                 patch("app.main.DISABLE_AUTH", True), \
                 patch("app.main.LOCAL_DUCKDB_DIR", "/data/local_duckdb"):
                _run_check()

        msgs = [r.getMessage() for r in caplog.records]
        assert not any("SQLite" in m for m in msgs)

    def test_postgres_quiet(self, caplog):
        with caplog.at_level(logging.WARNING, logger="app.main"):
            with patch("app.main.DATABASE_URL", "postgresql://u:p@host/db"), \
                 patch("app.main.DISABLE_AUTH", False), \
                 patch("app.main.LOCAL_DUCKDB_DIR", "/data/local_duckdb"):
                _run_check()

        msgs = [r.getMessage() for r in caplog.records]
        assert not any("SQLite" in m for m in msgs)


class TestLocalDuckdbDirWarning:
    def test_relative_path_warns(self, caplog):
        with caplog.at_level(logging.WARNING, logger="app.main"):
            with patch("app.main.DATABASE_URL", "postgresql://u:p@host/db"), \
                 patch("app.main.DISABLE_AUTH", False), \
                 patch("app.main.LOCAL_DUCKDB_DIR", "./local_duckdb"):
                _run_check()

        msgs = [r.getMessage() for r in caplog.records]
        assert any("LOCAL_DUCKDB_DIR" in m and "relative" in m.lower() for m in msgs)

    def test_absolute_path_quiet(self, caplog):
        with caplog.at_level(logging.WARNING, logger="app.main"):
            with patch("app.main.DATABASE_URL", "postgresql://u:p@host/db"), \
                 patch("app.main.DISABLE_AUTH", False), \
                 patch("app.main.LOCAL_DUCKDB_DIR", "/data/local_duckdb"):
                _run_check()

        msgs = [r.getMessage() for r in caplog.records]
        assert not any("LOCAL_DUCKDB_DIR" in m for m in msgs)
