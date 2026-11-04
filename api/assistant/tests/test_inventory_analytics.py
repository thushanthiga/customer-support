import json
from decimal import Decimal
from unittest.mock import MagicMock
from unittest.mock import patch

from django.test import RequestFactory, TestCase

from assistant.db_service import get_item_master_threshold_summary
from assistant.views import chat_query


class InventoryAnalyticsRoutingTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def post_chat(self, message):
        request = self.factory.post(
            "/api/chat/",
            data=json.dumps({"message": message, "username": "inventory-test", "session_id": "inventory-analytics"}),
            content_type="application/json",
            HTTP_X_TENANT_DOMAIN="example.test",
        )
        return chat_query(request)

    @patch("assistant.views.resolve_tenant_database", return_value="apptimate_test")
    @patch("assistant.views.get_item_master_threshold_summary")
    def test_master_maximum_question_with_common_typo_uses_live_threshold_summary(
        self, threshold_summary, _resolve_tenant
    ):
        threshold_summary.return_value = {
            "tenant_database": "apptimate_test",
            "max_qty_configured": 2,
            "min_qty_configured": 1,
            "max_items": [
                {"name": "Widget A", "sku": "W-A", "value": "12.0000"},
                {"name": "Widget B", "sku": "W-B", "value": "5.0000"},
            ],
            "min_items": [{"name": "Widget A", "sku": "W-A", "value": "2.0000"}],
        }

        payload = json.loads(self.post_chat("is there any mster maximum quantity").content)

        self.assertIn("Max Qty is configured on 2 active item(s)", payload["response"])
        self.assertIn("Widget A (SKU: W-A) — 12.0000", payload["response"])
        self.assertIn("Min Qty is configured on 1 active item(s)", payload["response"])
        self.assertEqual(payload["confidence"], 100.0)
        threshold_summary.assert_called_once_with(tenant_identifier="example.test")

    @patch("assistant.views.resolve_tenant_database", return_value="apptimate_test")
    @patch("assistant.views.get_items_below_maximum_stock")
    def test_below_item_master_maximum_question_routes_to_threshold_comparison_report(
        self, below_maximum_report, _resolve_tenant
    ):
        below_maximum_report.return_value = {
            "tenant_database": "apptimate_test",
            "count": 2,
            "items": [
                {"name": "Widget A", "sku": "W-A", "available_quantity": "3.0000", "max_stock_level": "12.0000"},
                {"name": "Widget B", "sku": "W-B", "available_quantity": "0.0000", "max_stock_level": "5.0000"},
            ],
        }

        payload = json.loads(self.post_chat(
            "List all items with stock quantity lesser than their item master maximumquantity"
        ).content)

        self.assertIn("I found **2** item(s) below their item-master maximum", payload["response"])
        self.assertIn("**Widget A** (SKU: W-A)", payload["response"])
        self.assertIn("Available: **3**; item-master maximum: **12**", payload["response"])
        self.assertIn("**Widget B** (SKU: W-B)", payload["response"])
        self.assertEqual(payload["confidence"], 100.0)
        below_maximum_report.assert_called_once_with(tenant_identifier="example.test")


class ItemMasterThresholdQueryTests(TestCase):
    @patch("assistant.db_service.resolve_tenant_database", return_value="apptimate_test")
    @patch("assistant.db_service.get_tenant_connection")
    def test_threshold_summary_counts_only_positive_values_on_active_items(self, get_connection, _resolve_tenant):
        connection = MagicMock()
        cursor = MagicMock()
        connection.__enter__.return_value = connection
        connection.cursor.return_value = cursor
        cursor.__enter__.return_value = cursor
        cursor.fetchall.return_value = [
            {"id": 1, "name": "Configured", "sku": "CFG", "min_stock_level": Decimal("2"), "max_stock_level": Decimal("5")},
            {"id": 2, "name": "Zero fields", "sku": "ZERO", "min_stock_level": Decimal("0"), "max_stock_level": Decimal("0")},
            {"id": 3, "name": "No fields", "sku": "NULL", "min_stock_level": None, "max_stock_level": None},
        ]
        get_connection.return_value = connection

        result = get_item_master_threshold_summary("example.test")

        sql = cursor.execute.call_args.args[0]
        self.assertIn("status = 'active'", sql)
        self.assertEqual(result["max_qty_configured"], 1)
        self.assertEqual(result["min_qty_configured"], 1)
        self.assertEqual([item["sku"] for item in result["max_items"]], ["CFG"])

