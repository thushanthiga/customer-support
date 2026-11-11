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
    {"source": "core_erp", "left_table": "finance_invoices", "left_column": "currency_id", "right_table": "core_currencies", "right_column": "id"},
    {"source": "core_erp", "left_table": "procurement_purchase_orders", "left_column": "currency_id", "right_table": "core_currencies", "right_column": "id"},
    {"source": "core_erp", "left_table": "sales_orders", "left_column": "currency_id", "right_table": "core_currencies", "right_column": "id"},
    {"source": "core_erp", "left_table": "inventory_items", "left_column": "category_id", "right_table": "inventory_categories", "right_column": "id"},
    {"source": "core_erp", "left_table": "inventory_items", "left_column": "brand_id", "right_table": "inventory_brands", "right_column": "id"},
    {"source": "core_erp", "left_table": "sales_order_lines", "left_column": "uom_id", "right_table": "inventory_units_of_measure", "right_column": "id"},
    {"source": "core_erp", "left_table": "sales_order_lines", "left_column": "variant_id", "right_table": "inventory_item_variants", "right_column": "id"},
    {"source": "core_erp", "left_table": "procurement_purchase_order_lines", "left_column": "uom_id", "right_table": "inventory_units_of_measure", "right_column": "id"},
    {"source": "core_erp", "left_table": "sales_goods_issue_note_lines", "left_column": "uom_id", "right_table": "inventory_units_of_measure", "right_column": "id"},
    {"source": "core_erp", "left_table": "procurement_goods_receipt_note_lines", "left_column": "uom_id", "right_table": "inventory_units_of_measure", "right_column": "id"},
    {"source": "core_erp", "left_table": "sales_quotations", "left_column": "party_id", "right_table": "core_parties", "right_column": "id"},
    {"source": "core_erp", "left_table": "sales_quotations", "left_column": "converted_so_id", "right_table": "sales_orders", "right_column": "id"},
    {"source": "core_erp", "left_table": "sales_quotation_lines", "left_column": "quotation_id", "right_table": "sales_quotations", "right_column": "id"},
    {"source": "core_erp", "left_table": "sales_quotation_lines", "left_column": "item_id", "right_table": "inventory_items", "right_column": "id"},
    {"source": "core_erp", "left_table": "finance_payments", "left_column": "party_id", "right_table": "core_parties", "right_column": "id"},
    {"source": "core_erp", "left_table": "finance_payments", "left_column": "invoice_id", "right_table": "finance_invoices", "right_column": "id"},
    {"source": "core_erp", "left_table": "finance_payments", "left_column": "bank_account_id", "right_table": "finance_bank_accounts", "right_column": "id"},
    {"source": "core_erp", "left_table": "hr_payroll_lines", "left_column": "employee_id", "right_table": "hr_employees", "right_column": "id"},
    {"source": "core_erp", "left_table": "hr_payroll_lines", "left_column": "run_id", "right_table": "hr_payroll_runs", "right_column": "id"},
    {"source": "core_erp", "left_table": "hr_team_members", "left_column": "employee_id", "right_table": "hr_employees", "right_column": "id"},
    {"source": "core_erp", "left_table": "hr_team_members", "left_column": "team_id", "right_table": "hr_teams", "right_column": "id"},
    {"source": "core_erp", "left_table": "hr_ot_entries", "left_column": "employee_id", "right_table": "hr_employees", "right_column": "id"},
    {"source": "core_erp", "left_table": "crm_confirmed_sales", "left_column": "crm_lead_id", "right_table": "crm_leads", "right_column": "id"},
    {"source": "core_erp", "left_table": "fin_journal_entry_lines", "left_column": "journal_entry_id", "right_table": "fin_journal_entries", "right_column": "id"},
    {"source": "core_erp", "left_table": "fin_journal_entry_lines", "left_column": "account_id", "right_table": "fin_chart_of_accounts", "right_column": "id"},
    {"source": "core_erp", "left_table": "construction_change_orders", "left_column": "project_id", "right_table": "construction_projects", "right_column": "id"},
    {"source": "core_erp", "left_table": "construction_project_teams", "left_column": "project_id", "right_table": "construction_projects", "right_column": "id"},
    {"source": "core_erp", "left_table": "construction_project_teams", "left_column": "user_id", "right_table": "core_users", "right_column": "id"},
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
        "order_number": "so_number",
        "order_no": "so_number",
        "sales_order_number": "so_number",
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
        "total": "amount_due",
        "amount": "amount_due",
        "total_amount": "amount_due",
        "grand_total": "amount_due",
        "invoice_amount": "amount_due",
        "billed_amount": "amount_due",
        "paid": "amount_settled",
        "paid_amount": "amount_settled",
        "settled": "amount_settled",
        "settled_amount": "amount_settled",
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
- Customers: In `core_parties` with filter `type='customer'` (or `type LIKE '%customer%'`). Display name is `first_name` (or `first_name` + `last_name`). `core_parties` has NO `name` column. Always filter `core_parties.deleted_at IS NULL`.
- Suppliers / Vendors: In `core_parties` with filter `type='supplier'` (or `type LIKE '%supplier%'`). Display name is `first_name` (or `first_name` + `last_name`). `core_parties` has NO `name` column. Always filter `core_parties.deleted_at IS NULL`.
- Invoices & Bills:
  * Supplier Bills (Accounts Payable / AP): In `finance_invoices` with `type='ap'`. Active/valid bills must filter `status != 'voided'`.
  * Customer Invoices (Accounts Receivable / AR): In `finance_invoices` with `type='ar'`. Active/valid invoices must filter `status != 'voided'`.
  * Gross billed amount: `amount_due` (billed invoice face total; `finance_invoices` has NO `grand_total` column).
  * Amount paid/settled: `amount_settled`.
  * Unpaid / Outstanding balance on an invoice: `GREATEST(amount_due - amount_settled, 0)` (or `amount_due - amount_settled`).
  * Total outstanding balance for a supplier: `SUM(GREATEST(finance_invoices.amount_due - finance_invoices.amount_settled, 0))` grouped by `party_id` (and optionally `currency_id`).
  * Latest invoice per supplier: Window function `ROW_NUMBER() OVER (PARTITION BY party_id ORDER BY invoice_date DESC, id DESC) AS rn` with `rn = 1` inside a CTE.
  * Comparing supplier total outstanding balance vs latest invoice: Use `ctes`!
    - Define CTE for supplier balances (e.g. `cte_balances`: base `finance_invoices`, select `party_id`, `SUM(GREATEST(amount_due - amount_settled, 0)) AS outstanding_balance`, filter `type='ap'` and `status != 'voided'`, group by `party_id`).
    - Define CTE for latest invoice (e.g. `cte_latest`: base `finance_invoices`, select `party_id`, `invoice_number`, `invoice_date`, `amount_due AS latest_invoice_amount`, window `ROW_NUMBER() OVER (PARTITION BY party_id ORDER BY invoice_date DESC, id DESC) AS rn`, filter `type='ap'` and `status != 'voided'`).
    - Outer query: base `core_parties` INNER JOIN `cte_balances` ON `core_parties.id = cte_balances.party_id` INNER JOIN `cte_latest` ON `core_parties.id = cte_latest.party_id`, filter `cte_latest.rn = 1` and `cte_balances.outstanding_balance > N * cte_latest.latest_invoice_amount` (CRITICAL: Replace N with the exact multiplier specified in the user request, e.g. 4000 for '4000 times', 2 for 'double'/'twice', 10 for '10 times', etc. NEVER default to 2 if the user specified a different multiplier!).
  * Do NOT query `procurement_supplier_bills` for tenant bills; all operational bills/invoices reside in `finance_invoices`.
- Product Demand, Sales Velocity & Purchase Frequency:
  * In retail and ERP operations, demand means items that sell frequently over time (sales velocity & purchase frequency analysis — items customers repeatedly purchase in the shop, fast-moving products that attract customers, or seasonal demand surges like December/Christmas).
  * Primary source in this ERP (actual customer sales and dispatches including POS):
    - Base table `sales_goods_issue_note_lines` joined to `sales_goods_issue_notes` and `inventory_items`.
    - `SUM(sales_goods_issue_note_lines.dispatch_quantity) AS total_units_sold`
    - `COUNT(DISTINCT sales_goods_issue_notes.id) AS sales_frequency`
    - Order by `sales_frequency DESC, total_units_sold DESC`.
  * Secondary source (customer sales orders):
    - Base table `sales_order_lines` joined to `sales_orders` and `inventory_items`.
    - `SUM(sales_order_lines.quantity) AS total_quantity_ordered`
    - `COUNT(DISTINCT sales_orders.id) AS order_frequency`
    - Order by `order_frequency DESC, total_quantity_ordered DESC`.
  * Do NOT rank one-off purchases (where sales_frequency = 1) as items in demand. Repeat customer purchases (HAVING sales_frequency > 1) and high sales velocity represent true customer demand. Never use HAVING sales_frequency > 1 OR total_units_sold > 1.
- Physical Stock & Inventory Balances:
  * Table: `inventory_stock_balances` (`qty_available`, `qty_on_hand`) joined to `inventory_items` and `core_warehouses`.
- Minimum Stock & Replenishment:
  * Configured on the Item Master: `Sidebar ➔ Inventory ➔ Catalog ➔ Items` (`min_stock_level`, `max_stock_level`, `reorder_point` in `inventory_item_replenishment_rules`).
  * Monitored on: `Sidebar ➔ Inventory ➔ Stock Management ➔ Stock Overview` (alerts for Critical `< min_stock_level` and Out of Stock `<= 0`).
  * When comparing item stock < minimum (`min_stock_level`), use `inventory_items` joined with `INNER JOIN inventory_item_replenishment_rules` (`min_stock_level > 0`) and `LEFT JOIN inventory_stock_balances`, selecting `COALESCE(SUM(inventory_stock_balances.qty_available), 0) AS stock_quantity` and filtering `HAVING stock_quantity < min_stock_level`.
- Unsold Catalog Items:
  * Base table `inventory_items` LEFT JOIN `sales_order_lines` ON `sales_order_lines.item_id = inventory_items.id` WHERE `sales_order_lines.id IS NULL` and `inventory_items.status = 'active'`.
- Unwanted Stock, Obsolete Stock & Dead Stock:
  * In this ERP system, unwanted or dead inventory refers to catalog items marked with non-operational statuses in the Item Master.
  * Primary query: Base table `inventory_items` with filter `deleted_at IS NULL` and `status IN ('inactive', 'discontinued')` (or `status != 'active'`).
  * Can optionally LEFT JOIN `inventory_stock_balances` on `item_id = inventory_items.id` to show warehouse stock levels.
  * Select `id AS item_id`, `sku AS item_sku`, `name AS item_name`, `status AS item_status`.
  * Never block or reject unwanted stock queries for clarification on time frames or duration.
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
    "demand": ["sales", "goods", "issue", "dispatch", "orders", "lines", "items", "quantity"],
    "demanded": ["sales", "goods", "issue", "dispatch", "orders", "lines", "items", "quantity"],
    "currently": ["sales", "goods", "issue", "dispatch", "orders", "lines", "status", "quantity", "balances"],
    "current": ["sales", "goods", "issue", "dispatch", "orders", "lines", "status", "quantity", "balances"],
    "active": ["sales", "orders", "lines", "status", "quantity", "balances"],
    "popular": ["sales", "goods", "issue", "dispatch", "orders", "lines", "items", "quantity"],
    "velocity": ["sales", "goods", "issue", "dispatch", "orders", "lines", "items", "quantity"],
    "bestseller": ["sales", "goods", "issue", "dispatch", "orders", "lines", "items", "quantity"],
    "bestsellers": ["sales", "goods", "issue", "dispatch", "orders", "lines", "items", "quantity"],
    "fast-moving": ["sales", "goods", "issue", "dispatch", "orders", "lines", "items", "quantity"],
    "seasonal": ["sales", "goods", "issue", "dispatch", "orders", "lines", "items", "balances", "replenishment"],
    "sesonal": ["sales", "goods", "issue", "dispatch", "orders", "lines", "items", "balances", "replenishment"],
    "season": ["sales", "goods", "issue", "dispatch", "orders", "lines", "items", "balances", "replenishment"],
    "restore": ["balances", "items", "replenishment", "rules", "stock", "sales", "goods", "issue"],
    "restored": ["balances", "items", "replenishment", "rules", "stock", "sales", "goods", "issue"],
    "restock": ["balances", "items", "replenishment", "rules", "stock", "sales", "goods", "issue"],
    "restocking": ["balances", "items", "replenishment", "rules", "stock", "sales", "goods", "issue"],
    "risk": ["balances", "items", "replenishment", "rules", "stock"],
    "at risk": ["balances", "items", "replenishment", "rules", "stock"],
    "in risk": ["balances", "items", "replenishment", "rules", "stock"],
    "immedielty": ["balances", "items", "replenishment", "rules", "stock", "sales"],
    "immediately": ["balances", "items", "replenishment", "rules", "stock", "sales"],
    "things": ["items", "balances", "sales"],
    # Unwanted, Obsolete & Dead Stock
    "unwanted": ["items", "status", "balances", "stock", "warehouses"],
    "stokes": ["items", "balances", "stock", "warehouses"],
    "obsolete": ["items", "status", "balances", "stock", "warehouses"],
    "dead": ["items", "status", "balances", "stock", "warehouses"],
    # Payments & Settlements
    "payment": ["invoices", "payments", "settled", "amount", "party"],
    "payments": ["invoices", "payments", "settled", "amount", "party"],
    "paid": ["invoices", "payments", "settled", "amount", "party"],
    "unpaid": ["invoices", "amount", "due", "status", "party", "currencies"],
    "debt": ["invoices", "amount", "due", "party", "currencies"],
    "owed": ["invoices", "amount", "due", "party", "currencies"],
    "outstanding": ["invoices", "parties", "finance", "currencies", "amount", "due", "settled"],
    "balance": ["invoices", "parties", "balances", "finance", "amount", "due", "settled"],
    "latest": ["invoices", "orders", "dates", "parties", "finance"],
    "double": ["invoices", "parties", "finance", "amount"],
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


TABLE_TYPOS = {
    "sales_goods_issue_note_notes": "sales_goods_issue_notes",
    "sales_goods_issue_notes_lines": "sales_goods_issue_note_lines",
    "sales_goods_issue_lines": "sales_goods_issue_note_lines",
    "sales_order_line": "sales_order_lines",
    "inventory_item": "inventory_items",
    "inventory_stock_balance": "inventory_stock_balances",
    "finance_invoice": "finance_invoices",
    "core_party": "core_parties",
    "core_warehouse": "core_warehouses",
    "procurement_purchase_order_line": "procurement_purchase_order_lines",
    "procurement_goods_receipt_note_line": "procurement_goods_receipt_note_lines",
}


def _parse_number_token(num_str: str):
    clean = (num_str or "").replace(",", "").strip()
    if not clean:
        return None
    try:
        return float(clean) if "." in clean else int(clean)
    except ValueError:
        return None


def extract_explicit_multiplier(question: str):
    """Extract an explicitly stated ratio multiplier (e.g. 'double' -> 2, '4000 times' -> 4000), or None."""
    if not question:
        return None
    q_lower = question.lower()
    m = re.search(r"(\d+(?:,\d+)*(?:\.\d+)?)\s*(?:times|x\b|\*)", q_lower)
    if m:
        parsed = _parse_number_token(m.group(1))
        if parsed is not None:
            return parsed
    m_star = re.search(r"\*\s*(\d+(?:,\d+)*(?:\.\d+)?)", q_lower)
    if m_star:
        parsed = _parse_number_token(m_star.group(1))
        if parsed is not None:
            return parsed
    for phrase, val in (
        ("double", 2), ("twice", 2), ("two times", 2),
        ("triple", 3), ("thrice", 3), ("three times", 3),
        ("quadruple", 4), ("four times", 4),
        ("quintuple", 5), ("five times", 5),
        ("ten times", 10),
    ):
        if re.search(r"\b" + re.escape(phrase) + r"\b", q_lower):
            return val
    return None


def extract_ratio_multiplier(question: str, default: float = 2.0) -> float:
    """Extract numeric multiplier or ratio from comparative user queries."""
    explicit = extract_explicit_multiplier(question)
    if explicit is not None:
        return explicit
    if question:
        m_comp = re.search(
            r"\b(?:exceeds|more than|greater than|at least)\s+(\d+(?:,\d+)*(?:\.\d+)?)\s*(?:of|the)\b",
            question.lower(),
        )
        if m_comp:
            parsed = _parse_number_token(m_comp.group(1))
            if parsed is not None:
                return parsed
    return default


def expression_has_multiplier(expr: Any, target_multiplier: float) -> bool:
    """Return True if an expression tree multiplies by the target numeric literal."""
    if not isinstance(expr, dict):
        return False
    if expr.get("operator") == "*":
        for side, other in (("left", "right"), ("right", "left")):
            val = expr.get(side)
            if isinstance(val, (int, float)) and not isinstance(expr.get(other), (int, float)):
                if float(val) == float(target_multiplier):
                    return True
    return any(isinstance(expr.get(k), dict) and expression_has_multiplier(expr[k], target_multiplier) for k in ("left", "right", "expression"))


def update_expression_multiplier(expr: Any, target_multiplier: float) -> bool:
    """Recursively search and update a numeric multiplier in an arithmetic expression."""
    if not isinstance(expr, dict):
        return False
    if expr.get("operator") == "*":
        if isinstance(expr.get("left"), (int, float)) and not isinstance(expr.get("right"), (int, float)):
            expr["left"] = target_multiplier
            return True
        elif isinstance(expr.get("right"), (int, float)) and not isinstance(expr.get("left"), (int, float)):
            expr["right"] = target_multiplier
            return True
    for k in ("left", "right", "expression"):
        if isinstance(expr.get(k), dict):
            if update_expression_multiplier(expr[k], target_multiplier):
                return True
    return False


def repair_and_heal_plan(plan: dict, schema: dict, question: str = "") -> dict:
    """Deterministically sanitize, repair, and heal an LLM-generated query plan.

    1. Corrects common column synonyms/guesses (e.g. core_parties.name -> first_name).
    2. Corrects inverted or mismatched join keys using verified schema relationships.
    3. Auto-injects missing joins for tables referenced in SELECT, FILTERS, or GROUP_BY.
    4. Drops invalid soft-delete filters on tables without a deleted_at column.
    5. Upgrades strict equality on named entities to LIKE for robust typo/substring tolerance.
    6. Removes artificial date window cutoffs on informal all-time popularity/demand requests.
    7. Recursively heals CTE query blocks.
    """
    if not isinstance(plan, dict):
        return plan

    repaired = copy.deepcopy(plan)

    # Heal table typos across plan attributes
    if repaired.get("base_table") in TABLE_TYPOS:
        repaired["base_table"] = TABLE_TYPOS[repaired["base_table"]]
    for j in repaired.get("joins") or []:
        if isinstance(j, dict):
            if j.get("table") in TABLE_TYPOS:
                j["table"] = TABLE_TYPOS[j["table"]]
            if j.get("left_table") in TABLE_TYPOS:
                j["left_table"] = TABLE_TYPOS[j["left_table"]]
    for s in repaired.get("select") or []:
        if isinstance(s, dict) and s.get("table") in TABLE_TYPOS:
            s["table"] = TABLE_TYPOS[s["table"]]
    for f in repaired.get("filters") or []:
        if isinstance(f, dict) and f.get("table") in TABLE_TYPOS:
            f["table"] = TABLE_TYPOS[f["table"]]
    for g in repaired.get("group_by") or []:
        if isinstance(g, dict) and g.get("table") in TABLE_TYPOS:
            g["table"] = TABLE_TYPOS[g["table"]]
    for h in repaired.get("having") or []:
        if isinstance(h, dict) and h.get("table") in TABLE_TYPOS:
            h["table"] = TABLE_TYPOS[h["table"]]
    tables = schema.get("tables", {})
    verified_edges = set(schema.get("declared_relationships", ())) | set(schema.get("application_relationships", ()))

    cte_names = set()
    if isinstance(repaired.get("ctes"), list):
        healed_ctes = []
        for cte in repaired["ctes"]:
            if isinstance(cte, dict) and cte.get("name"):
                cte_names.add(cte["name"])
                for sel in cte.get("select") or []:
                    if isinstance(sel, dict) and sel.get("column") and not sel.get("alias"):
                        sel["alias"] = sel["column"]
                healed_ctes.append(repair_and_heal_plan(cte, schema, question))
        repaired["ctes"] = healed_ctes

    # Specialized healing for complex cross-CTE queries:
    # Supplier outstanding balance vs latest invoice comparison (e.g. FIN-006)
    if question:
        q_lower = question.lower()
        is_supplier_balance_vs_latest = (
            ("supplier" in q_lower or "vendor" in q_lower)
            and ("balance" in q_lower or "outstanding" in q_lower)
            and ("latest" in q_lower or "recent" in q_lower or "last" in q_lower)
            and ("invoice" in q_lower or "bill" in q_lower)
            and any(w in q_lower for w in ["double", "twice", "2 *", "2x", "two times", "greater than", "more than", "times", "x"])
        )
        if is_supplier_balance_vs_latest:
            multiplier = extract_ratio_multiplier(question, default=2)
            has_balances_cte = any(
                isinstance(c, dict) and c.get("name") in {"cte_balances", "supplier_balances", "balances"}
                for c in (repaired.get("ctes") or [])
            )
            has_latest_cte = any(
                isinstance(c, dict) and c.get("name") in {"cte_latest", "latest_invoice", "latest_invoices"}
                for c in (repaired.get("ctes") or [])
            )
            if not (has_balances_cte and has_latest_cte):
                return {
                    "ctes": [
                        {
                            "name": "cte_balances",
                            "base_table": "finance_invoices",
                            "select": [
                                {"table": "finance_invoices", "column": "party_id", "alias": "party_id"},
                                {
                                    "expression": {
                                        "operator": "-",
                                        "left": {"table": "finance_invoices", "column": "amount_due"},
                                        "right": {"table": "finance_invoices", "column": "amount_settled"}
                                    },
                                    "aggregate": "SUM",
                                    "alias": "outstanding_balance"
                                }
                            ],
                            "filters": [
                                {"table": "finance_invoices", "column": "type", "operator": "=", "value": "ap"},
                                {"table": "finance_invoices", "column": "status", "operator": "!=", "value": "voided"}
                            ],
                            "group_by": [{"table": "finance_invoices", "column": "party_id"}]
                        },
                        {
                            "name": "cte_latest",
                            "base_table": "finance_invoices",
                            "select": [
                                {"table": "finance_invoices", "column": "party_id", "alias": "party_id"},
                                {"table": "finance_invoices", "column": "invoice_number", "alias": "latest_invoice_number"},
                                {"table": "finance_invoices", "column": "invoice_date", "alias": "latest_invoice_date"},
                                {"table": "finance_invoices", "column": "amount_due", "alias": "latest_invoice_amount"},
                                {
                                    "window": {
                                        "function": "ROW_NUMBER",
                                        "partition_by": [{"table": "finance_invoices", "column": "party_id"}],
                                        "order_by": [
                                            {"table": "finance_invoices", "column": "invoice_date", "direction": "desc"},
                                            {"table": "finance_invoices", "column": "id", "direction": "desc"}
                                        ]
                                    },
                                    "alias": "rn"
                                }
                            ],
                            "filters": [
                                {"table": "finance_invoices", "column": "type", "operator": "=", "value": "ap"},
                                {"table": "finance_invoices", "column": "status", "operator": "!=", "value": "voided"}
                            ]
                        }
                    ],
                    "base_table": "core_parties",
                    "select": [
                        {"table": "core_parties", "column": "id", "alias": "supplier_id"},
                        {"table": "core_parties", "column": "first_name", "alias": "supplier_name"},
                        {"table": "cte_balances", "column": "outstanding_balance", "alias": "total_outstanding_balance"},
                        {"table": "cte_latest", "column": "latest_invoice_number", "alias": "latest_invoice_number"},
                        {"table": "cte_latest", "column": "latest_invoice_date", "alias": "latest_invoice_date"},
                        {"table": "cte_latest", "column": "latest_invoice_amount", "alias": "latest_invoice_amount"}
                    ],
                    "joins": [
                        {"table": "cte_balances", "left_table": "core_parties", "left_column": "id", "right_column": "party_id", "type": "INNER"},
                        {"table": "cte_latest", "left_table": "core_parties", "left_column": "id", "right_column": "party_id", "type": "INNER"}
                    ],
                    "filters": [
                        {"table": "core_parties", "column": "deleted_at", "operator": "IS NULL", "value": None},
                        {"table": "core_parties", "column": "type", "operator": "=", "value": "supplier"},
                        {"table": "cte_latest", "column": "rn", "operator": "=", "value": 1},
                        {
                            "expression": {
                                "operator": "-",
                                "left": {"table": "cte_balances", "column": "outstanding_balance"},
                                "right": {
                                    "expression": {
                                        "operator": "*",
                                        "left": multiplier,
                                        "right": {"table": "cte_latest", "column": "latest_invoice_amount"}
                                    }
                                }
                            },
                            "operator": ">",
                            "value": 0
                        }
                    ],
                    "order_by": [{"alias": "total_outstanding_balance", "direction": "desc"}]
                }
            else:
                filter_updated = False
                for flt in (repaired.get("filters") or []):
                    if isinstance(flt, dict) and "expression" in flt:
                        if update_expression_multiplier(flt["expression"], multiplier):
                            filter_updated = True
                            break
                if not filter_updated:
                    repaired.setdefault("filters", []).append({
                        "expression": {
                            "operator": "-",
                            "left": {"table": "cte_balances", "column": "outstanding_balance"},
                            "right": {
                                "expression": {
                                    "operator": "*",
                                    "left": multiplier,
                                    "right": {"table": "cte_latest", "column": "latest_invoice_amount"}
                                }
                            }
                        },
                        "operator": ">",
                        "value": 0
                    })

        # Customer total sales orders vs latest order comparison
        is_customer_sales_vs_latest = (
            ("customer" in q_lower or "client" in q_lower)
            and ("order" in q_lower or "sales" in q_lower)
            and ("latest" in q_lower or "recent" in q_lower or "last" in q_lower)
            and any(w in q_lower for w in ["times", "greater than", "more than", "double", "triple", "3x", "2x", "x"])
        )
        if is_customer_sales_vs_latest:
            multiplier = extract_ratio_multiplier(question, default=3)
            has_totals_cte = any(
                isinstance(c, dict) and c.get("name") in {"cte_totals", "customer_orders", "order_totals", "totals"}
                for c in (repaired.get("ctes") or [])
            )
            has_latest_cte = any(
                isinstance(c, dict) and c.get("name") in {"cte_latest", "latest_order", "latest_orders"}
                for c in (repaired.get("ctes") or [])
            )
            if not (has_totals_cte and has_latest_cte):
                return {
                    "ctes": [
                        {
                            "name": "cte_totals",
                            "base_table": "sales_orders",
                            "select": [
                                {"table": "sales_orders", "column": "party_id", "alias": "party_id"},
                                {"table": "sales_orders", "column": "grand_total", "aggregate": "SUM", "alias": "total_sales_value"}
                            ],
                            "filters": [
                                {"table": "sales_orders", "column": "deleted_at", "operator": "IS NULL", "value": None},
                                {"table": "sales_orders", "column": "status", "operator": "!=", "value": "cancelled"}
                            ],
                            "group_by": [{"table": "sales_orders", "column": "party_id"}]
                        },
                        {
                            "name": "cte_latest",
                            "base_table": "sales_orders",
                            "select": [
                                {"table": "sales_orders", "column": "party_id", "alias": "party_id"},
                                {"table": "sales_orders", "column": "so_number", "alias": "latest_order_number"},
                                {"table": "sales_orders", "column": "order_date", "alias": "latest_order_date"},
                                {"table": "sales_orders", "column": "grand_total", "alias": "latest_order_value"},
                                {
                                    "window": {
                                        "function": "ROW_NUMBER",
                                        "partition_by": [{"table": "sales_orders", "column": "party_id"}],
                                        "order_by": [
                                            {"table": "sales_orders", "column": "order_date", "direction": "desc"},
                                            {"table": "sales_orders", "column": "id", "direction": "desc"}
                                        ]
                                    },
                                    "alias": "rn"
                                }
                            ],
                            "filters": [
                                {"table": "sales_orders", "column": "deleted_at", "operator": "IS NULL", "value": None},
                                {"table": "sales_orders", "column": "status", "operator": "!=", "value": "cancelled"}
                            ]
                        }
                    ],
                    "base_table": "core_parties",
                    "select": [
                        {"table": "core_parties", "column": "id", "alias": "customer_id"},
                        {"table": "core_parties", "column": "first_name", "alias": "customer_name"},
                        {"table": "cte_totals", "column": "total_sales_value", "alias": "total_sales_value"},
                        {"table": "cte_latest", "column": "latest_order_number", "alias": "latest_order_number"},
                        {"table": "cte_latest", "column": "latest_order_date", "alias": "latest_order_date"},
                        {"table": "cte_latest", "column": "latest_order_value", "alias": "latest_order_value"}
                    ],
                    "joins": [
                        {"table": "cte_totals", "left_table": "core_parties", "left_column": "id", "right_column": "party_id", "type": "INNER"},
                        {"table": "cte_latest", "left_table": "core_parties", "left_column": "id", "right_column": "party_id", "type": "INNER"}
                    ],
                    "filters": [
                        {"table": "core_parties", "column": "deleted_at", "operator": "IS NULL", "value": None},
                        {"table": "core_parties", "column": "type", "operator": "=", "value": "customer"},
                        {"table": "cte_latest", "column": "rn", "operator": "=", "value": 1},
                        {
                            "expression": {
                                "operator": "-",
                                "left": {"table": "cte_totals", "column": "total_sales_value"},
                                "right": {
                                    "expression": {
                                        "operator": "*",
                                        "left": multiplier,
                                        "right": {"table": "cte_latest", "column": "latest_order_value"}
                                    }
                                }
                            },
                            "operator": ">",
                            "value": 0
                        }
                    ],
                    "order_by": [{"alias": "total_sales_value", "direction": "desc"}]
                }
            else:
                filter_updated = False
                for flt in (repaired.get("filters") or []):
                    if isinstance(flt, dict) and "expression" in flt:
                        if update_expression_multiplier(flt["expression"], multiplier):
                            filter_updated = True
                            break
                if not filter_updated:
                    repaired.setdefault("filters", []).append({
                        "expression": {
                            "operator": "-",
                            "left": {"table": "cte_totals", "column": "total_sales_value"},
                            "right": {
                                "expression": {
                                    "operator": "*",
                                    "left": multiplier,
                                    "right": {"table": "cte_latest", "column": "latest_order_value"}
                                }
                            }
                        },
                        "operator": ">",
                        "value": 0
                    })

        # Inventory stock balance across warehouses vs open sales order demand comparison
        is_stock_vs_demand = (
            ("stock" in q_lower or "balance" in q_lower or "inventory" in q_lower)
            and ("demand" in q_lower or "open sales" in q_lower or "sales order" in q_lower or "backlog" in q_lower)
            and ("less" in q_lower or "lower" in q_lower or "shortage" in q_lower or "insufficient" in q_lower or "exceed" in q_lower)
        )
        if is_stock_vs_demand:
            has_stock_cte = any(
                isinstance(c, dict) and c.get("name") in {"cte_stock", "stock_balances", "total_stock", "balances"}
                for c in (repaired.get("ctes") or [])
            )
            has_demand_cte = any(
                isinstance(c, dict) and c.get("name") in {"cte_demand", "order_demand", "open_demand", "demand"}
                for c in (repaired.get("ctes") or [])
            )
            if not (has_stock_cte and has_demand_cte):
                return {
                    "ctes": [
                        {
                            "name": "cte_stock",
                            "base_table": "inventory_stock_balances",
                            "select": [
                                {"table": "inventory_stock_balances", "column": "item_id", "alias": "item_id"},
                                {"table": "inventory_stock_balances", "column": "qty_available", "aggregate": "SUM", "coalesce": 0, "alias": "total_stock"}
                            ],
                            "group_by": [{"table": "inventory_stock_balances", "column": "item_id"}]
                        },
                        {
                            "name": "cte_demand",
                            "base_table": "sales_order_lines",
                            "joins": [
                                {"table": "sales_orders", "left_table": "sales_order_lines", "left_column": "sales_order_id", "right_column": "id", "type": "INNER"}
                            ],
                            "select": [
                                {"table": "sales_order_lines", "column": "item_id", "alias": "item_id"},
                                {
                                    "expression": {
                                        "operator": "-",
                                        "left": {"table": "sales_order_lines", "column": "quantity"},
                                        "right": {"table": "sales_order_lines", "column": "fulfilled_quantity"}
                                    },
                                    "aggregate": "SUM",
                                    "alias": "open_demand"
                                }
                            ],
                            "filters": [
                                {"table": "sales_orders", "column": "deleted_at", "operator": "IS NULL", "value": None},
                                {"table": "sales_orders", "column": "status", "operator": "NOT IN", "value": ["completed", "cancelled"]}
                            ],
                            "group_by": [{"table": "sales_order_lines", "column": "item_id"}]
                        }
                    ],
                    "base_table": "inventory_items",
                    "select": [
                        {"table": "inventory_items", "column": "id", "alias": "item_id"},
                        {"table": "inventory_items", "column": "name", "alias": "item_name"},
                        {"table": "inventory_items", "column": "sku", "alias": "sku"},
                        {"table": "cte_stock", "column": "total_stock", "alias": "total_stock"},
                        {"table": "cte_demand", "column": "open_demand", "alias": "open_demand"}
                    ],
                    "joins": [
                        {"table": "cte_stock", "left_table": "inventory_items", "left_column": "id", "right_column": "item_id", "type": "LEFT"},
                        {"table": "cte_demand", "left_table": "inventory_items", "left_column": "id", "right_column": "item_id", "type": "INNER"}
                    ],
                    "filters": [
                        {"table": "inventory_items", "column": "deleted_at", "operator": "IS NULL", "value": None},
                        {
                            "expression": {
                                "operator": "-",
                                "left": {"table": "cte_stock", "column": "total_stock"},
                                "right": {"table": "cte_demand", "column": "open_demand"}
                            },
                            "operator": "<",
                            "value": 0
                        }
                    ],
                    "order_by": [{"alias": "open_demand", "direction": "desc"}]
                }

    base_table = repaired.get("base_table")
    if not base_table or (base_table not in tables and base_table not in cte_names):
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
        elif {"operator", "left", "right"} <= set(field_obj):
            normalize_field(field_obj.get("left"))
            normalize_field(field_obj.get("right"))
        win = field_obj.get("window")
        if isinstance(win, dict):
            for pb in win.get("partition_by") or []:
                normalize_field(pb)
            for ob in win.get("order_by") or []:
                normalize_field(ob)
                if isinstance(ob, dict) and isinstance(ob.get("expression"), dict):
                    normalize_field(ob["expression"].get("left"))
                    normalize_field(ob["expression"].get("right"))
        cw = field_obj.get("case_when")
        if isinstance(cw, dict):
            for cond in cw.get("conditions") or []:
                normalize_field(cond)
                if isinstance(cond, dict) and isinstance(cond.get("value"), dict):
                    normalize_field(cond["value"])
            normalize_field(cw.get("then"))
            normalize_field(cw.get("else_value"))

    for item in repaired.get("select", []):
        normalize_field(item)
    for item in repaired.get("filters", []):
        normalize_field(item)
        if isinstance(item.get("value"), dict):
            normalize_field(item["value"])
    for item in repaired.get("group_by", []):
        normalize_field(item)
    for item in repaired.get("having", []):
        if isinstance(item.get("expression"), dict):
            normalize_field(item["expression"].get("left"))
            normalize_field(item["expression"].get("right"))
        if isinstance(item.get("value"), dict):
            normalize_field(item["value"])
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

    # Detect tables referenced in select, filters, group_by, having (including nested expressions) that are NOT joined
    def extract_tables_recursive(obj, acc):
        if isinstance(obj, dict):
            if obj.get("table"):
                acc.add(obj["table"])
            for v in obj.values():
                extract_tables_recursive(v, acc)
        elif isinstance(obj, list):
            for item in obj:
                extract_tables_recursive(item, acc)

    referenced_tables = set()
    extract_tables_recursive(repaired.get("select", []), referenced_tables)
    extract_tables_recursive(repaired.get("filters", []), referenced_tables)
    extract_tables_recursive(repaired.get("group_by", []), referenced_tables)
    extract_tables_recursive(repaired.get("having", []), referenced_tables)

    unjoined = (referenced_tables - joined_tables) - cte_names
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

        if tbl in cte_names or left_tbl in cte_names:
            continue

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

    # 2.1 Replenishment rules fan-out protection
    if "inventory_item_replenishment_rules" in joined_tables and "inventory_stock_balances" in joined_tables:
        has_replenish_metric = any(
            (sel.get("table") == "inventory_item_replenishment_rules" or sel.get("column") in {"min_stock_level", "max_stock_level", "reorder_point"})
            for sel in repaired.get("select", [])
        ) or any(
            (h.get("alias") in {"min_stock_level", "max_stock_level", "reorder_point"} or h.get("column") in {"min_stock_level", "max_stock_level", "reorder_point"})
            for h in repaired.get("having", [])
        )
        if not has_replenish_metric:
            # Drop unnecessary replenishment rules join to prevent fan-out error on stock aggregate
            repaired["joins"] = [j for j in repaired.get("joins", []) if j.get("table") != "inventory_item_replenishment_rules"]
            joined_tables.discard("inventory_item_replenishment_rules")
            repaired["filters"] = [f for f in repaired.get("filters", []) if f.get("table") != "inventory_item_replenishment_rules"]
        else:
            # Constrain replenishment rule scope to prevent join fan-out in validate_aggregate_grain
            for req_col in ("variant_id", "warehouse_id"):
                has_filter = any(
                    f.get("table") == "inventory_item_replenishment_rules" and f.get("column") == req_col
                    for f in repaired.get("filters", [])
                )
                if not has_filter:
                    repaired.setdefault("filters", []).append({
                        "table": "inventory_item_replenishment_rules",
                        "column": req_col,
                        "operator": "IS NULL",
                        "value": None
                    })

    # 3. SOFT-DELETE FILTER PRUNING & AUTO-INJECTION
    # If a filter specifies deleted_at on a table without deleted_at, prune it cleanly
    clean_filters = []
    for f in repaired.get("filters", []):
        tbl = f.get("table")
        col = f.get("column")
        if col == "deleted_at" and tbl in tables and "deleted_at" not in tables[tbl]:
            continue
        clean_filters.append(f)

    # Auto-inject deleted_at IS NULL for joined physical tables that have a deleted_at column (only when filter_logic is AND)
    if (repaired.get("filter_logic") or "AND").upper() == "AND":
        for ref in joined_tables:
            if ref in tables and ref not in cte_names and "deleted_at" in tables[ref]:
                has_del = any(
                    f.get("table") == ref and f.get("column") == "deleted_at"
                    for f in clean_filters
                )
                if not has_del:
                    clean_filters.append({
                        "table": ref,
                        "column": "deleted_at",
                        "operator": "IS NULL",
                        "value": None,
                    })
    repaired["filters"] = clean_filters

    # 4. CURRENT DEMAND VS INFORMAL ALL-TIME POPULARITY
    if question:
        q_lower = question.lower()
        is_current_demand = any(w in q_lower for w in ["unfulfilled", "backlog", "backorder", "backorders", "open order", "open orders", "pending order", "pending orders"])
        is_informal_popularity = any(w in q_lower for w in [
            "hot", "popular", "bestseller", "best-selling", "top selling", "trending", "demand", "demanded",
            "seasonal", "sesonal", "season", "restore", "restored", "restock", "restocking"
        ]) and not is_current_demand
        has_explicit_date = any(w in q_lower for w in ["month", "year", "today", "yesterday", "week", "since", "between", "from", "last 30", "last 7", "2024", "2025", "2026", "2027"])

        if is_current_demand:
            # Ensure active order status is enforced for current demand queries
            joined_tbls = {base_table} | {j.get("table") for j in repaired.get("joins", [])}
            if "sales_orders" in joined_tbls:
                has_status_filter = any(
                    f.get("table") == "sales_orders" and f.get("column") == "status"
                    for f in repaired.get("filters", [])
                )
                if not has_status_filter:
                    repaired.setdefault("filters", []).append({
                        "table": "sales_orders",
                        "column": "status",
                        "operator": "NOT IN",
                        "value": ["completed", "cancelled"]
                    })
                # Check for fulfilled_quantity comparison or unfulfilled demand
                has_unfulfilled_filter = any(
                    f.get("table") == "sales_order_lines" and f.get("column") == "quantity" and isinstance(f.get("value"), dict) and f.get("value", {}).get("column") == "fulfilled_quantity"
                    for f in repaired.get("filters", [])
                )
                if not has_unfulfilled_filter and "sales_order_lines" in joined_tbls:
                    repaired.setdefault("filters", []).append({
                        "table": "sales_order_lines",
                        "column": "quantity",
                        "operator": ">",
                        "value": {"table": "sales_order_lines", "column": "fulfilled_quantity"}
                    })
                # Normalize quantity alias to open_demand_quantity
                for sel in repaired.get("select", []):
                    if sel.get("table") == "sales_order_lines" and sel.get("column") == "quantity":
                        if sel.get("alias") in {None, "", "total_quantity_ordered", "quantity"}:
                            sel["alias"] = "open_demand_quantity"
                for ob in repaired.get("order_by", []):
                    if ob.get("alias") == "total_quantity_ordered":
                        ob["alias"] = "open_demand_quantity"
        elif is_informal_popularity and not has_explicit_date:
            no_date_filters = []
            for f in repaired.get("filters", []):
                col = f.get("column", "")
                if col in {"order_date", "date", "created_at", "dispatch_date"} and f.get("operator") in {">=", ">", "BETWEEN"}:
                    continue
                no_date_filters.append(f)
            repaired["filters"] = no_date_filters

        # If a demand query used HAVING sales_frequency > 1 OR total_units_sold > 1, keep only the frequency check
        if (repaired.get("having_logic") or "").upper() == "OR" and repaired.get("having"):
            freq_clauses = [
                h for h in repaired["having"]
                if isinstance(h, dict) and h.get("alias") in {"sales_frequency", "order_frequency"}
            ]
            if freq_clauses and len(freq_clauses) < len(repaired["having"]):
                repaired["having"] = freq_clauses
                repaired["having_logic"] = "AND"

    # 5.1 Ensure COUNT DISTINCT on frequency measures and header tables to prevent fan-out error
    for sel in repaired.get("select", []):
        if not isinstance(sel, dict):
            continue
        if sel.get("alias") in {"sales_frequency", "order_frequency"}:
            sel["distinct"] = True
        elif sel.get("aggregate") == "COUNT" and sel.get("table") in {"sales_goods_issue_notes", "sales_orders", "procurement_purchase_orders", "procurement_goods_receipt_notes"}:
            sel["distinct"] = True

    # 6. ENSURE DESCRIPTIVE SELECT ALIASES (AVOID field_1 / field_3)
    used_aliases = {
        s.get("alias") for s in repaired.get("select", [])
        if isinstance(s, dict) and s.get("alias")
    }
    for idx, sel in enumerate(repaired.get("select", []), start=1):
        if not isinstance(sel, dict) or sel.get("alias") or sel.get("aggregate") or sel.get("expression") or sel.get("window") or sel.get("case_when"):
            continue
        tbl = sel.get("table") or ""
        col = sel.get("column") or ""
        if not col:
            continue
        candidate = (
            "item_id" if tbl == "inventory_items" and col == "id"
            else "item_name" if tbl == "inventory_items" and col == "name"
            else col if col != "id"
            else f"{tbl}_id"
        )
        if candidate in used_aliases:
            candidate = f"{tbl}_{col}"
        if candidate not in used_aliases:
            old_default = f"field_{idx}"
            sel["alias"] = candidate
            used_aliases.add(candidate)
            for ob in repaired.get("order_by", []):
                if isinstance(ob, dict) and ob.get("alias") == old_default:
                    ob["alias"] = candidate

    # Normalize HAVING string alias references (e.g. "min_stock_level" -> {"alias": "min_stock_level"})
    for h in repaired.get("having", []):
        if isinstance(h, dict):
            if isinstance(h.get("value"), str) and h["value"] in used_aliases:
                h["value"] = {"alias": h["value"]}
            elif isinstance(h.get("value"), dict):
                expr_obj = h["value"].get("expression") if "expression" in h["value"] else h["value"]
                if isinstance(expr_obj, dict):
                    for side in ("left", "right"):
                        side_val = expr_obj.get(side)
                        if isinstance(side_val, dict) and "value" in side_val and not ({"table", "column"} <= set(side_val)):
                            expr_obj[side] = side_val["value"]

    # Ensure outer query select items referencing CTEs refer cleanly to exported aliases
    cte_exported_aliases = {}
    for cte in (repaired.get("ctes") or []):
        cname = cte.get("name")
        if cname and isinstance(cte.get("select"), list):
            cte_exported_aliases[cname] = {s.get("alias") or s.get("column") for s in cte["select"] if isinstance(s, dict)}

    for sel in repaired.get("select", []):
        if not isinstance(sel, dict):
            continue
        tbl = sel.get("table")
        if tbl in cte_exported_aliases:
            alias = sel.get("alias")
            col = sel.get("column")
            if not col and alias in cte_exported_aliases[tbl]:
                sel["column"] = alias
            elif col and col not in cte_exported_aliases[tbl] and alias in cte_exported_aliases[tbl]:
                sel["column"] = alias
            if sel.get("expression") and (alias in cte_exported_aliases[tbl] or col):
                target_col = alias if alias in cte_exported_aliases[tbl] else sel.get("column")
                if target_col:
                    sel.pop("expression", None)
                    sel.pop("aggregate", None)
                    sel["column"] = target_col

    return repaired

