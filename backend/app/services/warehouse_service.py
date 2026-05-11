"""Warehouse connection management and caching."""

import asyncio
import json
import logging
import os
from collections import OrderedDict
from typing import Optional

import httpx

from app.connections.base import WarehouseExecutor
from app.connections.factory import create_executor
from app.connections.bigquery import get_bigquery_access_token

logger = logging.getLogger(__name__)

# Cache executors by warehouse_id so connections persist across chat messages.
# Bounded LRU eviction prevents unbounded growth in long-running processes with
# many distinct warehouse connections. Size is generous — each entry is one open
# DB connection, and most deployments have far fewer than this. Override via
# WAREHOUSE_CACHE_MAX_SIZE if a self-hoster ever needs to.
_CACHE_MAX_SIZE = int(os.getenv("WAREHOUSE_CACHE_MAX_SIZE", "256"))

_executor_cache: "OrderedDict[str, WarehouseExecutor]" = OrderedDict()
_schema_cache: "OrderedDict[str, str]" = OrderedDict()


def _close_quietly(executor: WarehouseExecutor) -> None:
    """Best-effort close on an evicted executor. Swallows everything because
    we're evicting a stale connection we no longer have a use for."""
    close = getattr(executor, "close", None)
    if not callable(close):
        return
    try:
        result = close()
        # close() may be sync or async; we don't have an event loop here in
        # the sync eviction path, so async closes are best-effort fire-and-forget.
        if asyncio.iscoroutine(result):
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(result)
                else:
                    loop.run_until_complete(result)
            except RuntimeError:
                pass
    except Exception:
        logger.debug("Ignored error while closing evicted executor", exc_info=True)


def _evict_oldest_if_full() -> None:
    while len(_executor_cache) >= _CACHE_MAX_SIZE:
        evicted_id, evicted_executor = _executor_cache.popitem(last=False)
        _schema_cache.pop(evicted_id, None)
        _close_quietly(evicted_executor)


def get_or_create_executor(warehouse_id: str, warehouse_type: str, credentials: dict) -> tuple[WarehouseExecutor, bool]:
    """Return (executor, is_new). Reuses cached executors to avoid reconnecting."""
    if warehouse_id in _executor_cache:
        _executor_cache.move_to_end(warehouse_id)
        return _executor_cache[warehouse_id], False
    _evict_oldest_if_full()
    executor = create_executor(warehouse_type, credentials)
    _executor_cache[warehouse_id] = executor
    return executor, True


async def get_or_fetch_schema(warehouse_id: str, executor: WarehouseExecutor) -> str:
    """Return cached schema summary, fetching on first call."""
    if warehouse_id in _schema_cache:
        _schema_cache.move_to_end(warehouse_id)
        return _schema_cache[warehouse_id]
    try:
        summary = await executor.get_schema_summary()
    except Exception:
        summary = ""
    while len(_schema_cache) >= _CACHE_MAX_SIZE:
        _schema_cache.popitem(last=False)
    _schema_cache[warehouse_id] = summary
    return summary


def evict_executor(warehouse_id: str) -> None:
    """Remove a cached executor and schema (e.g. after delete or credential change)."""
    executor = _executor_cache.pop(warehouse_id, None)
    _schema_cache.pop(warehouse_id, None)
    if executor is not None:
        _close_quietly(executor)


async def test_warehouse_connection(warehouse_type: str, credentials: dict) -> dict:
    """Test connection to a warehouse."""
    try:
        if warehouse_type == "motherduck":
            return await _test_motherduck_connection(credentials)
        elif warehouse_type == "bigquery":
            return await _test_bigquery_connection(credentials)
        elif warehouse_type == "snowflake":
            return await _test_snowflake_connection(credentials)
        elif warehouse_type == "postgresql":
            return await _test_postgresql_connection(credentials)
        elif warehouse_type == "redshift":
            return await _test_redshift_connection(credentials)
        else:
            return {"success": False, "error": f"Unknown warehouse type: {warehouse_type}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def _test_motherduck_connection(credentials: dict) -> dict:
    try:
        token = credentials.get("token")
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://api.motherduck.com/mcp",
                json={
                    "jsonrpc": "2.0",
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "datachat", "version": "1.0.0"},
                    },
                    "id": 1,
                },
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                },
            )
            if response.status_code == 200:
                return {"success": True, "message": "Connected to MotherDuck"}
            else:
                return {"success": False, "error": f"HTTP {response.status_code}: {response.text}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def _test_bigquery_connection(credentials: dict) -> dict:
    try:
        credentials_json = credentials.get("credentials_json")
        project_id = credentials.get("project_id")

        if not credentials_json:
            return {"success": False, "error": "Service account credentials JSON is required"}
        if not project_id:
            return {"success": False, "error": "Project ID is required"}

        try:
            creds_data = json.loads(credentials_json)
        except json.JSONDecodeError:
            return {"success": False, "error": "Invalid JSON in credentials"}

        required_fields = ["type", "project_id", "private_key", "client_email"]
        missing_fields = [f for f in required_fields if f not in creds_data]
        if missing_fields:
            return {"success": False, "error": f"Missing fields in service account: {', '.join(missing_fields)}"}

        if creds_data.get("type") != "service_account":
            return {"success": False, "error": "Credentials must be a service account JSON"}

        access_token = get_bigquery_access_token(credentials_json)
        if not access_token:
            return {"success": False, "error": "Failed to generate access token from service account"}

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://bigquery.googleapis.com/bigquery/v2/projects/{project_id}/datasets",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=10.0,
            )

        if response.status_code == 200:
            datasets = response.json().get("datasets", [])
            return {
                "success": True,
                "message": f"Connected to BigQuery project '{project_id}' ({len(datasets)} datasets found)",
            }
        elif response.status_code == 403:
            return {"success": False, "error": f"Service account lacks permission to access project '{project_id}'"}
        elif response.status_code == 404:
            return {"success": False, "error": f"Project '{project_id}' not found"}
        else:
            return {"success": False, "error": f"BigQuery API error: {response.status_code}"}

    except Exception as e:
        return {"success": False, "error": str(e)}


async def _test_snowflake_connection(credentials: dict) -> dict:
    import snowflake.connector

    def _test():
        conn = snowflake.connector.connect(
            account=credentials["account"],
            user=credentials["username"],
            password=credentials["password"],
            warehouse=credentials["warehouse"],
            database=credentials["database"],
        )
        try:
            cur = conn.cursor()
            cur.execute("SELECT 1")
            cur.close()
        finally:
            conn.close()

    try:
        await asyncio.to_thread(_test)
        return {"success": True, "message": "Connected to Snowflake"}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def _test_postgresql_connection(credentials: dict) -> dict:
    import psycopg2

    def _test():
        conn = psycopg2.connect(
            host=credentials["host"],
            port=int(credentials.get("port", 5432)),
            dbname=credentials["database"],
            user=credentials["username"],
            password=credentials["password"],
            connect_timeout=10,
        )
        try:
            cur = conn.cursor()
            cur.execute("SELECT 1")
            cur.close()
        finally:
            conn.close()

    try:
        await asyncio.to_thread(_test)
        return {"success": True, "message": "Connected to PostgreSQL"}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def _test_redshift_connection(credentials: dict) -> dict:
    from app.connections.factory import create_executor

    def _test():
        executor = create_executor("redshift", credentials)
        conn = executor._get_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT 1")
            cur.close()
        finally:
            conn.close()

    try:
        await asyncio.to_thread(_test)
        return {"success": True, "message": "Connected to Redshift"}
    except Exception as e:
        return {"success": False, "error": str(e)}
