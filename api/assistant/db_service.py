"""Pure-Python read-only MySQL tenant database connection and serialization utilities."""
from datetime import date, datetime, time
from decimal import Decimal
from functools import lru_cache
import logging
import os
import re

import pymysql

logger = logging.getLogger(__name__)

MYSQL_HOST = os.getenv("MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", 3306))
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
MYSQL_ROOT_DB = os.getenv("MYSQL_ROOT_DB", "apptimate_v5_root")
DEFAULT_TENANT_ID = os.getenv("DEFAULT_TENANT_ID", "apptimate_infinity")
_DEBUG_MODE = os.getenv("DJANGO_DEBUG", "true").strip().lower() in {"true", "1", "yes"}
ALLOW_DEFAULT_TENANT = os.getenv(
    "ALLOW_DEFAULT_TENANT", "true" if _DEBUG_MODE else "false"
).strip().lower() in {"true", "1", "yes"}

SAFE_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_.-]+$")


def _require_mysql_credentials():
    if not MYSQL_USER:
        raise RuntimeError("MYSQL_USER must be configured in the support API environment.")


def get_root_connection():
    """Connect to the central multi-tenant management database."""
    _require_mysql_credentials()
    return pymysql.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_ROOT_DB,
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=3,
    )


def resolve_tenant_database(tenant_identifier: str = None) -> str:
    """Safely resolves a tenant domain or tenant ID into an authorized tenant database name."""
    if tenant_identifier is None or str(tenant_identifier).strip().lower() in {"", "localhost", "127.0.0.1", "default"}:
        if ALLOW_DEFAULT_TENANT:
            return DEFAULT_TENANT_ID
        raise LookupError("A tenant identifier is required.")
    if not isinstance(tenant_identifier, str):
        raise ValueError("Tenant identifier must be a registered domain or tenant ID.")

    identifier = tenant_identifier.strip().lower()
    if ":" in identifier:
        identifier = identifier.split(":", 1)[0]
    if identifier in {"localhost", "127.0.0.1", DEFAULT_TENANT_ID.lower()}:
        return DEFAULT_TENANT_ID
    if not SAFE_NAME_PATTERN.match(identifier):
        raise ValueError("Tenant identifier is invalid.")

    try:
        with get_root_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT tenant_id FROM domains WHERE domain = %s LIMIT 1",
                    (identifier,),
                )
                row = cursor.fetchone()
                tenant_id = row["tenant_id"] if (row and row.get("tenant_id")) else identifier

                cursor.execute(
                    "SELECT id FROM tenants WHERE id = %s LIMIT 1",
                    (tenant_id,),
                )
                tenant_row = cursor.fetchone()
                if tenant_row:
                    target_db = tenant_row["id"]
                    if not target_db.startswith("apptimate_"):
                        target_db = f"apptimate_{target_db}"
                    if re.match(r"^apptimate_[a-zA-Z0-9_]+$", target_db):
                        return target_db
    except Exception as e:
        if ALLOW_DEFAULT_TENANT:
            return DEFAULT_TENANT_ID
        logger.error(f"Error resolving tenant database for '{identifier}': {e}")
        raise RuntimeError("Could not resolve the requested tenant database.") from e

    if ALLOW_DEFAULT_TENANT:
        return DEFAULT_TENANT_ID
    raise LookupError("The requested domain or tenant is not registered.")


def get_tenant_connection(tenant_db_name: str):
    """Connect to a specific tenant database."""
    if not re.match(r"^apptimate_[a-zA-Z0-9_]+$", tenant_db_name):
        raise ValueError(f"Unauthorized or invalid tenant database name: {tenant_db_name}")
    _require_mysql_credentials()

    return pymysql.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=tenant_db_name,
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=3,
    )


@lru_cache(maxsize=8)
def get_tenant_engine(tenant_db_name: str):
    """Return a pooled SQLAlchemy engine for validated tenant read queries."""
    if not re.match(r"^apptimate_[a-zA-Z0-9_]+$", tenant_db_name):
        raise ValueError("Unauthorized or invalid tenant database name")
    _require_mysql_credentials()
    from sqlalchemy import URL, create_engine

    url = URL.create(
        "mysql+pymysql",
        username=MYSQL_USER,
        password=MYSQL_PASSWORD,
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        database=tenant_db_name,
        query={"charset": "utf8mb4"},
    )
    return create_engine(url, pool_pre_ping=True, pool_recycle=1800)


def _serialize_decimals(data):
    """Convert Decimal values to float/int and dates/datetimes to ISO strings for clean JSON serialization."""
    if isinstance(data, list):
        return [_serialize_decimals(item) for item in data]
    if isinstance(data, dict):
        return {key: _serialize_decimals(value) for key, value in data.items()}
    if isinstance(data, Decimal):
        if data % 1 == 0:
            return int(data)
        number = float(data)
        return number if Decimal(str(number)) == data else format(data, "f")
    if isinstance(data, (date, datetime, time)):
        return data.isoformat()
    return data
