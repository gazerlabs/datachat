"""SQL-injection regression tests for the schema-discovery tools on every
warehouse executor.

In all five executors, list_tables and get_table_schema take caller-controlled
dataset / table names. They used to interpolate those names directly into SQL
(or, for BigQuery, into REST URL paths). This file pins the new behavior:

  - Postgres / Redshift / MotherDuck pass the names as bound parameters.
  - Snowflake validates them with a strict identifier regex (its SHOW
    statements don't accept bind params).
  - BigQuery validates them before embedding into URL path segments.
"""

import re
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Postgres
# ---------------------------------------------------------------------------
class TestPostgresParameterized:
    def _make_executor(self, mock_psycopg2):
        sys.modules["psycopg2"] = mock_psycopg2
        from app.connections.postgres import PostgreSQLExecutor
        return PostgreSQLExecutor

    def _setup(self):
        mock_pg = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchmany.return_value = []
        mock_cursor.fetchone.return_value = None
        mock_cursor.description = [("col",)]
        mock_conn = MagicMock()
        mock_conn.closed = False
        mock_conn.cursor.return_value = mock_cursor
        mock_pg.connect.return_value = mock_conn

        Cls = self._make_executor(mock_pg)
        executor = Cls(host="h", port="5432", database="d", username="u", password="p")
        return executor, mock_cursor

    async def test_list_tables_uses_bind_parameter(self):
        executor, cur = self._setup()
        malicious = "public'; DROP TABLE users; --"
        await executor.list_tables(malicious)
        sql, params = cur.execute.call_args.args
        # No interpolation of the malicious string into the SQL itself.
        assert malicious not in sql
        assert "%s" in sql
        assert params == (malicious,)

    async def test_get_table_schema_uses_bind_parameters(self):
        executor, cur = self._setup()
        await executor.get_table_schema("public'; DROP", "users'; DROP")
        sql, params = cur.execute.call_args.args
        assert "DROP" not in sql
        assert sql.count("%s") == 2
        assert params == ("public'; DROP", "users'; DROP")


# ---------------------------------------------------------------------------
# Redshift
# ---------------------------------------------------------------------------
class TestRedshiftParameterized:
    def _make_executor(self, mock_rs):
        sys.modules["redshift_connector"] = mock_rs
        from app.connections.redshift import RedshiftExecutor
        return RedshiftExecutor

    def _setup(self):
        mock_rs = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchmany.return_value = []
        mock_cursor.fetchone.return_value = None
        mock_cursor.description = [("col",)]
        mock_conn = MagicMock()
        mock_conn.closed = False
        mock_conn.cursor.return_value = mock_cursor
        mock_rs.connect.return_value = mock_conn

        Cls = self._make_executor(mock_rs)
        executor = Cls(host="h", port=5439, database="d", username="u", password="p")
        return executor, mock_cursor

    async def test_list_tables_uses_bind_parameter(self):
        executor, cur = self._setup()
        malicious = "public'; DROP TABLE users; --"
        await executor.list_tables(malicious)
        # Find the call that ran the user query (skip the SET statement_timeout
        # call made on connect).
        call = next(c for c in cur.execute.call_args_list if len(c.args) > 1)
        sql, params = call.args
        assert malicious not in sql
        assert "%s" in sql
        assert params == (malicious,)

    async def test_get_table_schema_uses_bind_parameters(self):
        executor, cur = self._setup()
        await executor.get_table_schema("schema_x", "table_x'; --")
        call = next(c for c in cur.execute.call_args_list if len(c.args) > 1)
        sql, params = call.args
        assert "'; --" not in sql
        assert sql.count("%s") == 2
        assert params == ("schema_x", "table_x'; --")


# ---------------------------------------------------------------------------
# MotherDuck
# ---------------------------------------------------------------------------
class TestMotherDuckParameterized:
    def _make_executor(self, mock_duckdb):
        sys.modules["duckdb"] = mock_duckdb
        from app.connections.motherduck import MotherDuckExecutor
        return MotherDuckExecutor

    def _setup(self):
        mock_duckdb = MagicMock()
        mock_query = MagicMock()
        mock_query.fetchmany.return_value = []
        mock_query.fetchone.return_value = None
        mock_query.description = [("col",)]
        mock_conn = MagicMock()
        mock_conn.execute.return_value = mock_query
        mock_duckdb.connect.return_value = mock_conn

        Cls = self._make_executor(mock_duckdb)
        executor = Cls(token="t", database="d")
        return executor, mock_conn

    async def test_list_tables_uses_bind_parameter(self):
        executor, conn = self._setup()
        malicious = "main'; DROP TABLE x; --"
        await executor.list_tables(malicious)
        sql, params = conn.execute.call_args.args
        assert malicious not in sql
        assert "?" in sql
        assert params == (malicious,)

    async def test_get_table_schema_uses_bind_parameters(self):
        executor, conn = self._setup()
        await executor.get_table_schema("ds", "tbl'; --")
        sql, params = conn.execute.call_args.args
        assert "'; --" not in sql
        assert sql.count("?") == 2
        # MotherDuck binds (table, dataset) — order matters for the test.
        assert "tbl'; --" in params
        assert "ds" in params


# ---------------------------------------------------------------------------
# Snowflake (SHOW statements take identifiers, not bind params — relies on
# strict-validation rejection instead)
# ---------------------------------------------------------------------------
class TestSnowflakeIdentifierValidation:
    def _make_executor(self, mock_sf_connector):
        mock_sf = MagicMock()
        mock_sf.connector = mock_sf_connector
        sys.modules["snowflake"] = mock_sf
        sys.modules["snowflake.connector"] = mock_sf_connector
        from app.connections.snowflake import SnowflakeExecutor
        return SnowflakeExecutor

    async def test_list_tables_rejects_unsafe_dataset(self):
        Cls = self._make_executor(MagicMock())
        executor = Cls(account="a", username="u", password="p", warehouse="w", database="d")
        with pytest.raises(ValueError, match="Invalid dataset identifier"):
            await executor.list_tables("evil'; DROP")

    async def test_get_table_schema_rejects_unsafe_table(self):
        Cls = self._make_executor(MagicMock())
        executor = Cls(account="a", username="u", password="p", warehouse="w", database="d")
        with pytest.raises(ValueError, match="Invalid table identifier"):
            await executor.get_table_schema("good_dataset", "evil; --")

    async def test_safe_identifier_passes_through(self):
        mock_connector = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchmany.return_value = []
        mock_cursor.fetchone.return_value = None
        mock_cursor.description = [("col",)]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connector.connect.return_value = mock_conn

        Cls = self._make_executor(mock_connector)
        executor = Cls(account="a", username="u", password="p", warehouse="w", database="d")
        await executor.list_tables("MY_DB")
        sql = mock_cursor.execute.call_args.args[0]
        assert "MY_DB" in sql


# ---------------------------------------------------------------------------
# BigQuery — identifiers go into REST URL paths, validated against allowlist
# ---------------------------------------------------------------------------
class TestBigQueryIdentifierValidation:
    @patch("app.connections.bigquery.get_bigquery_access_token", return_value="tok")
    async def test_list_tables_rejects_path_traversal(self, _token):
        from app.connections.bigquery import BigQueryExecutor
        executor = BigQueryExecutor(credentials_json='{}', project_id="p")
        with pytest.raises(ValueError, match="Invalid BigQuery dataset identifier"):
            await executor.list_tables("../../foo")

    @patch("app.connections.bigquery.get_bigquery_access_token", return_value="tok")
    async def test_get_table_schema_rejects_slash_in_table(self, _token):
        from app.connections.bigquery import BigQueryExecutor
        executor = BigQueryExecutor(credentials_json='{}', project_id="p")
        with pytest.raises(ValueError, match="Invalid BigQuery table identifier"):
            await executor.get_table_schema("ds", "tbl/oops")

    @patch("app.connections.bigquery.get_bigquery_access_token", return_value="tok")
    async def test_safe_identifier_passes_through(self, _token):
        from app.connections.bigquery import BigQueryExecutor
        executor = BigQueryExecutor(credentials_json='{}', project_id="p")

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"tables": []}

        with patch("httpx.AsyncClient") as client_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            client_cls.return_value = mock_client

            await executor.list_tables("my-dataset_42")
            url = mock_client.get.call_args.args[0]
            assert "my-dataset_42" in url
