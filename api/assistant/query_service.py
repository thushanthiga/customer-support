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
_MAX_JOINS = 5
_MAX_SELECTS = 12
_MAX_FILTERS = 20

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
_OPERATORS = {"=", "!=", "<>", ">", ">=", "<", "<=", "LIKE", "IN", "NOT IN", "BETWEEN", "IS NULL", "IS NOT NULL"}


def _quote(identifier: str) -> str:
    if not isinstance(identifier, str) or not _IDENTIFIER_RE.fullmatch(identifier):
        raise ValueError(f"Unsafe SQL identifier: {identifier!r}")
    return f"`{identifier}`"


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
    relationships.update(_infer_schema_relationships(tables))

    schema = {
        "tables": tables,
        "relationships": relationships,
        "column_constraints": column_constraints,
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
    "sales_goods_issue_notes": 10,
    "sales_goods_issue_note_lines": 10,
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
            elif value.endswith("s") and len(value) > 3:
                result.add(value[:-1])
        return result

    expanded = variants(words)

    # Quantity / Measurement / Replenishment
    if any(w in expanded for w in ["minimum", "min", "reorder", "threshold", "replenish", "replenishment"]):
        expanded.update(["min", "minimum", "replenishment", "reorder", "rules", "stock", "level"])
    if any(w in expanded for w in ["maximum", "max"]):
        expanded.update(["max", "maximum"])
    if any(w in expanded for w in ["quantity", "qty", "stock", "inventory", "balance", "balances", "depleted", "shortage"]):
        expanded.update(["qty", "quantity", "stock", "balances", "items", "warehouse"])

    # Parties: Suppliers & Customers
    if any(w in expanded for w in ["supplier", "suppliers", "vendor", "vendors", "procure", "procurement", "buy", "bought", "purchasing"]):
        expanded.update(["supplier", "suppliers", "vendor", "party", "parties", "procurement", "purchase"])
    if any(w in expanded for w in ["customer", "customers", "client", "clients", "buyer", "buyers"]):
        expanded.update(["customer", "customers", "party", "parties", "sales"])

    # Invoices & Bills (AP vs AR)
    if any(w in expanded for w in ["bill", "bills", "payable", "payables", "ap", "due", "unpaid", "debt", "owing"]):
        expanded.update(["invoice", "invoices", "bill", "bills", "amount", "due", "status", "party", "settled"])
    if any(w in expanded for w in ["invoice", "invoices", "receivable", "receivables", "ar", "overdue"]):
        expanded.update(["invoice", "invoices", "amount", "due", "status", "party", "settled"])

    # Demand, Popularity & Sales Velocity
    if any(w in expanded for w in ["demand", "demanded", "demands", "popular", "popularity", "velocity", "top", "trending", "bestseller", "bestsellers", "fast", "moving"]):
        expanded.update(["sales", "orders", "lines", "quantity", "items", "balances"])

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
            rows.append("Database enum values for " + table + ": " + json.dumps(enum_columns))
    table_rank = {table: index for index, table in enumerate(selected)}
    ranked_edges = sorted(
        schema["relationships"],
        key=lambda edge: (table_rank.get(edge[0], len(selected)) + table_rank.get(edge[2], len(selected)), edge),
    )
    edges = [
        f"{left}.{left_col} = {right}.{right_col}"
        for left, left_col, right, right_col in ranked_edges
        if left in selected and right in selected
    ]
    if edges:
        rows.append("Available verified joins: " + "; ".join(edges))
    rows.append("Authorized business table catalogue (request schema_tables for additional details): " + ", ".join(sorted(schema["tables"])))
    return "\n".join(rows)


def get_business_schema_context(
    question: str,
    tenant_identifier: str = None,
    force: bool = False,
    table_limit: int = 20,
) -> str:
    """Provide a cached, tenant-specific schema hint to the LLM."""
    tenant_db = resolve_tenant_database(tenant_identifier)
    try:
        from .erp_access import enforce_tenant, public_schema

        enforce_tenant(tenant_db)
        return _relevant_tables(public_schema(_schema_for(tenant_db)), question, limit=table_limit)
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
    base = result.get("base_table")
    references = {base: [base]}
    for item in result.get("joins") or []:
        references.setdefault(item.get("table"), []).append(item.get("alias") or item.get("table"))
    mapping = {name: refs[0] for name, refs in references.items() if len(refs) == 1}

    def field(value):
        if isinstance(value, dict) and "table" in value:
            value["table"] = mapping.get(value["table"], value["table"])
        if isinstance(value, dict) and isinstance(value.get("expression"), dict):
            field(value["expression"].get("left"))
            field(value["expression"].get("right"))

    for key in ("select", "filters", "group_by"):
        for item in result.get(key) or []:
            field(item)
            if isinstance(item, dict):
                field(item.get("value"))
    for item in result.get("joins") or []:
        item["left_table"] = mapping.get(item.get("left_table"), item.get("left_table"))
    return result


def query_business_data(
    query_plan: dict,
    tenant_identifier: str = None,
    user_question: str = None,
    resolved_records=None,
) -> dict:
    """Compile and execute a validated, bounded, read-only cross-module SELECT."""
    tenant_db = resolve_tenant_database(tenant_identifier)
    try:
        if not isinstance(query_plan, dict):
            raise ValueError("The query plan must be an object.")
        query_plan = normalize_table_references(query_plan)
        from .erp_access import enforce_tenant, organization_conditions, public_schema

        enforce_tenant(tenant_db)
        schema = public_schema(_schema_for(tenant_db))
        tables = schema["tables"]
        base = query_plan.get("base_table")
        if base not in tables:
            raise ValueError("The requested base table is unavailable. Use the supplied tenant schema context.")

        joined = {base}
        reference_tables = {base: base}
        aliases = {base: "t0"}
        join_sql = []
        join_params = {}
        executed_joins = []
        joins = query_plan.get("joins") or []
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
            reverse = (table, right_column, left_actual, left_column)
            if edge not in schema["relationships"] and reverse not in schema["relationships"]:
                alternatives = sorted(
                    [
                        relation
                        for relation in schema["relationships"]
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
            aliases[reference] = f"t{index}"
            join_type = str(join.get("type") or "LEFT").upper()
            if join_type not in {"INNER", "LEFT"}:
                raise ValueError("Join type must be INNER or LEFT.")
            join_sql.append(
                f"{join_type} JOIN {_quote(table)} {aliases[reference]} ON "
                f"{aliases[left_table]}.{_quote(left_column)} = {aliases[reference]}.{_quote(right_column)}"
            )
            ledger_ref, document_table = None, None
            if left_actual == "inventory_stock_ledger" and left_column == "reference_id":
                ledger_ref, document_table = left_table, table
            elif table == "inventory_stock_ledger" and right_column == "reference_id":
                ledger_ref, document_table = reference, left_actual
            if ledger_ref and document_table in _STOCK_DOCUMENT_TYPES:
                if "reference_type" not in tables["inventory_stock_ledger"]:
                    raise ValueError("A stock document join requires the reference_type discriminator.")
                key = f"join_type_{index}"
                join_params[key] = _STOCK_DOCUMENT_TYPES[document_table]
                join_sql[-1] += f" AND {aliases[ledger_ref]}.`reference_type` = %({key})s"
            executed_joins.append({**join, "type": join_type, "relationship_source": "database_schema"})
            joined.add(reference)
            reference_tables[reference] = table

        absent_deletion_tables = sorted({
            field.get("table")
            for field in (query_plan.get("filters") or [])
            if field.get("column") == "deleted_at"
            and field.get("table") in joined
            and "deleted_at" not in tables[reference_tables[field["table"]]]
        })
        if absent_deletion_tables:
            raise ValueError(
                "Unavailable fields: "
                + ", ".join(table + ".deleted_at" for table in absent_deletion_tables)
                + ". These tables have no soft-delete column; remove these deletion filters."
            )

        params = dict(join_params)

        def bind(value):
            name = f"p{len(params)}"
            params[name] = value
            return f"%({name})s"

        def validate_field(field):
            if "expression" in field:
                if any(k in field for k in ("table", "column", "date_part")):
                    raise ValueError("Use either a field reference or a calculated expression.")
                from .query_calculations import compile_arithmetic

                return compile_arithmetic(field["expression"], validate_field, bind), "decimal"
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

        selections = query_plan.get("select") or []
        if not selections or len(selections) > _MAX_SELECTS:
            raise ValueError(f"Select between 1 and {_MAX_SELECTS} fields.")
        select_sql, output_names = [], set()
        for index, item in enumerate(selections, start=1):
            expression, data_type = validate_field(item)
            aggregate = (item.get("aggregate") or "").upper()
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
            elif "coalesce" in item:
                coalesce_val = item.get("coalesce", 0)
                expression = f"COALESCE({expression}, {bind(coalesce_val)})"
            alias = item.get("alias") or f"field_{index}"
            if not _IDENTIFIER_RE.fullmatch(alias) or alias in output_names:
                raise ValueError("Output aliases must be unique simple names.")
            output_names.add(alias)
            select_sql.append(f"{expression} AS {_quote(alias)}")

        where_parts = []
        calendar_filters = []
        filters = query_plan.get("filters") or []
        if len(filters) > _MAX_FILTERS:
            raise ValueError(f"A query can use at most {_MAX_FILTERS} filters.")
        for condition in filters:
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
                if set(value) != {"table", "column"} or operator not in {"=", "!=", "<>", ">", ">=", "<", "<="}:
                    raise ValueError("Column comparisons require a validated table/column and a comparison operator.")
                right_expression, _ = validate_field(value)
                where_parts.append(f"{expression} {operator} {right_expression}")
                continue
            if isinstance(value, list) and any(isinstance(item, (dict, list)) for item in value):
                raise ValueError("Filter values must be scalar values or a flat list of scalar values.")
            from .query_calculations import calendar_predicate, normalize_timestamp

            value = normalize_timestamp(value, field_type)
            day_filter = calendar_predicate(expression, field_type, operator, value, bind)
            if day_filter:
                where_parts.append(day_filter)
                calendar_filters.append(condition)
                continue
            if operator in {"IS NULL", "IS NOT NULL"}:
                where_parts.append(f"{expression} {operator}")
            elif operator in {"IN", "NOT IN"}:
                if not isinstance(value, list) or not value or len(value) > 100:
                    raise ValueError("IN filters require a list of 1 to 100 values.")
                where_parts.append(f"{expression} {operator} ({', '.join(bind(item) for item in value)})")
            elif operator == "BETWEEN":
                if not isinstance(value, list) or len(value) != 2:
                    raise ValueError("BETWEEN filters require exactly two values.")
                where_parts.append(f"{expression} BETWEEN {bind(value[0])} AND {bind(value[1])}")
            elif value is None and operator in {"=", "!=", "<>"}:
                where_parts.append(f"{expression} {'IS NULL' if operator == '=' else 'IS NOT NULL'}")
            else:
                where_parts.append(f"{expression} {operator} {bind(value)}")

        group_sql = []
        groups = query_plan.get("group_by") or []
        if len(groups) > _MAX_SELECTS:
            raise ValueError("Too many grouping fields.")
        for group in groups:
            expression, _ = validate_field(group)
            group_sql.append(expression)
        if any(item.get("aggregate") for item in selections):
            def group_key(field):
                return (
                    field.get("table"),
                    field.get("column"),
                    field.get("date_part"),
                    json.dumps(field.get("expression"), sort_keys=True),
                )

            missing_groups = [
                (item.get("table"), item.get("column"))
                for item in selections
                if not item.get("aggregate") and not any(group_key(item) == group_key(group) for group in groups)
            ]
            if missing_groups:
                raise ValueError(
                    "A mixed aggregate/detail query must group every selected nonaggregate field. "
                    "Missing grouping fields: " + str(missing_groups)
                )

        order_sql = []
        order_by = query_plan.get("order_by") or []
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
                ]
                if len(matching_aliases) != 1:
                    raise ValueError("Sort only by a selected output alias or an unambiguous selected column.")
                alias = matching_aliases[0]
            direction = (order.get("direction") or "asc").upper()
            if direction not in {"ASC", "DESC"}:
                raise ValueError("Sort direction must be ASC or DESC.")
            order_sql.append(f"{_quote(alias)} {direction}")

        requested_limit = query_plan.get("limit", _MAX_ROWS)
        if not isinstance(requested_limit, int) or isinstance(requested_limit, bool) or requested_limit < 1:
            requested_limit = 50
        limit = min(requested_limit, _MAX_ROWS)
        offset = query_plan.get("offset", 0)
        if isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset <= 9223372036854775807:
            raise ValueError("Query offset must be a nonnegative database integer.")
        if offset and not order_sql:
            raise ValueError("Paged queries require explicit ordering by selected fields.")

        sql = f"SELECT {', '.join(select_sql)} FROM {_quote(base)} {aliases[base]}"
        if join_sql:
            sql += " " + " ".join(join_sql)
        scoped_parts = organization_conditions(base, reference_tables, aliases, schema, bind)
        for reference, actual in reference_tables.items():
            if actual == "core_config":
                scoped_parts.append(f"{aliases[reference]}.`key` = {bind('base_currency')}")
        if where_parts:
            filter_logic = (query_plan.get("filter_logic") or "AND").upper()
            if filter_logic not in {"AND", "OR"}:
                raise ValueError("filter_logic must be AND or OR.")
            sql += " WHERE (" + f" {filter_logic} ".join(where_parts) + ")"
            if scoped_parts:
                sql += " AND " + " AND ".join(scoped_parts)
        elif scoped_parts:
            sql += " WHERE " + " AND ".join(scoped_parts)
        if group_sql:
            sql += " GROUP BY " + ", ".join(group_sql)
        having_parts = []
        having_filters = query_plan.get("having") or []
        if len(having_filters) > _MAX_FILTERS:
            raise ValueError(f"A query can use at most {_MAX_FILTERS} HAVING filters.")
        for condition in having_filters:
            alias = condition.get("alias")
            if alias not in output_names:
                raise ValueError("HAVING filters must reference a selected output alias.")
            operator = (condition.get("operator") or "=").upper()
            if operator not in _OPERATORS:
                raise ValueError("Unsupported HAVING operator.")
            value = condition.get("value")
            if isinstance(value, dict):
                if set(value) == {"table", "column"}:
                    validate_field(value)
                    matching_aliases = [
                        selected.get("alias") or f"field_{index}"
                        for index, selected in enumerate(selections, start=1)
                        if selected.get("table") == value["table"]
                        and selected.get("column") == value["column"]
                        and not selected.get("aggregate")
                    ]
                    if len(matching_aliases) == 1:
                        value = {"alias": matching_aliases[0]}
                if set(value) != {"alias"} or value["alias"] not in output_names or operator not in {"=", "!=", "<>", ">", ">=", "<", "<="}:
                    raise ValueError("HAVING comparisons must reference another selected output alias.")
                having_parts.append(f"{_quote(alias)} {operator} {_quote(value['alias'])}")
                continue
            if isinstance(value, list) and any(isinstance(item, (dict, list)) for item in value):
                raise ValueError("HAVING values must be scalar values or a flat list of scalar values.")
            expression = _quote(alias)
            if operator in {"IS NULL", "IS NOT NULL"}:
                having_parts.append(f"{expression} {operator}")
            elif operator in {"IN", "NOT IN"}:
                if not isinstance(value, list) or not value or len(value) > 100:
                    raise ValueError("HAVING IN filters require a list of 1 to 100 values.")
                having_parts.append(f"{expression} {operator} ({', '.join(bind(item) for item in value)})")
            elif operator == "BETWEEN":
                if not isinstance(value, list) or len(value) != 2:
                    raise ValueError("HAVING BETWEEN filters require exactly two values.")
                having_parts.append(f"{expression} BETWEEN {bind(value[0])} AND {bind(value[1])}")
            elif value is None and operator in {"=", "!=", "<>"}:
                having_parts.append(f"{expression} {'IS NULL' if operator == '=' else 'IS NOT NULL'}")
            else:
                having_parts.append(f"{expression} {operator} {bind(value)}")
        if having_parts:
            having_logic = (query_plan.get("having_logic") or "AND").upper()
            if having_logic not in {"AND", "OR"}:
                raise ValueError("having_logic must be AND or OR.")
            sql += " HAVING " + f" {having_logic} ".join(having_parts)
        if order_sql:
            sql += " ORDER BY " + ", ".join(order_sql)

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
            raise ValueError(err_msg)

        rows = mcp_res.get("rows", [])
        was_truncated = bool(mcp_res.get("has_more"))
        next_offset = mcp_res.get("next_offset")
        return _serialize_decimals({
            "tenant_database": tenant_db,
            "row_count": len(rows),
            "limit": limit,
            "offset": offset,
            "next_offset": next_offset,
            "truncated": was_truncated,
            "mcp_elapsed_ms": mcp_res.get("elapsed_ms"),
            "mcp_read_at": mcp_res.get("read_at"),
            "query_audit": {
                "base_table": base,
                "joined_tables": [join.get("table") for join in joins],
                "joins": executed_joins,
                "table_references": reference_tables,
                "selected_fields": [
                    {
                        "table": item.get("table"),
                        "column": item.get("column"),
                        "aggregate": (item.get("aggregate") or "").upper(),
                        "date_part": item.get("date_part"),
                        "expression": item.get("expression"),
                        "alias": item.get("alias"),
                    }
                    for item in selections
                ],
                "filters": filters,
                "calendar_filters": calendar_filters,
                "calendar_timezone": str(timezone.get_current_timezone()) if calendar_filters else None,
                "group_by": groups,
                "having": having_filters,
                "soft_delete_columns": {
                    table: "deleted_at" if "deleted_at" in tables[reference_tables[table]] else None
                    for table in sorted(joined)
                },
                "available_columns": {table: sorted(tables[reference_tables[table]]) for table in sorted(joined)},
                "column_constraints": {
                    table: schema.get("column_constraints", {}).get(reference_tables[table], {})
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
