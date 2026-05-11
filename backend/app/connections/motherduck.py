"""MotherDuck warehouse executor."""

import asyncio
import logging

from tabulate import tabulate

from app.connections.base import (
    WarehouseExecutor, format_schema_summary,
    MAX_ROWS, MAX_CHARS,
)

logger = logging.getLogger("warehouse_executor")


class MotherDuckExecutor(WarehouseExecutor):
    """Execute queries against MotherDuck using the duckdb library."""

    def __init__(self, token: str, database: str):
        self._token = token
        self._database = database
        self._conn = None

    def _get_connection(self):
        import duckdb

        if self._conn is None:
            db_path = f"md:{self._database}?motherduck_token={self._token}"
            self._conn = duckdb.connect(db_path)
        return self._conn

    def _run_query(self, sql: str, params: tuple | None = None) -> str:
        conn = self._get_connection()
        q = conn.execute(sql, params) if params is not None else conn.execute(sql)
        rows = q.fetchmany(MAX_ROWS)
        has_more = q.fetchone() is not None
        headers = [d[0] for d in q.description]

        out = tabulate(rows, headers=headers, tablefmt="pretty")

        if len(out) > MAX_CHARS:
            out = out[:MAX_CHARS]
            out += f"\n\n-- Output truncated at {MAX_CHARS:,} characters."
        elif has_more:
            out += f"\n\n-- Showing first {len(rows)} rows."

        return out

    def _run_query_raw(self, sql: str, params: tuple | None = None) -> list[tuple]:
        conn = self._get_connection()
        q = conn.execute(sql, params) if params is not None else conn.execute(sql)
        return q.fetchall()

    async def connect(self) -> None:
        await asyncio.to_thread(self._get_connection)

    async def verify_read_only(self) -> bool:
        def _check():
            conn = self._get_connection()
            try:
                conn.execute("CREATE TEMP TABLE _datachat_readonly_test (id INTEGER)")
                conn.execute("DROP TABLE IF EXISTS _datachat_readonly_test")
                return False
            except Exception:
                return True

        return await asyncio.to_thread(_check)

    async def execute_sql(self, sql: str) -> str:
        return await asyncio.to_thread(self._run_query, sql)

    async def list_datasets(self) -> str:
        return await asyncio.to_thread(
            self._run_query,
            "SELECT database_name FROM information_schema.schemata GROUP BY database_name ORDER BY database_name",
        )

    async def list_tables(self, dataset: str) -> str:
        sql = (
            "SELECT table_schema, table_name, table_type FROM information_schema.tables "
            "WHERE table_catalog = ? ORDER BY table_schema, table_name"
        )
        return await asyncio.to_thread(self._run_query, sql, (dataset,))

    async def get_table_schema(self, dataset: str, table: str) -> str:
        sql = (
            "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
            "WHERE table_name = ? AND table_catalog = ? ORDER BY ordinal_position"
        )
        return await asyncio.to_thread(self._run_query, sql, (table, dataset))

    async def get_schema_summary(self) -> str:
        try:
            sql = (
                "SELECT table_schema, table_name, column_name, data_type "
                "FROM information_schema.columns "
                "WHERE table_catalog = ? "
                "ORDER BY table_schema, table_name, ordinal_position"
            )
            rows = await asyncio.to_thread(self._run_query_raw, sql, (self._database,))
            return format_schema_summary(rows, self._database)
        except Exception as e:
            logger.warning(f"MotherDuck schema summary failed: {e}")
            return ""
