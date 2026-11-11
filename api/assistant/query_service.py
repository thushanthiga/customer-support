"""Tenant-scoped, read-only structured database search for support questions.

The LLM supplies a structured JSON query plan (never raw SQL). This pure-Python
module introspects the live MySQL schema, validates every table, column, join,
operator, and aggregate, and executes a parameterized read-only SELECT.
"""

from collections import OrderedDict
from copy import deepcopy
from decimal import Decimal
import json
import logging
import re
import threading
import time

from django.utils import timezone

from .query_integrity import trusted_relationships, validate_aggregate_grain

from .db_service import (
    _serialize_decimals,
    get_tenant_connection,
    get_tenant_engine,
    resolve_tenant_database,
)

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 600
_CACHE_MAX_TENANTS = 8
_SCHEMA_CACHE = OrderedDict()
_SCHEMA_CACHE_LOCK = threading.Lock()
_MAX_ROWS = 500
_MAX_JOINS = 6
_MAX_SELECTS = 16
_MAX_FILTERS = 20
_MAX_CTES = 4
_MAX_CTE_ROWS = 5000

_STOCK_DOCUMENT_TYPES = {
    "inventory_opening_stocks": "OpeningStock",
    "inventory_stock_adjustments": "Adjustment",
    "inventory_stock_transfers": "Transfer",
    "sales_pos": "POS",
    "sales_goods_issue_notes": "GIN",
    "sales_returns": "SR",
    "procurement_goods_receipt_notes": "GRN",
}
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SENSITIVE_TABLE_PARTS = (
    "password", "token", "secret", "credential", "migration",
    "failed_job", "personal_access", "chat_usage", "document_chunk",
    "uploaded_document", "cache",
)
_SENSITIVE_TABLES = {"django_session", "sessions", "laravel_sessions"}
_SENSITIVE_COLUMN_PARTS = (
    "password", "passwd", "token", "secret", "credential", "private_key", "api_key",
)
_NUMERIC_TYPES = {
    "tinyint", "smallint", "mediumint", "int", "integer", "bigint",
    "decimal", "numeric", "float", "double", "real", "bit",
}
_AGGREGATES = {"COUNT", "SUM", "AVG", "MIN", "MAX"}
_WINDOW_FUNCTIONS = {"ROW_NUMBER", "RANK", "DENSE_RANK", "SUM", "AVG", "MIN", "MAX", "COUNT", "LAG", "LEAD"}
_OPERATORS = {"=", "!=", "<>", ">", ">=", "<", "<=", "LIKE", "IN", "NOT IN", "BETWEEN", "IS NULL", "IS NOT NULL"}
_CROSS_ORG_MASTER_TABLES = {"core_parties", "core_users", "core_organizations", "core_currencies"}


def _quote(identifier: str) -> str:
    if not isinstance(identifier, str) or not _IDENTIFIER_RE.fullmatch(identifier):
        raise ValueError(f"Unsafe SQL identifier: {identifier!r}")
    return f"`{identifier}`"


def format_display_sql(sql: str, params: dict = None) -> str:
    """Format parameterized SQL into clean, readable SQL for technical audit."""
    if not sql:
        return ""
    display = sql
    if params:
        for k, v in params.items():
            if isinstance(v, (int, float, Decimal)):
                val_str = str(v)
            elif v is None:
                val_str = "NULL"
            else:
                escaped = str(v).replace("'", "''")
                val_str = f"'{escaped}'"
            display = re.sub(rf"%\({k}\)s\b", val_str, display)
    return display


def _infer_schema_relationships(tables: dict) -> set:
    """Infer standard `*_id` foreign-key relationships from live MySQL table/column names."""
    relationships = set()
    common_fk_targets = {
        "organization_id": "core_organizations",
        "party_id": "core_parties",
        "supplier_id": "core_parties",
        "customer_id": "core_parties",
        "warehouse_id": "core_warehouses",
        "from_warehouse_id": "core_warehouses",
        "to_warehouse_id": "core_warehouses",
        "currency_id": "core_currencies",
        "user_id": "core_users",
        "created_by": "core_users",
        "updated_by": "core_users",
        "role_id": "core_roles",
        "permission_id": "core_permissions",
        "item_id": "inventory_items",
        "variant_id": "inventory_item_variants",
        "item_variant_id": "inventory_item_variants",
        "batch_id": "inventory_batches",
        "uom_id": "inventory_units_of_measure",
        "category_id": "inventory_categories",
        "brand_id": "inventory_brands",
        "tax_group_id": "finance_tax_groups",
        "invoice_id": "finance_invoices",
        "account_id": "finance_accounts",
        "journal_entry_id": "finance_journal_entries",
        "purchase_order_id": "procurement_purchase_orders",
        "purchase_order_line_id": "procurement_purchase_order_lines",
        "goods_receipt_note_id": "procurement_goods_receipt_notes",
        "sales_order_id": "sales_orders",
        "sales_order_line_id": "sales_order_lines",
        "quotation_id": "sales_quotations",
        "goods_issue_note_id": "sales_goods_issue_notes",
        "pos_sale_id": "sales_pos",
        "return_id": "sales_returns",
        "price_list_id": "sales_price_lists",
        "employee_id": "hr_employees",
        "run_id": "hr_payroll_runs",
        "payroll_run_id": "hr_payroll_runs",
        "department_id": "core_organizations",
        "shift_template_id": "hr_shift_templates",
        "team_id": "hr_teams",
        "lead_id": "crm_leads",
        "crm_lead_id": "crm_leads",
        "crm_space_id": "crm_spaces",
        "campaign_id": "core_campaigns",
        "project_id": "construction_projects",
        "boq_id": "construction_boqs",
        "karigar_order_id": "jewelry_karigar_orders",
        "terminal_id": "core_terminals",
        "entity_id": "core_entities",
        "tag_id": "core_tags",
        "dashboard_id": "dashboards",
    }

    suffix_lookup = {}
    for table_name, cols in tables.items():
        if "id" not in cols:
            continue
        parts = table_name.split("_")
        for idx in range(len(parts)):
            stem = "_".join(parts[idx:])
            if stem.endswith("ies") and len(stem) > 3:
                singular = stem[:-3] + "y"
            elif stem.endswith("es") and len(stem) > 3 and stem[:-2].endswith(("ch", "sh", "x", "s")):
                singular = stem[:-2]
            elif stem.endswith("s") and len(stem) > 2:
                singular = stem[:-1]
            else:
                singular = stem
            suffix_lookup.setdefault(f"{singular}_id", []).append(table_name)

    for left_table, cols in tables.items():
        left_prefix = left_table.split("_")[0]
        for col in cols:
            if not col.endswith("_id"):
                continue
            target = common_fk_targets.get(col)
            if target and target in tables and "id" in tables[target] and target != left_table:
                relationships.add((left_table, col, target, "id"))
            candidates = suffix_lookup.get(col, [])
            same_module = [t for t in candidates if t.split("_")[0] == left_prefix and t != left_table]
            chosen = same_module if len(same_module) == 1 else (candidates if len(candidates) == 1 else [])
            for right_table in chosen:
                relationships.add((left_table, col, right_table, "id"))
        if left_table == "inventory_stock_ledger" and "reference_id" in cols:
            for doc_table in _STOCK_DOCUMENT_TYPES:
                if doc_table in tables and "id" in tables[doc_table]:
                    relationships.add((left_table, "reference_id", doc_table, "id"))

    return relationships


def _schema_for(tenant_db: str):
    now = time.monotonic()
    with _SCHEMA_CACHE_LOCK:
        cached = _SCHEMA_CACHE.get(tenant_db)
        if cached and now - cached[0] < _CACHE_TTL_SECONDS:
            _SCHEMA_CACHE.move_to_end(tenant_db)
            return cached[1]

    with get_tenant_connection(tenant_db) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, COLUMN_TYPE, IS_NULLABLE
                   FROM INFORMATION_SCHEMA.COLUMNS
                   WHERE TABLE_SCHEMA = %s
                   ORDER BY TABLE_NAME, ORDINAL_POSITION""",
                (tenant_db,),
            )
            column_rows = cursor.fetchall()
            cursor.execute(
                """SELECT TABLE_NAME, COLUMN_NAME, REFERENCED_TABLE_NAME, REFERENCED_COLUMN_NAME
                   FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE
                   WHERE TABLE_SCHEMA = %s AND REFERENCED_TABLE_NAME IS NOT NULL""",
                (tenant_db,),
            )
            relationship_rows = cursor.fetchall()
            cursor.execute(
                """SELECT TABLE_NAME, INDEX_NAME, NON_UNIQUE, COLUMN_NAME, SEQ_IN_INDEX
                   FROM INFORMATION_SCHEMA.STATISTICS
                   WHERE TABLE_SCHEMA = %s
                   ORDER BY TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX""",
                (tenant_db,),
            )
            index_rows = cursor.fetchall()

    tables = {}
    column_constraints = {}
    for row in column_rows:
        name = row["TABLE_NAME"]
        lower_name = name.lower()
        if lower_name in _SENSITIVE_TABLES or any(part in lower_name for part in _SENSITIVE_TABLE_PARTS):
            continue
        columns = tables.setdefault(name, {})
        if any(part in row["COLUMN_NAME"].lower() for part in _SENSITIVE_COLUMN_PARTS):
            continue
        columns[row["COLUMN_NAME"]] = row["DATA_TYPE"].lower()
        info = {"nullable": None if row.get("IS_NULLABLE") is None else row["IS_NULLABLE"] == "YES"}
        if row.get("COLUMN_TYPE", "").startswith("enum("):
            info["values"] = re.findall(r"'([^']*)'", row["COLUMN_TYPE"])
        column_constraints.setdefault(name, {})[row["COLUMN_NAME"]] = info

    relationships = set()
    for row in relationship_rows:
        left, right = row["TABLE_NAME"], row["REFERENCED_TABLE_NAME"]
        if left in tables and right in tables:
            relationships.add((left, row["COLUMN_NAME"], right, row["REFERENCED_COLUMN_NAME"]))
    declared_relationships = set(relationships)
    relationships.update(_infer_schema_relationships(tables))
    from django.conf import settings
    from .domain_schema import CORE_APPLICATION_RELATIONSHIPS
    application_relationships = set()
    all_app_mappings = list(CORE_APPLICATION_RELATIONSHIPS) + list(getattr(settings, "SUPPORT_APPLICATION_RELATIONSHIPS", []))
    for mapping in all_app_mappings:
        if not isinstance(mapping, dict) or not mapping.get("source"):
            raise ValueError("Application relationship mappings require a source reference.")
        edge = tuple(mapping.get(key) for key in ("left_table", "left_column", "right_table", "right_column"))
        if len(edge) == 4 and edge[0] in tables and edge[2] in tables and edge[1] in tables[edge[0]] and edge[3] in tables[edge[2]]:
            application_relationships.add(edge)
    relationships.update(application_relationships)
    indexes = {}
    incomplete_indexes = set()
    for row in index_rows:
        table, column = row["TABLE_NAME"], row["COLUMN_NAME"]
        if table in tables and column not in tables[table]:
            incomplete_indexes.add((table, row["INDEX_NAME"]))
        if table in tables and column in tables[table]:
            index = indexes.setdefault(table, {}).setdefault(row["INDEX_NAME"], {
                "unique": not bool(row["NON_UNIQUE"]), "columns": [],
            })
            index["columns"].append(column)
    for table, name in incomplete_indexes:
        indexes.get(table, {}).pop(name, None)

    schema = {
        "tables": tables,
        "relationships": relationships,
        "column_constraints": column_constraints,
        "indexes": indexes,
        "declared_relationships": declared_relationships,
        "application_relationships": application_relationships,
    }
    with _SCHEMA_CACHE_LOCK:
        _SCHEMA_CACHE[tenant_db] = (now, schema)
        _SCHEMA_CACHE.move_to_end(tenant_db)
        while len(_SCHEMA_CACHE) > _CACHE_MAX_TENANTS:
            _SCHEMA_CACHE.popitem(last=False)
    return schema


_PRIMARY_TABLE_BOOSTS = {
    "finance_invoices": 14,
    "core_parties": 14,
    "inventory_items": 14,
    "inventory_stock_balances": 12,
    "sales_orders": 12,
    "sales_order_lines": 12,
    "procurement_purchase_orders": 12,
    "procurement_purchase_order_lines": 12,
    "core_warehouses": 10,
    "inventory_item_replenishment_rules": 10,
    "inventory_categories": 8,
    "inventory_brands": 8,
    "sales_goods_issue_notes": 12,
    "sales_goods_issue_note_lines": 12,
    "procurement_goods_receipt_notes": 10,
    "procurement_goods_receipt_note_lines": 10,
    "fin_chart_of_accounts": 8,
    "fin_journal_entries": 8,
    "fin_journal_entry_lines": 8,
}

_CORE_FK_MAP = {
    "party_id": "core_parties",
    "customer_id": "core_parties",
    "supplier_id": "core_parties",
    "item_id": "inventory_items",
    "warehouse_id": "core_warehouses",
    "sales_order_id": "sales_orders",
    "purchase_order_id": "procurement_purchase_orders",
    "invoice_id": "finance_invoices",
    "category_id": "inventory_categories",
    "brand_id": "inventory_brands",
    "uom_id": "inventory_units_of_measure",
    "goods_issue_note_id": "sales_goods_issue_notes",
    "goods_receipt_note_id": "procurement_goods_receipt_notes",
    "journal_entry_id": "fin_journal_entries",
    "account_id": "fin_chart_of_accounts",
    "currency_id": "core_currencies",
    "organization_id": "core_organizations",
}


def _relevant_tables(schema, question: str, limit: int = 20):
    """Select relevant tenant tables by matching question tokens against table and column names."""
    words = set(re.findall(r"[a-z0-9]+", (question or "").lower()))
    words -= {
        "show", "list", "tell", "give", "what", "which", "whose", "who", "how", "many", "much", "all",
        "the", "a", "an", "and", "or", "of", "for", "from", "to", "with", "by", "is", "are", "was", "were",
        "do", "does", "can", "i", "me", "my", "our", "their", "in", "at", "on", "that", "this", "each",
    }

    def variants(values):
        result = set(values)
        for value in values:
            if value.endswith("ies") and len(value) > 4:
                result.add(value[:-3] + "y")
            elif value.endswith("ed") and len(value) > 3:
                result.add(value[:-2])
                result.add(value[:-1])
            elif value.endswith("ing") and len(value) > 4:
                result.add(value[:-3])
            elif value.endswith("s") and len(value) > 3:
                result.add(value[:-1])
        return result

    expanded = variants(words)

    # Quantity / Measurement / Replenishment & Stock
    if any(w in expanded for w in ["minimum", "min", "reorder", "threshold", "replenish", "replenishment", "restore", "restored", "restoring", "restock", "restocked", "restocking"]):
        expanded.update(["min", "minimum", "replenishment", "reorder", "rules", "stock", "level", "balances"])
    if any(w in expanded for w in ["maximum", "max"]):
        expanded.update(["max", "maximum"])
    if any(w in expanded for w in ["quantity", "qty", "stock", "stocked", "inventory", "balance", "balances", "depleted", "shortage", "restore", "restored", "restock", "restocked", "restocking"]):
        expanded.update(["qty", "quantity", "stock", "balances", "items", "warehouse"])

    # Parties: Suppliers & Customers
    if any(w in expanded for w in ["supplier", "suppliers", "vendor", "vendors", "procure", "procurement", "buy", "bought", "purchasing"]):
        expanded.update(["supplier", "suppliers", "vendor", "party", "parties", "procurement", "purchase"])
    if any(w in expanded for w in ["customer", "customers", "client", "clients", "buyer", "buyers"]):
        expanded.update(["customer", "customers", "party", "parties", "sales"])

    # Invoices & Bills (AP vs AR)
    if any(w in expanded for w in ["bill", "bills", "payable", "payables", "ap", "due", "unpaid", "debt", "owing", "outstanding"]):
        expanded.update(["invoice", "invoices", "bill", "bills", "amount", "due", "status", "party", "settled", "currency"])
    if any(w in expanded for w in ["invoice", "invoices", "receivable", "receivables", "ar", "overdue"]):
        expanded.update(["invoice", "invoices", "amount", "due", "status", "party", "settled", "currency"])

    # Demand, Popularity, Velocity & Seasonality
    if any(w in expanded for w in ["demand", "demanded", "demands", "popular", "popularity", "velocity", "top", "trending", "bestseller", "bestsellers", "fast", "moving", "seasonal", "sesonal", "season", "hot", "sell", "selling"]):
        expanded.update(["sales", "goods", "issue", "notes", "lines", "dispatch", "orders", "quantity", "items", "balances"])
    if any(w in expanded for w in ["currently", "current", "active", "open", "present"]):
        expanded.update(["status", "sales", "orders", "lines", "balances", "allocated"])
    if any(w in expanded for w in ["thing", "things", "item", "items", "product", "products"]):
        expanded.update(["items", "balances", "inventory"])

    # Orders (Sales & Purchase)
    if any(w in expanded for w in ["order", "orders", "so", "po"]):
        expanded.update(["order", "orders", "lines", "party", "items"])
    if any(w in expanded for w in ["sale", "sales", "sold", "selling"]):
        expanded.update(["sales", "orders", "lines", "party", "items"])
    if any(w in expanded for w in ["purchase", "purchases", "purchased"]):
        expanded.update(["procurement", "purchase", "orders", "lines", "party", "items"])

    # Warehouse & Locations
    if any(w in expanded for w in ["warehouse", "warehouses", "store", "stores", "location", "locations"]):
        expanded.update(["warehouse", "warehouses", "balances", "stock"])

    # Deliveries & Receipts (GIN & GRN)
    if any(w in expanded for w in ["delivery", "deliveries", "dispatch", "dispatched", "gin", "ship", "shipped", "shipping"]):
        expanded.update(["goods", "issue", "notes", "lines", "dispatch", "sales", "orders"])
    if any(w in expanded for w in ["receipt", "receipts", "receiving", "grn", "inbound"]):
        expanded.update(["goods", "receipt", "notes", "lines", "procurement", "purchase"])

    # Accounting & GL
    if any(w in expanded for w in ["accounting", "account", "accounts", "journal", "gl", "ledger", "debit", "credit"]):
        expanded.update(["chart", "accounts", "journal", "entries", "lines", "fin"])

    from .domain_schema import CONCEPT_KEYWORD_EXPANSIONS, SYSTEM_TABLE_PREFIXES
    for kw, terms in CONCEPT_KEYWORD_EXPANSIONS.items():
        if kw in expanded:
            expanded.update(terms)

    q_lower = (question or "").lower()
    scores = []
    for table, columns in schema["tables"].items():
        table_terms = variants(set(re.findall(r"[a-z0-9]+", table.lower())))
        col_terms = set(table_terms)
        for column in columns:
            col_terms.update(re.findall(r"[a-z0-9]+", column.lower()))
        col_terms = variants(col_terms)
        score = 4 * len(expanded & table_terms) + len(expanded & col_terms)

        # Primary transactional table boost
        if table in _PRIMARY_TABLE_BOOSTS and (expanded & table_terms or any(c in expanded for c in columns)):
            score += _PRIMARY_TABLE_BOOSTS[table]

        # Deprioritize unrelated specialist verticals unless specifically requested
        if any(table.startswith(p) for p in ("jewelry_", "money_exchange_", "construction_", "manufacturing_")) and not any(k in q_lower for k in ("jewelry", "gold", "silver", "karigar", "money", "exchange", "currency", "construction", "boq", "mrp", "work order", "production order")):
            score -= 12
        # Suppress internal template/system tables unless explicitly requested
        if any(table.startswith(p) for p in SYSTEM_TABLE_PREFIXES) and not any(k in q_lower for k in ("template", "printable", "print")):
            score -= 20
        if score > 0:
            scores.append((score, table))

    scores.sort(key=lambda entry: (-entry[0], entry[1]))
    selected = [table for _, table in scores[:limit]]
    if not selected:
        selected = sorted(schema["tables"])[:limit]

    # ForeignKey parent table resolution: always include vital FK targets
    fk_targets = []
    for table in selected:
        for col in schema["tables"].get(table, {}):
            target = _CORE_FK_MAP.get(col)
            if target and target in schema["tables"] and target not in selected and target not in fk_targets:
                fk_targets.append(target)
    for target in fk_targets:
        if len(selected) < limit + 4:
            selected.append(target)

    # Connected relationships
    connected = set(selected)
    for left, _, right, _ in schema["relationships"]:
        if left in selected:
            connected.add(right)
        if right in selected:
            connected.add(left)
    for table in sorted(connected - set(selected))[:4]:
        if len(selected) < limit + 6:
            selected.append(table)

    return _format_schema_context(schema, selected)


def _format_schema_context(schema, selected):
    rows = ["Fully discovered tables (all columns are listed below): " + ", ".join(selected)]
    selected_set = set(selected)
    include_audit_edges = "core_users" in selected_set
    for table in selected:
        cols = [f"{column} ({data_type})" for column, data_type in schema["tables"][table].items()]
        deletion = "deleted_at" if "deleted_at" in schema["tables"][table] else "none (do not filter deleted_at)"
        rows.append(f"- {table}: {', '.join(cols)}. Soft-delete column: {deletion}.")
        enum_columns = {
            column: info["values"]
            for column, info in schema.get("column_constraints", {}).get(table, {}).items()
            if info.get("values")
        }
        if enum_columns:
            rows.append("Database enum values for " + table + ": " + json.dumps(enum_columns, separators=(",", ":")))
        indexes = schema.get("indexes", {}).get(table, {})
        if indexes:
            key_indexes = {
                name: info
                for name, info in indexes.items()
                if name == "PRIMARY" or (isinstance(info, dict) and info.get("unique"))
            }
            if key_indexes:
                rows.append("Database indexes for " + table + ": " + json.dumps(key_indexes, separators=(",", ":")))
    table_rank = {table: index for index, table in enumerate(selected)}
    declared = schema.get("declared_relationships", set())
    ranked_edges = sorted(
        schema["relationships"],
        key=lambda edge: (0 if edge in declared else 1, table_rank.get(edge[0], len(selected)) + table_rank.get(edge[2], len(selected)), edge),
    )
    edges = []
    for left, left_col, right, right_col in ranked_edges:
        if left not in selected_set or right not in selected_set:
            continue
        if not include_audit_edges and left_col in {"created_by", "updated_by", "deleted_by"}:
            continue
        edges.append(
            f"{left}.{left_col} = {right}.{right_col} ("
            + ("declared foreign key" if (left, left_col, right, right_col) in declared
               else "inferred application relationship; cardinality and business meaning are not proven") + ")"
        )
        if len(edges) >= 40:
            break
    if edges:
        rows.append("Allowed join candidates (source labels matter): " + "; ".join(edges))
    all_tables = sorted(schema["tables"])
    if len(all_tables) <= 60:
        catalogue = all_tables
    else:
        from .domain_schema import SYSTEM_TABLE_PREFIXES

        selected_prefixes = tuple({t.split("_")[0] + "_" for t in selected if "_" in t})
        core_prefixes = ("core_", "sales_", "procurement_", "inventory_", "finance_", "fin_")
        candidates = [
            t for t in all_tables
            if t not in selected_set
            and not any(t.startswith(p) for p in (*SYSTEM_TABLE_PREFIXES, "agent_chat_"))
            and (t.startswith(selected_prefixes) or t.startswith(core_prefixes))
        ]
        catalogue = candidates[:50]
    rows.append("Authorized business table catalogue (request schema_tables for additional details): " + ", ".join(catalogue))
    return "\n".join(rows)


def get_business_schema_context(
    question: str,
    tenant_identifier: str = None,
    force: bool = False,
    table_limit: int = 20,
) -> str:
    """Provide a cached, tenant-specific schema hint to the LLM."""
    tenant_db = resolve_tenant_database(tenant_identifier)
    logger.info("[STEP 4: SCHEMA CONTEXT] Fetching schema hints for question=%r tenant=%s", question, tenant_db)
    try:
        from .erp_access import enforce_tenant, public_schema

        enforce_tenant(tenant_db)
        base_schema = _relevant_tables(public_schema(_schema_for(tenant_db)), question, limit=table_limit)
        try:
            from . import catalog_service
            catalog_slice = catalog_service.get_catalog_slice(question)
            if catalog_slice:
                return base_schema + "\n\n" + catalog_slice
        except Exception as cat_exc:
            logger.warning("[STEP 4: CATALOG SLICE ERROR] %s", cat_exc)
        return base_schema
    except Exception as exc:
        logger.info("Could not load tenant schema hint for %s: %s", tenant_db, exc)
        return ""


def expand_business_schema_context(tenant_identifier, table_names):
    """Discover requested authorized schema only; no business rows are read."""
    from .erp_access import enforce_tenant, public_schema

    tenant = resolve_tenant_database(tenant_identifier)
    enforce_tenant(tenant)
    schema = public_schema(_schema_for(tenant))
    selected = list(dict.fromkeys(table_names))
    if len(selected) > 96 or any(table not in schema["tables"] for table in selected):
        raise ValueError("Requested schema tables must come from the authorized business table catalogue.")
    return _format_schema_context(schema, selected)


def normalize_table_references(plan):
    """Resolve an unambiguous physical name to its declared query alias."""
    result = deepcopy(plan)
    if isinstance(result.get("ctes"), list):
        result["ctes"] = [
            normalize_table_references(cte) if isinstance(cte, dict) else cte
            for cte in result["ctes"]
        ]
    base = result.get("base_table")
    references = {base: [base]}
    for item in result.get("joins") or []:
        references.setdefault(item.get("table"), []).append(item.get("alias") or item.get("table"))
    mapping = {name: refs[0] for name, refs in references.items() if len(refs) == 1}

    def field(value):
        if not isinstance(value, dict):
            return
        if "table" in value:
            value["table"] = mapping.get(value["table"], value["table"])
        if isinstance(value.get("expression"), dict):
            field(value["expression"])
        if "left" in value or "right" in value:
            field(value.get("left"))
            field(value.get("right"))
        win = value.get("window")
        if isinstance(win, dict):
            for pb in win.get("partition_by") or []:
                field(pb)
            for ob in win.get("order_by") or []:
                field(ob)
        cw = value.get("case_when")
        if isinstance(cw, dict):
            for cond in cw.get("conditions") or []:
                field(cond)
                if isinstance(cond, dict):
                    field(cond.get("value"))
            field(cw.get("then"))
            field(cw.get("else_value"))

    for key in ("select", "filters", "group_by", "having"):
        for item in result.get(key) or []:
            field(item)
            if isinstance(item, dict):
                field(item.get("value"))
    for item in result.get("joins") or []:
        item["left_table"] = mapping.get(item.get("left_table"), item.get("left_table"))
        for extra in item.get("extra_on") or []:
            if isinstance(extra, dict) and "left_table" in extra:
                extra["left_table"] = mapping.get(extra["left_table"], extra["left_table"])
    return result


def _verified_join_pair(left_actual, left_col, right_actual, right_col, verified_edges, declared_edges, cte_catalog):
    """Verify that a join column pair is backed by a trusted constraint, mapping, or CTE lineage."""
    if left_actual not in cte_catalog and right_actual not in cte_catalog:
        edge = (left_actual, left_col, right_actual, right_col)
        reverse = (right_actual, right_col, left_actual, left_col)
        if edge not in verified_edges and reverse not in verified_edges:
            return False, None
        source = (
            "database_constraint"
            if edge in declared_edges or reverse in declared_edges
            else "configured_application_mapping"
        )
        return True, source

    left_origins = (
        cte_catalog[left_actual]["column_origins"].get(left_col, set())
        if left_actual in cte_catalog
        else {(left_actual, left_col)}
    )
    right_origins = (
        cte_catalog[right_actual]["column_origins"].get(right_col, set())
        if right_actual in cte_catalog
        else {(right_actual, right_col)}
    )
    if not left_origins or not right_origins:
        return False, None
    if left_origins & right_origins:
        return True, "verified_cte_lineage"
    for lt, lc in left_origins:
        for rt, rc in right_origins:
            if (lt, lc, rt, rc) in verified_edges or (rt, rc, lt, lc) in verified_edges:
                return True, "verified_cte_lineage"

    def parent_targets(origins):
        targets = set()
        for t, c in origins:
            if c == "id":
                targets.add((t, "id"))
            elif c == "organization_id":
                targets.add(("core_organizations", "id"))
            elif c == "currency_id":
                targets.add(("core_currencies", "id"))
            for a, ac, b, bc in verified_edges:
                if (a, ac) == (t, c) and bc == "id":
                    targets.add((b, "id"))
                elif (b, bc) == (t, c) and ac == "id":
                    targets.add((a, "id"))
        return targets

    if parent_targets(left_origins) & parent_targets(right_origins):
        return True, "verified_cte_lineage"
    return False, None


def _compile_select_block(
    block: dict,
    working_schema: dict,
    physical_schema: dict,
    cte_catalog: dict,
    bind,
    *,
    alias_prefix: str = "",
    is_cte: bool = False,
) -> dict:
    from .erp_access import organization_conditions
    from .query_calculations import calendar_predicate, compile_arithmetic, normalize_timestamp

    tables = working_schema["tables"]
    physical_tables = physical_schema["tables"]
    verified_edges = trusted_relationships(working_schema)
    declared_edges = working_schema.get("declared_relationships", set())

    base = block.get("base_table")
    if base not in tables:
        raise ValueError("The requested base table is unavailable. Use the supplied tenant schema context.")

    joined = {base}
    reference_tables = {base: base}
    aliases = {base: f"{alias_prefix}t0"}
    join_sql = []
    executed_joins = []
    joins = block.get("joins") or []
    if len(joins) > _MAX_JOINS:
        raise ValueError(f"A query can join at most {_MAX_JOINS} tables.")

    for index, join in enumerate(joins, start=1):
        table = join.get("table")
        reference = join.get("alias") or table
        left_table = join.get("left_table")
        left_column = join.get("left_column")
        right_column = join.get("right_column")
        if (
            table not in tables
            or left_table not in joined
            or reference in joined
            or not isinstance(reference, str)
            or not _IDENTIFIER_RE.fullmatch(reference)
        ):
            raise ValueError(
                "The requested join is invalid. Join a new table reference at a time. "
                "Repeated tables need a unique alias."
            )
        left_actual = reference_tables[left_table]
        if left_column not in tables[left_actual] or right_column not in tables[table]:
            raise ValueError("The requested join references an unavailable column.")
        edge = (left_actual, left_column, table, right_column)
        ok_join, rel_source = _verified_join_pair(
            left_actual, left_column, table, right_column, verified_edges, declared_edges, cte_catalog
        )
        if not ok_join:
            alternatives = sorted(
                [
                    relation
                    for relation in verified_edges
                    if relation[0] in {left_actual, table} or relation[2] in {left_actual, table}
                ],
                key=lambda relation: (not ({relation[0], relation[2]} == {left_actual, table}), relation),
            )[:12]
            raise ValueError(
                "Only verified joins are allowed. Unsupported relationship: "
                + str(edge)
                + ". Verified alternatives: "
                + "; ".join(f"{a}.{b} = {c}.{d}" for a, b, c, d in alternatives)
            )
        aliases[reference] = f"{alias_prefix}t{index}"
        join_type = str(join.get("type") or "LEFT").upper()
        if join_type not in {"INNER", "LEFT"}:
            raise ValueError("Join type must be INNER or LEFT.")
        on_clauses = [
            f"{aliases[left_table]}.{_quote(left_column)} = {aliases[reference]}.{_quote(right_column)}"
        ]
        for extra in join.get("extra_on") or []:
            if not isinstance(extra, dict):
                raise ValueError("Invalid extra_on join condition.")
            ex_left_ref = extra.get("left_table") or left_table
            ex_left_col = extra.get("left_column")
            ex_right_col = extra.get("right_column")
            if ex_left_ref not in joined:
                raise ValueError("extra_on left_table must reference an already joined table.")
            ex_left_actual = reference_tables[ex_left_ref]
            if ex_left_col not in tables[ex_left_actual] or ex_right_col not in tables[table]:
                raise ValueError("extra_on references an unavailable column.")
            ok_extra, _ = _verified_join_pair(
                ex_left_actual, ex_left_col, table, ex_right_col, verified_edges, declared_edges, cte_catalog
            )
            if not ok_extra:
                raise ValueError(
                    f"Only verified extra_on joins are allowed: ({ex_left_actual}, {ex_left_col}, {table}, {ex_right_col})."
                )
            on_clauses.append(
                f"{aliases[ex_left_ref]}.{_quote(ex_left_col)} = {aliases[reference]}.{_quote(ex_right_col)}"
            )

        join_sql.append(
            f"{join_type} JOIN {_quote(table)} {aliases[reference]} ON " + " AND ".join(on_clauses)
        )
        if (
            left_actual not in cte_catalog
            and table not in cte_catalog
            and left_actual not in _CROSS_ORG_MASTER_TABLES
            and table not in _CROSS_ORG_MASTER_TABLES
            and "organization_id" in tables.get(left_actual, {})
            and "organization_id" in tables.get(table, {})
        ):
            left_nullable = (
                working_schema.get("column_constraints", {})
                .get(left_actual, {})
                .get("organization_id", {})
                .get("nullable")
                is True
            )
            right_nullable = (
                working_schema.get("column_constraints", {})
                .get(table, {})
                .get("organization_id", {})
                .get("nullable")
                is True
            )
            l_org = f"{aliases[left_table]}.`organization_id`"
            r_org = f"{aliases[reference]}.`organization_id`"
            if left_nullable or right_nullable:
                org_ors = []
                if left_nullable:
                    org_ors.append(f"{l_org} IS NULL")
                if right_nullable:
                    org_ors.append(f"{r_org} IS NULL")
                org_ors.append(f"{l_org} = {r_org}")
                join_sql[-1] += f" AND ({' OR '.join(org_ors)})"
            else:
                join_sql[-1] += f" AND {l_org} = {r_org}"

        ledger_ref, document_table = None, None
        if left_actual == "inventory_stock_ledger" and left_column == "reference_id":
            ledger_ref, document_table = left_table, table
        elif table == "inventory_stock_ledger" and right_column == "reference_id":
            ledger_ref, document_table = reference, left_actual
        if ledger_ref and document_table in _STOCK_DOCUMENT_TYPES:
            if "reference_type" not in tables["inventory_stock_ledger"]:
                raise ValueError("A stock document join requires the reference_type discriminator.")
            join_sql[-1] += f" AND {aliases[ledger_ref]}.`reference_type` = {bind(_STOCK_DOCUMENT_TYPES[document_table])}"

        executed_joins.append({**join, "type": join_type, "relationship_source": rel_source})
        joined.add(reference)
        reference_tables[reference] = table

    absent_deletion_tables = sorted({
        field.get("table")
        for field in (block.get("filters") or [])
        if field.get("column") == "deleted_at"
        and field.get("table") in joined
        and reference_tables[field["table"]] in physical_tables
        and "deleted_at" not in tables[reference_tables[field["table"]]]
    })
    if absent_deletion_tables:
        raise ValueError(
            "Unavailable fields: "
            + ", ".join(table + ".deleted_at" for table in absent_deletion_tables)
            + ". These tables have no soft-delete column; remove these deletion filters."
        )

    selections = block.get("select") or []
    if not selections or len(selections) > _MAX_SELECTS:
        raise ValueError(f"Select between 1 and {_MAX_SELECTS} fields.")

    def _resolve_scalar_or_expr(val):
        if isinstance(val, dict):
            if "expression" in val or {"operator", "left", "right"} <= set(val):
                expr_body = val["expression"] if "expression" in val else val
                return compile_arithmetic(expr_body, validate_field, bind), "decimal"
            return validate_field(val)
        if isinstance(val, bool) or not isinstance(val, (int, float, Decimal)) or not Decimal(str(val)).is_finite():
            raise ValueError("CASE constant values must be finite numbers.")
        return bind(val), "decimal"

    def validate_field(field):
        if not isinstance(field, dict):
            raise ValueError("Field specification must be an object.")
        if "case_when" in field and field["case_when"] is not None:
            cw = field["case_when"]
            if not isinstance(cw, dict) or not cw.get("conditions"):
                raise ValueError("case_when requires a non-empty conditions array.")
            cw_logic = (cw.get("logic") or "AND").upper()
            if cw_logic not in {"AND", "OR"}:
                raise ValueError("case_when logic must be AND or OR.")
            cw_parts = [_compile_where_condition(c)[0] for c in cw["conditions"]]
            cond_sql = f" {cw_logic} ".join(cw_parts)
            if "then" in cw and cw["then"] is not None:
                then_sql, then_type = _resolve_scalar_or_expr(cw["then"])
            elif field.get("expression") is not None or (field.get("table") and field.get("column")):
                stripped = {k: v for k, v in field.items() if k != "case_when"}
                then_sql, then_type = validate_field(stripped)
            else:
                then_sql, then_type = bind(1), "int"
            if "else_value" in cw and cw["else_value"] is not None:
                else_sql, _ = _resolve_scalar_or_expr(cw["else_value"])
            else:
                else_sql = "NULL"
            return f"CASE WHEN ({cond_sql}) THEN {then_sql} ELSE {else_sql} END", then_type

        if "expression" in field and field["expression"] is not None:
            if any(field.get(k) is not None for k in ("table", "column", "date_part")):
                raise ValueError("Use either a field reference or a calculated expression.")
            return compile_arithmetic(field["expression"], validate_field, bind), "decimal"

        if set(field.keys()) <= {"alias", "operator", "value"} and field.get("alias") and not field.get("table"):
            alias_name = field["alias"]
            for sel in selections:
                if sel.get("alias") == alias_name:
                    if sel.get("aggregate") or sel.get("window"):
                        raise ValueError(
                            f"Alias '{alias_name}' is an aggregate or window calculation; filter aggregates in 'having' "
                            "or compute window functions inside 'ctes' and filter in the outer query."
                        )
                    stripped = {k: v for k, v in sel.items() if k not in {"alias", "coalesce"}}
                    expr_sql, expr_type = validate_field(stripped)
                    if sel.get("coalesce") is not None:
                        expr_sql = f"COALESCE({expr_sql}, {bind(sel['coalesce'])})"
                    return expr_sql, expr_type
            candidates = [ref for ref in joined if alias_name in tables.get(reference_tables[ref], {})]
            if len(candidates) == 1:
                return validate_field({"table": candidates[0], "column": alias_name})
            raise ValueError(f"Unknown or ambiguous alias reference {alias_name!r}.")

        table, column = field.get("table"), field.get("column")
        table_columns = tables.get(reference_tables.get(table), {})
        if table not in joined or column not in table_columns:
            if table in joined:
                raise ValueError(
                    f"Unavailable field {table}.{column}. Use only these verified columns: "
                    + ", ".join(table_columns)
                )
            raise ValueError(
                f"Field {table}.{column} is outside the validated query tables. "
                f"Available table references: {', '.join(sorted(joined))}."
            )
        expression = f"{aliases[table]}.{_quote(column)}"
        date_part = field.get("date_part")
        if date_part:
            if table_columns[column] not in {"date", "datetime", "timestamp"}:
                raise ValueError("Date grouping requires a date or timestamp column.")
            if date_part == "month":
                expression = f"EXTRACT(YEAR_MONTH FROM {expression})"
            elif date_part == "year":
                expression = f"YEAR({expression})"
            elif date_part == "day":
                expression = f"DATE({expression})"
            else:
                raise ValueError("Date grouping supports day, month or year only.")
        return expression, "date" if date_part == "day" else table_columns[column]

    def _compile_where_condition(condition):
        expression, field_type = validate_field(condition)
        operator = (condition.get("operator") or "=").upper()
        if operator not in _OPERATORS:
            raise ValueError("Unsupported filter operator.")
        value = condition.get("value")
        if field_type in _NUMERIC_TYPES and operator not in {"LIKE", "IS NULL", "IS NOT NULL"} and not isinstance(value, dict):
            numeric_values = value if isinstance(value, list) else [value]
            for numeric_value in numeric_values:
                if numeric_value is None:
                    continue
                try:
                    parsed_number = Decimal(str(numeric_value))
                    if not parsed_number.is_finite():
                        raise ValueError("Non-finite number")
                except (ValueError, ArithmeticError):
                    raise ValueError(
                        f"Numeric field {condition.get('table')}.{condition.get('column')} requires a numeric value."
                    )
        if isinstance(value, dict):
            if "expression" in value or {"operator", "left", "right"} <= set(value):
                if operator not in {"=", "!=", "<>", ">", ">=", "<", "<="}:
                    raise ValueError("Expression comparisons require a comparison operator.")
                expr_body = value["expression"] if "expression" in value else value
                right_expression = compile_arithmetic(expr_body, validate_field, bind)
                return f"{expression} {operator} {right_expression}", None
            if {"table", "column"} <= set(value):
                value = {"table": value["table"], "column": value["column"]}
            elif set(value) == {"alias"}:
                for sel in selections:
                    if sel.get("alias") == value["alias"] and sel.get("table") and sel.get("column") and not sel.get("aggregate") and not sel.get("window"):
                        value = {"table": sel["table"], "column": sel["column"]}
                        break
            if set(value) not in ({"table", "column"}, {"alias"}) or operator not in {"=", "!=", "<>", ">", ">=", "<", "<="}:
                raise ValueError("Column comparisons require a validated table/column and a comparison operator.")
            right_expression, _ = validate_field(value)
            return f"{expression} {operator} {right_expression}", None
        if isinstance(value, list) and any(isinstance(item, (dict, list)) for item in value):
            raise ValueError("Filter values must be scalar values or a flat list of scalar values.")
        value = normalize_timestamp(value, field_type)
        day_filter = calendar_predicate(expression, field_type, operator, value, bind)
        if day_filter:
            return day_filter, condition
        if operator in {"IS NULL", "IS NOT NULL"}:
            return f"{expression} {operator}", None
        if operator in {"IN", "NOT IN"}:
            if not isinstance(value, list) or not value or len(value) > 100:
                raise ValueError("IN filters require a list of 1 to 100 values.")
            return f"{expression} {operator} ({', '.join(bind(item) for item in value)})", None
        if operator == "BETWEEN":
            if not isinstance(value, list) or len(value) != 2:
                raise ValueError("BETWEEN filters require exactly two values.")
            return f"{expression} BETWEEN {bind(value[0])} AND {bind(value[1])}", None
        if value is None and operator in {"=", "!=", "<>"}:
            return f"{expression} {'IS NULL' if operator == '=' else 'IS NOT NULL'}", None
        return f"{expression} {operator} {bind(value)}", None

    aggregation_grains = validate_aggregate_grain(block, working_schema, reference_tables)
    select_sql, output_names = [], set()
    output_types = {}
    column_origins = {}
    rn_specs = []

    for index, item in enumerate(selections, start=1):
        candidate_alias = item.get("alias")
        if not candidate_alias and is_cte and item.get("column") and item["column"] not in output_names:
            candidate_alias = item["column"]
        alias = candidate_alias or f"field_{index}"
        if not _IDENTIFIER_RE.fullmatch(alias) or alias in output_names:
            raise ValueError("Output aliases must be unique simple names.")

        win = item.get("window")
        aggregate = (item.get("aggregate") or "").upper()

        if win is not None:
            if not isinstance(win, dict):
                raise ValueError("Window specification must be an object.")
            func = (win.get("function") or "").upper()
            if func not in _WINDOW_FUNCTIONS:
                raise ValueError(f"Unsupported window function: {func!r}.")
            if aggregate and aggregate != func:
                raise ValueError("Do not combine separate aggregate and window functions on one field.")
            if item.get("distinct"):
                raise ValueError("DISTINCT is not supported inside window functions.")
            if func in {"ROW_NUMBER", "RANK", "DENSE_RANK"}:
                fn_sql = f"{func}()"
                data_type = "bigint"
            else:
                inner_item = {k: v for k, v in item.items() if k not in {"window", "aggregate", "coalesce"}}
                inner_sql, inner_type = validate_field(inner_item)
                if func in {"SUM", "AVG"} and inner_type not in _NUMERIC_TYPES:
                    raise ValueError(f"Window {func} can only be used with numeric fields.")
                fn_sql = f"{func}({inner_sql})"
                data_type = "bigint" if func == "COUNT" else ("decimal" if func in {"SUM", "AVG"} else inner_type)

            part_sqls = []
            part_refs = []
            for pb in win.get("partition_by") or []:
                p_sql, _ = validate_field(pb)
                part_sqls.append(p_sql)
                part_refs.append((pb.get("table"), pb.get("column")))

            w_order_sqls = []
            for ob in win.get("order_by") or []:
                o_sql, _ = validate_field(ob)
                o_dir = (ob.get("direction") or "asc").upper()
                if o_dir not in {"ASC", "DESC"}:
                    raise ValueError("Window sort direction must be ASC or DESC.")
                w_order_sqls.append(f"{o_sql} {o_dir}")

            over_parts = []
            if part_sqls:
                over_parts.append("PARTITION BY " + ", ".join(part_sqls))
            if w_order_sqls:
                over_parts.append("ORDER BY " + ", ".join(w_order_sqls))
            expression = f"{fn_sql} OVER ({' '.join(over_parts)})"
            if item.get("coalesce") is not None:
                expression = f"COALESCE({expression}, {bind(item['coalesce'])})"
            if func == "ROW_NUMBER":
                rn_specs.append((alias, part_refs))
            output_types[alias] = data_type
            column_origins[alias] = set()
        else:
            expression, data_type = validate_field(item)
            if aggregate:
                if aggregate not in _AGGREGATES:
                    raise ValueError("Unsupported aggregate function.")
                if aggregate in {"SUM", "AVG"} and data_type not in _NUMERIC_TYPES:
                    raise ValueError(f"{aggregate} can only be used with numeric fields.")
                if item.get("distinct"):
                    if aggregate != "COUNT":
                        raise ValueError("distinct is supported only with COUNT.")
                    expression = f"COUNT(DISTINCT {expression})"
                else:
                    expression = f"{aggregate}({expression})"
                out_type = "bigint" if aggregate == "COUNT" else ("decimal" if aggregate in {"SUM", "AVG"} else data_type)
                if item.get("coalesce") is not None:
                    expression = f"COALESCE({expression}, {bind(item.get('coalesce', 0))})"
                output_types[alias] = out_type
                column_origins[alias] = set()
            else:
                if item.get("coalesce") is not None:
                    expression = f"COALESCE({expression}, {bind(item.get('coalesce', 0))})"
                output_types[alias] = data_type
                if (
                    item.get("table")
                    and item.get("column")
                    and not item.get("expression")
                    and not item.get("case_when")
                    and not item.get("date_part")
                ):
                    src_actual = reference_tables[item["table"]]
                    if src_actual in cte_catalog:
                        column_origins[alias] = set(
                            cte_catalog[src_actual]["column_origins"].get(item["column"], set())
                        )
                    else:
                        column_origins[alias] = {(src_actual, item["column"])}
                else:
                    column_origins[alias] = set()

        output_names.add(alias)
        select_sql.append(f"{expression} AS {_quote(alias)}")

    where_parts = []
    calendar_filters = []
    filters = block.get("filters") or []
    if len(filters) > _MAX_FILTERS:
        raise ValueError(f"A query can use at most {_MAX_FILTERS} filters.")
    for condition in filters:
        w_sql, cal_cond = _compile_where_condition(condition)
        where_parts.append(w_sql)
        if cal_cond is not None:
            calendar_filters.append(cal_cond)

    group_sql = []
    groups = block.get("group_by") or []
    if len(groups) > _MAX_SELECTS:
        raise ValueError("Too many grouping fields.")
    for group in groups:
        expression, _ = validate_field(group)
        group_sql.append(expression)

    def group_key(field):
        return (
            field.get("table"),
            field.get("column"),
            field.get("date_part"),
            json.dumps(field.get("expression"), sort_keys=True),
        )

    if groups or any(item.get("aggregate") for item in selections):
        missing_groups = [
            (item.get("table"), item.get("column"))
            for item in selections
            if not item.get("aggregate")
            and not item.get("window")
            and not any(group_key(item) == group_key(group) for group in groups)
        ]
        if missing_groups:
            raise ValueError(
                "A mixed aggregate/detail query must group every selected nonaggregate field. "
                "Missing grouping fields: " + str(missing_groups)
            )

    order_sql = []
    order_by = block.get("order_by") or []
    if len(order_by) > _MAX_SELECTS:
        raise ValueError("Too many sort fields.")
    for order in order_by:
        alias = order.get("alias")
        if alias not in output_names:
            matching_aliases = [
                selected.get("alias") or f"field_{index}"
                for index, selected in enumerate(selections, start=1)
                if alias in {selected.get("column"), f"{selected.get('table')}.{selected.get('column')}"}
                and not selected.get("aggregate")
                and not selected.get("window")
            ]
            if len(matching_aliases) != 1:
                raise ValueError("Sort only by a selected output alias or an unambiguous selected column.")
            alias = matching_aliases[0]
        direction = (order.get("direction") or "asc").upper()
        if direction not in {"ASC", "DESC"}:
            raise ValueError("Sort direction must be ASC or DESC.")
        order_sql.append(f"{_quote(alias)} {direction}")

    sql = f"SELECT {', '.join(select_sql)} FROM {_quote(base)} {aliases[base]}"
    if join_sql:
        sql += " " + " ".join(join_sql)
    scoped_parts = organization_conditions(base, reference_tables, aliases, physical_schema, bind)
    for reference, actual in reference_tables.items():
        if actual == "core_config":
            scoped_parts.append(f"{aliases[reference]}.`key` = {bind('base_currency')}")
    if where_parts:
        filter_logic = (block.get("filter_logic") or "AND").upper()
        if filter_logic not in {"AND", "OR"}:
            raise ValueError("filter_logic must be AND or OR.")
        sql += " WHERE (" + f" {filter_logic} ".join(where_parts) + ")"
        if scoped_parts:
            sql += " AND " + " AND ".join(scoped_parts)
    elif scoped_parts:
        sql += " WHERE " + " AND ".join(scoped_parts)
    if group_sql:
        sql += " GROUP BY " + ", ".join(group_sql)

    def resolve_having_operand(ref):
        if isinstance(ref, dict):
            if set(ref) == {"alias"}:
                a_name = ref["alias"]
                if a_name not in output_names:
                    raise ValueError(f"HAVING reference {a_name!r} must be a selected output alias.")
                return _quote(a_name), output_types.get(a_name, "decimal")
            if {"table", "column"} <= set(ref):
                val_field = {"table": ref["table"], "column": ref["column"]}
                expr_sql, expr_type = validate_field(val_field)
                matching_aliases = [
                    selected.get("alias") or f"field_{index}"
                    for index, selected in enumerate(selections, start=1)
                    if selected.get("table") == ref["table"]
                    and selected.get("column") == ref["column"]
                    and not selected.get("aggregate")
                    and not selected.get("window")
                ]
                if len(matching_aliases) == 1:
                    m_alias = matching_aliases[0]
                    return _quote(m_alias), output_types.get(m_alias, expr_type)
                if any(group_key(val_field) == group_key(g) for g in groups):
                    return expr_sql, expr_type
        raise ValueError("HAVING operands must reference a selected output alias or grouped column.")

    having_parts = []
    having_filters = block.get("having") or []
    if len(having_filters) > _MAX_FILTERS:
        raise ValueError(f"A query can use at most {_MAX_FILTERS} HAVING filters.")
    for condition in having_filters:
        if condition.get("expression") is not None:
            lhs_sql = compile_arithmetic(condition["expression"], resolve_having_operand, bind)
        else:
            alias = condition.get("alias")
            if alias not in output_names:
                raise ValueError("HAVING filters must reference a selected output alias.")
            lhs_sql = _quote(alias)
        operator = (condition.get("operator") or "=").upper()
        if operator not in _OPERATORS:
            raise ValueError("Unsupported HAVING operator.")
        value = condition.get("value")
        if isinstance(value, dict):
            if "expression" in value or {"operator", "left", "right"} <= set(value):
                if operator not in {"=", "!=", "<>", ">", ">=", "<", "<="}:
                    raise ValueError("HAVING expression comparisons require a comparison operator.")
                expr_body = value["expression"] if "expression" in value else value
                rhs_sql = compile_arithmetic(expr_body, resolve_having_operand, bind)
                having_parts.append(f"{lhs_sql} {operator} {rhs_sql}")
                continue
            if {"table", "column"} <= set(value):
                val_field = {"table": value["table"], "column": value["column"]}
                validate_field(val_field)
                matching_aliases = [
                    selected.get("alias") or f"field_{index}"
                    for index, selected in enumerate(selections, start=1)
                    if selected.get("table") == value["table"]
                    and selected.get("column") == value["column"]
                    and not selected.get("aggregate")
                    and not selected.get("window")
                ]
                if len(matching_aliases) == 1:
                    value = {"alias": matching_aliases[0]}
            if set(value) != {"alias"} or value["alias"] not in output_names or operator not in {"=", "!=", "<>", ">", ">=", "<", "<="}:
                raise ValueError("HAVING comparisons must reference another selected output alias.")
            having_parts.append(f"{lhs_sql} {operator} {_quote(value['alias'])}")
            continue
        if isinstance(value, list) and any(isinstance(item, (dict, list)) for item in value):
            raise ValueError("HAVING values must be scalar values or a flat list of scalar values.")
        if operator in {"IS NULL", "IS NOT NULL"}:
            having_parts.append(f"{lhs_sql} {operator}")
        elif operator in {"IN", "NOT IN"}:
            if not isinstance(value, list) or not value or len(value) > 100:
                raise ValueError("HAVING IN filters require a list of 1 to 100 values.")
            having_parts.append(f"{lhs_sql} {operator} ({', '.join(bind(item) for item in value)})")
        elif operator == "BETWEEN":
            if not isinstance(value, list) or len(value) != 2:
                raise ValueError("HAVING BETWEEN filters require exactly two values.")
            having_parts.append(f"{lhs_sql} BETWEEN {bind(value[0])} AND {bind(value[1])}")
        elif value is None and operator in {"=", "!=", "<>"}:
            having_parts.append(f"{lhs_sql} {'IS NULL' if operator == '=' else 'IS NOT NULL'}")
        else:
            having_parts.append(f"{lhs_sql} {operator} {bind(value)}")

    if having_parts:
        having_logic = (block.get("having_logic") or "AND").upper()
        if having_logic not in {"AND", "OR"}:
            raise ValueError("having_logic must be AND or OR.")
        sql += " HAVING " + f" {having_logic} ".join(having_parts)
    if order_sql:
        sql += " ORDER BY " + ", ".join(order_sql)

    limit = None
    offset = 0
    if is_cte:
        if "limit" in block and block["limit"] is not None:
            cte_limit = block["limit"]
            if isinstance(cte_limit, bool) or not isinstance(cte_limit, int) or not 1 <= cte_limit <= _MAX_CTE_ROWS:
                raise ValueError(f"CTE limit must be an integer between 1 and {_MAX_CTE_ROWS}.")
            cte_offset = block.get("offset", 0) or 0
            if isinstance(cte_offset, bool) or not isinstance(cte_offset, int) or cte_offset < 0:
                raise ValueError("CTE offset must be a nonnegative integer.")
            if cte_offset and not order_sql:
                raise ValueError("CTE offset requires explicit ordering.")
            sql += f" LIMIT {cte_limit}" + (f" OFFSET {cte_offset}" if cte_offset else "")
            limit = cte_limit
            offset = cte_offset
    else:
        requested_limit = block.get("limit", _MAX_ROWS)
        if not isinstance(requested_limit, int) or isinstance(requested_limit, bool) or requested_limit < 1:
            requested_limit = 50
        limit = min(requested_limit, _MAX_ROWS)
        offset = block.get("offset", 0)
        if isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset <= 9223372036854775807:
            raise ValueError("Query offset must be a nonnegative database integer.")
        if offset and not order_sql:
            raise ValueError("Paged queries require explicit ordering by selected fields.")

    # Compute proven unique indexes for CTE output columns
    cte_indexes = {}
    direct_alias_by_ref = {}
    for idx, sel in enumerate(selections, start=1):
        if (
            sel.get("table")
            and sel.get("column")
            and not sel.get("aggregate")
            and not sel.get("window")
            and not sel.get("expression")
            and not sel.get("case_when")
            and not sel.get("date_part")
        ):
            direct_alias_by_ref.setdefault((sel["table"], sel["column"]), sel.get("alias") or f"field_{idx}")

    if groups:
        group_aliases = []
        all_grouped_selected = True
        for grp in groups:
            matched = [
                sel.get("alias") or f"field_{idx}"
                for idx, sel in enumerate(selections, start=1)
                if not sel.get("aggregate") and not sel.get("window") and group_key(sel) == group_key(grp)
            ]
            if matched:
                group_aliases.append(matched[0])
            else:
                all_grouped_selected = False
                break
        if all_grouped_selected and group_aliases:
            cte_indexes["CTE_GROUP_KEY"] = {"unique": True, "columns": group_aliases}
    else:
        for rn_idx, (rn_alias, part_refs) in enumerate(rn_specs, start=1):
            if not part_refs:
                cte_indexes[f"CTE_RN_{rn_idx}"] = {"unique": True, "columns": [rn_alias]}
            elif all(pr in direct_alias_by_ref for pr in part_refs):
                cols = [direct_alias_by_ref[pr] for pr in part_refs] + [rn_alias]
                cte_indexes[f"CTE_RN_{rn_idx}"] = {"unique": True, "columns": cols}

        # Propagate base table unique indexes when no join multiplies base rows
        if not joins:
            is_and = (block.get("filter_logic") or "AND").upper() == "AND"
            eq_constrained = {
                f.get("column")
                for f in filters
                if is_and
                and isinstance(f, dict)
                and f.get("table") == base
                and f.get("column")
                and (f.get("operator") or "").upper() in {"=", "IS", "IS NULL"}
            }
            for idx_name, idx_info in working_schema.get("indexes", {}).get(reference_tables[base], {}).items():
                if not idx_info.get("unique"):
                    continue
                rem_cols = [c for c in idx_info.get("columns", []) if c not in eq_constrained]
                if rem_cols and all((base, c) in direct_alias_by_ref for c in rem_cols):
                    cte_indexes[f"PROP_{idx_name}"] = {
                        "unique": True,
                        "columns": [direct_alias_by_ref[(base, c)] for c in rem_cols],
                    }

    return {
        "sql": sql,
        "base": base,
        "joins": joins,
        "executed_joins": executed_joins,
        "joined": joined,
        "reference_tables": reference_tables,
        "selections": selections,
        "aggregation_grains": aggregation_grains,
        "filters": filters,
        "calendar_filters": calendar_filters,
        "groups": groups,
        "having_filters": having_filters,
        "limit": limit,
        "offset": offset,
        "output_types": output_types,
        "column_origins": column_origins,
        "cte_indexes": cte_indexes,
    }


def query_business_data(
    query_plan: dict,
    tenant_identifier: str = None,
    user_question: str = None,
    resolved_records=None,
) -> dict:
    """Compile and execute a validated, bounded, read-only cross-module SELECT (with optional CTEs)."""
    tenant_db = resolve_tenant_database(tenant_identifier)
    logger.info(
        "[STEP 5: SQL COMPILER] Compiling plan for base_table=%r on tenant=%s",
        query_plan.get("base_table") if isinstance(query_plan, dict) else None,
        tenant_db,
    )
    try:
        if not isinstance(query_plan, dict):
            raise ValueError("The query plan must be an object.")
        query_plan = normalize_table_references(query_plan)
        from .erp_access import enforce_tenant, public_schema

        enforce_tenant(tenant_db)
        physical_schema = public_schema(_schema_for(tenant_db))
        working_schema = {
            "tables": dict(physical_schema["tables"]),
            "relationships": set(physical_schema.get("relationships", ())),
            "declared_relationships": set(physical_schema.get("declared_relationships", ())),
            "application_relationships": set(physical_schema.get("application_relationships", ())),
            "column_constraints": dict(physical_schema.get("column_constraints", {})),
            "indexes": {k: dict(v) for k, v in physical_schema.get("indexes", {}).items()},
        }

        params = {}

        def bind(value):
            name = f"p{len(params)}"
            params[name] = value
            return f"%({name})s"

        ctes = query_plan.get("ctes") or []
        if len(ctes) > _MAX_CTES:
            raise ValueError(f"A query can define at most {_MAX_CTES} CTEs.")

        cte_catalog = {}
        cte_sql_parts = []
        cte_audits = []
        all_calendar_filters = []

        for cte_idx, cte in enumerate(ctes, start=1):
            if not isinstance(cte, dict):
                raise ValueError("Each CTE must be an object.")
            cte_name = cte.get("name")
            if not isinstance(cte_name, str) or not _IDENTIFIER_RE.fullmatch(cte_name):
                raise ValueError(f"Invalid CTE name: {cte_name!r}.")
            lower_cte = cte_name.lower()
            if (
                cte_name in cte_catalog
                or cte_name in physical_schema["tables"]
                or lower_cte in _SENSITIVE_TABLES
                or any(part in lower_cte for part in _SENSITIVE_TABLE_PARTS)
            ):
                raise ValueError(f"CTE name {cte_name!r} conflicts with an existing or restricted table name.")

            compiled_cte = _compile_select_block(
                cte,
                working_schema,
                physical_schema,
                cte_catalog,
                bind,
                alias_prefix=f"c{cte_idx}_",
                is_cte=True,
            )
            cte_sql_parts.append(f"{_quote(cte_name)} AS ({compiled_cte['sql']})")
            working_schema["tables"][cte_name] = dict(compiled_cte["output_types"])
            if compiled_cte["cte_indexes"]:
                working_schema["indexes"][cte_name] = dict(compiled_cte["cte_indexes"])
            cte_catalog[cte_name] = {
                "output_types": compiled_cte["output_types"],
                "column_origins": compiled_cte["column_origins"],
                "indexes": compiled_cte["cte_indexes"],
            }
            all_calendar_filters.extend(compiled_cte["calendar_filters"])
            cte_audits.append({
                "name": cte_name,
                "base_table": compiled_cte["base"],
                "joins": compiled_cte["executed_joins"],
                "aggregation_grains": compiled_cte["aggregation_grains"],
                "indexes": compiled_cte["cte_indexes"],
            })

        outer = _compile_select_block(
            query_plan,
            working_schema,
            physical_schema,
            cte_catalog,
            bind,
            alias_prefix="",
            is_cte=False,
        )
        all_calendar_filters.extend(outer["calendar_filters"])

        sql = (
            f"WITH {', '.join(cte_sql_parts)} {outer['sql']}"
            if cte_sql_parts
            else outer["sql"]
        )
        limit = outer["limit"]
        offset = outer["offset"]
        tables = working_schema["tables"]
        joined = outer["joined"]
        reference_tables = outer["reference_tables"]

        logger.info("[STEP 5: SQL EXECUTION] Executing compiled query on tenant=%s", tenant_db)
        from .mcp_client import mcp_run_select

        mcp_res = mcp_run_select(
            sql=sql,
            database=tenant_db,
            page_size=limit,
            offset=offset,
            params=params,
        )
        if mcp_res.get("error") or mcp_res.get("is_error"):
            err_msg = mcp_res.get("error") or "Database read via MCP failed."
            logger.error("[STEP 5: SQL EXECUTION FAILED] %s", err_msg)
            raise ValueError(err_msg)

        rows = mcp_res.get("rows", [])
        was_truncated = bool(mcp_res.get("has_more"))
        next_offset = mcp_res.get("next_offset")
        display_sql = format_display_sql(sql, params)
        if limit:
            display_sql += f" LIMIT {limit}"
        if offset:
            display_sql += f" OFFSET {offset}"
        logger.info(
            "[STEP 5: SQL EXECUTION SUCCESS] Returned %d rows from tenant=%s (truncated=%s)",
            len(rows),
            tenant_db,
            was_truncated,
        )
        return _serialize_decimals({
            "tenant_database": tenant_db,
            "row_count": len(rows),
            "limit": limit,
            "offset": offset,
            "next_offset": next_offset,
            "truncated": was_truncated,
            "mcp_elapsed_ms": mcp_res.get("elapsed_ms"),
            "mcp_read_at": mcp_res.get("read_at"),
            "compiled_sql": display_sql,
            "raw_sql": sql,
            "query_audit": {
                "compiled_sql": display_sql,
                "raw_sql": sql,
                "base_table": outer["base"],
                "ctes": cte_audits,
                "aggregation_grains": outer["aggregation_grains"],
                "joined_tables": [join.get("table") for join in outer["joins"]],
                "joins": outer["executed_joins"],
                "table_references": reference_tables,
                "selected_fields": [
                    {
                        "table": item.get("table"),
                        "column": item.get("column"),
                        "aggregate": (item.get("aggregate") or "").upper(),
                        "window": (item.get("window") or {}).get("function"),
                        "date_part": item.get("date_part"),
                        "expression": item.get("expression"),
                        "alias": item.get("alias"),
                    }
                    for item in outer["selections"]
                ],
                "filters": outer["filters"],
                "calendar_filters": all_calendar_filters,
                "calendar_timezone": str(timezone.get_current_timezone()) if all_calendar_filters else None,
                "group_by": outer["groups"],
                "having": outer["having_filters"],
                "soft_delete_columns": {
                    table: "deleted_at" if "deleted_at" in tables[reference_tables[table]] else None
                    for table in sorted(joined)
                },
                "available_columns": {table: sorted(tables[reference_tables[table]]) for table in sorted(joined)},
                "column_constraints": {
                    table: working_schema.get("column_constraints", {}).get(reference_tables[table], {})
                    for table in sorted(joined)
                },
            },
            "results": rows,
        })
    except Exception as exc:
        logger.info("Business data query could not be completed for %s: %s", tenant_db, exc, exc_info=True)
        return {
            "error": str(exc) if isinstance(exc, (ValueError, PermissionError)) else "The database read failed; no result was verified.",
            "error_type": "validation" if isinstance(exc, ValueError) else "database",
            "tenant_database": tenant_db,
        }
