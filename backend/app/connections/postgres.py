"""PostgreSQL warehouse executor."""

import asyncio
import logging

from tabulate import tabulate

from app.connections.base import (
    WarehouseExecutor, format_schema_summary,
    MAX_ROWS, MAX_CHARS,
)
from app.core.config import WAREHOUSE_QUERY_TIMEOUT_SECONDS

logger = logging.getLogger("warehouse_executor")


class PostgreSQLExecutor(WarehouseExecutor):
    """Execute queries against PostgreSQL using psycopg2."""

    def __init__(self, host: str, port: str, database: str, username: str, password: str):
        self._host = host
        self._port = int(port)
        self._database = database
        self._username = username
        self._password = password
        self._conn = None

    def _get_connection(self):
        import psycopg2

        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(
                host=self._host,
                port=self._port,
                dbname=self._database,
                user=self._username,
                password=self._password,
                connect_timeout=10,
                options=f"-c statement_timeout={WAREHOUSE_QUERY_TIMEOUT_SECONDS * 1000}",
            )
            self._conn.autocommit = True
        return self._conn

    def _run_query(self, sql: str, params: tuple | None = None) -> str:
        conn = self._get_connection()
        cur = conn.cursor()
        try:
            if params is None:
                cur.execute(sql)
            else:
                cur.execute(sql, params)
            if cur.description is None:
                return "Query executed successfully (no results)."
            rows = cur.fetchmany(MAX_ROWS)
            has_more = cur.fetchone() is not None
            headers = [desc[0] for desc in cur.description]
        finally:
            cur.close()

        out = tabulate(rows, headers=headers, tablefmt="pretty")

        if len(out) > MAX_CHARS:
            out = out[:MAX_CHARS]
            out += f"\n\n-- Output truncated at {MAX_CHARS:,} characters."
        elif has_more:
            out += f"\n\n-- Showing first {len(rows)} rows."

        return out

    def _run_query_raw(self, sql: str, params: tuple | None = None) -> list[tuple]:
        conn = self._get_connection()
        cur = conn.cursor()
        try:
            if params is None:
                cur.execute(sql)
            else:
                cur.execute(sql, params)
            return cur.fetchall()
        finally:
            cur.close()

    async def connect(self) -> None:
        await asyncio.to_thread(self._get_connection)

    async def verify_read_only(self) -> bool:
        def _check():
            conn = self._get_connection()
            cur = conn.cursor()
            try:
                cur.execute("CREATE TEMP TABLE _datachat_readonly_test (id INTEGER)")
                cur.execute("DROP TABLE IF EXISTS _datachat_readonly_test")
                return False
            except Exception:
                return True
            finally:
                cur.close()

        return await asyncio.to_thread(_check)

    async def execute_sql(self, sql: str) -> str:
        return await asyncio.to_thread(self._run_query, sql)

    async def list_datasets(self) -> str:
        sql = (
            "SELECT schema_name FROM information_schema.schemata "
            "WHERE schema_name NOT IN ('pg_catalog', 'information_schema', 'pg_toast') "
            "ORDER BY schema_name"
        )
        return await asyncio.to_thread(self._run_query, sql)

    async def list_tables(self, dataset: str) -> str:
        sql = (
            "SELECT table_schema, table_name, table_type FROM information_schema.tables "
            "WHERE table_schema = %s ORDER BY table_name"
        )
        return await asyncio.to_thread(self._run_query, sql, (dataset,))

    async def get_table_schema(self, dataset: str, table: str) -> str:
        sql = (
            "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
            "WHERE table_schema = %s AND table_name = %s "
            "ORDER BY ordinal_position"
        )
        return await asyncio.to_thread(self._run_query, sql, (dataset, table))

    async def get_schema_summary(self) -> str:
        try:
            sql = (
                "SELECT table_schema, table_name, column_name, data_type "
                "FROM information_schema.columns "
                "WHERE table_schema NOT IN ('pg_catalog', 'information_schema', 'pg_toast') "
                "ORDER BY table_schema, table_name, ordinal_position"
            )
            rows = await asyncio.to_thread(self._run_query_raw, sql)
            return format_schema_summary(rows, self._database)
        except Exception as e:
            logger.warning(f"PostgreSQL schema summary failed: {e}")
            return ""
