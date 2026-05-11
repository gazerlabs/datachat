"""BigQuery warehouse executor."""

import asyncio
import json
import logging
import re
from typing import Optional

import httpx
from google.oauth2 import service_account
from google.auth.transport.requests import Request
from tabulate import tabulate

from app.connections.base import (
    WarehouseExecutor, format_schema_summary,
    MAX_ROWS, MAX_CHARS, MAX_SCHEMA_TABLES,
)

logger = logging.getLogger("warehouse_executor")

# BigQuery dataset / table / project IDs are constrained to letters, digits,
# underscores, and (for tables) dashes. We get these from caller-supplied tool
# arguments and embed them directly in REST URL paths, so reject anything that
# could break out of the path segment (e.g. "..", "/", "?").
_SAFE_BQ_IDENTIFIER = re.compile(r"\A[A-Za-z0-9_\-]+\Z")


def _check_bq_identifier(name: str, *, kind: str) -> str:
    if not name or not _SAFE_BQ_IDENTIFIER.fullmatch(name):
        raise ValueError(f"Invalid BigQuery {kind} identifier: {name!r}")
    return name


def get_bigquery_access_token(credentials_json: str) -> Optional[str]:
    """Generate an OAuth access token from BigQuery service account credentials."""
    try:
        creds_data = json.loads(credentials_json)
        creds = service_account.Credentials.from_service_account_info(
            creds_data,
            scopes=[
                "https://www.googleapis.com/auth/bigquery",
                "https://www.googleapis.com/auth/cloud-platform",
            ],
        )
        creds.refresh(Request())
        return creds.token
    except Exception as e:
        logger.error(f"Error generating BigQuery access token: {e}")
        return None


class BigQueryExecutor(WarehouseExecutor):
    """Execute queries against BigQuery using the REST API."""

    def __init__(self, credentials_json: str, project_id: str):
        self._credentials_json = credentials_json
        self._project_id = project_id

    def _get_token(self) -> str:
        token = get_bigquery_access_token(self._credentials_json)
        if not token:
            raise RuntimeError("Failed to generate BigQuery access token")
        return token

    async def _run_query(self, sql: str) -> str:
        token = self._get_token()
        url = f"https://bigquery.googleapis.com/bigquery/v2/projects/{self._project_id}/queries"

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                url,
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "query": sql,
                    "useLegacySql": False,
                    "maxResults": MAX_ROWS,
                },
            )
            resp.raise_for_status()
            data = resp.json()

            job_id = data.get("jobReference", {}).get("jobId")
            if not data.get("jobComplete", False) and job_id:
                poll_url = f"https://bigquery.googleapis.com/bigquery/v2/projects/{self._project_id}/queries/{job_id}"
                for _ in range(60):
                    await asyncio.sleep(1)
                    resp = await client.get(
                        poll_url,
                        headers={"Authorization": f"Bearer {token}"},
                        params={"maxResults": MAX_ROWS},
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    if data.get("jobComplete", False):
                        break
                else:
                    raise RuntimeError("BigQuery query timed out after 60s")

        schema_fields = data.get("schema", {}).get("fields", [])
        headers = [f["name"] for f in schema_fields]
        raw_rows = data.get("rows", [])
        rows = [[cell.get("v") for cell in row.get("f", [])] for row in raw_rows]

        total_rows = int(data.get("totalRows", len(rows)))
        has_more = total_rows > len(rows)

        out = tabulate(rows, headers=headers, tablefmt="pretty")

        if len(out) > MAX_CHARS:
            out = out[:MAX_CHARS]
            out += f"\n\n-- Output truncated at {MAX_CHARS:,} characters."
        elif has_more:
            out += f"\n\n-- Showing first {len(rows)} of {total_rows} rows."

        return out

    async def verify_read_only(self) -> bool:
        try:
            await self._run_query(
                "CREATE TEMP TABLE _datachat_readonly_test (id INT64)"
            )
            try:
                await self._run_query("DROP TABLE IF EXISTS _datachat_readonly_test")
            except Exception:
                pass
            return False
        except Exception:
            return True

    async def execute_sql(self, sql: str) -> str:
        return await self._run_query(sql)

    async def list_datasets(self) -> str:
        token = self._get_token()
        url = f"https://bigquery.googleapis.com/bigquery/v2/projects/{self._project_id}/datasets"
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {token}"})
            resp.raise_for_status()
            data = resp.json()

        datasets = data.get("datasets", [])
        rows = [[d["datasetReference"]["datasetId"]] for d in datasets]
        return tabulate(rows, headers=["dataset_id"], tablefmt="pretty")

    async def list_tables(self, dataset: str) -> str:
        safe_dataset = _check_bq_identifier(dataset, kind="dataset")
        token = self._get_token()
        url = f"https://bigquery.googleapis.com/bigquery/v2/projects/{self._project_id}/datasets/{safe_dataset}/tables"
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {token}"})
            resp.raise_for_status()
            data = resp.json()

        tables = data.get("tables", [])
        rows = [[t["tableReference"]["tableId"], t.get("type", "")] for t in tables]
        return tabulate(rows, headers=["table_id", "type"], tablefmt="pretty")

    async def get_table_schema(self, dataset: str, table: str) -> str:
        safe_dataset = _check_bq_identifier(dataset, kind="dataset")
        safe_table = _check_bq_identifier(table, kind="table")
        token = self._get_token()
        url = f"https://bigquery.googleapis.com/bigquery/v2/projects/{self._project_id}/datasets/{safe_dataset}/tables/{safe_table}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {token}"})
            resp.raise_for_status()
            data = resp.json()

        fields = data.get("schema", {}).get("fields", [])
        rows = [[f["name"], f["type"], f.get("mode", "")] for f in fields]
        return tabulate(rows, headers=["column_name", "data_type", "mode"], tablefmt="pretty")

    async def get_schema_summary(self) -> str:
        try:
            token = self._get_token()
            base = f"https://bigquery.googleapis.com/bigquery/v2/projects/{self._project_id}"
            tuples: list[tuple] = []

            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    f"{base}/datasets",
                    headers={"Authorization": f"Bearer {token}"},
                )
                resp.raise_for_status()
                datasets = resp.json().get("datasets", [])

                table_count = 0
                for ds in datasets:
                    dataset_id = ds["datasetReference"]["datasetId"]
                    if table_count >= MAX_SCHEMA_TABLES:
                        break

                    resp = await client.get(
                        f"{base}/datasets/{dataset_id}/tables",
                        headers={"Authorization": f"Bearer {token}"},
                    )
                    resp.raise_for_status()
                    tables = resp.json().get("tables", [])

                    for tbl in tables:
                        if table_count >= MAX_SCHEMA_TABLES:
                            break
                        table_id = tbl["tableReference"]["tableId"]

                        resp = await client.get(
                            f"{base}/datasets/{dataset_id}/tables/{table_id}",
                            headers={"Authorization": f"Bearer {token}"},
                        )
                        resp.raise_for_status()
                        fields = resp.json().get("schema", {}).get("fields", [])
                        for f in fields:
                            tuples.append((dataset_id, table_id, f["name"], f["type"]))

                        table_count += 1

            return format_schema_summary(tuples, self._project_id)
        except Exception as e:
            logger.warning(f"BigQuery schema summary failed: {e}")
            return ""
