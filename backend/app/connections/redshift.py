"""Amazon Redshift warehouse executor."""

import asyncio
import logging

from tabulate import tabulate

from app.connections.base import (
    WarehouseExecutor, format_schema_summary,
    MAX_ROWS, MAX_CHARS,
)

logger = logging.getLogger("warehouse_executor")

# System schemas to exclude from discovery
EXCLUDED_SCHEMAS = (
    "pg_catalog",
    "information_schema",
    "pg_toast",
    "pg_internal",
)


class RedshiftExecutor(WarehouseExecutor):
    """Execute queries against Amazon Redshift using redshift_connector."""

    def __init__(
        self,
        *,
        # Standard auth
        host: str | None = None,
        port: int = 5439,
        database: str = "dev",
        username: str | None = None,
        password: str | None = None,
        # IAM auth
        iam: bool = False,
        access_key: str | None = None,
        secret_key: str | None = None,
        cluster_identifier: str | None = None,
        db_user: str | None = None,
        region: str | None = None,
        # Serverless
        is_serverless: bool = False,
        workgroup: str | None = None,
    ):
        self._host = host
        self._port = port
        self._database = database
        self._username = username
        self._password = password
        self._iam = iam
        self._access_key = access_key
        self._secret_key = secret_key
        self._cluster_identifier = cluster_identifier
        self._db_user = db_user
        self._region = region
        self._is_serverless = is_serverless
        self._workgroup = workgroup
        self._conn = None

    def _get_connection(self):
        import redshift_connector
        from app.core.config import WAREHOUSE_QUERY_TIMEOUT_SECONDS

        if self._conn is not None:
            try:
                if not getattr(self._conn, "closed", False):
                    return self._conn
            except Exception:
                pass

        if self._is_serverless:
            # Redshift Serverless — let the library resolve the endpoint via API
            connect_kwargs = {
                "database": self._database,
                "iam": True,
                "is_serverless": True,
                "serverless_work_group": self._workgroup,
                "access_key_id": self._access_key,
                "secret_access_key": self._secret_key,
                "region": self._region,
                "ssl": True,
                "timeout": 90,
            }
            # Only pass host if explicitly provided (otherwise library resolves it)
            if self._host:
                connect_kwargs["host"] = self._host
                connect_kwargs["port"] = self._port
            self._conn = redshift_connector.connect(**connect_kwargs)
        elif self._iam:
            # IAM auth for provisioned clusters
            self._conn = redshift_connector.connect(
                iam=True,
                database=self._database,
                cluster_identifier=self._cluster_identifier,
                db_user=self._db_user,
                access_key_id=self._access_key,
                secret_access_key=self._secret_key,
                region=self._region,
                ssl=True,
                timeout=30,
            )
        else:
            # Standard username/password auth
            self._conn = redshift_connector.connect(
                host=self._host,
                port=self._port,
                database=self._database,
                user=self._username,
                password=self._password,
                ssl=True,
                timeout=30,
            )

        self._conn.autocommit = True
        try:
            cur = self._conn.cursor()
            cur.execute(f"SET statement_timeout TO {WAREHOUSE_QUERY_TIMEOUT_SECONDS * 1000}")
            cur.close()
        except Exception:
            logger.debug("Failed to set statement_timeout on Redshift connection", exc_info=True)
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
        excluded = ", ".join(f"'{s}'" for s in EXCLUDED_SCHEMAS)
        sql = (
            "SELECT DISTINCT schemaname AS schema_name "
            "FROM pg_table_def "
            f"WHERE schemaname NOT IN ({excluded}) "
            "ORDER BY schema_name"
        )
        return await asyncio.to_thread(self._run_query, sql)

    async def list_tables(self, dataset: str) -> str:
        sql = (
            "SELECT DISTINCT schemaname AS table_schema, tablename AS table_name, 'TABLE' AS table_type "
            "FROM pg_table_def WHERE schemaname = %s "
            "ORDER BY table_name"
        )
        return await asyncio.to_thread(self._run_query, sql, (dataset,))

    async def get_table_schema(self, dataset: str, table: str) -> str:
        sql = (
            "SELECT \"column\" AS column_name, type AS data_type, notnull "
            "FROM pg_table_def WHERE schemaname = %s AND tablename = %s "
            "ORDER BY \"column\""
        )
        return await asyncio.to_thread(self._run_query, sql, (dataset, table))

    async def get_schema_summary(self) -> str:
        try:
            excluded = ", ".join(f"'{s}'" for s in EXCLUDED_SCHEMAS)
            sql = (
                "SELECT schemaname AS table_schema, tablename AS table_name, "
                "\"column\" AS column_name, type AS data_type "
                "FROM pg_table_def "
                f"WHERE schemaname NOT IN ({excluded}) "
                "ORDER BY schemaname, tablename, \"column\""
            )
            rows = await asyncio.to_thread(self._run_query_raw, sql)
            return format_schema_summary(rows, self._database)
        except Exception as e:
            logger.warning(f"Redshift schema summary failed: {e}")
            return ""
