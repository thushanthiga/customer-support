"""Authoritative Database Catalog Generator for Apptimate One ERP.

Automatically updates uploads/apptimate_db_catalog.md on Django server startup
by inspecting the live MySQL schema (columns, data types, keys, and foreign keys)
across all core business modules and linking them with application relationship lineage.
"""
import os
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_CATALOG_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "uploads", "apptimate_db_catalog.md")
)

CORE_BUSINESS_MODULES = {
    "Module 1: Inventory & Stock Management": {
        "description": "Manages catalog items, item variants, unit of measures, stock replenishment rules, warehouse stock balances, batches, serial numbers, stock transfers, physical adjustments, and opening stock ledgers.",
        "tables": [
            "inventory_items", "inventory_item_variants", "inventory_item_replenishment_rules",
            "inventory_stock_balances", "inventory_batches", "inventory_serial_numbers",
            "inventory_categories", "inventory_brands", "inventory_units_of_measure",
            "inventory_uom_groups", "inventory_stock_transfers", "inventory_stock_transfer_lines",
            "inventory_stock_adjustments", "inventory_stock_adjustment_lines",
            "inventory_opening_stocks", "inventory_opening_stock_lines",
            "inventory_stock_reservations", "inventory_stock_ledger", "inventory_stock_values",
            "inventory_stock_transfer_orders", "inventory_stock_transfer_order_lines",
            "inventory_item_purchasing_preferences"
        ]
    },
    "Module 2: Sales, Orders & Logistics": {
        "description": "Covers customer sales orders, order line items, sales dispatches (goods issue notes), POS retail transactions, sales quotations, returns, and customer price lists.",
        "tables": [
            "sales_orders", "sales_order_lines", "sales_goods_issue_notes",
            "sales_goods_issue_note_lines", "sales_pos", "sales_pos_terminal_sessions",
            "sales_quotations", "sales_quotation_lines", "sales_returns", "sales_return_lines",
            "sales_price_lists", "sales_price_rules"
        ]
    },
    "Module 3: Procurement & Purchasing": {
        "description": "Covers purchase orders, line items, inbound warehouse goods receipt notes (GRN), purchase requisitions, supplier RFQs, supplier quotations, purchase returns, and supplier bills.",
        "tables": [
            "procurement_purchase_orders", "procurement_purchase_order_lines",
            "procurement_goods_receipt_notes", "procurement_goods_receipt_note_lines",
            "procurement_purchase_requisitions", "procurement_purchase_requisition_lines",
            "procurement_purchase_returns", "procurement_purchase_return_lines",
            "procurement_rfqs", "procurement_rfq_lines", "procurement_rfq_suppliers",
            "procurement_supplier_quotations", "procurement_supplier_bills",
            "procurement_supplier_bill_lines", "procurement_supplier_bill_reviews"
        ]
    },
    "Module 4: Finance, Receivables & Payables": {
        "description": "Covers accounts receivable (customer invoices), accounts payable (supplier bills), customer/supplier payment receipts, company bank accounts, bank statements, chart of accounts, and financial journal entries.",
        "tables": [
            "finance_invoices", "finance_payments", "finance_bank_accounts",
            "finance_bank_statements", "finance_bank_statement_lines", "finance_bank_transactions",
            "fin_chart_of_accounts", "fin_journal_entries", "fin_journal_entry_lines", "fin_fiscal_years"
        ]
    },
    "Module 5: Core Master Entities & Enterprise Structure": {
        "description": "Covers core enterprise masters including business parties (customers and suppliers), addresses, contacts, organizations (subsidiaries/branches), warehouses, POS terminals, currencies, system users, roles, and sales commission configurations.",
        "tables": [
            "core_parties", "core_party_addresses", "core_party_contacts", "core_party_groups",
            "core_organizations", "core_warehouses", "core_terminals", "core_currencies",
            "core_countries", "core_users", "core_roles", "core_commission_salespersons",
            "core_commission_plans", "core_commission_transactions", "core_config"
        ]
    },
    "Module 6: Human Resources & Payroll": {
        "description": "Covers employee master records, designations, payroll runs, payroll component lines, salary structures, daily attendance records, leave applications, leave balances, overtime entries, and department teams.",
        "tables": [
            "hr_employees", "hr_designations", "hr_payroll_runs", "hr_payroll_lines",
            "hr_salary_structures", "hr_salary_structure_lines", "hr_attendance_days",
            "hr_leave_applications", "hr_leave_balances", "hr_ot_entries", "hr_teams", "hr_team_members"
        ]
    },
    "Module 7: CRM & Customer Relationship Management": {
        "description": "Covers sales opportunities, sales leads, interactions, tasks, confirmed CRM sales, expected payment installments, CRM quotations, and pipeline status stages.",
        "tables": [
            "crm_leads", "crm_lead_interactions", "crm_lead_tasks", "crm_confirmed_sales",
            "crm_expected_payments", "crm_quotations", "crm_spaces", "crm_statuses"
        ]
    }
}

CANONICAL_RECIPES_MARKDOWN = '''### Recipe 1: Items Below Item Master Minimum Stock
Identifies items requiring immediate restock based on Item Master thresholds:
- **Base Table**: `inventory_items`
- **Joins**:
  - `INNER JOIN inventory_item_replenishment_rules ON inventory_items.id = inventory_item_replenishment_rules.item_id`
  - `LEFT JOIN inventory_stock_balances ON inventory_items.id = inventory_stock_balances.item_id`
- **Canonical Plan JSON**:
```json
{
  "base_table": "inventory_items",
  "joins": [
    {
      "table": "inventory_item_replenishment_rules",
      "left_table": "inventory_items",
      "left_column": "id",
      "right_column": "item_id",
      "type": "INNER"
    },
    {
      "table": "inventory_stock_balances",
      "left_table": "inventory_items",
      "left_column": "id",
      "right_column": "item_id",
      "type": "LEFT"
    }
  ],
  "select": [
    {"table": "inventory_items", "column": "id", "alias": "item_id"},
    {"table": "inventory_items", "column": "name", "alias": "item_name"},
    {"table": "inventory_items", "column": "sku", "alias": "sku"},
    {"table": "inventory_stock_balances", "column": "qty_available", "aggregate": "SUM", "coalesce": 0, "alias": "stock_quantity"},
    {"table": "inventory_item_replenishment_rules", "column": "min_stock_level", "alias": "min_stock_level"}
  ],
  "filters": [
    {"table": "inventory_items", "column": "deleted_at", "operator": "IS NULL", "value": null},
    {"table": "inventory_item_replenishment_rules", "column": "deleted_at", "operator": "IS NULL", "value": null},
    {"table": "inventory_item_replenishment_rules", "column": "variant_id", "operator": "IS NULL", "value": null},
    {"table": "inventory_item_replenishment_rules", "column": "warehouse_id", "operator": "IS NULL", "value": null}
  ],
  "group_by": [
    {"table": "inventory_items", "column": "id"},
    {"table": "inventory_items", "column": "name"},
    {"table": "inventory_items", "column": "sku"},
    {"table": "inventory_item_replenishment_rules", "column": "min_stock_level"}
  ],
  "having": [
    {"alias": "stock_quantity", "operator": "<", "value": {"alias": "min_stock_level"}}
  ],
  "order_by": [
    {"alias": "stock_quantity", "direction": "asc"},
    {"alias": "item_name", "direction": "asc"}
  ],
  "limit": 50
}
```

---

### Recipe 2: Coordinated Demand & Restocking Assessment
Evaluates whether hot-selling / high-velocity products have sufficient stock:
- **Plan 0 (Demand Ranking)**:
```json
{
  "base_table": "sales_goods_issue_note_lines",
  "joins": [
    {
      "table": "sales_goods_issue_notes",
      "left_table": "sales_goods_issue_note_lines",
      "left_column": "goods_issue_note_id",
      "right_column": "id",
      "type": "INNER"
    },
    {
      "table": "inventory_items",
      "left_table": "sales_goods_issue_note_lines",
      "left_column": "item_id",
      "right_column": "id",
      "type": "INNER"
    }
  ],
  "select": [
    {"table": "inventory_items", "column": "id", "alias": "item_id"},
    {"table": "inventory_items", "column": "name", "alias": "item_name"},
    {"table": "inventory_items", "column": "sku", "alias": "sku"},
    {"table": "sales_goods_issue_note_lines", "column": "dispatch_quantity", "aggregate": "SUM", "alias": "total_units_sold"},
    {"table": "sales_goods_issue_notes", "column": "id", "aggregate": "COUNT", "distinct": true, "alias": "sales_frequency"}
  ],
  "filters": [
    {"table": "sales_goods_issue_notes", "column": "deleted_at", "operator": "IS NULL", "value": null},
    {"table": "inventory_items", "column": "deleted_at", "operator": "IS NULL", "value": null}
  ],
  "group_by": [
    {"table": "inventory_items", "column": "id"},
    {"table": "inventory_items", "column": "name"},
    {"table": "inventory_items", "column": "sku"}
  ],
  "having": [
    {"alias": "sales_frequency", "operator": ">", "value": 1}
  ],
  "order_by": [
    {"alias": "sales_frequency", "direction": "desc"},
    {"alias": "total_units_sold", "direction": "desc"}
  ],
  "limit": 10
}
```
- **Plan 1 (Stock Availability)**:
```json
{
  "base_table": "inventory_items",
  "joins": [
    {
      "table": "inventory_stock_balances",
      "left_table": "inventory_items",
      "left_column": "id",
      "right_column": "item_id",
      "type": "LEFT"
    }
  ],
  "select": [
    {"table": "inventory_items", "column": "id", "alias": "item_id"},
    {"table": "inventory_items", "column": "name", "alias": "item_name"},
    {"table": "inventory_items", "column": "sku", "alias": "sku"},
    {"table": "inventory_stock_balances", "column": "qty_available", "aggregate": "SUM", "coalesce": 0, "alias": "available_quantity"}
  ],
  "filters": [
    {"table": "inventory_items", "column": "deleted_at", "operator": "IS NULL", "value": null}
  ],
  "group_by": [
    {"table": "inventory_items", "column": "id"},
    {"table": "inventory_items", "column": "name"},
    {"table": "inventory_items", "column": "sku"}
  ]
}
```
- **Runtime Execution**: The runtime engine chains the top item IDs from Plan 0 into Plan 1 and synthesizes the unified restocking assessment table with honest date disclosure.

---

### Recipe 3: Multi-Step CTE — Comparing Aggregate Balance vs Latest Record
(e.g. *"List suppliers whose outstanding balance is more than double the amount of their latest invoice"*):
- **Canonical Plan JSON**:
```json
{
  "base_table": "core_parties",
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
      "group_by": [
        {"table": "finance_invoices", "column": "party_id"}
      ]
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
  "joins": [
    {
      "table": "cte_balances",
      "left_table": "core_parties",
      "left_column": "id",
      "right_column": "party_id",
      "type": "INNER"
    },
    {
      "table": "cte_latest",
      "left_table": "core_parties",
      "left_column": "id",
      "right_column": "party_id",
      "type": "INNER"
    }
  ],
  "select": [
    {"table": "core_parties", "column": "id", "alias": "supplier_id"},
    {"table": "core_parties", "column": "first_name", "alias": "supplier_name"},
    {"table": "cte_balances", "column": "outstanding_balance", "alias": "total_outstanding_balance"},
    {"table": "cte_latest", "column": "latest_invoice_number", "alias": "latest_invoice_number"},
    {"table": "cte_latest", "column": "latest_invoice_amount", "alias": "latest_invoice_amount"}
  ],
  "filters": [
    {"table": "core_parties", "column": "type", "operator": "=", "value": "supplier"},
    {"table": "core_parties", "column": "deleted_at", "operator": "IS NULL", "value": null},
    {"table": "cte_latest", "column": "rn", "operator": "=", "value": 1},
    {
      "expression": {
        "operator": "-",
        "left": {"table": "cte_balances", "column": "outstanding_balance"},
        "right": {
          "operator": "*",
          "left": 2,
          "right": {"table": "cte_latest", "column": "latest_invoice_amount"}
        }
      },
      "operator": ">",
      "value": 0
    }
  ],
  "order_by": [
    {"alias": "total_outstanding_balance", "direction": "desc"}
  ],
  "limit": 50
}
```
- **Multiplier Note**: Use literal `2` when the user says "double" or "twice", `3` for "triple", or the exact number N when "N times" is specified (e.g., `4000` for "4000 times"). Because words like "double" already specify an exact multiplier (`2`), never reject or ask for clarification on dynamic input.

---

### Recipe 4: Warehouse Stock vs Open Sales Order Demand
Identifies items where total stock across all warehouses is less than unfulfilled sales order demand:
- **Canonical Plan JSON**:
```json
{
  "base_table": "inventory_items",
  "ctes": [
    {
      "name": "cte_stock",
      "base_table": "inventory_stock_balances",
      "select": [
        {"table": "inventory_stock_balances", "column": "item_id", "alias": "item_id"},
        {"table": "inventory_stock_balances", "column": "qty_available", "aggregate": "SUM", "coalesce": 0, "alias": "total_stock"}
      ],
      "group_by": [
        {"table": "inventory_stock_balances", "column": "item_id"}
      ]
    },
    {
      "name": "cte_demand",
      "base_table": "sales_order_lines",
      "joins": [
        {
          "table": "sales_orders",
          "left_table": "sales_order_lines",
          "left_column": "sales_order_id",
          "right_column": "id",
          "type": "INNER"
        }
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
        {"table": "sales_orders", "column": "deleted_at", "operator": "IS NULL", "value": null},
        {"table": "sales_orders", "column": "status", "operator": "NOT IN", "value": ["completed", "cancelled"]}
      ],
      "group_by": [
        {"table": "sales_order_lines", "column": "item_id"}
      ]
    }
  ],
  "joins": [
    {
      "table": "cte_stock",
      "left_table": "inventory_items",
      "left_column": "id",
      "right_column": "item_id",
      "type": "LEFT"
    },
    {
      "table": "cte_demand",
      "left_table": "inventory_items",
      "left_column": "id",
      "right_column": "item_id",
      "type": "INNER"
    }
  ],
  "select": [
    {"table": "inventory_items", "column": "id", "alias": "item_id"},
    {"table": "inventory_items", "column": "name", "alias": "item_name"},
    {"table": "inventory_items", "column": "sku", "alias": "sku"},
    {"table": "cte_stock", "column": "total_stock", "alias": "total_stock"},
    {"table": "cte_demand", "column": "open_demand", "alias": "open_demand"}
  ],
  "filters": [
    {"table": "inventory_items", "column": "deleted_at", "operator": "IS NULL", "value": null},
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
  "order_by": [
    {"alias": "open_demand", "direction": "desc"}
  ],
  "limit": 50
}
```
'''


def generate_database_catalog(tenant_db: Optional[str] = None, target_file: Optional[str] = None) -> bool:
    """Extract physical MySQL schema from tenant DB and generate authoritative apptimate_db_catalog.md."""
    target_path = os.path.abspath(target_file or DEFAULT_CATALOG_PATH)
    tenant = str(tenant_db or os.getenv("DEFAULT_TENANT_ID", "apptimate_infinity")).strip()

    logger.info("[CATALOG_GENERATOR] Beginning authoritative database catalog generation for tenant '%s'...", tenant)

    try:
        from .db_service import get_tenant_connection
        from .domain_schema import CORE_APPLICATION_RELATIONSHIPS

        conn = get_tenant_connection(tenant)
        cursor = conn.cursor()

        all_target_tables = [t for mod in CORE_BUSINESS_MODULES.values() for t in mod["tables"]]

        # 1. Fetch physical columns from information_schema
        table_list_sql = ", ".join(f"'{t}'" for t in all_target_tables)
        cursor.execute(f"""
            SELECT TABLE_NAME, COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, COLUMN_KEY, COLUMN_DEFAULT, EXTRA, COLUMN_COMMENT
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME IN ({table_list_sql})
            ORDER BY TABLE_NAME, ORDINAL_POSITION;
        """, (tenant,))

        cols_by_table: Dict[str, list] = {}
        for row in cursor.fetchall():
            t = row["TABLE_NAME"]
            cols_by_table.setdefault(t, []).append(row)

        # 2. Fetch all foreign keys from information_schema
        cursor.execute(f"""
            SELECT TABLE_NAME, COLUMN_NAME, REFERENCED_TABLE_NAME, REFERENCED_COLUMN_NAME
            FROM information_schema.KEY_COLUMN_USAGE
            WHERE TABLE_SCHEMA = %s AND REFERENCED_TABLE_NAME IS NOT NULL
              AND TABLE_NAME IN ({table_list_sql})
            ORDER BY TABLE_NAME, COLUMN_NAME;
        """, (tenant,))

        fks_by_table: Dict[str, list] = {}
        for row in cursor.fetchall():
            t = row["TABLE_NAME"]
            fks_by_table.setdefault(t, []).append(row)

        # 3. Merge with application relationships from domain_schema
        app_rels_by_table: Dict[str, list] = {}
        for rel in CORE_APPLICATION_RELATIONSHIPS:
            lt = rel.get("left_table")
            lc = rel.get("left_column")
            rt = rel.get("right_table")
            rc = rel.get("right_column")
            if lt in all_target_tables and rt in all_target_tables:
                existing_fks = fks_by_table.get(lt, [])
                if not any(f["COLUMN_NAME"] == lc and f["REFERENCED_TABLE_NAME"] == rt for f in existing_fks):
                    app_rels_by_table.setdefault(lt, []).append({
                        "COLUMN_NAME": lc,
                        "REFERENCED_TABLE_NAME": rt,
                        "REFERENCED_COLUMN_NAME": rc,
                        "IS_APP_REL": True
                    })

        conn.close()

        # Build markdown lines
        lines: List[str] = []
        lines.append("# Apptimate One ERP — Authoritative Database Catalog & Schema Reference\n")
        lines.append("> **Immutable Schema Architecture Specification**  ")
        lines.append("> This catalog is the permanent, authoritative architectural reference for tenant databases in the Apptimate One ERP platform. The physical database structure, table definitions, column types, primary/foreign keys, and cross-table relationships are invariant across all tenants. All analytical queries generated by the support assistant must adhere strictly to the tables, columns, constraints, and canonical recipes documented herein.\n")
        lines.append("---\n")

        # Section 1: System-Wide Principles
        lines.append("## 1. System-Wide Architectural & Query Principles\n")
        lines.append("### 1.1 Read-Only Security Boundary")
        lines.append("The analytics assistant operates with **strict read-only permissions** (`SELECT` statements only). Mutation statements (`INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `TRUNCATE`) are strictly forbidden and intercepted by database security guardrails.\n")

        lines.append("### 1.2 Tenant & Organization Scoping")
        lines.append("- Each tenant database is strictly isolated (`apptimate_<tenant>`).")
        lines.append("- Every operational table contains `organization_id` referencing `core_organizations.id`.")
        lines.append("- The SQL compiler (`organization_conditions`) automatically injects tenant organization scoping at execution time. The query planner does not need to manually inject `organization_id` filters or join on `organization_id`.\n")

        lines.append("### 1.3 Soft Deletion Standard (`deleted_at`)")
        lines.append("Most operational tables implement soft deletion via a timestamp column `deleted_at`.")
        lines.append("When querying active operational records, always filter: `<table>.deleted_at IS NULL`.")
        lines.append("Tables supporting soft-delete include: `inventory_items`, `sales_orders`, `sales_goods_issue_notes`, `finance_invoices`, `procurement_purchase_orders`, `core_parties`, `core_warehouses`, etc.\n")

        lines.append("### 1.4 Single-Column Join DSL Standard")
        lines.append("- The JSON query plan DSL uses single-column equality joins: `left_table.left_column = table.right_column`.")
        lines.append("- Multi-column joins or conditional join ON clauses are neither needed nor permitted by the compiler.")
        lines.append("- In 1-to-1 relationships (e.g. `inventory_items.id = inventory_item_replenishment_rules.item_id`), filter variant/warehouse qualifiers in WHERE/filters (`variant_id IS NULL`, `warehouse_id IS NULL`), never in join ON clauses.\n")

        lines.append("### 1.5 Common Table Expressions (CTEs) & Window Functions")
        lines.append("- CTEs are authored inside the `ctes` array property of the plan.")
        lines.append("- The outer query joins CTEs by their declared `name` as if they were base tables.")
        lines.append("- Window functions (`ROW_NUMBER()`, `RANK()`, `SUM() OVER (...)`) are computed inside CTEs and filtered in the outer query.\n")

        lines.append("### 1.6 Critical Column Naming Standards")
        lines.append("- `core_parties`: Party name is **`first_name`** (and optionally `last_name`). `core_parties` has **NO `name` column**.")
        lines.append("- `finance_invoices`: Invoices have `type = 'ar'` (customer sales invoices) and `type = 'ap'` (supplier purchase bills). Gross amount is **`amount_due`** (NO `grand_total` column). Amount paid is **`amount_settled`**. Outstanding balance is `amount_due - amount_settled`.")
        lines.append("- `inventory_stock_balances`: Physical stock on hand is `qty_on_hand`; unreserved available stock is **`qty_available`** (NO `stock` or `quantity` column).")
        lines.append("- `sales_orders` & `procurement_purchase_orders`: Order total amount is **`grand_total`**.\n")

        lines.append("---\n")

        # Modules 1 to 7
        mod_num = 2
        for mod_title, mod_data in CORE_BUSINESS_MODULES.items():
            lines.append(f"## {mod_num}. {mod_title}\n")
            lines.append(f"{mod_data['description']}\n")

            for tbl in mod_data["tables"]:
                cols = cols_by_table.get(tbl, [])
                fks = fks_by_table.get(tbl, [])
                app_fks = app_rels_by_table.get(tbl, [])
                all_fks = fks + app_fks

                pk_cols = [c["COLUMN_NAME"] for c in cols if c["COLUMN_KEY"] == "PRI"]
                pk_str = ", ".join(f"`{k}`" for k in pk_cols) if pk_cols else "`id`"

                lines.append(f"### `{tbl}`")
                lines.append(f"- **Primary Key**: {pk_str}")

                if all_fks:
                    lines.append("- **Foreign Key Relationships**:")
                    for fk in all_fks:
                        source_note = " *(App registered)*" if fk.get("IS_APP_REL") else ""
                        lines.append(f"  - `{tbl}.{fk['COLUMN_NAME']}` ➔ `{fk['REFERENCED_TABLE_NAME']}.{fk['REFERENCED_COLUMN_NAME']}`{source_note}")
                else:
                    lines.append("- **Foreign Key Relationships**: None (Base Master Table)")

                lines.append("\n**Physical Columns & Data Types**:\n")
                lines.append("| Column | Data Type | Nullable | Key | Notes / Semantics |")
                lines.append("|---|---|---|---|---|")

                for c in cols:
                    c_name = c["COLUMN_NAME"]
                    c_type = c["COLUMN_TYPE"]
                    c_null = c["IS_NULLABLE"]
                    c_key = c["COLUMN_KEY"] or ""

                    notes = []
                    if c_key == "PRI":
                        notes.append("Primary Key")
                    elif c_key == "UNI":
                        notes.append("Unique constraint")
                    elif c_key == "MUL":
                        match_fk = next((fk for fk in all_fks if fk["COLUMN_NAME"] == c_name), None)
                        if match_fk:
                            notes.append(f"FK ➔ `{match_fk['REFERENCED_TABLE_NAME']}.{match_fk['REFERENCED_COLUMN_NAME']}`")
                        else:
                            notes.append("Indexed")

                    if c_name == "deleted_at":
                        notes.append("Soft-delete timestamp (`IS NULL` for active)")
                    elif c_name == "organization_id":
                        notes.append("Tenant organization scope")
                    elif c_name in ("created_at", "updated_at"):
                        notes.append("Audit timestamp")
                    elif "enum" in c_type:
                        notes.append("Status / category enum")

                    note_str = "; ".join(notes) if notes else "-"
                    lines.append(f"| `{c_name}` | `{c_type}` | {c_null} | {c_key} | {note_str} |")

                lines.append("\n---\n")
            mod_num += 1

        # Section 9: Cross-Table Relationship Matrix
        lines.append(f"## {mod_num}. Cross-Table Relationship Matrix (Master Foreign Key Directory)\n")
        lines.append("The table below documents the verified relationships between all major tables in the ERP tenant database for join resolution:\n")
        lines.append("| Left Table (Child) | Foreign Key Column | Right Table (Parent) | Primary Key Column | Source |")
        lines.append("|---|---|---|---|---|")

        all_relations = []
        for tbl in all_target_tables:
            for fk in fks_by_table.get(tbl, []):
                all_relations.append((tbl, fk["COLUMN_NAME"], fk["REFERENCED_TABLE_NAME"], fk["REFERENCED_COLUMN_NAME"], "Database FK"))
            for fk in app_rels_by_table.get(tbl, []):
                all_relations.append((tbl, fk["COLUMN_NAME"], fk["REFERENCED_TABLE_NAME"], fk["REFERENCED_COLUMN_NAME"], "Core ERP Lineage"))

        all_relations.sort(key=lambda x: (x[0], x[1]))
        for r in all_relations:
            lines.append(f"| `{r[0]}` | `{r[1]}` | `{r[2]}` | `{r[3]}` | {r[4]} |")

        lines.append("\n---\n")
        mod_num += 1

        # Section 10: Canonical Analytical Recipes
        lines.append(f"## {mod_num}. Canonical Analytical Recipes & CTE Query Patterns\n")
        lines.append(CANONICAL_RECIPES_MARKDOWN)

        full_content = "\n".join(lines)

        # Atomic file write
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        tmp_path = target_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(full_content)
        os.replace(tmp_path, target_path)

        # Invalidate in-memory slice caches
        try:
            from .catalog_service import invalidate_catalog_cache
            invalidate_catalog_cache()
        except Exception:
            pass

        logger.info("[CATALOG_GENERATOR] Successfully generated authoritative catalog at '%s' (%d bytes, %d lines across %d tables).",
                    target_path, len(full_content), len(lines), len(all_target_tables))
        return True

    except Exception as exc:
        logger.warning("[CATALOG_GENERATOR] Could not auto-generate database catalog from '%s': %s. Existing catalog preserved.",
                       tenant, exc)
        return False

