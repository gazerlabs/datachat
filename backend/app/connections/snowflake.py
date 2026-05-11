"""Snowflake warehouse executor."""

import asyncio
import logging
import re

from tabulate import tabulate

from app.connections.base import (
    WarehouseExecutor, format_schema_summary,
    MAX_ROWS, MAX_CHARS,
)
from app.core.config import WAREHOUSE_QUERY_TIMEOUT_SECONDS

# Snowflake SHOW statements take identifiers, not bind parameters, so we can't
# parameterize them. Restrict to ASCII letters/digits/underscore/dot (enough for
# unquoted db.schema.table) and refuse anything else.
_SAFE_IDENTIFIER = re.compile(r"\A[A-Za-z0-9_.]+\Z")


def _check_identifier(name: str, *, kind: str) -> str:
    if not name or not _SAFE_IDENTIFIER.fullmatch(name):
        raise ValueError(f"Invalid {kind} identifier: {name!r}")
    return name

logger = logging.getLogger("warehouse_executor")


class SnowflakeExecutor(WarehouseExecutor):
    """Execute queries against Snowflake using snowflake-connector-python."""

    def __init__(self, account: str, username: str, password: str, warehouse: str, database: str):
        self._account = account
        self._username = username
        self._password = password
        self._warehouse = warehouse
        self._database = database
        self._conn = None

    def _get_connection(self):
        import snowflake.connector

        if self._conn is None:
            self._conn = snowflake.connector.connect(
                account=self._account,
                user=self._username,
                password=self._password,
                warehouse=self._warehouse,
                database=self._database,
                session_parameters={
                    "STATEMENT_TIMEOUT_IN_SECONDS": WAREHOUSE_QUERY_TIMEOUT_SECONDS,
                },
            )
        return self._conn

    def _run_query(self, sql: str) -> str:
        conn = self._get_connection()
        cur = conn.cursor()
        try:
            cur.execute(sql)
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

    def _run_query_raw(self, sql: str) -> list[tuple]:
        conn = self._get_connection()
        cur = conn.cursor()
        try:
            cur.execute(sql)
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
        return await asyncio.to_thread(self._run_query, "SHOW DATABASES")

    async def list_tables(self, dataset: str) -> str:
        safe_dataset = _check_identifier(dataset, kind="dataset")
        return await asyncio.to_thread(self._run_query, f"SHOW TABLES IN DATABASE {safe_dataset}")

    async def get_table_schema(self, dataset: str, table: str) -> str:
        safe_dataset = _check_identifier(dataset, kind="dataset")
        safe_table = _check_identifier(table, kind="table")
        return await asyncio.to_thread(
            self._run_query, f"SHOW COLUMNS IN TABLE {safe_dataset}.{safe_table}"
        )

    async def get_schema_summary(self) -> str:
        try:
            safe_database = _check_identifier(self._database, kind="database")
            sql = (
                f"SELECT TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME, DATA_TYPE "
                f"FROM {safe_database}.INFORMATION_SCHEMA.COLUMNS "
                f"WHERE TABLE_SCHEMA != 'INFORMATION_SCHEMA' "
                f"ORDER BY TABLE_SCHEMA, TABLE_NAME, ORDINAL_POSITION"
            )
            rows = await asyncio.to_thread(self._run_query_raw, sql)
            return format_schema_summary(rows, self._database)
        except Exception as e:
            logger.warning(f"Snowflake schema summary failed: {e}")
            return ""
