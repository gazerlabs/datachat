"""Per-user persistent DuckDB executor.

Each user has one .duckdb file on disk holding all their uploaded local data files
(csv/excel/parquet/json) as tables. This enables cross-file joins natively and
persists across server restarts (assuming the storage directory is on a persistent
volume in production).
"""

import asyncio
import logging
import os
import re
from typing import Optional

from tabulate import tabulate

from app.connections.base import WarehouseExecutor, MAX_ROWS, MAX_CHARS
from app.connections.duckdb_local import _filename_to_table_name, _load_file_into_table

logger = logging.getLogger("warehouse_executor")

# Clerk user IDs look like `user_<base32>` — letters, digits, hyphen, underscore.
# Be strict here: anything else hitting the filesystem is either a coding bug
# or an attempt to escape the storage directory via path-traversal characters
# (".", "/", "\\", null bytes, etc.). Refuse rather than try to sanitize.
_SAFE_USER_ID = re.compile(r"\A[A-Za-z0-9_\-]+\Z")


def _safe_user_id(user_id: str) -> str:
    if not user_id or not _SAFE_USER_ID.fullmatch(user_id):
        raise ValueError(f"Invalid user_id for DuckDB path: {user_id!r}")
    return user_id


def get_user_db_path(base_dir: str, user_id: str) -> str:
    """Return the absolute path to a user's persistent DuckDB file.

    Caller is responsible for ensuring the parent directory exists before opening
    the file for write. Raises ValueError if user_id contains characters that
    could break out of base_dir."""
    safe_id = _safe_user_id(user_id)
    return os.path.abspath(os.path.join(base_dir, f"{safe_id}.duckdb"))


def ensure_storage_dir(base_dir: str) -> None:
    """Create the storage directory if it doesn't exist yet."""
    os.makedirs(base_dir, exist_ok=True)


def _open_rw(file_path: str):
    import duckdb
    conn = duckdb.connect(file_path, read_only=False)
    conn.execute("INSTALL json; LOAD json;")
    return conn


def _open_ro(file_path: str):
    import duckdb
    conn = duckdb.connect(file_path, read_only=True)
    return conn


def list_existing_table_names(file_path: str) -> set[str]:
    """Open the user's DuckDB file briefly and read the existing table identifiers."""
    if not os.path.exists(file_path):
        return set()
    conn = _open_ro(file_path)
    try:
        rows = conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'main'"
        ).fetchall()
        return {r[0] for r in rows}
    finally:
        conn.close()


def append_file_blocking(
    file_path_db: str,
    upload_path: str,
    filename: str,
    existing_tables: set[str],
) -> dict:
    """Synchronously open the user's DuckDB (RW), load the upload as a new table,
    return the table info dict. Closes the connection before returning so the file
    is unlocked for read-only consumers."""
    table_name = _filename_to_table_name(filename, existing_tables)
    conn = _open_rw(file_path_db)
    try:
        return _load_file_into_table(conn, upload_path, filename, table_name)
    finally:
        conn.close()


def drop_table_blocking(file_path_db: str, table_name: str) -> None:
    """Synchronously DROP a table from the user's DuckDB."""
    conn = _open_rw(file_path_db)
    try:
        conn.execute(f'DROP TABLE IF EXISTS "{table_name}"')
    finally:
        conn.close()


async def append_file(file_path_db: str, upload_path: str, filename: str, existing_tables: set[str]) -> dict:
    return await asyncio.to_thread(append_file_blocking, file_path_db, upload_path, filename, existing_tables)


async def drop_table(file_path_db: str, table_name: str) -> None:
    await asyncio.to_thread(drop_table_blocking, file_path_db, table_name)


class LocalDuckDBExecutor(WarehouseExecutor):
    """Read-only executor against a user's persistent DuckDB file.

    Opens a fresh read-only connection on construction; close() releases it. Safe
    to use even while another process holds a write lock briefly, because we open
    on demand inside each query thread.
    """

    def __init__(self, file_path: str):
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Local DuckDB file not found: {file_path}")
        self._file_path = file_path
        self._conn = _open_ro(file_path)

    def close(self):
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def _run_query(self, sql: str) -> str:
        if self._conn is None:
            raise RuntimeError("LocalDuckDB connection is closed")

        q = self._conn.execute(sql)
        if q.description is None:
            return "Query executed successfully (no results)."

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

    async def execute_sql(self, sql: str) -> str:
        return await asyncio.to_thread(self._run_query, sql)

    async def list_datasets(self) -> str:
        return await asyncio.to_thread(
            self._run_query,
            "SELECT DISTINCT table_schema FROM information_schema.tables "
            "WHERE table_schema NOT IN ('information_schema', 'pg_catalog') "
            "ORDER BY table_schema",
        )

    async def list_tables(self, dataset: str) -> str:
        sql = (
            "SELECT table_name, table_type FROM information_schema.tables "
            f"WHERE table_schema = '{dataset}' ORDER BY table_name"
        )
        return await asyncio.to_thread(self._run_query, sql)

    async def get_table_schema(self, dataset: str, table: str) -> str:
        sql = (
            "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
            f"WHERE table_schema = '{dataset}' AND table_name = '{table}' "
            "ORDER BY ordinal_position"
        )
        return await asyncio.to_thread(self._run_query, sql)

    async def get_schema_summary(self) -> str:
        try:
            return await asyncio.to_thread(self._build_schema_summary)
        except Exception as e:
            logger.warning(f"LocalDuckDB schema summary failed: {e}")
            return ""

    def _build_schema_summary(self) -> str:
        if self._conn is None:
            return ""
        from app.connections.duckdb_local import MAX_SAMPLE_ROWS

        tables = self._conn.execute(
            "SELECT table_schema, table_name FROM information_schema.tables "
            "WHERE table_schema NOT IN ('information_schema', 'pg_catalog') "
            "ORDER BY table_schema, table_name"
        ).fetchall()

        parts = []
        for schema_name, table_name in tables[:50]:
            fqn = f'"{table_name}"' if schema_name == "main" else f'"{schema_name}"."{table_name}"'

            try:
                row_count = self._conn.execute(f"SELECT COUNT(*) FROM {fqn}").fetchone()[0]
            except Exception:
                row_count = "unknown"

            columns = self._conn.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_schema = ? AND table_name = ? ORDER BY ordinal_position",
                [schema_name, table_name],
            ).fetchall()

            col_lines = "\n".join(f"  - {c[0]} ({c[1]})" for c in columns[:30])

            sample_lines = ""
            try:
                sample = self._conn.execute(f"SELECT * FROM {fqn} LIMIT {MAX_SAMPLE_ROWS}").fetchall()
                if sample:
                    headers = [c[0] for c in columns[:30]]
                    header_line = " | ".join(headers)
                    data_lines = []
                    for row in sample:
                        vals = []
                        for v in row[:30]:
                            s = str(v) if v is not None else "NULL"
                            if len(s) > 50:
                                s = s[:47] + "..."
                            vals.append(s)
                        data_lines.append(" | ".join(vals))
                    sample_lines = (
                        f"\nSample data (first {len(sample)} rows):\n"
                        f"{header_line}\n" + "\n".join(data_lines)
                    )
            except Exception:
                pass

            display_name = table_name if schema_name == "main" else f"{schema_name}.{table_name}"
            row_count_str = f"{row_count:,}" if isinstance(row_count, int) else str(row_count)
            parts.append(
                f"Table: {display_name} ({row_count_str} rows)\n"
                f"Columns:\n{col_lines}{sample_lines}"
            )

        return "\n\n".join(parts)
