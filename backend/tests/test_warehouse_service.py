"""Tests for services/warehouse_service.py."""

from unittest.mock import MagicMock, patch, AsyncMock

import pytest


class TestGetOrCreateExecutor:
    def test_creates_new_executor(self):
        from app.services.warehouse_service import get_or_create_executor, _executor_cache

        _executor_cache.clear()

        with patch("app.services.warehouse_service.create_executor") as mock_create:
            mock_exec = MagicMock()
            mock_create.return_value = mock_exec
            executor, is_new = get_or_create_executor("wh-1", "postgresql", {"host": "h"})
            assert is_new is True
            assert executor is mock_exec
            mock_create.assert_called_once_with("postgresql", {"host": "h"})

    def test_returns_cached_executor(self):
        from app.services.warehouse_service import get_or_create_executor, _executor_cache

        _executor_cache.clear()
        mock_exec = MagicMock()
        _executor_cache["wh-cached"] = mock_exec

        executor, is_new = get_or_create_executor("wh-cached", "postgresql", {})
        assert is_new is False
        assert executor is mock_exec


class TestEvictExecutor:
    def test_evicts_from_cache(self):
        from app.services.warehouse_service import evict_executor, _executor_cache, _schema_cache

        _executor_cache["wh-evict"] = MagicMock()
        _schema_cache["wh-evict"] = "schema"
        evict_executor("wh-evict")
        assert "wh-evict" not in _executor_cache
        assert "wh-evict" not in _schema_cache

    def test_evict_nonexistent_is_noop(self):
        from app.services.warehouse_service import evict_executor

        evict_executor("does-not-exist")  # Should not raise


class TestGetOrFetchSchema:
    async def test_fetches_and_caches(self):
        from app.services.warehouse_service import get_or_fetch_schema, _schema_cache

        _schema_cache.clear()

        mock_exec = AsyncMock()
        mock_exec.get_schema_summary.return_value = "schema data"

        result = await get_or_fetch_schema("wh-schema", mock_exec)
        assert result == "schema data"
        assert _schema_cache["wh-schema"] == "schema data"

    async def test_returns_cached(self):
        from app.services.warehouse_service import get_or_fetch_schema, _schema_cache

        _schema_cache["wh-cached-schema"] = "cached"
        mock_exec = AsyncMock()

        result = await get_or_fetch_schema("wh-cached-schema", mock_exec)
        assert result == "cached"
        mock_exec.get_schema_summary.assert_not_called()

    async def test_handles_schema_error(self):
        from app.services.warehouse_service import get_or_fetch_schema, _schema_cache

        _schema_cache.clear()
        mock_exec = AsyncMock()
        mock_exec.get_schema_summary.side_effect = Exception("network error")

        result = await get_or_fetch_schema("wh-error", mock_exec)
        assert result == ""


class TestCacheBound:
    """The executor and schema caches are bounded LRU OrderedDicts so a long-
    running process with many distinct warehouses doesn't leak memory."""

    def test_lru_evicts_oldest_executor(self, monkeypatch):
        from app.services import warehouse_service as ws

        monkeypatch.setattr(ws, "_CACHE_MAX_SIZE", 3)
        ws._executor_cache.clear()
        ws._schema_cache.clear()

        with patch.object(ws, "create_executor", side_effect=lambda *a, **kw: MagicMock()):
            for i in range(3):
                ws.get_or_create_executor(f"wh-{i}", "postgresql", {})
            # 4th entry triggers eviction of the LRU (wh-0)
            ws.get_or_create_executor("wh-3", "postgresql", {})

        assert "wh-0" not in ws._executor_cache
        assert {"wh-1", "wh-2", "wh-3"}.issubset(ws._executor_cache.keys())
        assert len(ws._executor_cache) == 3

    async def test_lru_evicts_oldest_schema(self, monkeypatch):
        from app.services import warehouse_service as ws

        monkeypatch.setattr(ws, "_CACHE_MAX_SIZE", 2)
        ws._schema_cache.clear()

        for i in range(3):
            mock_exec = AsyncMock()
            mock_exec.get_schema_summary.return_value = f"schema-{i}"
            await ws.get_or_fetch_schema(f"wh-{i}", mock_exec)

        assert "wh-0" not in ws._schema_cache
        assert len(ws._schema_cache) == 2

    def test_access_moves_to_mru(self, monkeypatch):
        from app.services import warehouse_service as ws

        monkeypatch.setattr(ws, "_CACHE_MAX_SIZE", 2)
        ws._executor_cache.clear()
        ws._schema_cache.clear()

        with patch.object(ws, "create_executor", side_effect=lambda *a, **kw: MagicMock()):
            ws.get_or_create_executor("wh-A", "postgresql", {})
            ws.get_or_create_executor("wh-B", "postgresql", {})
            # Touch A so it becomes MRU; next insert should evict B, not A.
            ws.get_or_create_executor("wh-A", "postgresql", {})
            ws.get_or_create_executor("wh-C", "postgresql", {})

        assert "wh-A" in ws._executor_cache
        assert "wh-B" not in ws._executor_cache
        assert "wh-C" in ws._executor_cache

    def test_evict_closes_executor(self):
        from app.services import warehouse_service as ws

        ws._executor_cache.clear()
        mock_exec = MagicMock()
        mock_exec.close = MagicMock()
        ws._executor_cache["wh-close"] = mock_exec

        ws.evict_executor("wh-close")
        mock_exec.close.assert_called_once()


class TestTestWarehouseConnection:
    async def test_unknown_type(self):
        from app.services.warehouse_service import test_warehouse_connection

        result = await test_warehouse_connection("oracle", {})
        assert result["success"] is False
        assert "Unknown warehouse type" in result["error"]

    @patch("app.services.warehouse_service._test_motherduck_connection")
    async def test_motherduck_dispatch(self, mock_test):
        from app.services.warehouse_service import test_warehouse_connection

        mock_test.return_value = {"success": True, "message": "ok"}
        result = await test_warehouse_connection("motherduck", {"token": "t"})
        assert result["success"] is True
        mock_test.assert_called_once_with({"token": "t"})

    @patch("app.services.warehouse_service._test_bigquery_connection")
    async def test_bigquery_dispatch(self, mock_test):
        from app.services.warehouse_service import test_warehouse_connection

        mock_test.return_value = {"success": True, "message": "ok"}
        result = await test_warehouse_connection("bigquery", {"project_id": "p"})
        assert result["success"] is True

    @patch("app.services.warehouse_service._test_snowflake_connection")
    async def test_snowflake_dispatch(self, mock_test):
        from app.services.warehouse_service import test_warehouse_connection

        mock_test.return_value = {"success": True, "message": "ok"}
        result = await test_warehouse_connection("snowflake", {})
        assert result["success"] is True

    @patch("app.services.warehouse_service._test_postgresql_connection")
    async def test_postgresql_dispatch(self, mock_test):
        from app.services.warehouse_service import test_warehouse_connection

        mock_test.return_value = {"success": True, "message": "ok"}
        result = await test_warehouse_connection("postgresql", {})
        assert result["success"] is True

    @patch("app.services.warehouse_service._test_redshift_connection")
    async def test_redshift_dispatch(self, mock_test):
        from app.services.warehouse_service import test_warehouse_connection

        mock_test.return_value = {"success": True, "message": "ok"}
        result = await test_warehouse_connection("redshift", {})
        assert result["success"] is True

    async def test_exception_returns_error(self):
        from app.services.warehouse_service import test_warehouse_connection

        with patch("app.services.warehouse_service._test_motherduck_connection", side_effect=Exception("boom")):
            result = await test_warehouse_connection("motherduck", {})
            assert result["success"] is False
            assert "boom" in result["error"]


class TestEncryptionRoundtrip:
    def test_encrypt_decrypt_credentials(self):
        from app.core.security import encrypt_credentials, decrypt_credentials

        creds = {"host": "db.example.com", "password": "hunter2"}
        encrypted = encrypt_credentials(creds)
        assert encrypted != str(creds)
        decrypted = decrypt_credentials(encrypted)
        assert decrypted == creds
