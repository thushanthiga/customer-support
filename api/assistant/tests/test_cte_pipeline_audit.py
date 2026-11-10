from django.test import SimpleTestCase
from assistant.pipeline_audit import evaluate_query
from assistant.domain_schema import repair_and_heal_plan


class CtePipelineAuditTests(SimpleTestCase):
    def setUp(self):
        self.raw_schema = {
            "tables": {
                "core_parties": {
                    "id": "bigint",
                    "first_name": "varchar",
                    "type": "varchar",
                    "deleted_at": "datetime",
                },
                "sales_orders": {
                    "id": "bigint",
                    "party_id": "bigint",
                    "grand_total": "decimal",
                    "status": "varchar",
                    "order_date": "date",
                    "deleted_at": "datetime",
                },
                "sales_order_lines": {
                    "id": "bigint",
                    "sales_order_id": "bigint",
                    "item_id": "bigint",
                    "quantity": "decimal",
                },
                "inventory_items": {
                    "id": "bigint",
                    "name": "varchar",
                    "sku": "varchar",
                    "deleted_at": "datetime",
                },
                "inventory_stock_balances": {
                    "id": "bigint",
                    "item_id": "bigint",
                    "warehouse_id": "bigint",
                    "qty_available": "decimal",
                },
                "finance_invoices": {
                    "id": "bigint",
                    "party_id": "bigint",
                    "amount_due": "decimal",
                    "amount_settled": "decimal",
                    "type": "varchar",
                    "status": "varchar",
                    "invoice_date": "date",
                    "invoice_number": "varchar",
                },
            },
            "declared_relationships": [
                ("sales_orders", "party_id", "core_parties", "id"),
                ("sales_order_lines", "sales_order_id", "sales_orders", "id"),
                ("sales_order_lines", "item_id", "inventory_items", "id"),
                ("inventory_stock_balances", "item_id", "inventory_items", "id"),
                ("finance_invoices", "party_id", "core_parties", "id"),
            ],
            "application_relationships": [],
        }

    def test_supplier_balance_vs_latest_invoice_evaluates_and_passes(self):
        question = "list down all the suppliers whose outstanding balance is more than double the amount of their latest invoice"
        raw_plan = {"base_table": "core_parties", "select": [{"table": "core_parties", "column": "id"}]}
        healed = repair_and_heal_plan(raw_plan, self.raw_schema, question=question)

        # Plan must have 2 CTEs
        self.assertIn("ctes", healed)
        self.assertEqual(len(healed["ctes"]), 2)
        cte_names = [c["name"] for c in healed["ctes"]]
        self.assertIn("cte_balances", cte_names)
        self.assertIn("cte_latest", cte_names)

        # Evaluate query through pipeline audit
        result = evaluate_query(healed, self.raw_schema)
        self.assertTrue(result["passed"], f"Query evaluation failed: {result['reasons']}")
        self.assertEqual(result["score"], 100)

    def test_cte_aliases_auto_default_to_column_names(self):
        plan = {
            "ctes": [
                {
                    "name": "cte_test",
                    "base_table": "finance_invoices",
                    "select": [
                        {"table": "finance_invoices", "column": "party_id"}
                    ],
                }
            ],
            "base_table": "core_parties",
            "select": [{"table": "core_parties", "column": "id"}],
        }
        healed = repair_and_heal_plan(plan, self.raw_schema)
        self.assertEqual(healed["ctes"][0]["select"][0]["alias"], "party_id")

    def test_customer_lifetime_sales_vs_latest_order_evaluates_and_passes(self):
        customer_plan = {
            "ctes": [
                {
                    "name": "cte_cust_totals",
                    "base_table": "sales_orders",
                    "select": [
                        {"table": "sales_orders", "column": "party_id", "alias": "party_id"},
                        {"table": "sales_orders", "column": "grand_total", "aggregate": "SUM", "alias": "lifetime_total"},
                    ],
                    "filters": [
                        {"table": "sales_orders", "column": "deleted_at", "operator": "IS NULL", "value": None},
                        {"table": "sales_orders", "column": "status", "operator": "!=", "value": "cancelled"},
                    ],
                    "group_by": [{"table": "sales_orders", "column": "party_id"}],
                },
                {
                    "name": "cte_cust_latest",
                    "base_table": "sales_orders",
                    "select": [
                        {"table": "sales_orders", "column": "party_id", "alias": "party_id"},
                        {"table": "sales_orders", "column": "grand_total", "alias": "latest_order_amount"},
                        {
                            "window": {
                                "function": "ROW_NUMBER",
                                "partition_by": [{"table": "sales_orders", "column": "party_id"}],
                                "order_by": [{"table": "sales_orders", "column": "order_date", "direction": "desc"}],
                            },
                            "alias": "rn",
                        },
                    ],
                    "filters": [
                        {"table": "sales_orders", "column": "deleted_at", "operator": "IS NULL", "value": None},
                        {"table": "sales_orders", "column": "status", "operator": "!=", "value": "cancelled"},
                    ],
                },
            ],
            "base_table": "core_parties",
            "select": [
                {"table": "core_parties", "column": "id", "alias": "customer_id"},
                {"table": "core_parties", "column": "first_name", "alias": "customer_name"},
                {"table": "cte_cust_totals", "column": "lifetime_total", "alias": "lifetime_total"},
                {"table": "cte_cust_latest", "column": "latest_order_amount", "alias": "latest_order_amount"},
            ],
            "joins": [
                {"table": "cte_cust_totals", "left_table": "core_parties", "left_column": "id", "right_column": "party_id"},
                {"table": "cte_cust_latest", "left_table": "core_parties", "left_column": "id", "right_column": "party_id"},
            ],
            "filters": [
                {"table": "core_parties", "column": "deleted_at", "operator": "IS NULL", "value": None},
                {"table": "core_parties", "column": "type", "operator": "=", "value": "customer"},
                {"table": "cte_cust_latest", "column": "rn", "operator": "=", "value": 1},
                {
                    "expression": {
                        "operator": "-",
                        "left": {"table": "cte_cust_totals", "column": "lifetime_total"},
                        "right": {
                            "expression": {
                                "operator": "*",
                                "left": 3,
                                "right": {"table": "cte_cust_latest", "column": "latest_order_amount"},
                            }
                        },
                    },
                    "operator": ">",
                    "value": 0,
                },
            ],
        }
        result = evaluate_query(customer_plan, self.raw_schema)
        self.assertTrue(result["passed"], f"Query evaluation failed: {result['reasons']}")
        self.assertEqual(result["score"], 100)

    def test_inventory_demand_vs_stock_balance_evaluates_and_passes(self):
        inventory_plan = {
            "ctes": [
                {
                    "name": "cte_demand",
                    "base_table": "sales_order_lines",
                    "select": [
                        {"table": "sales_order_lines", "column": "item_id", "alias": "item_id"},
                        {"table": "sales_order_lines", "column": "quantity", "aggregate": "SUM", "alias": "total_ordered"},
                    ],
                    "group_by": [{"table": "sales_order_lines", "column": "item_id"}],
                },
                {
                    "name": "cte_stock",
                    "base_table": "inventory_stock_balances",
                    "select": [
                        {"table": "inventory_stock_balances", "column": "item_id", "alias": "item_id"},
                        {"table": "inventory_stock_balances", "column": "qty_available", "aggregate": "SUM", "alias": "total_available"},
                    ],
                    "group_by": [{"table": "inventory_stock_balances", "column": "item_id"}],
                },
            ],
            "base_table": "inventory_items",
            "select": [
                {"table": "inventory_items", "column": "id", "alias": "item_id"},
                {"table": "inventory_items", "column": "name", "alias": "item_name"},
                {"table": "cte_demand", "column": "total_ordered", "alias": "total_ordered"},
                {"table": "cte_stock", "column": "total_available", "alias": "total_available"},
            ],
            "joins": [
                {"table": "cte_demand", "left_table": "inventory_items", "left_column": "id", "right_column": "item_id"},
                {"table": "cte_stock", "left_table": "inventory_items", "left_column": "id", "right_column": "item_id"},
            ],
            "filters": [
                {"table": "inventory_items", "column": "deleted_at", "operator": "IS NULL", "value": None},
                {
                    "expression": {
                        "operator": "-",
                        "left": {"table": "cte_demand", "column": "total_ordered"},
                        "right": {"table": "cte_stock", "column": "total_available"},
                    },
                    "operator": ">",
                    "value": 0,
                },
            ],
        }
        result = evaluate_query(inventory_plan, self.raw_schema)
        self.assertTrue(result["passed"], f"Query evaluation failed: {result['reasons']}")
        self.assertEqual(result["score"], 100)

    def test_cross_module_cte_join_on_parent_targets_evaluates_and_passes(self):
        cross_cte_plan = {
            "ctes": [
                {
                    "name": "cte_orders",
                    "base_table": "sales_orders",
                    "select": [
                        {"table": "sales_orders", "column": "party_id", "alias": "party_id"},
                        {"table": "sales_orders", "column": "grand_total", "aggregate": "SUM", "alias": "order_sum"},
                    ],
                    "filters": [
                        {"table": "sales_orders", "column": "deleted_at", "operator": "IS NULL", "value": None},
                        {"table": "sales_orders", "column": "status", "operator": "!=", "value": "cancelled"},
                    ],
                    "group_by": [{"table": "sales_orders", "column": "party_id"}],
                },
                {
                    "name": "cte_invoices",
                    "base_table": "finance_invoices",
                    "select": [
                        {"table": "finance_invoices", "column": "party_id", "alias": "party_id"},
                        {"table": "finance_invoices", "column": "amount_due", "aggregate": "SUM", "alias": "invoice_sum"},
                    ],
                    "filters": [
                        {"table": "finance_invoices", "column": "status", "operator": "!=", "value": "voided"},
                    ],
                    "group_by": [{"table": "finance_invoices", "column": "party_id"}],
                },
            ],
            "base_table": "cte_orders",
            "select": [
                {"table": "cte_orders", "column": "party_id", "alias": "party_id"},
                {"table": "cte_orders", "column": "order_sum", "alias": "order_sum"},
                {"table": "cte_invoices", "column": "invoice_sum", "alias": "invoice_sum"},
            ],
            "joins": [
                {"table": "cte_invoices", "left_table": "cte_orders", "left_column": "party_id", "right_column": "party_id"},
            ],
        }
        result = evaluate_query(cross_cte_plan, self.raw_schema)
        self.assertTrue(result["passed"], f"Query evaluation failed: {result['reasons']}")
        self.assertEqual(result["score"], 100)
