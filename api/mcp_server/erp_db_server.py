"""Apptimate ERP database MCP server (pure Python, read-only, live MySQL).

Exposes the live tenant database to any MCP client (the Apptimate Assist chat
engine, an IDE, or another agent) through these tools:

    list_tables       compact catalogue: table names, estimated rows, column counts
    describe_tables   columns, types, enums, primary keys, indexes, foreign keys
    find_columns      search every table for columns matching a keyword
    explain_select    MySQL EXPLAIN plan, so the LLM can check index usage
    run_select        run one read-only SELECT and return a chunk (page) of rows

Schema is read from INFORMATION_SCHEMA and cached for a short TTL only, so new
migrations show up automatically. Business data is never cached: every
run_select reads the live database.

Run:
    python mcp_server/erp_db_server.py                     # stdio (IDE / subprocess)
    python mcp_server/erp_db_server.py --http --port 8765  # streamable HTTP daemon
"""
from __future__ import annotations

import argparse
import functools
import json
import os
import re
import threading
import time
from datetime import date, datetime, time as dtime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pymysql
from dotenv import load_dotenv
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

API_DIR = Path(__file__).resolve().parents[1]
load_dotenv(API_DIR / ".env")

MYSQL_HOST = os.getenv("MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
DEFAULT_DATABASE = os.getenv("DEFAULT_TENANT_ID", "apptimate_infinity")

SCHEMA_TTL_SECONDS = int(os.getenv("MCP_SCHEMA_TTL_SECONDS", "60"))
QUERY_TIMEOUT_MS = int(os.getenv("MCP_QUERY_TIMEOUT_MS", "15000"))
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 500
MAX_CELL_CHARS = 500

_DATABASE_RE = re.compile(r"^(?:apptimate_[A-Za-z0-9_]+|test)$")
_SENSITIVE_COLUMN_RE = re.compile(r"password|passwd|token|secret|credential|private_?key|api_?key", re.I)
_FORBIDDEN_SQL_RE = re.compile(
    r"\b(?:INSERT|UPDATE|DELETE|ALTER|DROP|CREATE|TRUNCATE|RENAME|GRANT|REVOKE|LOCK|UNLOCK|CALL|"
    r"HANDLER|LOAD|SET|DO|PREPARE|EXECUTE|DEALLOCATE|KILL|SHUTDOWN|FLUSH|RESET|PURGE|INSTALL|UNINSTALL)\b"
    r"|\bREPLACE\b(?!\s*\()"
    r"|\bINTO\s+(?:OUTFILE|DUMPFILE|@)"
    r"|\bFOR\s+(?:UPDATE|SHARE)\b|\bLOCK\s+IN\s+SHARE\s+MODE\b"
    r"|\b(?:SLEEP|BENCHMARK|GET_LOCK|RELEASE_LOCK|LOAD_FILE)\s*\(",
    re.I,
)
_TRAILING_LIMIT_RE = re.compile(r"\bLIMIT\s+\d+(?:\s*,\s*\d+|\s+OFFSET\s+\d+)?\s*$", re.I)

mcp = MCPServer(
    name="apptimate-erp-db",
    title="Apptimate ERP Database",
    version="1.0.0",
    instructions=(
        "Read-only access to the live Apptimate One ERP MySQL database. "
        "Workflow: list_tables or find_columns to locate data -> describe_tables for exact columns, "
        "keys and indexes -> write ONE MySQL SELECT using only the described columns -> run_select. "
        "Push filtering, joins and aggregation (COUNT/SUM/AVG/GROUP BY) into SQL instead of fetching raw rows. "
        "Results are paged; use next_offset to fetch the next chunk. Respect deleted_at IS NULL where the column exists."
    ),
)

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)


def _model_visible_errors(fn):
    """Return validation and MySQL errors to the caller so the LLM can correct its SQL.

    MCP hides the text of unexpected exceptions; ToolError messages are delivered as
    is_error results. Connection credentials never appear in these messages.
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ValueError as exc:
            raise ToolError(str(exc)) from exc
        except pymysql.MySQLError as exc:
            code, message = (exc.args + ("",))[:2] if exc.args else ("", str(exc))
            raise ToolError(f"MySQL error {code}: {message}") from exc
    return wrapper


# ---------------------------------------------------------------------------
# Connection and serialization helpers
# ---------------------------------------------------------------------------

def _database(name: str | None) -> str:
    database = (name or DEFAULT_DATABASE).strip()
    if not _DATABASE_RE.fullmatch(database):
        raise ValueError(f"Database must match apptimate_<name>; got {database!r}.")
    return database


def _connect(database: str):
    return pymysql.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=database,
        cursorclass=pymysql.cursors.DictCursor,
        charset="utf8mb4",
        connect_timeout=5,
        read_timeout=max(5, QUERY_TIMEOUT_MS // 1000 + 5),
        autocommit=False,
    )


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        if value % 1 == 0:
            return int(value)
        as_float = float(value)
        return as_float if Decimal(str(as_float)) == value else format(value, "f")
    if isinstance(value, (datetime, date, dtime)):
        return value.isoformat()
    if isinstance(value, timedelta):
        return str(value)
    if isinstance(value, (bytes, bytearray)):
        return f"<{len(value)} bytes>"
    if isinstance(value, str) and len(value) > MAX_CELL_CHARS:
        return value[:MAX_CELL_CHARS] + f"... (+{len(value) - MAX_CELL_CHARS} chars)"
    return value


def _clean_row(row: dict) -> dict:
    return {
        key: ("[redacted]" if _SENSITIVE_COLUMN_RE.search(str(key)) else _json_value(value))
        for key, value in row.items()
    }


# ---------------------------------------------------------------------------
# Live schema introspection (short TTL cache; data itself is never cached)
# ---------------------------------------------------------------------------

_schema_cache: dict[str, tuple[float, dict]] = {}
_schema_lock = threading.Lock()


def _plural_stems(table: str) -> set[str]:
    """Singular stems a `<stem>_id` column could use to reference this table."""
    stems = set()
    parts = table.split("_")
    for index in range(len(parts)):
        stem = "_".join(parts[index:])
        if stem.endswith("ies") and len(stem) > 4:
            stems.add(stem[:-3] + "y")
        elif stem.endswith(("ches", "shes", "xes", "sses")):
            stems.add(stem[:-2])
        elif stem.endswith("s") and len(stem) > 2:
            stems.add(stem[:-1])
        stems.add(stem)
    return stems


def _load_schema(database: str, refresh: bool = False) -> dict:
    now = time.monotonic()
    with _schema_lock:
        cached = _schema_cache.get(database)
        if cached and not refresh and now - cached[0] < SCHEMA_TTL_SECONDS:
            return cached[1]

    with _connect(database) as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT TABLE_NAME, TABLE_ROWS, TABLE_COMMENT FROM INFORMATION_SCHEMA.TABLES
               WHERE TABLE_SCHEMA=%s AND TABLE_TYPE IN ('BASE TABLE','VIEW') ORDER BY TABLE_NAME""",
            (database,),
        )
        table_rows = cur.fetchall()
        cur.execute(
            """SELECT TABLE_NAME, COLUMN_NAME, COLUMN_TYPE, DATA_TYPE, IS_NULLABLE, COLUMN_KEY, COLUMN_COMMENT
               FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA=%s ORDER BY TABLE_NAME, ORDINAL_POSITION""",
            (database,),
        )
        column_rows = cur.fetchall()
        cur.execute(
            """SELECT TABLE_NAME, COLUMN_NAME, REFERENCED_TABLE_NAME, REFERENCED_COLUMN_NAME
               FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE
               WHERE TABLE_SCHEMA=%s AND REFERENCED_TABLE_NAME IS NOT NULL""",
            (database,),
        )
        fk_rows = cur.fetchall()
        cur.execute(
            """SELECT TABLE_NAME, INDEX_NAME, NON_UNIQUE, SEQ_IN_INDEX, COLUMN_NAME
               FROM INFORMATION_SCHEMA.STATISTICS WHERE TABLE_SCHEMA=%s
               ORDER BY TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX""",
            (database,),
        )
        index_rows = cur.fetchall()

    tables: dict[str, dict] = {
        row["TABLE_NAME"]: {
            "estimated_rows": int(row["TABLE_ROWS"] or 0),
            "comment": row["TABLE_COMMENT"] or "",
            "columns": {},
            "primary_key": [],
            "indexes": {},
            "foreign_keys": [],
        }
        for row in table_rows
    }
    for row in column_rows:
        table = tables.get(row["TABLE_NAME"])
        if table is None or _SENSITIVE_COLUMN_RE.search(row["COLUMN_NAME"]):
            continue
        column = {"type": row["COLUMN_TYPE"], "nullable": row["IS_NULLABLE"] == "YES"}
        if row["DATA_TYPE"] == "enum":
            column["values"] = re.findall(r"'((?:[^']|'')*)'", row["COLUMN_TYPE"])
            column["type"] = "enum"
        if row["COLUMN_COMMENT"]:
            column["comment"] = row["COLUMN_COMMENT"]
        table["columns"][row["COLUMN_NAME"]] = column
        if row["COLUMN_KEY"] == "PRI":
            table["primary_key"].append(row["COLUMN_NAME"])
    for row in index_rows:
        table = tables.get(row["TABLE_NAME"])
        if table is None or row["INDEX_NAME"] == "PRIMARY":
            continue
        index = table["indexes"].setdefault(row["INDEX_NAME"], {"unique": not row["NON_UNIQUE"], "columns": []})
        index["columns"].append(row["COLUMN_NAME"])

    declared = set()
    for row in fk_rows:
        if row["TABLE_NAME"] in tables and row["REFERENCED_TABLE_NAME"] in tables:
            edge = (row["TABLE_NAME"], row["COLUMN_NAME"], row["REFERENCED_TABLE_NAME"], row["REFERENCED_COLUMN_NAME"])
            declared.add(edge[:2])
            tables[edge[0]]["foreign_keys"].append(
                {"column": edge[1], "references": f"{edge[2]}.{edge[3]}", "source": "declared"}
            )

    # Naming-convention inference for `<stem>_id` columns that have no declared FK
    # (common in Laravel schemas). Prefer a target in the same module prefix.
    stem_index: dict[str, list[str]] = {}
    for name, table in tables.items():
        if "id" in table["columns"]:
            for stem in _plural_stems(name):
                stem_index.setdefault(f"{stem}_id", []).append(name)
    for name, table in tables.items():
        prefix = name.split("_")[0]
        for column in table["columns"]:
            if not column.endswith("_id") or (name, column) in declared:
                continue
            candidates = [t for t in stem_index.get(column, []) if t != name]
            same_module = [t for t in candidates if t.split("_")[0] == prefix]
            chosen = same_module if len(same_module) == 1 else candidates if len(candidates) == 1 else []
            for target in chosen:
                table["foreign_keys"].append({"column": column, "references": f"{target}.id", "source": "inferred"})

    schema = {"database": database, "loaded_at": datetime.now().isoformat(timespec="seconds"), "tables": tables}
    with _schema_lock:
        _schema_cache[database] = (now, schema)
    return schema


# ---------------------------------------------------------------------------
# SQL safety
# ---------------------------------------------------------------------------

def _strip_literals_and_comments(sql: str) -> str:
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    sql = re.sub(r"(?:--\s|#)[^\n]*", " ", sql)
    return re.sub(r"'(?:[^'\\]|\\.|'')*'|\"(?:[^\"\\]|\\.)*\"", "''", sql)


def _validate_select(sql: str) -> str:
    if not isinstance(sql, str) or not sql.strip():
        raise ValueError("sql must be a non-empty SELECT statement.")
    sql = sql.strip().rstrip(";").strip()
    skeleton = _strip_literals_and_comments(sql)
    if ";" in skeleton:
        raise ValueError("Only one statement is allowed.")
    if not re.match(r"^\s*\(?\s*(?:SELECT|WITH)\b", skeleton, re.I):
        raise ValueError("Only SELECT (or WITH ... SELECT) queries are allowed.")
    forbidden = _FORBIDDEN_SQL_RE.search(skeleton)
    if forbidden:
        raise ValueError(f"Read-only violation: '{forbidden.group(0).strip()}' is not allowed.")
    return sql


def _read_only_session(cur) -> None:
    cur.execute(f"SET SESSION MAX_EXECUTION_TIME={int(QUERY_TIMEOUT_MS)}")
    cur.execute("START TRANSACTION READ ONLY")


# ---------------------------------------------------------------------------
# MCP tools
# ---------------------------------------------------------------------------

@mcp.tool(annotations=READ_ONLY)
@_model_visible_errors
def list_tables(pattern: str = "", database: str = "", refresh: bool = False) -> dict:
    """List tables in the live ERP database with estimated row counts and column counts.

    Args:
        pattern: optional case-insensitive substring or regex to filter table names (e.g. "inventory", "^sales_").
        database: tenant database (default: the configured tenant, e.g. apptimate_infinity).
        refresh: force re-reading INFORMATION_SCHEMA instead of the short-lived schema cache.
    """
    schema = _load_schema(_database(database), refresh)
    try:
        matcher = re.compile(pattern, re.I) if pattern else None
    except re.error:
        matcher = re.compile(re.escape(pattern), re.I)
    tables = [
        {"table": name, "estimated_rows": info["estimated_rows"], "columns": len(info["columns"])}
        for name, info in schema["tables"].items()
        if not matcher or matcher.search(name)
    ]
    return {"database": schema["database"], "schema_loaded_at": schema["loaded_at"], "count": len(tables), "tables": tables}


@mcp.tool(annotations=READ_ONLY)
@_model_visible_errors
def describe_tables(tables: list[str], database: str = "") -> dict:
    """Describe tables exactly: columns (type, nullability, enum values), primary key, indexes and foreign keys.

    Always call this before writing SQL so every column and join you use is real.
    Foreign keys marked "inferred" come from <name>_id naming conventions; "declared" ones are real constraints.

    Args:
        tables: up to 20 table names from list_tables.
        database: tenant database (default: configured tenant).
    """
    schema = _load_schema(_database(database))
    names = list(dict.fromkeys(tables or []))[:20]
    unknown = [name for name in names if name not in schema["tables"]]
    described = {}
    for name in names:
        if name in schema["tables"]:
            info = schema["tables"][name]
            described[name] = {**info, "soft_delete": "deleted_at" in info["columns"]}
    referenced_by = {
        name: [
            f"{other}.{fk['column']}"
            for other, info in schema["tables"].items()
            for fk in info["foreign_keys"]
            if fk["references"].split(".")[0] == name
        ][:25]
        for name in described
    }
    return {
        "database": schema["database"],
        "tables": described,
        "referenced_by": referenced_by,
        "unknown_tables": unknown,
        "hint": (
            "Use only these columns. Add `deleted_at IS NULL` when soft_delete is true and the user wants live records. "
            "Filter on indexed columns where possible."
        ),
    }


@mcp.tool(annotations=READ_ONLY)
@_model_visible_errors
def find_columns(keyword: str, database: str = "", limit: int = 60) -> dict:
    """Find tables/columns whose name or comment matches a keyword (e.g. "min_stock", "balance", "serial").

    Args:
        keyword: case-insensitive substring or regex.
        database: tenant database (default: configured tenant).
        limit: maximum matches to return (1-200).
    """
    schema = _load_schema(_database(database))
    try:
        matcher = re.compile(keyword, re.I)
    except re.error:
        matcher = re.compile(re.escape(keyword), re.I)
    matches = []
    for table, info in schema["tables"].items():
        for column, meta in info["columns"].items():
            if matcher.search(column) or matcher.search(meta.get("comment", "")):
                matches.append({"table": table, "column": column, "type": meta["type"], "estimated_rows": info["estimated_rows"]})
    limit = max(1, min(int(limit or 60), 200))
    return {"database": schema["database"], "count": len(matches), "matches": matches[:limit], "truncated": len(matches) > limit}


@mcp.tool(annotations=READ_ONLY)
@_model_visible_errors
def explain_select(sql: str, database: str = "") -> dict:
    """Return MySQL's EXPLAIN plan for a SELECT so you can check index usage before running a heavy query.

    Args:
        sql: one read-only SELECT statement.
        database: tenant database (default: configured tenant).
    """
    database = _database(database)
    statement = _validate_select(sql)
    with _connect(database) as conn, conn.cursor() as cur:
        _read_only_session(cur)
        cur.execute("EXPLAIN " + statement)
        plan = [_clean_row(row) for row in cur.fetchall()]
        conn.rollback()
    full_scans = [row.get("table") for row in plan if str(row.get("type")).upper() == "ALL"]
    return {"database": database, "plan": plan, "full_table_scans": full_scans}


@mcp.tool(annotations=READ_ONLY)
@_model_visible_errors
def run_select(
    sql: str,
    database: str = "",
    page_size: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
    include_total: bool = False,
    params: list | dict | None = None,
) -> dict:
    """Run ONE read-only SELECT on the live ERP database and return one chunk (page) of rows.

    Rows are always read live (no data cache). Results are paged: when has_more is true, call again with
    offset=next_offset to fetch the next chunk. Prefer COUNT/SUM/AVG/GROUP BY in SQL for totals instead of
    paging through raw rows. Do not add your own LIMIT for paging; use page_size/offset.

    Args:
        sql: one MySQL SELECT (or WITH ... SELECT). Writes, locks and multi-statements are rejected.
        database: tenant database (default: configured tenant).
        page_size: rows per chunk (1-500, default 50).
        offset: starting row for this chunk (default 0).
        include_total: also return the total row count of the full result (runs an extra COUNT query).
        params: optional list or dict of bind parameters for parameterized queries (%s or %(key)s).
    """
    database = _database(database)
    statement = _validate_select(sql)
    page_size = max(1, min(int(page_size or DEFAULT_PAGE_SIZE), MAX_PAGE_SIZE))
    offset = max(0, int(offset or 0))

    if _TRAILING_LIMIT_RE.search(_strip_literals_and_comments(statement)):
        paged = f"SELECT * FROM ({statement}) AS _page LIMIT {page_size + 1} OFFSET {offset}"
    else:
        paged = f"{statement} LIMIT {page_size + 1} OFFSET {offset}"

    started = time.perf_counter()
    with _connect(database) as conn, conn.cursor() as cur:
        _read_only_session(cur)
        if params is not None:
            cur.execute(paged, params)
        else:
            cur.execute(paged)
        rows = cur.fetchall()
        columns = [d[0] for d in (cur.description or [])]
        total = None
        if include_total:
            if params is not None:
                cur.execute(f"SELECT COUNT(*) AS total FROM ({statement}) AS _count", params)
            else:
                cur.execute(f"SELECT COUNT(*) AS total FROM ({statement}) AS _count")
            total = int((cur.fetchone() or {}).get("total") or 0)
        conn.rollback()
    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)

    has_more = len(rows) > page_size
    rows = [_clean_row(row) for row in rows[:page_size]]
    return {
        "database": database,
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "offset": offset,
        "page_size": page_size,
        "has_more": has_more,
        "next_offset": offset + page_size if has_more else None,
        "total_rows": total,
        "elapsed_ms": elapsed_ms,
        "read_at": datetime.now().isoformat(timespec="seconds"),
        "sql": statement,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Apptimate ERP database MCP server")
    parser.add_argument("--http", action="store_true", help="serve streamable HTTP instead of stdio")
    parser.add_argument("--host", default=os.getenv("MCP_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("MCP_PORT", "8765")))
    args = parser.parse_args()
    if args.http:
        mcp.run("streamable-http", host=args.host, port=args.port)
    else:
        mcp.run("stdio")


if __name__ == "__main__":
    main()
