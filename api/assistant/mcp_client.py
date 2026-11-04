"""Model Context Protocol (MCP) Client interface for the Apptimate ERP database.

Connects the Django assistant engine directly to the pure-Python MCP server
(mcp_server/erp_db_server.py) using the official `mcp.Client`.
"""
from __future__ import annotations

import anyio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Ensure mcp_server is in sys.path
_API_DIR = Path(__file__).resolve().parents[1]
_MCP_DIR = _API_DIR / "mcp_server"
if str(_MCP_DIR) not in sys.path:
    sys.path.insert(0, str(_MCP_DIR))

try:
    from erp_db_server import mcp as _mcp_server
    from mcp import Client
except ImportError as exc:
    logger.warning(f"MCP server or SDK not yet available: {exc}")
    _mcp_server = None
    Client = None


def call_mcp_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Execute an MCP tool call against the ERP database MCP server and return parsed JSON."""
    if _mcp_server is None or Client is None:
        raise RuntimeError("MCP server or client SDK is not installed.")

    async def _runner():
        async with Client(_mcp_server) as client:
            result = await client.call_tool(name, arguments)
            text = "".join(getattr(x, "text", "") for x in result.content)
            try:
                data = json.loads(text)
                if result.is_error:
                    return {"error": text, "is_error": True}
                return data
            except Exception:
                return {"error": text, "is_error": result.is_error}

    return anyio.run(_runner)


def mcp_list_tables(pattern: str = "", database: str = "", refresh: bool = False) -> dict[str, Any]:
    """MCP tool call: list_tables."""
    return call_mcp_tool("list_tables", {"pattern": pattern, "database": database, "refresh": refresh})


def mcp_describe_tables(tables: list[str], database: str = "") -> dict[str, Any]:
    """MCP tool call: describe_tables."""
    return call_mcp_tool("describe_tables", {"tables": tables, "database": database})


def mcp_find_columns(keyword: str, database: str = "", limit: int = 60) -> dict[str, Any]:
    """MCP tool call: find_columns."""
    return call_mcp_tool("find_columns", {"keyword": keyword, "database": database, "limit": limit})


def mcp_explain_select(sql: str, database: str = "") -> dict[str, Any]:
    """MCP tool call: explain_select."""
    return call_mcp_tool("explain_select", {"sql": sql, "database": database})


def mcp_run_select(
    sql: str,
    database: str = "",
    page_size: int = 50,
    offset: int = 0,
    include_total: bool = False,
    params: list | dict | None = None,
) -> dict[str, Any]:
    """MCP tool call: run_select."""
    arguments = {
        "sql": sql,
        "database": database,
        "page_size": page_size,
        "offset": offset,
        "include_total": include_total,
    }
    if params is not None:
        arguments["params"] = params
    return call_mcp_tool("run_select", arguments)
