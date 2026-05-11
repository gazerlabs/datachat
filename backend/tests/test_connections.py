"""Tests for warehouse connection adapters."""

import asyncio
from unittest.mock import MagicMock, patch, AsyncMock

import pytest


# ---------------------------------------------------------------------------
# MotherDuck
# ---------------------------------------------------------------------------
class TestMotherDuckExecutor:
    def _make_executor(self, mock_duckdb):
        """Create executor with mocked duckdb module."""
        import sys
        sys.modules["duckdb"] = mock_duckdb
        from app.connections.motherduck import MotherDuckExecutor
        return MotherDuckExecutor

    def test_connection_creates_duckdb_conn(self):
        mock_duckdb = MagicMock()
        mock_conn = MagicMock()
        mock_duckdb.connect.return_value = mock_conn

        Cls = self._make_executor(mock_duckdb)
        executor = Cls(token="test-token", database="testdb")
        conn = executor._get_connection()
        mock_duckdb.connect.assert_called_once_with("md:testdb?motherduck_token=test-token")
        assert conn is mock_conn

    def test_connection_reuses_existing(self):
        mock_duckdb = MagicMock()
        mock_conn = MagicMock()
        mock_duckdb.connect.return_value = mock_conn

        Cls = self._make_executor(mock_duckdb)
        executor = Cls(token="t", database="db")
        executor._get_connection()
        executor._get_connection()
        assert mock_duckdb.connect.call_count == 1

    async def test_execute_sql_returns_formatted(self):
        mock_duckdb = MagicMock()
        mock_conn = MagicMock()
        mock_query = MagicMock()
        mock_query.fetchmany.return_value = [("alice", 30)]
        mock_query.fetchone.return_value = None
        mock_query.description = [("name",), ("age",)]
        mock_conn.execute.return_value = mock_query
        mock_duckdb.connect.return_value = mock_conn

        Cls = self._make_executor(mock_duckdb)
        executor = Cls(token="t", database="db")
        result = await executor.execute_sql("SELECT * FROM users")
        assert "alice" in result
        assert "30" in result

    async def test_execute_sql_error(self):
        mock_duckdb = MagicMock()
        mock_conn = MagicMock()
        mock_conn.execute.side_effect = Exception("bad SQL")
        mock_duckdb.connect.return_value = mock_conn

        Cls = self._make_executor(mock_duckdb)
        executor = Cls(token="t", database="db")
        with pytest.raises(Exception, match="bad SQL"):
            await executor.execute_sql("INVALID SQL")

    async def test_list_datasets(self):
        mock_duckdb = MagicMock()
        mock_conn = MagicMock()
        mock_query = MagicMock()
        mock_query.fetchmany.return_value = [("mydb",)]
        mock_query.fetchone.return_value = None
        mock_query.description = [("database_name",)]
        mock_conn.execute.return_value = mock_query
        mock_duckdb.connect.return_value = mock_conn

        Cls = self._make_executor(mock_duckdb)
        executor = Cls(token="t", database="db")
        result = await executor.list_datasets()
        assert "mydb" in result


# ---------------------------------------------------------------------------
# BigQuery
# ---------------------------------------------------------------------------
class TestBigQueryExecutor:
    @patch("app.connections.bigquery.get_bigquery_access_token", return_value="fake-token")
    async def test_execute_sql(self, mock_token):
        from app.connections.bigquery import BigQueryExecutor

        executor = BigQueryExecutor(credentials_json='{"type":"service_account"}', project_id="proj")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "jobComplete": True,
            "schema": {"fields": [{"name": "id"}, {"name": "name"}]},
            "rows": [{"f": [{"v": "1"}, {"v": "Alice"}]}],
            "totalRows": "1",
        }

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            result = await executor.execute_sql("SELECT * FROM t")
            assert "Alice" in result

    @patch("app.connections.bigquery.get_bigquery_access_token", return_value=None)
    async def test_bad_credentials(self, mock_token):
        from app.connections.bigquery import BigQueryExecutor

        executor = BigQueryExecutor(credentials_json='{}', project_id="proj")
        with pytest.raises(RuntimeError, match="Failed to generate BigQuery access token"):
            await executor.execute_sql("SELECT 1")

    @patch("app.connections.bigquery.get_bigquery_access_token", return_value="fake-token")
    async def test_list_datasets(self, mock_token):
        from app.connections.bigquery import BigQueryExecutor

        executor = BigQueryExecutor(credentials_json='{}', project_id="proj")

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "datasets": [{"datasetReference": {"datasetId": "ds1"}}]
        }

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            result = await executor.list_datasets()
            assert "ds1" in result


# ---------------------------------------------------------------------------
# Snowflake
# ---------------------------------------------------------------------------
class TestSnowflakeExecutor:
    def _make_executor(self, mock_sf_connector):
        """Inject a mock snowflake.connector module."""
        import sys
        mock_sf = MagicMock()
        mock_sf.connector = mock_sf_connector
        sys.modules["snowflake"] = mock_sf
        sys.modules["snowflake.connector"] = mock_sf_connector
        from app.connections.snowflake import SnowflakeExecutor
        return SnowflakeExecutor

    def test_connection(self):
        mock_connector = MagicMock()
        mock_conn = MagicMock()
        mock_connector.connect.return_value = mock_conn

        Cls = self._make_executor(mock_connector)
        executor = Cls(account="acc", username="user", password="pass", warehouse="wh", database="db")
        conn = executor._get_connection()
        assert conn is mock_conn
        mock_connector.connect.assert_called_once()

    async def test_execute_sql(self):
        mock_connector = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchmany.return_value = [("val1",)]
        mock_cursor.fetchone.return_value = None
        mock_cursor.description = [("col1",)]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connector.connect.return_value = mock_conn

        Cls = self._make_executor(mock_connector)
        executor = Cls(account="acc", username="user", password="pass", warehouse="wh", database="db")
        result = await executor.execute_sql("SELECT 1")
        assert "val1" in result

    async def test_connection_error(self):
        mock_connector = MagicMock()
        mock_connector.connect.side_effect = Exception("Connection refused")

        Cls = self._make_executor(mock_connector)
        executor = Cls(account="acc", username="user", password="pass", warehouse="wh", database="db")
        with pytest.raises(Exception, match="Connection refused"):
            await executor.execute_sql("SELECT 1")

    def test_connection_includes_statement_timeout(self):
        mock_connector = MagicMock()
        mock_conn = MagicMock()
        mock_connector.connect.return_value = mock_conn

        Cls = self._make_executor(mock_connector)
        executor = Cls(account="acc", username="user", password="pass", warehouse="wh", database="db")
        executor._get_connection()

        _, kwargs = mock_connector.connect.call_args
        assert "session_parameters" in kwargs
        assert "STATEMENT_TIMEOUT_IN_SECONDS" in kwargs["session_parameters"]


# ---------------------------------------------------------------------------
# PostgreSQL
# ---------------------------------------------------------------------------
class TestPostgreSQLExecutor:
    def _make_executor(self, mock_psycopg2):
        import sys
        sys.modules["psycopg2"] = mock_psycopg2
        from app.connections.postgres import PostgreSQLExecutor
        return PostgreSQLExecutor

    def test_connection(self):
        mock_pg = MagicMock()
        mock_conn = MagicMock()
        mock_conn.closed = False
        mock_pg.connect.return_value = mock_conn

        Cls = self._make_executor(mock_pg)
        executor = Cls(host="localhost", port="5432", database="testdb", username="user", password="pass")
        conn = executor._get_connection()
        assert conn is mock_conn

    async def test_execute_sql(self):
        mock_pg = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchmany.return_value = [("row1",)]
        mock_cursor.fetchone.return_value = None
        mock_cursor.description = [("result",)]
        mock_conn = MagicMock()
        mock_conn.closed = False
        mock_conn.cursor.return_value = mock_cursor
        mock_pg.connect.return_value = mock_conn

        Cls = self._make_executor(mock_pg)
        executor = Cls(host="localhost", port="5432", database="testdb", username="user", password="pass")
        result = await executor.execute_sql("SELECT 1")
        assert "row1" in result

    async def test_no_results(self):
        mock_pg = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.description = None
        mock_conn = MagicMock()
        mock_conn.closed = False
        mock_conn.cursor.return_value = mock_cursor
        mock_pg.connect.return_value = mock_conn

        Cls = self._make_executor(mock_pg)
        executor = Cls(host="localhost", port="5432", database="testdb", username="user", password="pass")
        result = await executor.execute_sql("CREATE TABLE foo (id INT)")
        assert "no results" in result.lower()

    async def test_connection_refused(self):
        mock_pg = MagicMock()
        mock_pg.connect.side_effect = Exception("Connection refused")

        Cls = self._make_executor(mock_pg)
        executor = Cls(host="badhost", port="5432", database="testdb", username="user", password="pass")
        with pytest.raises(Exception, match="Connection refused"):
            await executor.execute_sql("SELECT 1")

    def test_connection_includes_statement_timeout(self):
        mock_pg = MagicMock()
        mock_conn = MagicMock()
        mock_conn.closed = False
        mock_pg.connect.return_value = mock_conn

        Cls = self._make_executor(mock_pg)
        executor = Cls(host="localhost", port="5432", database="testdb", username="user", password="pass")
        executor._get_connection()

        _, kwargs = mock_pg.connect.call_args
        assert "options" in kwargs
        assert "statement_timeout" in kwargs["options"]


# ---------------------------------------------------------------------------
# Redshift
# ---------------------------------------------------------------------------
class TestRedshiftExecutor:
    def _make_executor(self, mock_rs):
        import sys
        sys.modules["redshift_connector"] = mock_rs
        from app.connections.redshift import RedshiftExecutor
        return RedshiftExecutor

    def test_standard_connection(self):
        mock_rs = MagicMock()
        mock_conn = MagicMock()
        mock_rs.connect.return_value = mock_conn

        Cls = self._make_executor(mock_rs)
        executor = Cls(host="rs-host", port=5439, database="dev", username="admin", password="pass")
        conn = executor._get_connection()
        assert conn is mock_conn
        mock_rs.connect.assert_called_once()

    def test_serverless_connection(self):
        mock_rs = MagicMock()
        mock_conn = MagicMock()
        mock_rs.connect.return_value = mock_conn

        Cls = self._make_executor(mock_rs)
        executor = Cls(
            is_serverless=True, workgroup="wg",
            database="dev", access_key="ak", secret_key="sk", region="us-east-1",
        )
        conn = executor._get_connection()
        assert conn is mock_conn
        call_kwargs = mock_rs.connect.call_args[1]
        assert call_kwargs["is_serverless"] is True
        assert call_kwargs["serverless_work_group"] == "wg"

    def test_iam_connection(self):
        mock_rs = MagicMock()
        mock_conn = MagicMock()
        mock_rs.connect.return_value = mock_conn

        Cls = self._make_executor(mock_rs)
        executor = Cls(
            iam=True, cluster_identifier="cluster-1",
            database="dev", db_user="admin",
            access_key="ak", secret_key="sk", region="us-east-1",
        )
        conn = executor._get_connection()
        call_kwargs = mock_rs.connect.call_args[1]
        assert call_kwargs["iam"] is True
        assert call_kwargs["cluster_identifier"] == "cluster-1"

    async def test_execute_sql(self):
        mock_rs = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchmany.return_value = [("data",)]
        mock_cursor.fetchone.return_value = None
        mock_cursor.description = [("col",)]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_rs.connect.return_value = mock_conn

        Cls = self._make_executor(mock_rs)
        executor = Cls(host="rs-host", port=5439, database="dev", username="admin", password="pass")
        result = await executor.execute_sql("SELECT 1")
        assert "data" in result

    async def test_timeout_error(self):
        mock_rs = MagicMock()
        mock_rs.connect.side_effect = Exception("Connection timed out")

        Cls = self._make_executor(mock_rs)
        executor = Cls(host="rs-host", port=5439, database="dev", username="admin", password="pass")
        with pytest.raises(Exception, match="Connection timed out"):
            await executor.execute_sql("SELECT 1")


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------
class TestFactory:
    def test_create_motherduck(self):
        from app.connections.factory import create_executor
        from app.connections.motherduck import MotherDuckExecutor

        executor = create_executor("motherduck", {"token": "t", "database": "db"})
        assert isinstance(executor, MotherDuckExecutor)

    def test_create_postgresql(self):
        from app.connections.factory import create_executor
        from app.connections.postgres import PostgreSQLExecutor

        executor = create_executor("postgresql", {
            "host": "h", "port": "5432", "database": "d",
            "username": "u", "password": "p",
        })
        assert isinstance(executor, PostgreSQLExecutor)

    def test_create_snowflake(self):
        from app.connections.factory import create_executor
        from app.connections.snowflake import SnowflakeExecutor

        executor = create_executor("snowflake", {
            "account": "a", "username": "u", "password": "p",
            "warehouse": "w", "database": "d",
        })
        assert isinstance(executor, SnowflakeExecutor)

    def test_create_bigquery(self):
        from app.connections.factory import create_executor
        from app.connections.bigquery import BigQueryExecutor

        executor = create_executor("bigquery", {
            "credentials_json": '{}', "project_id": "proj",
        })
        assert isinstance(executor, BigQueryExecutor)

    def test_create_redshift_standard(self):
        from app.connections.factory import create_executor
        from app.connections.redshift import RedshiftExecutor

        executor = create_executor("redshift", {
            "host": "h", "port": "5439", "database": "d",
            "username": "u", "password": "p",
        })
        assert isinstance(executor, RedshiftExecutor)

    def test_create_redshift_serverless(self):
        from app.connections.factory import create_executor
        from app.connections.redshift import RedshiftExecutor

        executor = create_executor("redshift", {
            "workgroup": "wg", "database": "d",
            "access_key": "ak", "secret_key": "sk", "region": "us-east-1",
        })
        assert isinstance(executor, RedshiftExecutor)

    def test_create_redshift_iam(self):
        from app.connections.factory import create_executor
        from app.connections.redshift import RedshiftExecutor

        executor = create_executor("redshift", {
            "cluster_identifier": "c", "database": "d",
            "db_user": "u", "access_key": "ak", "secret_key": "sk", "region": "us-east-1",
        })
        assert isinstance(executor, RedshiftExecutor)

    def test_unknown_type_raises(self):
        from app.connections.factory import create_executor

        with pytest.raises(ValueError, match="Unknown warehouse type"):
            create_executor("oracle", {})


# ---------------------------------------------------------------------------
# Base utilities
# ---------------------------------------------------------------------------
class TestBaseUtilities:
    def test_format_schema_summary(self):
        from app.connections.base import format_schema_summary

        rows = [
            ("public", "users", "id", "integer"),
            ("public", "users", "name", "text"),
            ("public", "orders", "id", "integer"),
        ]
        result = format_schema_summary(rows, "mydb")
        assert "mydb.public.users" in result
        assert "mydb.public.orders" in result
        assert "id (integer)" in result

    def test_format_schema_summary_truncation(self):
        from app.connections.base import format_schema_summary, MAX_SCHEMA_TABLES

        rows = [
            (f"schema_{i}", f"table_{i}", "id", "int")
            for i in range(MAX_SCHEMA_TABLES + 10)
        ]
        result = format_schema_summary(rows, "db")
        assert "truncated" in result.lower()
