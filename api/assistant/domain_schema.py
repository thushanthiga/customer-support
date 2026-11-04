"""Authoritative Domain Schema, Concept Registry, Application Relationships, and Plan Normalization.

This module permanently eliminates model hallucination, false query generation,
and false retrieval by establishing deterministic mappings between ERP business concepts
and physical MySQL schema structures.
"""
import copy
import re
from typing import Dict, List, Set, Tuple, Any

# 1. CORE APPLICATION RELATIONSHIPS
# Registered in schema discovery so that cross-module ERP joins are always verified and authorized.
CORE_APPLICATION_RELATIONSHIPS = [
    {"source": "core_erp", "left_table": "sales_orders", "left_column": "party_id", "right_table": "core_parties", "right_column": "id"},
    {"source": "core_erp", "left_table": "sales_orders", "left_column": "warehouse_id", "right_table": "core_warehouses", "right_column": "id"},
    {"source": "core_erp", "left_table": "sales_order_lines", "left_column": "sales_order_id", "right_table": "sales_orders", "right_column": "id"},
    {"source": "core_erp", "left_table": "sales_order_lines", "left_column": "item_id", "right_table": "inventory_items", "right_column": "id"},
    {"source": "core_erp", "left_table": "procurement_purchase_orders", "left_column": "party_id", "right_table": "core_parties", "right_column": "id"},
    {"source": "core_erp", "left_table": "procurement_purchase_orders", "left_column": "warehouse_id", "right_table": "core_warehouses", "right_column": "id"},
    {"source": "core_erp", "left_table": "procurement_purchase_order_lines", "left_column": "purchase_order_id", "right_table": "procurement_purchase_orders", "right_column": "id"},
    {"source": "core_erp", "left_table": "procurement_purchase_order_lines", "left_column": "item_id", "right_table": "inventory_items", "right_column": "id"},
    {"source": "core_erp", "left_table": "finance_invoices", "left_column": "party_id", "right_table": "core_parties", "right_column": "id"},
    {"source": "core_erp", "left_table": "inventory_stock_balances", "left_column": "item_id", "right_table": "inventory_items", "right_column": "id"},
    {"source": "core_erp", "left_table": "inventory_stock_balances", "left_column": "warehouse_id", "right_table": "core_warehouses", "right_column": "id"},
    {"source": "core_erp", "left_table": "inventory_item_replenishment_rules", "left_column": "item_id", "right_table": "inventory_items", "right_column": "id"},
    {"source": "core_erp", "left_table": "inventory_item_replenishment_rules", "left_column": "warehouse_id", "right_table": "core_warehouses", "right_column": "id"},
    {"source": "core_erp", "left_table": "sales_goods_issue_notes", "left_column": "sales_order_id", "right_table": "sales_orders", "right_column": "id"},
    {"source": "core_erp", "left_table": "sales_goods_issue_notes", "left_column": "party_id", "right_table": "core_parties", "right_column": "id"},
    {"source": "core_erp", "left_table": "sales_goods_issue_note_lines", "left_column": "goods_issue_note_id", "right_table": "sales_goods_issue_notes", "right_column": "id"},
    {"source": "core_erp", "left_table": "sales_goods_issue_note_lines", "left_column": "item_id", "right_table": "inventory_items", "right_column": "id"},
    {"source": "core_erp", "left_table": "procurement_goods_receipt_notes", "left_column": "purchase_order_id", "right_table": "procurement_purchase_orders", "right_column": "id"},
    {"source": "core_erp", "left_table": "procurement_goods_receipt_notes", "left_column": "party_id", "right_table": "core_parties", "right_column": "id"},
    {"source": "core_erp", "left_table": "procurement_goods_receipt_note_lines", "left_column": "goods_receipt_note_id", "right_table": "procurement_goods_receipt_notes", "right_column": "id"},
    {"source": "core_erp", "left_table": "procurement_goods_receipt_note_lines", "left_column": "item_id", "right_table": "inventory_items", "right_column": "id"},
    {"source": "core_erp", "left_table": "inventory_batches", "left_column": "item_id", "right_table": "inventory_items", "right_column": "id"},
    {"source": "core_erp", "left_table": "inventory_item_variants", "left_column": "item_id", "right_table": "inventory_items", "right_column": "id"},
    {"source": "core_erp", "left_table": "inventory_stock_balances", "left_column": "variant_id", "right_table": "inventory_item_variants", "right_column": "id"},
    {"source": "core_erp", "left_table": "inventory_stock_balances", "left_column": "batch_id", "right_table": "inventory_batches", "right_column": "id"},
    {"source": "core_erp", "left_table": "hr_employees", "left_column": "organization_id", "right_table": "core_organizations", "right_column": "id"},
    {"source": "core_erp", "left_table": "core_commission_salespersons", "left_column": "party_id", "right_table": "core_parties", "right_column": "id"},
    {"source": "core_erp", "left_table": "finance_bank_accounts", "left_column": "organization_id", "right_table": "core_organizations", "right_column": "id"},
    {"source": "core_erp", "left_table": "sales_returns", "left_column": "party_id", "right_table": "core_parties", "right_column": "id"},
    {"source": "core_erp", "left_table": "sales_return_lines", "left_column": "return_id", "right_table": "sales_returns", "right_column": "id"},
    {"source": "core_erp", "left_table": "sales_return_lines", "left_column": "item_id", "right_table": "inventory_items", "right_column": "id"},
]

# 2. COLUMN SYNONYM & HALLUCINATION REPAIR MAP
# Maps typical LLM guesses to the real physical column in that table.
COLUMN_SYNONYMS = {
    "core_parties": {
        "name": "first_name",
        "party_name": "first_name",
        "customer_name": "first_name",
        "supplier_name": "first_name",
        "full_name": "first_name",
        "contact_name": "first_name",
    },
    "core_warehouses": {
        "warehouse_name": "name",
        "warehouse_code": "code",
    },
    "inventory_items": {
        "item_name": "name",
        "product_name": "name",
        "item_code": "sku",
        "title": "name",
    },
    "sales_orders": {
        "customer_id": "party_id",
        "total": "grand_total",
        "amount": "grand_total",
        "total_amount": "grand_total",
        "order_total": "grand_total",
    },
    "procurement_purchase_orders": {
        "supplier_id": "party_id",
        "vendor_id": "party_id",
        "total": "grand_total",
        "amount": "grand_total",
        "total_amount": "grand_total",
        "order_total": "grand_total",
    },
    "finance_invoices": {
        "customer_id": "party_id",
        "supplier_id": "party_id",
        "vendor_id": "party_id",
        "total": "grand_total",
        "amount": "grand_total",
        "total_amount": "grand_total",
        "balance": "amount_due",
        "unpaid_amount": "amount_due",
        "outstanding": "amount_due",
        "outstanding_amount": "amount_due",
    },
    "inventory_stock_balances": {
        "quantity": "qty_available",
        "stock": "qty_available",
        "stock_quantity": "qty_available",
        "available_stock": "qty_available",
        "available_quantity": "qty_available",
        "on_hand": "qty_on_hand",
        "on_hand_stock": "qty_on_hand",
        "on_hand_quantity": "qty_on_hand",
    },
}

# 3. SEMANTIC BUSINESS CONCEPT DEFINITIONS FOR PROMPT INJECTION
SEMANTIC_CONCEPT_GUIDE = """AUTHORITATIVE ERP BUSINESS ENTITY & SCHEMA CONCEPTS:
- Customers: In `core_parties` with filter `type='customer'`. Display name is `first_name` (or `first_name` + `last_name`). `core_parties` has NO `name` column.
- Suppliers / Vendors: In `core_parties` with filter `type='supplier'`. Display name is `first_name` (or `first_name` + `last_name`). `core_parties` has NO `name` column.
- Invoices & Bills:
  * Supplier Bills (Accounts Payable / AP): `finance_invoices` with `type='ap'`. For unpaid/outstanding, filter `amount_due > 0` (or `status != 'paid'`). Join `core_parties` on `finance_invoices.party_id = core_parties.id`.
  * Customer Invoices (Accounts Receivable / AR): `finance_invoices` with `type='ar'`. For unpaid/outstanding, filter `amount_due > 0` (or `status != 'paid'`). Join `core_parties` on `finance_invoices.party_id = core_parties.id`.
  * Do NOT query `procurement_supplier_bills` for tenant bills; all operational bills/invoices reside in `finance_invoices`.
- Product Demand & Sales Velocity:
  * Measure demand from customer sales orders: base table `sales_order_lines` joined to `sales_orders` and `inventory_items`.
  * Order by `SUM(sales_order_lines.quantity) DESC`. Do NOT query `manufacturing_demands` for product sales demand.
- Physical Stock & Inventory Balances:
  * Table: `inventory_stock_balances` (`qty_available`, `qty_on_hand`) joined to `inventory_items` and `core_warehouses`.
- Minimum Stock & Replenishment:
  * Table: `inventory_item_replenishment_rules` (`min_stock_level`).
  * When comparing stock < minimum, use LEFT JOIN and `COALESCE(inventory_item_replenishment_rules.min_stock_level, 0)`.
- Unsold Catalog Items:
  * Base table `inventory_items` LEFT JOIN `sales_order_lines` ON `sales_order_lines.item_id = inventory_items.id` WHERE `sales_order_lines.id IS NULL` and `inventory_items.status = 'active'`.
"""

# 4. CONCEPT EXPANSION KEYWORDS FOR SMART TABLE RETRIEVAL
CONCEPT_KEYWORD_EXPANSIONS = {
    # Profit, Margins, Cost & Pricing
    "profit": ["sales", "orders", "lines", "items", "unit_price", "invoices"],
    "margin": ["sales", "orders", "lines", "items", "unit_price", "invoices"],
    "markup": ["sales", "orders", "lines", "items", "unit_price"],
    "cost": ["sales", "order", "lines", "items", "purchase", "orders"],
    "price": ["items", "sales", "order", "lines", "price", "lists"],
    # Demand, Popularity & Velocity
    "demand": ["sales", "orders", "lines", "items", "quantity"],
    "demanded": ["sales", "orders", "lines", "items", "quantity"],
    "popular": ["sales", "orders", "lines", "items", "quantity"],
    "velocity": ["sales", "orders", "lines", "items", "quantity"],
    "bestseller": ["sales", "orders", "lines", "items", "quantity"],
    "bestsellers": ["sales", "orders", "lines", "items", "quantity"],
    "fast-moving": ["sales", "orders", "lines", "items", "quantity"],
    # Payments & Settlements
    "payment": ["invoices", "payments", "settled", "amount", "party"],
    "payments": ["invoices", "payments", "settled", "amount", "party"],
    "paid": ["invoices", "payments", "settled", "amount", "party"],
    "unpaid": ["invoices", "amount", "due", "status", "party"],
    "debt": ["invoices", "amount", "due", "party"],
    "owed": ["invoices", "amount", "due", "party"],
    # Returns & Refunds
    "return": ["returns", "sales", "items", "party"],
    "returns": ["returns", "sales", "items", "party"],
    "refund": ["returns", "invoices", "party"],
    # Employees & Sales Representatives
    "employee": ["employees", "salespersons", "parties", "organizations"],
    "employees": ["employees", "salespersons", "parties", "organizations"],
    "salesperson": ["salespersons", "employees", "sales", "orders"],
    "salespersons": ["salespersons", "employees", "sales", "orders"],
    "staff": ["employees", "users", "organizations"],
    # Inventory Batches & Expiry
    "batch": ["batches", "items", "balances"],
    "batches": ["batches", "items", "balances"],
    "expiry": ["batches", "items", "balances"],
    "expiration": ["batches", "items", "balances"],
    "lot": ["batches", "items", "balances"],
    # Stock Transfers
    "transfer": ["transfers", "balances", "warehouses", "items"],
    "transfers": ["transfers", "balances", "warehouses", "items"],
}

# Tables to strictly deprioritize/suppress from generic business queries
SYSTEM_TABLE_PREFIXES = (
    "core_printable_",
    "core_template_",
    "core_command_",
    "core_outbox_",
    "django_",
    "auth_",
)


def repair_and_heal_plan(plan: dict, schema: dict, question: str = "") -> dict:
    """Deterministically sanitize, repair, and heal an LLM-generated query plan.

    1. Corrects common column synonyms/guesses (e.g. core_parties.name -> first_name).
    2. Corrects inverted or mismatched join keys using verified schema relationships.
    3. Auto-injects missing joins for tables referenced in SELECT, FILTERS, or GROUP_BY.
    4. Drops invalid soft-delete filters on tables without a deleted_at column.
    5. Upgrades strict equality on named entities to LIKE for robust typo/substring tolerance.
    6. Removes artificial date window cutoffs on informal all-time popularity/demand requests.
    """
    if not isinstance(plan, dict):
        return plan

    repaired = copy.deepcopy(plan)
    tables = schema.get("tables", {})
    verified_edges = set(schema.get("declared_relationships", ())) | set(schema.get("application_relationships", ()))

    base_table = repaired.get("base_table")
    if not base_table or base_table not in tables:
        return repaired

    # 1. COLUMN SYNONYM NORMALIZATION
    def normalize_field(field_obj: Any):
        if not isinstance(field_obj, dict):
            return
        tbl = field_obj.get("table")
        col = field_obj.get("column")
        if tbl and col and tbl in COLUMN_SYNONYMS:
            synonyms = COLUMN_SYNONYMS[tbl]
            if col in synonyms:
                field_obj["column"] = synonyms[col]
                # If alias was missing, preserve the user-facing name as the alias
                if "alias" in field_obj and not field_obj.get("alias"):
                    field_obj["alias"] = col

        if isinstance(field_obj.get("expression"), dict):
            normalize_field(field_obj["expression"].get("left"))
            normalize_field(field_obj["expression"].get("right"))

    for item in repaired.get("select", []):
        normalize_field(item)
    for item in repaired.get("filters", []):
        normalize_field(item)
        if isinstance(item.get("value"), dict):
            normalize_field(item["value"])
    for item in repaired.get("group_by", []):
        normalize_field(item)
    for item in repaired.get("order_by", []):
        pass  # order_by uses alias

    # 2. AUTO-INJECT MISSING JOINS & FIX INVERTED JOINS
    joins = repaired.setdefault("joins", [])
    joined_tables = {base_table}
    for j in joins:
        tbl = j.get("table")
        ref = j.get("alias") or tbl
        if ref:
            joined_tables.add(ref)

    # Detect tables referenced in select, filters, group_by that are NOT joined
    referenced_tables = set()
    for item in repaired.get("select", []):
        if item.get("table"):
            referenced_tables.add(item["table"])
    for item in repaired.get("filters", []):
        if item.get("table"):
            referenced_tables.add(item["table"])
    for item in repaired.get("group_by", []):
        if item.get("table"):
            referenced_tables.add(item["table"])

    unjoined = referenced_tables - joined_tables
    for missing_table in unjoined:
        if missing_table not in tables:
            continue
        # Find a verified edge connecting missing_table to any already joined table
        found_edge = None
        for j_tbl in list(joined_tables):
            for edge in verified_edges:
                # edge is (left_table, left_col, right_table, right_col)
                if edge[0] == j_tbl and edge[2] == missing_table:
                    found_edge = (edge[0], edge[1], edge[2], edge[3])
                    break
                elif edge[2] == j_tbl and edge[0] == missing_table:
                    found_edge = (edge[2], edge[3], edge[0], edge[1])
                    break
            if found_edge:
                break

        if found_edge:
            left_tbl, left_col, right_tbl, right_col = found_edge
            joins.append({
                "table": right_tbl,
                "left_table": left_tbl,
                "left_column": left_col,
                "right_column": right_col,
                "type": "LEFT"
            })
            joined_tables.add(right_tbl)

    # Validate and repair existing joins against verified_edges
    for j in joins:
        tbl = j.get("table")
        left_tbl = j.get("left_table")
        left_col = j.get("left_column")
        right_col = j.get("right_column")

        edge = (left_tbl, left_col, tbl, right_col)
        reverse = (tbl, right_col, left_tbl, left_col)

        if edge in verified_edges:
            continue
        if reverse in verified_edges:
            # Join is inverted, but column pair matches reverse: flip to match standard direction
            continue

        # Check if there is an exact single verified edge between left_tbl and tbl
        candidates = [e for e in verified_edges if (e[0] == left_tbl and e[2] == tbl) or (e[2] == left_tbl and e[0] == tbl)]
        if len(candidates) == 1:
            cand = candidates[0]
            if cand[0] == left_tbl and cand[2] == tbl:
                j["left_column"] = cand[1]
                j["right_column"] = cand[3]
            elif cand[2] == left_tbl and cand[0] == tbl:
                j["left_column"] = cand[3]
                j["right_column"] = cand[1]

    # 3. SOFT-DELETE FILTER PRUNING
    # If a filter specifies deleted_at on a table without deleted_at, prune it cleanly
    clean_filters = []
    for f in repaired.get("filters", []):
        tbl = f.get("table")
        col = f.get("column")
        if col == "deleted_at" and tbl in tables and "deleted_at" not in tables[tbl]:
            continue
        clean_filters.append(f)
    repaired["filters"] = clean_filters

    # 4. PARTIAL TEXT MATCHING (LIKE) FOR STRING ENTITY FILTERS
    # If a filter uses '=' on name or description, upgrade to LIKE '%...%' for typo/substring tolerance
    for f in repaired.get("filters", []):
        col = f.get("column", "")
        op = (f.get("operator") or "").upper()
        val = f.get("value")
        if op == "=" and isinstance(val, str) and col in {"name", "description", "title", "remarks"} and not col.endswith("_id") and not col.endswith("_code"):
            if "%" not in val and len(val) >= 2:
                f["operator"] = "LIKE"
                f["value"] = f"%{val.strip()}%"

    # 5. REMOVE ARTIFICIAL DATE CUTOFFS ON INFORMAL POPULARITY / DEMAND QUESTIONS
    if question:
        q_lower = question.lower()
        is_informal_popularity = any(w in q_lower for w in ["hot", "demand", "demanded", "popular", "bestseller", "best-selling", "top selling", "trending"])
        has_explicit_date = any(w in q_lower for w in ["month", "year", "today", "yesterday", "week", "since", "between", "from", "last 30", "last 7", "2024", "2025", "2026", "2027"])
        if is_informal_popularity and not has_explicit_date:
            no_date_filters = []
            for f in repaired.get("filters", []):
                col = f.get("column", "")
                if col in {"order_date", "date", "created_at", "dispatch_date"} and f.get("operator") in {">=", ">", "BETWEEN"}:
                    continue
                no_date_filters.append(f)
            repaired["filters"] = no_date_filters

    return repaired

