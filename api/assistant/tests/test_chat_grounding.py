import json
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, TestCase, override_settings

from assistant.models import ChatUsageLog
from assistant.views import CHAT_MODEL, _is_aggregate_only_result, chat_query, chat_history


def approved_answer_review(prompt_tokens=8, completion_tokens=2):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(
            content='{"valid": true, "reason": "The answer is supported by the retrieved documentation."}'
        ))],
        usage=SimpleNamespace(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        ),
    )


@override_settings(ENABLE_ANSWER_VALIDATION=True)
class ChatGroundingTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def post_chat(self, message, session_id="test-session"):
        request = self.factory.post(
            "/api/chat/",
            data=json.dumps({"message": message, "username": "test-user", "session_id": session_id}),
            content_type="application/json",
            HTTP_X_TENANT_DOMAIN="example.test",
        )
        return chat_query(request)

    @patch("assistant.views.resolve_tenant_database", return_value="apptimate_test")
    @patch("assistant.views.get_item_stock_and_rules")
    @patch("assistant.views.client.chat.completions.create")
    def test_ambiguous_buy_question_gets_a_focused_channel_clarification(
        self, create_completion, stock_lookup, _resolve_tenant
    ):
        payload = json.loads(self.post_chat("Can I buy 19 vitamin C?").content)

        self.assertIn("19 units of **vitamin C**", payload["response"])
        self.assertIn("customer sale", payload["response"])
        self.assertIn("supplier purchase order", payload["response"])
        self.assertIn("no tenant business data was queried", payload["confidence_basis"])
        self.assertEqual(payload["confidence"], 0.0)
        create_completion.assert_not_called()
        stock_lookup.assert_not_called()

    @patch("assistant.views.resolve_tenant_database", return_value="apptimate_test")
    @patch("assistant.views.get_business_schema_context", return_value="")
    @patch("assistant.views.get_item_stock_and_rules")
    @patch("assistant.views.client.chat.completions.create")
    def test_explicit_customer_purchase_routes_to_stock_not_purchase_order_diagnostic(
        self, create_completion, stock_lookup, _schema, _resolve_tenant
    ):
        stock_lookup.return_value = {
            "found": True,
            "item_match_confidence": 100.0,
            "items": [{"item_name": "Vitamin C", "status": "active",
                       "has_variants": False, "is_available_sell": True,
                       "has_stocks": True, "tracking_type": "none", "unit": "tablet",
                       "stock_summary": {"total_available": 25},
                       "warehouses_with_stock": [{"warehouse_name": "Main Store", "warehouse_is_active": True,
                                                  "qty_available": 25, "qty_available_without_batch": 25}]}],
        }
        tool_call = SimpleNamespace(
            id="call_stock",
            function=SimpleNamespace(
                name="check_item_stock_and_rules",
                arguments=json.dumps({"item_query": "incorrect model extraction", "include_pricing": False}),
            ),
        )
        create_completion.side_effect = [
            SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[tool_call], content=None))],
                usage=SimpleNamespace(prompt_tokens=10, completion_tokens=3, total_tokens=13),
            ),
            SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(
                    tool_calls=None, content="Vitamin C is available for a customer sale based on current stock."
                ))],
                usage=SimpleNamespace(prompt_tokens=15, completion_tokens=8, total_tokens=23),
            ),
            approved_answer_review(),
        ]

        payload = json.loads(self.post_chat("Can I buy 19 Vitamin C at checkout?").content)

        stock_lookup.assert_called_once_with("Vitamin C", tenant_identifier="example.test")
        self.assertIn("Yes", payload["response"])
        self.assertIn("Main Store", payload["response"])
        self.assertIn("19 tablet", payload["response"])
        self.assertEqual(create_completion.call_count, 1)

    @patch("assistant.views.resolve_tenant_database", return_value="apptimate_test")
    @patch("assistant.views.get_business_schema_context", return_value="")
    @patch("assistant.views.get_item_stock_and_rules")
    @patch("assistant.views.client.chat.completions.create")
    def test_explicit_sell_quantity_for_customer_routes_to_stock_with_item_and_quantity(
        self, create_completion, stock_lookup, _schema, _resolve_tenant
    ):
        stock_lookup.return_value = {
            "found": True,
            "item_match_confidence": 100.0,
            "items": [{
                "item_name": "Watch",
                "sku": "WATCH-01",
                "status": "active",
                "is_available_sell": True,
                "has_variants": False,
                "has_stocks": True,
                "tracking_type": "none",
                "unit": "Piece",
                "stock_summary": {"total_available": 15},
                "warehouses_with_stock": [{
                    "warehouse_name": "Main Store",
                    "warehouse_is_active": True,
                    "qty_available": 15,
                    "qty_available_without_batch": 15,
                }],
            }],
        }
        tool_call = SimpleNamespace(
            id="call_watch_stock",
            function=SimpleNamespace(
                name="check_item_stock_and_rules",
                arguments=json.dumps({"item_query": "wrong item", "include_pricing": False}),
            ),
        )
        create_completion.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[tool_call], content=None))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=2, total_tokens=12),
        )

        payload = json.loads(self.post_chat("Can I sell 20 watches to a single customer?").content)

        stock_lookup.assert_called_once_with("watches", tenant_identifier="example.test")
        self.assertIn("20 Piece", payload["response"])
        self.assertIn("Main Store", payload["response"])
        self.assertNotIn("Yes—", payload["response"])
        self.assertIn("This is a stock result", payload["response"])
        self.assertEqual(
            create_completion.call_args.kwargs["tool_choice"]["function"]["name"],
            "check_item_stock_and_rules",
        )

    @patch("assistant.views.resolve_tenant_database", return_value="apptimate_test")
    @patch("assistant.views.get_business_schema_context", return_value="")
    @patch("assistant.views.get_item_stock_and_rules")
    @patch("assistant.views.client.chat.completions.create")
    def test_customer_sale_clarification_carries_original_quantity_and_item_into_stock_check(
        self, create_completion, stock_lookup, _schema, _resolve_tenant
    ):
        first = json.loads(self.post_chat("Can I buy 10 water bottle?").content)
        self.assertIn("customer sale", first["response"])
        self.assertIn("supplier purchase order", first["response"])

        stock_lookup.return_value = {
            "found": True,
            "item_match_confidence": 100.0,
            "items": [{
                "item_name": "Water Bottle",
                "sku": "WB-01",
                "status": "active",
                "is_available_sell": True,
                "has_variants": False,
                "has_stocks": True,
                "tracking_type": "none",
                "unit": "Piece",
                "stock_summary": {"total_available": 14},
                "warehouses_with_stock": [{
                    "warehouse_name": "Main Store",
                    "warehouse_is_active": True,
                    "qty_available": 14,
                    "qty_available_without_batch": 14,
                }],
            }],
        }
        tool_call = SimpleNamespace(
            id="call_water_stock",
            function=SimpleNamespace(
                name="check_item_stock_and_rules",
                arguments=json.dumps({"item_query": "water", "include_pricing": False}),
            ),
        )
        create_completion.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[tool_call], content=None))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=2, total_tokens=12),
        )

        payload = json.loads(self.post_chat("for customer sale").content)

        stock_lookup.assert_called_once_with("water bottle", tenant_identifier="example.test")
        self.assertIn("Yes", payload["response"])
        self.assertIn("10 Piece", payload["response"])
        self.assertIn("Main Store", payload["response"])
        self.assertNotIn("purchase order", payload["response"].lower())
        create_completion.assert_called_once()
        self.assertEqual(
            create_completion.call_args.kwargs["tool_choice"]["function"]["name"],
            "check_item_stock_and_rules",
        )

    @override_settings(ENABLE_ANSWER_VALIDATION=False)
    @patch("assistant.views.resolve_tenant_database", return_value="apptimate_test")
    @patch("assistant.views.diagnose_purchase_order_item")
    @patch("assistant.views.get_item_stock_and_rules")
    @patch("assistant.views.client.chat.completions.create")
    def test_supplier_po_clarification_carries_original_item_to_po_diagnostic(
        self, create_completion, stock_lookup, diagnose, _resolve_tenant
    ):
        self.post_chat("Can I buy 10 water bottle?")
        diagnose.return_value = {"item_found": True, "matched_items": []}
        tool_call = SimpleNamespace(
            id="call_water_po",
            function=SimpleNamespace(
                name="diagnose_purchase_order_item",
                arguments=json.dumps({"item_query": "incorrect model extraction"}),
            ),
        )
        create_completion.side_effect = [
            SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[tool_call], content=None))],
                usage=SimpleNamespace(prompt_tokens=10, completion_tokens=2, total_tokens=12),
            ),
            SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(
                    tool_calls=None, content="The purchase-order diagnostic checked Water Bottle."
                ))],
                usage=SimpleNamespace(prompt_tokens=12, completion_tokens=5, total_tokens=17),
            ),
            approved_answer_review(),
        ]

        payload = json.loads(self.post_chat("for supplier purchase order").content)

        diagnose.assert_called_once_with(item_query="water bottle", tenant_identifier="example.test")
        stock_lookup.assert_not_called()
        self.assertIn("purchase-order diagnostic", payload["response"])
        self.assertEqual(
            create_completion.call_args_list[0].kwargs["tool_choice"]["function"]["name"],
            "diagnose_purchase_order_item",
        )

    def test_grouped_aggregate_is_not_treated_as_complete_after_truncation(self):
        result = {
            "query_audit": {
                "selected_fields": [{"aggregate": "SUM"}],
                "group_by": [{"table": "sales", "column": "customer_id"}],
            }
        }

        self.assertFalse(_is_aggregate_only_result(result))

    def test_scalar_aggregate_is_complete_after_truncation_check(self):
        result = {
            "query_audit": {
                "selected_fields": [{"aggregate": "COUNT"}],
                "group_by": [],
            }
        }

        self.assertTrue(_is_aggregate_only_result(result))

    @patch("assistant.views.resolve_tenant_database", return_value="apptimate_test")
    @patch("assistant.views.get_item_stock_and_rules")
    @patch("assistant.views.client.chat.completions.create")
    def test_variant_availability_uses_extracted_iphone_name_and_reports_live_variant_stock(
        self, create_completion, stock_lookup, _resolve_tenant
    ):
        stock_lookup.return_value = {
            "found": True,
            "item_match_confidence": 92.3,
            "items": [{
                "item_name": "iPhone 16",
                "sku": "IPH-16",
                "has_variants": True,
                "stock_summary": {"total_available": 9},
                "variants": [
                    {
                        "variant_name": "Black / 128GB",
                        "sku": "IPH-16-BLK-128",
                        "attribute_values": {"color": "Black", "storage": "128GB"},
                        "status": "active",
                        "stock_summary": {"total_available": 4},
                    },
                    {
                        "variant_name": "Blue / 256GB",
                        "sku": "IPH-16-BLU-256",
                        "attribute_values": {"color": "Blue", "storage": "256GB"},
                        "status": "active",
                        "stock_summary": {"total_available": 0},
                    },
                ],
            }],
        }

        payload = json.loads(self.post_chat(
            "Can you check if a specific size, color, or variant is available for i phone"
        ).content)

        self.assertIn("**iPhone 16** (SKU: IPH-16)", payload["response"])
        self.assertIn("Black / 128GB", payload["response"])
        self.assertIn("Color: Black, Storage: 128GB", payload["response"])
        self.assertIn("available across warehouses: **4**", payload["response"])
        self.assertIn("Blue / 256GB", payload["response"])
        self.assertIn("available across warehouses: **0**", payload["response"])
        self.assertEqual(payload["confidence"], 92.3)
        stock_lookup.assert_called_once_with("iphone", tenant_identifier="example.test")
        create_completion.assert_not_called()

    @patch("assistant.views.resolve_tenant_database", return_value="apptimate_test")
    @patch("assistant.views.get_item_stock_and_rules")
    @patch("assistant.views.client.chat.completions.create")
    def test_variant_availability_keeps_common_misspelling_for_fuzzy_catalog_match(
        self, create_completion, stock_lookup, _resolve_tenant
    ):
        stock_lookup.return_value = {
            "found": True,
            "item_match_confidence": 92.3,
            "items": [{
                "item_name": "iPhone 16",
                "sku": "IPH-16",
                "has_variants": False,
                "stock_summary": {"total_available": 3},
                "variants": [],
            }],
        }

        payload = json.loads(self.post_chat("Is the i Phione variant available?").content)

        self.assertIn("**iPhone 16**", payload["response"])
        self.assertIn("**3** available", payload["response"])
        self.assertEqual(payload["confidence"], 92.3)
        stock_lookup.assert_called_once_with("iphione", tenant_identifier="example.test")
        create_completion.assert_not_called()

    @patch("assistant.views.resolve_tenant_database", return_value="apptimate_test")
    @patch("assistant.views.get_item_stock_and_rules")
    @patch("assistant.views.client.chat.completions.create")
    def test_low_confidence_variant_candidate_is_confirmed_before_stock_is_reported(
        self, create_completion, stock_lookup, _resolve_tenant
    ):
        stock_lookup.return_value = {
            "found": True,
            "item_match_confidence": 80.0,
            "items": [{
                "item_name": "iPhone 16",
                "sku": "IPH-16",
                "has_variants": True,
                "variants": [{
                    "variant_name": "Black / 128GB",
                    "status": "active",
                    "stock_summary": {"total_available": 4},
                }],
            }],
        }

        payload = json.loads(self.post_chat("Is the iPhon variant available?").content)

        self.assertIn("possible catalog match", payload["response"])
        self.assertIn("Please confirm", payload["response"])
        self.assertNotIn("available across warehouses: **4**", payload["response"])
        self.assertEqual(payload["confidence"], 80.0)
        create_completion.assert_not_called()

    @patch("assistant.views.resolve_tenant_database", return_value="apptimate_test")
    @patch("assistant.views.client.chat.completions.create")
    def test_pos_visibility_follow_up_is_answered_as_a_verified_rule(self, create_completion, _resolve_tenant):
        response = self.post_chat(
            "in pos sales when an item showing there then it is a purchsed item no"
        )
        payload = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        self.assertIn("does not prove the item was purchased from a supplier", payload["response"])
        self.assertIn("POS Sales transaction history", payload["response"])
        self.assertEqual(payload["confidence"], 100.0)
        self.assertEqual(payload["confidence_type"], "verified_rule")
        self.assertTrue(payload["confidence_basis"])
        create_completion.assert_not_called()

    @patch("assistant.views.resolve_tenant_database", return_value="apptimate_test")
    @patch("assistant.views.client.chat.completions.create")
    def test_pos_item_without_supplier_question_explains_catalog_and_stock_rules(
        self, create_completion, _resolve_tenant
    ):
        payload = json.loads(self.post_chat(
            "how can some items will be in the pos sales without a supplier"
        ).content)

        self.assertIn("active and marked available for sale", payload["response"])
        self.assertIn("does not require a supplier to be assigned", payload["response"])
        self.assertIn("non-stock items do not use that stock check", payload["response"])
        self.assertIn("purchase orders", payload["response"])
        self.assertEqual(payload["confidence"], 100.0)
        self.assertEqual(payload["confidence_type"], "verified_rule")
        create_completion.assert_not_called()

    @patch("assistant.views.resolve_tenant_database", return_value="apptimate_test")
    @patch("assistant.views.retrieve_relevant_chunks")
    @patch("assistant.views.get_business_schema_context")
    @patch("assistant.views.diagnose_purchase_order_item")
    @patch("assistant.views.client.chat.completions.create")
    def test_purchase_order_receiving_how_to_uses_help_content_not_live_diagnostic(
        self, create_completion, diagnose_item, schema_context, retrieve_chunks, _resolve_tenant
    ):
        references = [{"document_title": "Procurement guide", "section_title": "Goods Receipt", "similarity_score": 0.78}]
        retrieve_chunks.return_value = ("Verified Goods Receipt workflow", references)
        create_completion.side_effect = [
            SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=None, content="Open Goods Receipt to receive the PO."))],
                usage=SimpleNamespace(prompt_tokens=20, completion_tokens=8, total_tokens=28),
            ),
            approved_answer_review(),
        ]

        payload = json.loads(self.post_chat(
            "How do I receive the goods against a purchase order?"
        ).content)

        self.assertIn("Open Goods Receipt", payload["response"])
        self.assertEqual(payload["confidence"], 78.0)
        self.assertEqual(payload["confidence_type"], "model")
        self.assertIn("retrieval score", payload["confidence_basis"])
        self.assertEqual(create_completion.call_count, 2)
        self.assertEqual(create_completion.call_args_list[0].kwargs["tools"], [])
        self.assertEqual(create_completion.call_args_list[0].kwargs["tool_choice"], "none")
        retrieve_chunks.assert_called_once()
        schema_context.assert_not_called()
        diagnose_item.assert_not_called()

    @patch("assistant.views.resolve_tenant_database", return_value="apptimate_test")
    @patch("assistant.views.query_business_data")
    @patch("assistant.views.get_items_below_minimum_stock")
    @patch("assistant.views.client.chat.completions.create")
    def test_below_minimum_report_returns_all_verified_rows_without_generic_query(
        self, create_completion, stock_report, generic_query, _resolve_tenant
    ):
        stock_report.return_value = {
            "comparison": "total available stock across warehouses < item min_stock_level",
            "count": 2,
            "items": [
                {"name": "Blue Widget", "sku": "BW-1", "available_quantity": "3.5000", "min_stock_level": "8.0000"},
                {"name": "Red Widget", "sku": "RW-2", "available_quantity": 0, "min_stock_level": 2},
            ],
        }

        payload = json.loads(self.post_chat(
            "list down all the items with stock quantity lesser than their item master minimum quantity"
        ).content)

        self.assertIn("I found **2** item(s)", payload["response"])
        self.assertIn("**Blue Widget** (SKU: BW-1) — Available: **3.5**; item-master minimum: **8**; below by: **4.5**", payload["response"])
        self.assertIn("**Red Widget** (SKU: RW-2) — Available: **0**; item-master minimum: **2**; below by: **2**", payload["response"])
        self.assertIn("across all warehouses", payload["response"])
        self.assertEqual(payload["confidence"], 100.0)
        self.assertEqual(payload["confidence_type"], "evidence")
        stock_report.assert_called_once_with(tenant_identifier="example.test")
        generic_query.assert_not_called()
        create_completion.assert_not_called()

    @patch("assistant.views.resolve_tenant_database", return_value="apptimate_test")
    @patch("assistant.views.get_items_below_minimum_stock")
    @patch("assistant.views.client.chat.completions.create")
    def test_below_minimum_report_with_missing_level_abstains_at_zero_confidence(
        self, create_completion, stock_report, _resolve_tenant
    ):
        stock_report.return_value = {
            "count": 1,
            "items": [{"name": "Unknown level", "sku": "UL-1", "available_quantity": 0, "min_stock_level": None}],
        }

        payload = json.loads(self.post_chat("show items below minimum stock").content)

        self.assertIn("incomplete or inconsistent minimum-stock data", payload["response"])
        self.assertEqual(payload["confidence"], 0.0)
        self.assertIn("missing a numeric", payload["confidence_basis"])
        create_completion.assert_not_called()

    @patch("assistant.views.resolve_tenant_database", return_value="apptimate_test")
    @patch("assistant.views.client.chat.completions.create")
    def test_greeting_is_deterministic_and_has_numeric_confidence(self, create_completion, _resolve_tenant):
        payload = json.loads(self.post_chat("hello").content)

        self.assertEqual(payload["response"], "Hi! What would you like help with in Apptimate One?")
        self.assertEqual(payload["confidence"], 100.0)
        self.assertEqual(payload["confidence_type"], "evidence")
        create_completion.assert_not_called()

    @patch("assistant.views.resolve_tenant_database", return_value="apptimate_test")
    @patch("assistant.views.query_business_data")
    @patch("assistant.views.get_business_schema_context")
    @patch("assistant.views.retrieve_relevant_chunks")
    @patch("assistant.views.client.chat.completions.create")
    def test_item_master_minimum_definition_uses_verified_product_rule_without_live_lookup(
        self, create_completion, retrieve_chunks, schema_context, business_query, _resolve_tenant
    ):
        payloads = [
            json.loads(self.post_chat(question).content)
            for question in (
                "what is item master minimum",
                "What does the item-master minimum quantity mean?",
                "What is the item-master minimum quantity?",
            )
        ]

        for payload in payloads:
            self.assertIn("optional stock threshold saved on each item", payload["response"])
            self.assertIn("positive available stock below a positive Min Qty is marked **Critical**", payload["response"])
            self.assertIn("zero available stock is labeled **Out of Stock**", payload["response"])
            self.assertIn("separate from **Reorder Level**", payload["response"])
            self.assertEqual(payload["confidence"], 100.0)
            self.assertEqual(payload["confidence_type"], "verified_rule")
            self.assertIn("Stock Overview status rule", payload["confidence_basis"])
        create_completion.assert_not_called()
        retrieve_chunks.assert_not_called()
        schema_context.assert_not_called()
        business_query.assert_not_called()

    @patch("assistant.views.resolve_tenant_database", return_value="apptimate_test")
    @patch("assistant.views.get_warehouses_list")
    @patch("assistant.views.query_business_data")
    @patch("assistant.views.get_business_schema_context")
    @patch("assistant.views.retrieve_relevant_chunks")
    @patch("assistant.views.client.chat.completions.create")
    def test_store_location_list_returns_all_rows_including_inactive_and_zero_stock(
        self, create_completion, retrieve_chunks, schema_context, business_query, location_report, _resolve_tenant
    ):
        location_report.return_value = {
            "total_warehouses": 2,
            "warehouses": [
                {
                    "id": 11,
                    "organization_id": 1,
                    "name": "Main Store",
                    "code": "STORE-01",
                    "location_type": "showroom",
                    "address": None,
                    "city": None,
                    "is_active": 1,
                    "is_default": 1,
                    "total_available_stock": 15,
                    "distinct_items_count": 5,
                },
                {
                    "id": 12,
                    "organization_id": 2,
                    "name": "Outlet East",
                    "code": "OUT-02",
                    "location_type": "warehouse",
                    "address": "4 Lake Street",
                    "city": "Kandy",
                    "is_active": 0,
                    "is_default": 0,
                    "total_available_stock": 0,
                    "distinct_items_count": 0,
                },
            ],
        }

        payload = json.loads(self.post_chat("list down the stores and locations").content)

        self.assertIn("**Main Store**", payload["response"])
        self.assertIn("Organization ID: **1**", payload["response"])
        self.assertIn("Address/city: Not recorded", payload["response"])
        self.assertIn("**Outlet East**", payload["response"])
        self.assertIn("ID: **12**", payload["response"])
        self.assertIn("Location: 4 Lake Street, Kandy", payload["response"])
        self.assertIn("Status: Inactive", payload["response"])
        self.assertIn("Available stock: **0**", payload["response"])
        self.assertEqual(payload["confidence"], 100.0)
        self.assertIn("regardless of active status or stock quantity", payload["confidence_basis"])
        location_report.assert_called_once_with(tenant_identifier="example.test")
        create_completion.assert_not_called()
        retrieve_chunks.assert_not_called()
        schema_context.assert_not_called()
        business_query.assert_not_called()

    @patch("assistant.views.resolve_tenant_database", return_value="apptimate_test")
    @patch("assistant.views.get_warehouses_list")
    @patch("assistant.views.client.chat.completions.create")
    def test_location_count_question_returns_a_count_not_an_unrequested_list(
        self, create_completion, location_report, _resolve_tenant
    ):
        location_report.return_value = {
            "total_warehouses": 3,
            "warehouses": [
                {"name": "A", "is_active": 1, "total_available_stock": 10},
                {"name": "B", "is_active": 0, "total_available_stock": 0},
                {"name": "C", "is_active": 1, "total_available_stock": 2},
            ],
        }

        payload = json.loads(self.post_chat("How many active warehouse locations do we have?").content)

        self.assertEqual(payload["response"], "There are **2** active non-deleted store/location records in the tenant.")
        self.assertNotIn("**A**", payload["response"])
        self.assertEqual(payload["confidence"], 100.0)
        create_completion.assert_not_called()
        location_report.assert_called_once_with(tenant_identifier="example.test")

        stock_payload = json.loads(self.post_chat(
            "How many warehouse locations have stock?",
            session_id="stock-location-count",
        ).content)
        self.assertEqual(
            stock_payload["response"],
            "There are **2** non-deleted store/location records with available stock in the tenant.",
        )

    @patch("assistant.views.resolve_tenant_database", return_value="apptimate_test")
    @patch("assistant.views.query_business_data")
    @patch("assistant.views.get_business_schema_context", return_value="customer schema")
    @patch("assistant.views.retrieve_relevant_chunks", return_value=("", []))
    @patch("assistant.views.client.chat.completions.create")
    def test_live_answer_is_reviewed_against_the_executed_query_and_usage_is_counted(
        self, create_completion, _retrieve, _schema, business_query, _resolve_tenant
    ):
        plan = {
            "base_table": "core_parties",
            "joins": [],
            "select": [{"table": "core_parties", "column": "id", "aggregate": "COUNT", "alias": "count"}],
            "filters": [],
        }
        tool_call = SimpleNamespace(
            id="call_query",
            function=SimpleNamespace(name="query_business_data", arguments=json.dumps({"query_plan": plan})),
        )
        create_completion.side_effect = [
            SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[tool_call], content=None))],
                usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            ),
            SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=None, content="There are 12 active customers."))],
                usage=SimpleNamespace(prompt_tokens=20, completion_tokens=8, total_tokens=28),
            ),
            SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content='{"valid": true, "reason": "The count matches."}'))],
                usage=SimpleNamespace(prompt_tokens=14, completion_tokens=4, total_tokens=18),
            ),
        ]
        business_query.return_value = {
            "row_count": 1,
            "truncated": False,
            "query_audit": {"base_table": "core_parties", "selected_fields": [{"column": "id", "aggregate": "COUNT"}]},
            "results": [{"count": 12}],
        }

        payload = json.loads(self.post_chat("How many active customers do we have?").content)

        self.assertEqual(payload["response"], "There are 12 active customers.")
        self.assertEqual(payload["usage"]["prompt_tokens"], 44)
        self.assertEqual(payload["usage"]["completion_tokens"], 17)
        self.assertEqual(payload["usage"]["total_tokens"], 61)
        self.assertEqual(payload["confidence"], 100.0)
        business_query.assert_called_once_with(
            plan,
            tenant_identifier="example.test",
            user_question="How many active customers do we have?",
        )
        self.assertEqual(create_completion.call_count, 3)

    @patch("assistant.views.resolve_tenant_database", return_value="apptimate_test")
    @patch("assistant.views.query_business_data", return_value={
        "row_count": 1,
        "truncated": False,
        "query_audit": {"base_table": "core_parties"},
        "results": [{"count": 12}],
    })
    @patch("assistant.views.get_business_schema_context", return_value="customer schema")
    @patch("assistant.views.retrieve_relevant_chunks", return_value=("", []))
    @patch("assistant.views.client.chat.completions.create")
    def test_live_answer_is_withheld_when_evidence_review_rejects_it(
        self, create_completion, _retrieve, _schema, _business_query, _resolve_tenant
    ):
        tool_call = SimpleNamespace(
            id="call_query",
            function=SimpleNamespace(
                name="query_business_data",
                arguments=json.dumps({"query_plan": {
                    "base_table": "core_parties",
                    "joins": [],
                    "select": [{"table": "core_parties", "column": "id", "aggregate": "COUNT", "alias": "count"}],
                    "filters": [],
                }}),
            ),
        )
        create_completion.side_effect = [
            SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[tool_call], content=None))],
                usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            ),
            SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=None, content="There are 18 warehouses."))],
                usage=SimpleNamespace(prompt_tokens=20, completion_tokens=8, total_tokens=28),
            ),
            SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content='{"valid": false, "reason": "The answer changes the entity."}'))],
                usage=SimpleNamespace(prompt_tokens=14, completion_tokens=4, total_tokens=18),
            ),
        ]

        payload = json.loads(self.post_chat("How many active customers do we have?").content)

        self.assertIn("couldn't verify that answer", payload["response"])
        self.assertEqual(payload["confidence"], 0.0)
        self.assertIn("validation step", payload["confidence_basis"])
        self.assertEqual(payload["usage"]["total_tokens"], 61)

    @patch("assistant.views.resolve_tenant_database", return_value="apptimate_test")
    @patch("assistant.views.query_business_data", return_value={"row_count": 100, "truncated": True, "results": []})
    @patch("assistant.views.get_business_schema_context", return_value="supplier schema")
    @patch("assistant.views.retrieve_relevant_chunks", return_value=("", []))
    @patch("assistant.views.client.chat.completions.create")
    def test_truncated_live_results_are_reported_as_incomplete_without_model_summary(
        self, create_completion, _retrieve, _schema, _business_query, _resolve_tenant
    ):
        tool_call = SimpleNamespace(
            id="call_query",
            function=SimpleNamespace(
                name="query_business_data",
                arguments=json.dumps({"query_plan": {
                    "base_table": "core_parties",
                    "joins": [],
                    "select": [{"table": "core_parties", "column": "id"}],
                    "filters": [],
                }}),
            ),
        )
        create_completion.side_effect = [SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[tool_call], content=None))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        ), approved_answer_review()]

        payload = json.loads(self.post_chat("List all suppliers").content)

        self.assertIn("can't present this as a complete answer", payload["response"])
        self.assertIn("narrow it", payload["response"])
        self.assertEqual(payload["confidence"], 100.0)
        self.assertEqual(create_completion.call_count, 2)

    @patch("assistant.views.resolve_tenant_database", return_value="apptimate_test")
    @patch("assistant.views.get_warehouses_list")
    @patch("assistant.views.get_business_schema_context")
    @patch("assistant.views.retrieve_relevant_chunks")
    @patch("assistant.views.client.chat.completions.create")
    def test_warehouse_management_question_returns_navigation_not_tenant_records(
        self, create_completion, retrieve_chunks, schema_context, location_report, _resolve_tenant
    ):
        payload = json.loads(self.post_chat("Where do I manage warehouses and branches?").content)

        self.assertIn("Sidebar ➔ Core ➔ Resources ➔ Warehouses", payload["response"])
        self.assertIn("Sidebar ➔ Core ➔ User Management ➔ Organizations", payload["response"])
        self.assertNotIn("store/location record", payload["response"])
        self.assertEqual(payload["confidence"], 100.0)
        self.assertIn("no tenant records were queried", payload["confidence_basis"])
        self.assertEqual(payload["usage"]["total_tokens"], 0)
        self.assertEqual(payload["usage"]["source"], "not_used")
        location_report.assert_not_called()
        schema_context.assert_not_called()
        retrieve_chunks.assert_not_called()
        create_completion.assert_not_called()

    @patch("assistant.views.resolve_tenant_database", return_value="apptimate_test")
    @patch("assistant.views.get_warehouses_list")
    @patch("assistant.views.get_business_schema_context")
    @patch("assistant.views.retrieve_relevant_chunks")
    @patch("assistant.views.client.chat.completions.create")
    def test_warehouse_page_navigation_handles_typos_without_searching_or_querying(
        self, create_completion, retrieve_chunks, schema_context, location_report, _resolve_tenant
    ):
        payload = json.loads(self.post_chat("how can i see wherehouse").content)

        self.assertEqual(
            payload["response"],
            "You can view warehouses at **Sidebar ➔ Core ➔ Resources ➔ Warehouses**.",
        )
        self.assertEqual(payload["confidence"], 100.0)
        self.assertEqual(payload["confidence_type"], "evidence")
        self.assertEqual(payload["usage"]["total_tokens"], 0)
        self.assertEqual(payload["usage"]["source"], "not_used")
        location_report.assert_not_called()
        schema_context.assert_not_called()
        retrieve_chunks.assert_not_called()
        create_completion.assert_not_called()

    @patch("assistant.views.resolve_tenant_database", return_value="apptimate_test")
    @patch("assistant.views.retrieve_navigation_chunks")
    @patch("assistant.views.retrieve_relevant_chunks")
    @patch("assistant.views.get_business_schema_context")
    @patch("assistant.views.client.chat.completions.create")
    @patch("assistant.views._review_generated_answer", return_value=(True, "Supported by route documentation.", 0, 0))
    def test_generic_screen_navigation_uses_route_focused_evidence_before_answering(
        self, review_answer, create_completion, schema_context, semantic_retrieval,
        navigation_retrieval, _resolve_tenant
    ):
        route_evidence = (
            "Terminals: Sidebar ➔ Core ➔ Resources ➔ Terminals. "
            "Terminal Sessions: Sidebar ➔ Sales ➔ POS ➔ Terminal Sessions."
        )
        navigation_retrieval.return_value = (route_evidence, [{
            "chunk_id": 42,
            "document_title": "Apptimate One help",
            "section_title": "Terminal navigation",
            "hierarchy": ["POS", "Global navigation"],
            "similarity_score": 1.0,
            "preview": route_evidence,
            "match_type": "navigation_terms_and_route",
        }])
        payload = json.loads(self.post_chat("how can i see the terminal").content)

        self.assertIn("**Terminals** — **Sidebar ➔ Core ➔ Resources ➔ Terminals**", payload["response"])
        self.assertIn("**Terminal Sessions** — **Sidebar ➔ Sales ➔ POS ➔ Terminal Sessions**", payload["response"])
        self.assertIn("Which one are you looking for?", payload["response"])
        navigation_retrieval.assert_called_once_with("how can i see the terminal", top_k=5)
        semantic_retrieval.assert_not_called()
        schema_context.assert_not_called()
        create_completion.assert_not_called()
        review_answer.assert_not_called()
        self.assertEqual(payload["usage"]["total_tokens"], 0)
        self.assertEqual(payload["usage"]["source"], "not_used")
        self.assertEqual(payload["confidence"], 100.0)

    @patch("assistant.views.resolve_tenant_database", return_value="apptimate_test")
    @patch("assistant.views.retrieve_navigation_chunks")
    @patch("assistant.views.retrieve_relevant_chunks")
    @patch("assistant.views.get_business_schema_context")
    @patch("assistant.views.client.chat.completions.create")
    @patch("assistant.views._review_generated_answer", return_value=(True, "Supported by route documentation.", 0, 0))
    def test_where_is_invoice_is_routed_to_screen_guidance_not_tenant_lookup(
        self, review_answer, create_completion, schema_context, semantic_retrieval,
        navigation_retrieval, _resolve_tenant
    ):
        route_evidence = (
            "Sales Invoices: Sidebar ➔ Sales ➔ Post-Sales ➔ Sales Invoices. "
            "Finance Invoices: Sidebar ➔ Finance ➔ Transactions ➔ Invoices."
        )
        navigation_retrieval.return_value = (route_evidence, [{
            "chunk_id": 43,
            "document_title": "Apptimate One help",
            "section_title": "Invoice navigation",
            "hierarchy": ["Sales", "Finance", "Navigation"],
            "similarity_score": 1.0,
            "preview": route_evidence,
            "match_type": "navigation_terms_and_route",
        }])
        payload = json.loads(self.post_chat("where is invoice").content)

        self.assertIn("**Sales Invoices** — **Sidebar ➔ Sales ➔ Post-Sales ➔ Sales Invoices**", payload["response"])
        self.assertIn("**Invoices** — **Sidebar ➔ Finance ➔ Transactions ➔ Invoices**", payload["response"])
        self.assertIn("Which one are you looking for?", payload["response"])
        navigation_retrieval.assert_called_once_with("where is invoice", top_k=5)
        semantic_retrieval.assert_not_called()
        schema_context.assert_not_called()
        create_completion.assert_not_called()
        review_answer.assert_not_called()
        self.assertEqual(payload["usage"]["total_tokens"], 0)
        self.assertEqual(payload["usage"]["source"], "not_used")
        self.assertEqual(payload["confidence"], 100.0)

    @patch("assistant.views.resolve_tenant_database", return_value="apptimate_test")
    @patch("assistant.views.retrieve_relevant_chunks", return_value=("", []))
    @patch("assistant.views.get_business_schema_context", return_value="")
    @patch("assistant.views.client.chat.completions.create")
    def test_unsupported_model_answer_is_withheld_after_evidence_review(
        self, create_completion, _schema, _retrieve, _resolve_tenant
    ):
        create_completion.side_effect = [
            SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=None, content="Here is a joke."))],
                usage=SimpleNamespace(prompt_tokens=4, completion_tokens=2, total_tokens=6),
            ),
            SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(
                    content='{"valid": false, "reason": "No supporting source was retrieved."}'
                ))],
                usage=SimpleNamespace(prompt_tokens=6, completion_tokens=3, total_tokens=9),
            ),
        ]

        payload = json.loads(self.post_chat("tell me a quick joke").content)

        self.assertIn("couldn't verify that guidance", payload["response"])
        self.assertEqual(payload["confidence"], 0.0)
        self.assertEqual(create_completion.call_args_list[0].kwargs["model"], CHAT_MODEL)
        self.assertEqual(create_completion.call_args_list[0].kwargs["reasoning_effort"], "none")
        self.assertEqual(create_completion.call_args_list[0].kwargs["tool_choice"], "auto")
        self.assertIn("request_clarification", [tool["function"]["name"] for tool in create_completion.call_args_list[0].kwargs["tools"]])
        self.assertNotIn("temperature", create_completion.call_args_list[0].kwargs)

    @patch("assistant.views.resolve_tenant_database", return_value="apptimate_test")
    @patch("assistant.views.get_business_schema_context")
    @patch("assistant.views.retrieve_relevant_chunks")
    @patch("assistant.views.client.chat.completions.create")
    def test_pos_screen_question_uses_kb_evidence_without_live_tools(
        self, create_completion, retrieve_chunks, schema_context, _resolve_tenant
    ):
        retrieve_chunks.return_value = (
            "The POS Sales page lists recorded point-of-sale transactions.",
            [{"chunk_id": 9, "document_title": "Help", "section_title": "POS Sales", "hierarchy": [],
              "similarity_score": 0.74, "preview": "POS transaction history"}],
        )
        create_completion.side_effect = [
            SimpleNamespace(
                choices=[SimpleNamespace(
                    message=SimpleNamespace(tool_calls=None, content="POS Sales is the transaction-history page.")
                )],
                usage=SimpleNamespace(prompt_tokens=20, completion_tokens=8, total_tokens=28),
            ),
            approved_answer_review(),
        ]

        payload = json.loads(self.post_chat("What does the POS Sales page show?").content)

        self.assertIn("transaction-history page", payload["response"])
        self.assertEqual(payload["confidence"], 74.0)
        self.assertEqual(payload["confidence_type"], "model")
        self.assertEqual(payload["usage"]["source"], "provider")
        self.assertEqual(payload["usage"]["total_tokens"], 38)
        self.assertIn("cosine similarity", payload["confidence_basis"])
        self.assertEqual(create_completion.call_args_list[0].kwargs["tools"], [])
        self.assertEqual(create_completion.call_args_list[0].kwargs["tool_choice"], "none")
        schema_context.assert_not_called()

    @patch("assistant.views.resolve_tenant_database", return_value="apptimate_test")
    @patch("assistant.views.get_business_schema_context")
    @patch("assistant.views.retrieve_relevant_chunks")
    @patch("assistant.views.client.chat.completions.create")
    def test_general_concept_question_uses_markdown_evidence_not_live_tenant_data(
        self, create_completion, retrieve_chunks, schema_context, _resolve_tenant
    ):
        retrieve_chunks.return_value = (
            "A purchase order is a procurement document that records an order to a supplier.",
            [{"chunk_id": 21, "document_title": "Procurement Guide", "section_title": "Purchase Orders",
              "hierarchy": [], "similarity_score": 0.91, "preview": "Records an order to a supplier"}],
        )
        create_completion.side_effect = [
            SimpleNamespace(
                choices=[SimpleNamespace(
                    message=SimpleNamespace(tool_calls=None, content="A purchase order records goods or services ordered from a supplier.")
                )],
                usage=SimpleNamespace(prompt_tokens=18, completion_tokens=11, total_tokens=29),
            ),
            approved_answer_review(),
        ]

        payload = json.loads(self.post_chat("What is a purchase order?").content)

        self.assertIn("records goods or services ordered from a supplier", payload["response"])
        self.assertEqual(payload["confidence"], 91.0)
        self.assertEqual(payload["confidence_type"], "model")
        retrieve_chunks.assert_called_once()
        schema_context.assert_not_called()
        self.assertEqual(create_completion.call_args_list[0].kwargs["tools"], [])

    @patch("assistant.views.resolve_tenant_database", return_value="apptimate_test")
    @patch("assistant.views.get_business_schema_context")
    @patch("assistant.views.retrieve_relevant_chunks")
    @patch("assistant.views.client.chat.completions.create")
    def test_sales_growth_page_guidance_does_not_force_live_data_tool(
        self, create_completion, retrieve_chunks, schema_context, _resolve_tenant
    ):
        retrieve_chunks.return_value = (
            "The Sales Growth page summarizes sales trends over time.",
            [{"chunk_id": 10, "document_title": "Help", "section_title": "Sales Growth",
              "hierarchy": [], "similarity_score": 0.81, "preview": "Sales trends over time"}],
        )
        create_completion.side_effect = [
            SimpleNamespace(
                choices=[SimpleNamespace(
                    message=SimpleNamespace(tool_calls=None, content="It summarizes sales trends over time.")
                )],
                usage=SimpleNamespace(prompt_tokens=20, completion_tokens=8, total_tokens=28),
            ),
            approved_answer_review(),
        ]

        payload = json.loads(self.post_chat("What does the sales growth page show?").content)

        self.assertEqual(payload["confidence"], 81.0)
        self.assertEqual(create_completion.call_args_list[0].kwargs["tools"], [])
        self.assertEqual(create_completion.call_args_list[0].kwargs["tool_choice"], "none")
        schema_context.assert_not_called()

    @patch("assistant.views.resolve_tenant_database", return_value="apptimate_test")
    @patch("assistant.views.client.chat.completions.create")
    def test_verified_supplier_rules_do_not_depend_on_model(self, create_completion, _resolve_tenant):
        response = self.post_chat("is it possible to have items woithout the supplire")
        payload = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        self.assertIn("item can exist in the catalog without a supplier", payload["response"])
        self.assertEqual(payload["confidence"], 100.0)
        self.assertEqual(payload["confidence_type"], "verified_rule")
        create_completion.assert_not_called()

        history_request = self.factory.get(
            "/api/history/", {"username": "test-user", "session_id": "test-session"}
        )
        history_payload = json.loads(chat_history(history_request).content)
        bot_message = history_payload["history"][1]
        self.assertEqual(bot_message["metrics"]["confidenceType"], "verified_rule")
        self.assertEqual(bot_message["metrics"]["confidence"], 100.0)
        self.assertTrue(bot_message["metrics"]["confidenceBasis"])

    @patch("assistant.views.resolve_tenant_database", return_value="apptimate_test")
    @patch("assistant.views.client.chat.completions.create")
    def test_supplier_source_question_without_item_asks_for_item_instead_of_guessing(
        self, create_completion, _resolve_tenant
    ):
        response = self.post_chat("without any supplier where does it come from?")
        payload = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        self.assertIn("that alone doesn't show where its stock came from", payload["response"])
        self.assertIn("Which item do you mean?", payload["response"])
        self.assertEqual(payload["confidence"], 100.0)
        self.assertEqual(payload["confidence_type"], "verified_rule")
        create_completion.assert_not_called()

    @patch("assistant.views.resolve_tenant_database", return_value="apptimate_test")
    @patch("assistant.views.get_business_schema_context")
    @patch("assistant.views.get_item_stock_and_rules")
    @patch("assistant.views.query_business_data")
    @patch("assistant.views.client.chat.completions.create")
    def test_stock_question_without_item_clarifies_without_running_a_lookup(
        self, create_completion, generic_query, stock_lookup, schema_context, _resolve_tenant
    ):
        payload = json.loads(self.post_chat("Is it in stock?").content)

        self.assertIn("Which item are you asking about?", payload["response"])
        self.assertIn("name or SKU", payload["response"])
        self.assertEqual(payload["confidence"], 100.0)
        self.assertEqual(payload["confidence_type"], "evidence")
        self.assertIn("no live stock lookup was run", payload["confidence_basis"])
        self.assertEqual(payload["usage"]["total_tokens"], 0)
        create_completion.assert_not_called()
        generic_query.assert_not_called()
        stock_lookup.assert_not_called()
        schema_context.assert_not_called()

    @patch("assistant.views.resolve_tenant_database", return_value="apptimate_test")
    @patch("assistant.views.get_business_schema_context", return_value="")
    @patch("assistant.views.client.chat.completions.create")
    @patch("assistant.views.diagnose_purchase_order_item")
    def test_supplier_history_without_records_does_not_invent_suppliers(
        self, diagnose_item, create_completion, _schema, _resolve_tenant
    ):
        tool_call = SimpleNamespace(
            id="call_1",
            function=SimpleNamespace(
                name="diagnose_purchase_order_item",
                arguments='{"item_query":"phone"}',
            ),
        )
        completion = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[tool_call], content=None))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=4, total_tokens=14),
        )
        create_completion.return_value = completion
        diagnose_item.return_value = {
            "item_found": True,
            "item_match_confidence": 100.0,
            "matched_items": [{
                "name": "Phone",
                "sku": "PHONE-001",
                "suppliers_with_recorded_purchase_orders": [],
                "suppliers_with_recorded_goods_receipts": [],
                "supplier_history_sources_checked": ["purchase_orders", "goods_receipts"],
            }],
        }

        response = self.post_chat("phone supplier details")
        payload = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        self.assertIn("No supplier was found", payload["response"])
        self.assertNotIn("active supplier", payload["response"].lower())
        self.assertEqual(payload["confidence"], 100.0)
        self.assertEqual(payload["confidence_type"], "evidence")
        diagnose_item.assert_called_once_with(item_query="phone", tenant_identifier="example.test")

    @patch("assistant.views.resolve_tenant_database", return_value="apptimate_test")
    @patch("assistant.views.get_business_schema_context", return_value="")
    @patch("assistant.views.client.chat.completions.create")
    @patch("assistant.views.diagnose_purchase_order_item", return_value={"error": "database offline"})
    def test_supplier_lookup_failure_returns_numeric_evidence_confidence(
        self, _diagnose_item, create_completion, _schema, _resolve_tenant
    ):
        tool_call = SimpleNamespace(
            id="call_1",
            function=SimpleNamespace(
                name="diagnose_purchase_order_item",
                arguments='{"item_query":"phone"}',
            ),
        )
        create_completion.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[tool_call], content=None))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=4, total_tokens=14),
        )

        payload = json.loads(self.post_chat("phone supplier details").content)

        self.assertIn("couldn't verify supplier purchase history", payload["response"])
        self.assertEqual(payload["confidence"], 0.0)
        self.assertEqual(payload["confidence_type"], "evidence")
        self.assertIn("lookup failed", payload["confidence_basis"])

    @patch("assistant.views.resolve_tenant_database", return_value="apptimate_test")
    @patch("assistant.views.is_likely_live_data_question", return_value=True)
    @patch("assistant.views.get_business_schema_context", return_value="")
    @patch("assistant.views.client.chat.completions.create")
    def test_live_question_without_tool_result_does_not_use_model_guess(
        self, create_completion, _schema, _live_question, _resolve_tenant
    ):
        create_completion.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=None, content="There are 20 items."))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=4, total_tokens=14),
        )

        payload = json.loads(self.post_chat("how many items are available now").content)

        self.assertIn("couldn't verify this from the live tenant data", payload["response"])
        self.assertNotIn("20 items", payload["response"])
        self.assertEqual(payload["confidence"], 0.0)
        self.assertEqual(payload["confidence_type"], "evidence")

    @patch("assistant.views.resolve_tenant_database", return_value="apptimate_test")
    @patch("assistant.views.get_business_schema_context")
    @patch("assistant.views.retrieve_relevant_chunks", return_value=("", []))
    @patch("assistant.views.client.chat.completions.create")
    def test_product_guidance_without_relevant_documentation_abstains(
        self, create_completion, retrieve_chunks, schema_context, _resolve_tenant
    ):
        payload = json.loads(self.post_chat("How do I create a return?").content)

        self.assertIn("couldn't find a sufficiently relevant, verified help section", payload["response"])
        self.assertEqual(payload["retrieved_references"], [])
        self.assertEqual(payload["confidence"], 0.0)
        self.assertEqual(payload["confidence_type"], "evidence")
        create_completion.assert_not_called()
        retrieve_chunks.assert_called_once()
        schema_context.assert_not_called()

    @patch("assistant.views.resolve_tenant_database", return_value="apptimate_test")
    @patch("assistant.views.get_business_schema_context", return_value="")
    @patch("assistant.views.client.chat.completions.create")
    @patch("assistant.views.diagnose_purchase_order_item")
    def test_incomplete_supplier_history_schema_does_not_claim_no_history(
        self, diagnose_item, create_completion, _schema, _resolve_tenant
    ):
        tool_call = SimpleNamespace(
            id="call_1",
            function=SimpleNamespace(name="diagnose_purchase_order_item", arguments='{"item_query":"phone"}'),
        )
        create_completion.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[tool_call], content=None))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=4, total_tokens=14),
        )
        diagnose_item.return_value = {
            "item_found": True,
            "item_match_confidence": 100.0,
            "matched_items": [{
                "name": "Phone",
                "sku": "PHONE-001",
                "suppliers_with_recorded_purchase_orders": [],
                "suppliers_with_recorded_goods_receipts": [],
                "supplier_history_sources_checked": ["purchase_orders"],
            }],
        }

        payload = json.loads(self.post_chat("phone supplier details").content)

        self.assertIn("couldn't verify whether it has supplier history", payload["response"])
        self.assertNotIn("No supplier was found", payload["response"])

    def test_older_chat_history_without_confidence_metadata_does_not_invent_zero_score(self):
        ChatUsageLog.objects.create(
            user_id="test-user",
            session_id="legacy-session",
            user_message="A legacy question",
            bot_response="A legacy response",
        )

        response = self.factory.get(
            "/api/history/", {"username": "test-user", "session_id": "legacy-session"}
        )
        payload = json.loads(chat_history(response).content)

        self.assertIsNone(payload["history"][1]["metrics"]["confidence"])
        self.assertEqual(payload["history"][1]["metrics"]["confidenceType"], "evidence")
        self.assertEqual(payload["history"][1]["metrics"]["tokenSource"], "not_used")
        self.assertIn("earlier response", payload["history"][1]["metrics"]["confidenceBasis"])

    @override_settings(ENABLE_ANSWER_VALIDATION=False)
    @patch("assistant.views.resolve_tenant_database", return_value="apptimate_test")
    @patch("assistant.views.get_business_schema_context")
    @patch("assistant.views.retrieve_navigation_chunks")
    @patch("assistant.views.retrieve_relevant_chunks")
    @patch("assistant.views.client.chat.completions.create")
    def test_default_mode_answers_without_strict_evidence_rejection(
        self, create_completion, retrieve_chunks, retrieve_nav_chunks, schema_context, _resolve_tenant
    ):
        mock_retrieval = (
            "POS documentation with basic route information.",
            [{"similarity_score": 0.88, "section": "POS", "preview": "POS sales counter"}],
        )
        retrieve_chunks.return_value = mock_retrieval
        retrieve_nav_chunks.return_value = mock_retrieval
        create_completion.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(
                tool_calls=None,
                content="You can find POS Sales at Sidebar ➔ Sales ➔ POS ➔ POS Sales. Clicking New Sale opens checkout."
            ))],
            usage=SimpleNamespace(prompt_tokens=20, completion_tokens=15, total_tokens=35),
        )

        payload = json.loads(self.post_chat("where is pos sales").content)

        # Confirm the model's actual answer is preserved, not rejected or overwritten
        self.assertIn("Sidebar ➔ Sales ➔ POS ➔ POS Sales", payload["response"])
        self.assertIn("New Sale", payload["response"])
        self.assertNotIn("I couldn't verify that guidance", payload["response"])
        self.assertEqual(payload["confidence"], 88.0)
        self.assertEqual(payload["confidence_type"], "model")


class MultiQueryContinuationTests(TestCase):
    @override_settings(ENABLE_ANSWER_VALIDATION=True)
    @patch('assistant.views.resolve_tenant_database', return_value='apptimate_test')
    @patch('assistant.views.get_business_schema_context', return_value='payroll schema')
    @patch('assistant.views.retrieve_relevant_chunks', return_value=('', []))
    @patch('assistant.views.query_business_data')
    @patch('assistant.views.client.chat.completions.create')
    def test_reconciliation_can_read_header_after_detail_result(self, completion, query, _docs, _schema, _tenant):
        def response(message):
            return SimpleNamespace(choices=[SimpleNamespace(message=message)],
                usage=SimpleNamespace(prompt_tokens=5, completion_tokens=2, total_tokens=7))
        def call(table, field):
            return SimpleNamespace(id=table, function=SimpleNamespace(name='query_business_data', arguments=json.dumps(
                {'query_plan': {'base_table': table, 'select': [{'table': table, 'column': field}]}})))
        completion.side_effect = [
            response(SimpleNamespace(tool_calls=[call('hr_payroll_lines', 'net_pay')], content=None)),
            response(SimpleNamespace(tool_calls=[call('hr_payroll_runs', 'total_net')], content=None)),
            response(SimpleNamespace(tool_calls=None, content='The payroll lines and run header both total 144000.')),
            approved_answer_review(),
        ]
        query.side_effect = [{'results': [{'net_pay': 144000}]}, {'results': [{'total_net': 144000}]}]
        request = RequestFactory().post('/api/chat/', content_type='application/json',
            data=json.dumps({'message': 'Reconcile payroll run ID 7 lines with its stored run total.', 'username': 'continuation-test'}),
            HTTP_X_TENANT_DOMAIN='example.test')
        payload = json.loads(chat_query(request).content)
        self.assertEqual(query.call_count, 2)
        self.assertIn('144000', payload['response'])
        self.assertEqual(completion.call_count, 4)
        self.assertEqual(payload['usage']['total_tokens'], payload['usage']['prompt_tokens'] + payload['usage']['completion_tokens'])
