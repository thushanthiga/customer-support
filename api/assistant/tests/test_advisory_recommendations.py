"""Tests for business advisory / sales recommendation routing and grounded synthesis."""
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from assistant.local_engine import LocalAnswer, classify_query


def _fake_schema(_tenant):
    return {
        "tables": {
            "inventory_items": {
                "columns": {
                    "id": {"type": "bigint"},
                    "name": {"type": "varchar"},
                    "sku": {"type": "varchar"},
                    "status": {"type": "varchar"},
                    "is_available_sell": {"type": "tinyint"},
                    "deleted_at": {"type": "timestamp"},
                }
            },
            "inventory_stock_balances": {
                "columns": {"item_id": {"type": "bigint"}, "qty_available": {"type": "decimal"}}
            },
            "sales_goods_issue_note_lines": {
                "columns": {
                    "goods_issue_note_id": {"type": "bigint"},
                    "item_id": {"type": "bigint"},
                    "dispatch_quantity": {"type": "decimal"},
                }
            },
            "sales_goods_issue_notes": {"columns": {"id": {"type": "bigint"}, "status": {"type": "varchar"}}},
            "sales_orders": {
                "columns": {
                    "id": {"type": "bigint"},
                    "status": {"type": "varchar"},
                    "grand_total": {"type": "decimal"},
                    "deleted_at": {"type": "timestamp"},
                }
            },
            "sales_order_lines": {"columns": {"id": {"type": "bigint"}}},
            "sales_quotations": {
                "columns": {
                    "id": {"type": "bigint"},
                    "status": {"type": "varchar"},
                    "grand_total": {"type": "decimal"},
                    "deleted_at": {"type": "timestamp"},
                }
            },
            "sales_return_lines": {
                "columns": {
                    "sales_return_id": {"type": "bigint"},
                    "return_reason": {"type": "varchar"},
                    "return_quantity": {"type": "decimal"},
                    "subtotal": {"type": "decimal"},
                }
            },
            "sales_price_lists": {"columns": {"id": {"type": "bigint"}, "is_active": {"type": "tinyint"}}},
        },
        "declared_relationships": [
            ("sales_goods_issue_note_lines", "goods_issue_note_id", "sales_goods_issue_notes", "id"),
            ("sales_goods_issue_note_lines", "item_id", "inventory_items", "id"),
            ("inventory_items", "id", "inventory_stock_balances", "item_id"),
        ],
        "application_relationships": [],
    }


def _fake_query_business_data(plan, tenant, **_kwargs):
    for item in plan.get("select") or []:
        agg = item.get("aggregate")
        if agg and str(agg).upper() not in {"SUM", "COUNT", "AVG", "MIN", "MAX"}:
            return {"error": f"Unsupported aggregate function: {agg}"}
    base = plan.get("base_table")
    joins = plan.get("joins") or []
    rows = []
    if base == "sales_goods_issue_note_lines":
        rows = [
            {"item_id": 71, "item_name": "Munchee 50g", "sku": "BIS-BRN-01", "total_units_sold": 30, "sales_frequency": 13},
            {"item_id": 72, "item_name": "Anarkali kurti", "sku": "CLO-BRN-05", "total_units_sold": 8, "sales_frequency": 6},
            {"item_id": 19, "item_name": "A-batch", "sku": "batch-100", "total_units_sold": 13, "sales_frequency": 4},
        ]
    elif base == "inventory_items" and joins:
        filters = plan.get("filters") or []
        is_high_stock = any(f.get("column") == "is_available_sell" for f in filters)
        if is_high_stock:
            rows = [{"item_id": 19, "item_name": "A-batch", "sku": "batch-100", "available_quantity": 319}]
        else:
            rows = [
                {"item_id": 71, "item_name": "Munchee 50g", "sku": "BIS-BRN-01", "available_quantity": 0},
                {"item_id": 72, "item_name": "Anarkali kurti", "sku": "CLO-BRN-05", "available_quantity": 37},
                {"item_id": 19, "item_name": "A-batch", "sku": "batch-100", "available_quantity": 319},
            ]
    elif base == "sales_orders":
        rows = [
            {"status": "completed", "order_count": 16, "total_value": 874452},
            {"status": "cancelled", "order_count": 4, "total_value": 1248000},
            {"status": "draft", "order_count": 3, "total_value": 506000},
            {"status": "confirmed", "order_count": 1, "total_value": 290000},
        ]
    elif base == "sales_quotations":
        rows = [
            {"status": "converted", "quotation_count": 10, "total_value": 1072705},
            {"status": "sent", "quotation_count": 1, "total_value": 1600200},
            {"status": "revised", "quotation_count": 1, "total_value": 120000},
        ]
    elif base == "sales_return_lines":
        rows = [
            {"return_reason": "damaged", "return_count": 3, "returned_qty": 16, "returned_value": 3110},
            {"return_reason": "other", "return_count": 1, "returned_qty": 2, "returned_value": 520},
        ]
    elif base == "sales_price_lists":
        rows = [
            {"is_active": 1, "price_list_count": 4},
            {"is_active": 0, "price_list_count": 2},
        ]
    return {
        "results": rows,
        "row_count": len(rows),
        "truncated": False,
        "compiled_sql": f"SELECT * FROM `{base}`",
        "query_audit": {"selected_fields": plan.get("select") or []},
        "mcp_elapsed_ms": 2.1,
        "mcp_read_at": "2026-11-11T10:00:00",
    }


class AdvisoryRecommendationsTests(SimpleTestCase):
    @override_settings(SUPPORT_DISABLE_MODEL_CALLS=True)
    def test_advisory_classification_vs_db_and_docs(self):
        advisory_queries = [
            "give me any reclamations that need to do in oder to improve the sales",
            "give me recommendations to improve sales",
            "how can we increase our sales?",
            "what changes should we do to boost sales performance",
            "you see the upcoming time is a festive one so suggest me the better items to stock on the werehouse",
            "tell me what season I need to be prepare next",
        ]
        for q in advisory_queries:
            with self.subTest(advisory=q):
                cls = classify_query(q)
                self.assertEqual(cls["classification"], "advisory")

        non_advisory = [
            ("which items need restocking?", "database"),
            ("what is the seasonal things need to be restore", "database"),
            ("list top selling items", "database"),
            ("how do I add a discount on an invoice", "document"),
        ]
        for q, expected in non_advisory:
            with self.subTest(non_advisory=q):
                cls = classify_query(q)
                self.assertEqual(cls["classification"], expected)

    @override_settings(SUPPORT_DISABLE_MODEL_CALLS=True)
    @patch("assistant.local_engine.query_service.query_business_data", side_effect=_fake_query_business_data)
    @patch("assistant.local_engine.query_service._schema_for", side_effect=_fake_schema)
    def test_advisory_answer_synthesizes_grounded_recommendations(self, _mock_schema, _mock_query):
        res = LocalAnswer(
            "apptimate_infinity",
            {"user_id": 1},
            "give me any reclamations that need to do in oder to improve the sales",
            (),
            state={},
        ).run()

        self.assertEqual(res["answer_status"], "answered")
        self.assertEqual(res["search_type"], "advisory")
        body = res["response"]
        self.assertIn("Munchee 50g", body)
        self.assertIn("1,720,200", body)
        self.assertIn("damaged", body)
        self.assertIn("16", body)
        self.assertIn("1,248,000", body)
        self.assertIn("Sidebar ➔ Procurement ➔ Purchase Orders", body)
        self.assertIn("Sidebar ➔ Sales ➔ Transactions ➔ Sales Quotations", body)
        self.assertIn("Technical Execution & Pipeline Audit", body)
        self.assertNotIn("Found **10 matching record(s)** with sales frequency", body)

    @staticmethod
    def _rich_seasonal_schema(_tenant):
        base = _fake_schema(_tenant)
        base["tables"]["inventory_items"]["columns"]["category_id"] = {"type": "bigint"}
        base["tables"]["inventory_categories"] = {
            "columns": {"id": {"type": "bigint"}, "name": {"type": "varchar"}, "deleted_at": {"type": "timestamp"}}
        }
        base["tables"]["sales_goods_issue_notes"]["columns"]["dispatch_date"] = {"type": "date"}
        base["declared_relationships"] = list(base["declared_relationships"]) + [
            ("inventory_items", "category_id", "inventory_categories", "id"),
        ]
        return base

    @staticmethod
    def _rich_seasonal_query(plan, tenant, **_kwargs):
        base = plan.get("base_table")
        joins = plan.get("joins") or []
        filters = plan.get("filters") or []
        select_aliases = {s.get("alias") for s in (plan.get("select") or [])}
        rows = []
        if base == "inventory_categories":
            rows = [
                {"category_id": 1, "category_name": "Electronics", "item_count": 44507},
                {"category_id": 2, "category_name": "Groceries", "item_count": 15},
                {"category_id": 3, "category_name": "Clothing", "item_count": 8},
                {"category_id": 15, "category_name": "Biscuit", "item_count": 6},
                {"category_id": 11, "category_name": "Test", "item_count": 0},
            ]
        elif base == "sales_goods_issue_note_lines" and "category_id" in select_aliases:
            rows = [
                {"category_id": 15, "category_name": "Biscuit", "total_units_sold": 44, "sales_frequency": 21, "distinct_items_sold": 3},
                {"category_id": 3, "category_name": "Clothing", "total_units_sold": 27, "sales_frequency": 17, "distinct_items_sold": 4},
                {"category_id": 1, "category_name": "Electronics", "total_units_sold": 14, "sales_frequency": 7, "distinct_items_sold": 3},
            ]
        elif base == "sales_goods_issue_note_lines":
            rows = [
                {"item_id": 71, "item_name": "Munchee 50g", "sku": "BIS-BRN-01", "total_units_sold": 30, "sales_frequency": 13},
                {"item_id": 50, "item_name": "Batch without variant", "sku": "BLO-BRN-09", "total_units_sold": 10, "sales_frequency": 2},
                {"item_id": 77, "item_name": "Anarkali kurti", "sku": "CLO-BRN-05", "total_units_sold": 8, "sales_frequency": 6},
                {"item_id": 61, "item_name": "Chungudi cotton", "sku": "CLO-BRN-02", "total_units_sold": 7, "sales_frequency": 5},
                {"item_id": 20844, "item_name": "Load Test Item 266 DvfD8V", "sku": "LD-266-SXWEPV", "total_units_sold": 6, "sales_frequency": 2},
            ]
        elif base == "sales_goods_issue_notes" and "dispatch_month" in select_aliases:
            rows = [
                {"dispatch_month": 202607, "dispatch_count": 10, "total_units_sold": 19},
                {"dispatch_month": 202608, "dispatch_count": 96, "total_units_sold": 117.5},
                {"dispatch_month": 202609, "dispatch_count": 3, "total_units_sold": 3},
                {"dispatch_month": 202610, "dispatch_count": 3, "total_units_sold": 12},
            ]
        elif base == "inventory_items" and joins:
            is_high_stock = any(f.get("column") == "is_available_sell" for f in filters)
            if is_high_stock:
                rows = [
                    {"item_id": 11, "item_name": "Ponni rice", "sku": "GRO-PON-006", "category_name": "Groceries", "available_quantity": 220},
                    {"item_id": 77, "item_name": "Anarkali kurti", "sku": "CLO-BRN-05", "category_name": "Clothing", "available_quantity": 37},
                    {"item_id": 99999, "item_name": "Load Test Item 2365 lJm63M", "sku": "LD-2365-UU8JBL", "category_name": "Electronics", "available_quantity": 1746},
                ]
            else:
                rows = [
                    {"item_id": 71, "item_name": "Munchee 50g", "sku": "BIS-BRN-01", "category_name": "Biscuit", "available_quantity": 0},
                    {"item_id": 50, "item_name": "Batch without variant", "sku": "BLO-BRN-09", "category_name": "blouse", "available_quantity": 0},
                    {"item_id": 61, "item_name": "Chungudi cotton", "sku": "CLO-BRN-02", "category_name": "Clothing", "available_quantity": 0},
                    {"item_id": 77, "item_name": "Anarkali kurti", "sku": "CLO-BRN-05", "category_name": "Clothing", "available_quantity": 37},
                ]
        elif base == "sales_price_lists":
            rows = [{"is_active": 1, "price_list_count": 4}, {"is_active": 0, "price_list_count": 2}]
        return {
            "results": rows,
            "row_count": len(rows),
            "truncated": False,
            "compiled_sql": f"SELECT * FROM `{base}`",
            "query_audit": {"selected_fields": plan.get("select") or []},
            "mcp_elapsed_ms": 2.0,
            "mcp_read_at": "2026-11-11T10:00:00",
        }

    @override_settings(SUPPORT_DISABLE_MODEL_CALLS=True)
    @patch("assistant.local_engine.query_service.query_business_data", side_effect=_rich_seasonal_query.__func__)
    @patch("assistant.local_engine.query_service._schema_for", side_effect=_rich_seasonal_schema.__func__)
    def test_festive_stocking_filters_load_test_items_and_focuses_on_merchandising(self, _mock_schema, _mock_query):
        res = LocalAnswer(
            "apptimate_infinity",
            {"user_id": 1},
            "you see the upcoming time is a festive one so suggest me the better items to stock on the werehouse",
            (),
            state={},
        ).run()

        self.assertEqual(res["answer_status"], "answered")
        self.assertEqual(res["search_type"], "advisory")
        body = res["response"]
        self.assertIn("Munchee 50g", body)
        self.assertIn("Ponni rice", body)
        self.assertIn("Anarkali kurti", body)
        self.assertIn("Biscuit", body)
        self.assertIn("Pros:", body)
        self.assertIn("Cons:", body)
        self.assertIn("Option A", body)
        self.assertIn("Option B", body)
        self.assertIn("landmark", body.lower())
        self.assertNotIn("Urgent restocks (proven sellers at 0 stock):** **Batch without variant", body)
        self.assertNotIn("Load Test Item 2365", body)
        self.assertNotIn("Load Test Item 266", body)
        self.assertNotIn("Cancelled order leakage", body)
        self.assertIn("Sidebar ➔ Procurement ➔ Purchase Orders", body)

    @override_settings(SUPPORT_DISABLE_MODEL_CALLS=True)
    @patch("assistant.local_engine.query_service.query_business_data", side_effect=_rich_seasonal_query.__func__)
    @patch("assistant.local_engine.query_service._schema_for", side_effect=_rich_seasonal_schema.__func__)
    def test_next_season_prep_and_followup_continuity(self, _mock_schema, _mock_query):
        chat_state = {}
        first_q = "tell me what season I need to be prepare next"
        res1 = LocalAnswer("apptimate_infinity", {"user_id": 1}, first_q, (), state=chat_state).run()

        self.assertEqual(res1["answer_status"], "answered")
        self.assertEqual(res1["search_type"], "advisory")
        body1 = res1["response"]
        self.assertIn("Seasonal Planning & Merchandising Strategy", body1)
        self.assertIn("August 2026", body1)
        self.assertIn("July 2026", body1)
        self.assertIn("October 2026", body1)
        self.assertIn("Biscuit", body1)
        self.assertIn("Pros:", body1)
        self.assertIn("Cons:", body1)
        self.assertIn("Clarifications", body1)
        self.assertNotIn("dedicated ERP support assistant for **Apptimate One**", body1)
        self.assertEqual((chat_state.get("last_advisory") or {}).get("focus"), "seasonal_prep")

        # Turn 2: user answers follow-up questions with location landmark, store model, and category focus
        res2 = LocalAnswer(
            "apptimate_infinity",
            {"user_id": 1},
            "Colombo retail store, mostly groceries and snacks, open to Option A new festive hampers",
            (first_q,),
            state=chat_state,
        ).run()
        self.assertEqual(res2["answer_status"], "answered")
        self.assertEqual(res2["search_type"], "advisory")
        self.assertIn("Colombo retail store", res2["response"])
        self.assertIn("Option A", res2["response"])

    @override_settings(SUPPORT_DISABLE_MODEL_CALLS=True)
    @patch("assistant.local_engine.query_service._schema_for", side_effect=_rich_seasonal_schema.__func__)
    def test_festive_to_combo_followup_uses_positive_consumer_stock_and_excludes_test_items(self, _mock_schema):
        def _combo_query(plan, tenant, **kwargs):
            res = self._rich_seasonal_query(plan, tenant, **kwargs)
            base = plan.get("base_table")
            filters = plan.get("filters") or []
            if base == "inventory_categories":
                res["results"] = list(res["results"]) + [
                    {"category_id": 4, "category_name": "Dairy", "item_count": 5},
                    {"category_id": 5, "category_name": "Cement", "item_count": 4},
                ]
                res["row_count"] = len(res["results"])
            elif base == "inventory_items" and any(f.get("column") == "is_available_sell" for f in filters):
                res["results"] = list(res["results"]) + [
                    {"item_id": 12, "item_name": "Kothmale milk pack", "sku": "DAI-KOT-01", "category_name": "Dairy", "available_quantity": 90},
                    {"item_id": 13, "item_name": "vitamin C", "sku": "WEL-VIT-01", "category_name": "Wellness", "available_quantity": 189},
                    {"item_id": 801, "item_name": "No Variant/Batch", "sku": "TST-NV-01", "category_name": "Groceries", "available_quantity": 500},
                    {"item_id": 802, "item_name": "Has Vari", "sku": "TST-HV-01", "category_name": "Groceries", "available_quantity": 400},
                    {"item_id": 803, "item_name": "Awsed", "sku": "AA-001", "category_name": "Groceries", "available_quantity": 300},
                    {"item_id": 804, "item_name": "Tempora perferendis", "sku": "LOR-001", "category_name": "Clothing", "available_quantity": 250},
                    {"item_id": 805, "item_name": "kalyani cotton - N/V", "sku": "CLO-KAL-NV", "category_name": "Clothing", "available_quantity": 120},
                    {"item_id": 901, "item_name": "Cement Bag 50kg", "sku": "CEM-001", "category_name": "Cement", "available_quantity": 600},
                    {"item_id": 902, "item_name": "River Sand", "sku": "SND-001", "category_name": "Sand", "available_quantity": 400},
                ]
                res["row_count"] = len(res["results"])
            return res

        with patch("assistant.local_engine.query_service.query_business_data", side_effect=_combo_query):
            chat_state = {}
            q1 = "you see the upcoming time is a festive one so suggest me the better items to stock on the werehouse"
            res1 = LocalAnswer("apptimate_infinity", {"user_id": 1}, q1, (), state=chat_state).run()
            self.assertEqual(res1["search_type"], "advisory")

            q2 = "this is completely fine but in the stocks items we have shall we make the combo things and give a bit discount for that"
            res2 = LocalAnswer("apptimate_infinity", {"user_id": 1}, q2, (q1,), state=chat_state).run()
            self.assertEqual(res2["answer_status"], "answered")
            self.assertEqual(res2["search_type"], "advisory")
            self.assertEqual((chat_state.get("last_advisory") or {}).get("focus"), "combo_bundling")
            self.assertIn("Price Lists", res2["response"])
            self.assertIn("Min Qty", res2["response"])
            self.assertIn("Specific Items", res2["response"])

            q3 = "give me the suggestions which items can make the combo"
            res3 = LocalAnswer("apptimate_infinity", {"user_id": 1}, q3, (q1, q2), state=chat_state).run()
            self.assertEqual(res3["answer_status"], "answered")
            self.assertEqual(res3["search_type"], "advisory")
            body3 = res3["response"]
            self.assertIn("Ponni rice", body3)
            self.assertIn("Anarkali kurti", body3)
            self.assertIn("Kothmale milk pack", body3)
            self.assertIn("Munchee 50g", body3)
            self.assertIn("0 available", body3)
            self.assertIn("Combo SKU", body3)
            for forbidden in (
                "No Variant/Batch",
                "Has Vari",
                "Awsed",
                "Tempora perferendis",
                "kalyani cotton - N/V",
                "Batch without variant",
                "Load Test Item",
            ):
                self.assertNotIn(forbidden, body3)
            # Construction/industrial items may only appear in a separate trade/exclusion note, not inside consumer hamper lines.
            consumer_section = body3.split("Separate Trade/Construction Stock")[0]
            self.assertNotIn("Cement Bag 50kg", consumer_section)
            self.assertNotIn("River Sand", consumer_section)

    @override_settings(SUPPORT_DISABLE_MODEL_CALLS=True)
    @patch("assistant.local_engine.query_service._schema_for", side_effect=_rich_seasonal_schema.__func__)
    def test_combo_followup_answers_margin_and_setup_directly_and_separates_thin_and_cross_vertical_stock(self, _mock_schema):
        def _split_combo_query(plan, tenant, **kwargs):
            res = self._rich_seasonal_query(plan, tenant, **kwargs)
            base = plan.get("base_table")
            filters = plan.get("filters") or []
            if base == "inventory_items" and any(f.get("column") == "is_available_sell" for f in filters):
                res["results"] = [
                    {"item_id": 11, "item_name": "Ponni rice", "sku": "GRO-PON-006", "category_name": "Groceries", "available_quantity": 220},
                    {"item_id": 13, "item_name": "vitamin C", "sku": "MED-COT-01", "category_name": "medicine", "available_quantity": 189},
                    {"item_id": 14, "item_name": "anchor 350g", "sku": "MIL-ANC-ANC-001", "category_name": "milk powderd items", "available_quantity": 151},
                    {"item_id": 6, "item_name": "Anarkali kurti", "sku": "CLO-BRN-05", "category_name": "Clothing", "available_quantity": 37},
                    {"item_id": 12, "item_name": "Kothmale milk pack", "sku": "MIL-KOT-001", "category_name": "Juice", "available_quantity": 35},
                    {"item_id": 15, "item_name": "alya cut blouse", "sku": "BLO-YOU-01", "category_name": "blouse", "available_quantity": 12},
                    {"item_id": 16, "item_name": "Water bottle", "sku": "ORN-COT-01", "category_name": "Ornaments", "available_quantity": 5},
                    {"item_id": 17, "item_name": "rainbow saree", "sku": "CLO-BRN-04", "category_name": "Clothing", "available_quantity": 3},
                    {"item_id": 3, "item_name": "Munchee 100-2", "sku": "BIS-MUN-06", "category_name": "Biscuit", "available_quantity": 2},
                ]
                res["row_count"] = len(res["results"])
            return res

        with patch("assistant.local_engine.query_service.query_business_data", side_effect=_split_combo_query):
            chat_state = {}
            q_items = "give me the suggestions which items can make the combo"
            res_items = LocalAnswer("apptimate_infinity", {"user_id": 1}, q_items, (), state=chat_state).run()
            self.assertEqual(res_items["search_type"], "advisory")
            body_items = res_items["response"]

            # Deep consumer bundles use only >=6 avail items and keep Apparel strictly separated from Biscuit/Groceries.
            apparel_marker = "Festive Apparel & Ethnic Outfit Combo"
            self.assertIn(apparel_marker, body_items)
            apparel_chunk = body_items.split(apparel_marker, 1)[1].split("####", 1)[0]
            self.assertIn("Anarkali kurti", apparel_chunk)
            self.assertIn("alya cut blouse", apparel_chunk)
            self.assertNotIn("Munchee 100-2", apparel_chunk)
            self.assertIn("Limited-Stock Items", body_items)
            self.assertIn("Munchee 100-2", body_items.split("Limited-Stock Items", 1)[1])

            # Discount bands align consistently across bundle suggestions and strategy notes.
            pantry_chunk = body_items.split("Festive Pantry, Dairy & Snack Combo", 1)[1].split("####", 1)[0]
            self.assertIn("5%–8%", pantry_chunk)
            self.assertIn("10%–15%", apparel_chunk)

            # Follow-up 1: target margin / discount ceiling must answer directly without looping or re-asking itself.
            q_margin = "What is your target margin or discount ceiling for these bundles?"
            res_margin = LocalAnswer("apptimate_infinity", {"user_id": 1}, q_margin, (q_items,), state=chat_state).run()
            self.assertEqual(res_margin["search_type"], "advisory")
            body_margin = res_margin["response"]
            self.assertIn("Recommended Discount Ceilings", body_margin)
            self.assertIn("5%–8%", body_margin)
            self.assertIn("10%–15%", body_margin)
            self.assertIn("Target Gross Margin", body_margin)
            self.assertNotIn("What is your target margin or discount ceiling", body_margin)
            self.assertNotIn("Quick Follow-Ups to Finalize Your Bundle", body_margin)

            # Follow-up 2: pre-packed Combo SKU vs POS/Price List must answer directly without looping.
            q_setup = "Would you prefer to create a pre-packed Combo SKU or roll out discounts via the POS/Price List?"
            res_setup = LocalAnswer("apptimate_infinity", {"user_id": 1}, q_setup, (q_items, q_margin), state=chat_state).run()
            self.assertEqual(res_setup["search_type"], "advisory")
            body_setup = res_setup["response"]
            self.assertIn("Pre-Packed Combo SKU vs. POS / Price List", body_setup)
            self.assertIn("Specific Items", body_setup)
            self.assertIn("Min Qty", body_setup)
            self.assertIn("Markdown %", body_setup)
            self.assertNotIn("Would you prefer to create a pre-packed Combo SKU", body_setup)
            self.assertNotIn("Quick Follow-Ups to Finalize Your Bundle", body_setup)

            # Follow-up 3: confirmed decision executes focused rollout checklist.
            q_confirm = "Keep discount capped at 8% and roll out via Price Lists"
            res_confirm = LocalAnswer("apptimate_infinity", {"user_id": 1}, q_confirm, (q_items, q_margin, q_setup), state=chat_state).run()
            self.assertEqual(res_confirm["search_type"], "advisory")
            body_confirm = res_confirm["response"]
            self.assertIn("Tailored Combo Rollout Plan", body_confirm)
            self.assertNotIn("Quick Follow-Ups to Finalize Your Bundle", body_confirm)
