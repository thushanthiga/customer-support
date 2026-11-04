"""Comprehensive test cases for multi-turn conversational follow-up queries.

Validates that conversational follow-ups (e.g. 'for vitamin c', 'why for vitamin c',
'what about phone', 'and car toy', 'tablet?') dynamically inherit live-data
and diagnostic intent from recent session context across all scenarios without
requiring ad-hoc or temporary keyword matching.
"""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings

from assistant.models import ChatUsageLog
from assistant.views import (
    _detect_conversational_followup_intent,
    chat_query,
)


class ConversationalFollowUpIntentUnitTests(SimpleTestCase):
    """Unit tests for multi-turn conversational follow-up intent detection."""

    def setUp(self):
        self.po_log = SimpleNamespace(
            user_message="what ia the maxmimum purchase count of car toy",
            confidence_basis="The response was generated from a successful tenant-scoped live-data result.",
        )
        self.stock_log = SimpleNamespace(
            user_message="can i sell 6 vitaminc",
            confidence_basis="The response was generated from a successful tenant-scoped live-data result.",
        )
        self.thanks_log = SimpleNamespace(
            user_message="thanks",
            confidence_basis="Deterministic greeting; no product or tenant facts were asserted.",
        )

    def test_purchase_order_followup_phrasings_inherit_diagnostic_intent(self):
        """All natural conversational follow-up variations must inherit PO diagnostic intent."""
        phrasings = [
            "for vitamin c",
            "why for vitamin c",
            "what about vitamin c",
            "how about vitamin c",
            "and vitamin c",
            "vitamin c",
            "vitamin c?",
            "same for vitamin c",
            "what of vitamin c",
            "in case of vitamin c",
            "as for vitamin c",
            "can you check vitamin c as well",
            "check vitamin c too",
            "also check vitamin c",
            "is it the same for vitamin c",
        ]
        for phrase in phrasings:
            with self.subTest(phrase=phrase):
                is_live, is_po = _detect_conversational_followup_intent(phrase, [self.po_log])
                self.assertTrue(is_live, f"Expected is_live=True for '{phrase}'")
                self.assertTrue(is_po, f"Expected is_po=True for '{phrase}'")

    def test_purchase_order_followups_work_for_diverse_item_names(self):
        """Follow-up inheritance must be generalized for any item, SKU, or product name."""
        items = [
            "phone",
            "iPhone 16",
            "MED-COT-01",
            "paracetamol 500mg",
            "laptop computer",
            "gold ring 22k",
            "TOY-CAR-99",
        ]
        for item in items:
            with self.subTest(item=item):
                is_live, is_po = _detect_conversational_followup_intent(f"for {item}", [self.po_log])
                self.assertTrue(is_live, f"Expected is_live=True for 'for {item}'")
                self.assertTrue(is_po, f"Expected is_po=True for 'for {item}'")

    def test_stock_followups_inherit_live_data_without_forcing_po_diagnostic(self):
        """When following up on a stock/selling question, live data must be active but not PO help."""
        stock_followups = [
            "for car toy",
            "what about phone",
            "and for watch",
            "laptop",
            "same for paracetamol",
            "check toy car too",
        ]
        for phrase in stock_followups:
            with self.subTest(phrase=phrase):
                is_live, is_po = _detect_conversational_followup_intent(phrase, [self.stock_log])
                self.assertTrue(is_live, f"Expected is_live=True for '{phrase}'")
                self.assertFalse(is_po, f"Expected is_po=False for '{phrase}'")

    def test_substantive_context_survives_intervening_pleasantries(self):
        """If the user says 'thanks' or 'ok', subsequent follow-ups still link to the earlier inquiry."""
        history_with_thanks = [self.po_log, self.thanks_log]
        is_live, is_po = _detect_conversational_followup_intent("what about vitamin c", history_with_thanks)
        self.assertTrue(is_live)
        self.assertTrue(is_po)

    def test_navigation_and_greetings_never_misclassified_as_followups(self):
        """Standard navigation, documentation, and greeting questions must not inherit live data."""
        non_followups = [
            "where is the purchase order page",
            "where can i see inventory",
            "how to access settings",
            "what is a purchase order",
            "explain minimum stock level",
            "hello",
            "good morning",
        ]
        for phrase in non_followups:
            with self.subTest(phrase=phrase):
                is_live, is_po = _detect_conversational_followup_intent(phrase, [self.po_log])
                self.assertFalse(is_live, f"Expected is_live=False for non-followup '{phrase}'")
                self.assertFalse(is_po, f"Expected is_po=False for non-followup '{phrase}'")

    def test_explicit_operation_overrides_history(self):
        """If the user asks an explicit new operation like selling, PO history does not override it."""
        is_live, is_po = _detect_conversational_followup_intent("can i sell vitamin c", [self.po_log])
        self.assertFalse(is_po, "Explicit sell operation should not inherit PO diagnostic mode")


@override_settings(ENABLE_ANSWER_VALIDATION=False)
class ConversationalFollowUpChatIntegrationTests(TestCase):
    """End-to-end integration tests verifying that chat_query provides tools for follow-up turns."""

    def setUp(self):
        self.factory = RequestFactory()
        self.username = "eval_user"
        self.session_id = "test_multi_turn_session"
        self.tenant_id = "example.test"

    def _post(self, message):
        request = self.factory.post(
            "/assistant/chat/",
            data=json.dumps({
                "message": message,
                "username": self.username,
                "session_id": self.session_id,
                "tenant_identifier": self.tenant_id,
            }),
            content_type="application/json",
            HTTP_X_TENANT_DOMAIN=self.tenant_id,
        )
        return chat_query(request)

    @patch("assistant.views.resolve_tenant_database", return_value="apptimate_test")
    @patch("assistant.views.get_business_schema_context", return_value="")
    @patch("assistant.views.diagnose_purchase_order_item")
    @patch("assistant.views.client.chat.completions.create")
    def test_po_diagnostic_followup_provides_tools_and_answers_accurately(
        self, mock_create, mock_diagnose, _schema, _resolve
    ):
        """Turn 1 asks for car toy purchase count; Turn 2 asks 'for vitamin c'.
        Turn 2 must receive tools and invoke diagnose_purchase_order_item."""
        # Setup Turn 1 in ChatUsageLog
        ChatUsageLog.objects.create(
            user_id=self.username,
            session_id=self.session_id,
            user_message="what ia the maxmimum purchase count of car toy",
            bot_response="There's no fixed maximum purchase count shown for Toy car.",
            confidence=100.0,
            confidence_type="evidence",
            confidence_basis="The response was generated from a successful tenant-scoped live-data result.",
        )

        # Mock tool return for vitamin c
        mock_diagnose.return_value = {
            "item_found": True,
            "item_match_confidence": 95.0,
            "matched_items": [{
                "name": "vitamin C",
                "sku": "MED-COT-01",
                "status": "active",
                "purchase_enabled": True,
                "unit": {"name": "Pieces"},
                "stock": {"available": 189},
                "recent_purchase_orders": [{
                    "po_number": "PO-2026-00016",
                    "status": "completed",
                    "quantity": 100,
                    "received_quantity": 100,
                }],
                "outstanding_purchase_orders": [],
                "purchase_order_validation": "Quantity > 0 required, no maximum set.",
            }],
        }

        # Mock OpenAI completions:
        # 1st call triggers diagnose_purchase_order_item
        tool_call = SimpleNamespace(
            id="call_vitaminc_1",
            function=SimpleNamespace(
                name="diagnose_purchase_order_item",
                arguments='{"item_query": "vitamin c"}',
            ),
        )
        first_completion = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[tool_call], content=None))],
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=15, total_tokens=115),
        )
        second_completion = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(
                tool_calls=None,
                content="For Vitamin C, there is no fixed maximum purchase quantity. It is active with 189 pieces in stock.",
            ))],
            usage=SimpleNamespace(prompt_tokens=150, completion_tokens=30, total_tokens=180),
        )
        evidence_review = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(
                content='{"valid": true, "reason": "The item status, available stock and purchase rule match the tenant result."}'
            ))],
            usage=SimpleNamespace(prompt_tokens=20, completion_tokens=5, total_tokens=25),
        )
        mock_create.side_effect = [first_completion, second_completion, evidence_review]

        # Send Turn 2: 'for vitamin c'
        response = self._post("for vitamin c")
        data = json.loads(response.content)

        # Verifications
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["confidence"], 100.0)
        self.assertEqual(data["confidence_type"], "evidence")
        self.assertIn("tenant-scoped live-data result", data["confidence_basis"])
        self.assertIn("Vitamin C", data["response"])

        # Crucial check: mock_create MUST have been called with tools populated
        first_call_kwargs = mock_create.call_args_list[0].kwargs
        self.assertTrue(
            first_call_kwargs.get("tools"),
            "Expected 'tools' to be provided to client.chat.completions.create for follow-up turn",
        )
        tool_names = [t["function"]["name"] for t in first_call_kwargs["tools"]]
        self.assertIn("diagnose_purchase_order_item", tool_names)

        # Verify diagnose_purchase_order_item was called
        mock_diagnose.assert_called_once()

    @patch("assistant.views.resolve_tenant_database", return_value="apptimate_test")
    @patch("assistant.views.get_business_schema_context", return_value="")
    @patch("assistant.views.get_item_stock_and_rules")
    @patch("assistant.views.client.chat.completions.create")
    def test_stock_followup_provides_stock_tool(
        self, mock_create, mock_stock, _schema, _resolve
    ):
        """Turn 1 asks 'can i sell 6 vitaminc'; Turn 2 asks 'for car toy'.
        Turn 2 must receive tools and invoke check_item_stock_and_rules."""
        ChatUsageLog.objects.create(
            user_id=self.username,
            session_id=self.session_id,
            user_message="can i sell 6 vitaminc",
            bot_response="Yes, Vitamin C has 189 units available.",
            confidence=100.0,
            confidence_type="evidence",
            confidence_basis="The response was generated from a successful tenant-scoped live-data result.",
        )

        mock_stock.return_value = {
            "found": True,
            "item_match_confidence": 98.0,
            "items": [{
                "item_name": "Toy car",
                "sku": "TOY-CAR-01",
                "has_variants": False, "has_stocks": True, "tracking_type": "none", "unit": "Piece",
                "warehouses_with_stock": [{"warehouse_name": "Main warehouse 2", "warehouse_is_active": True, "qty_available": 19}],
                "status": "active",
                "is_available_sell": True,
                "stock_summary": {"total_available": 19},
            }],
        }

        tool_call = SimpleNamespace(
            id="call_toy_1",
            function=SimpleNamespace(
                name="check_item_stock_and_rules",
                arguments='{"item_query": "car toy"}',
            ),
        )
        first_completion = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[tool_call], content=None))],
            usage=SimpleNamespace(prompt_tokens=80, completion_tokens=15, total_tokens=95),
        )
        second_completion = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(
                tool_calls=None,
                content="For Toy car, you have 19 units available in Main warehouse 2.",
            ))],
            usage=SimpleNamespace(prompt_tokens=120, completion_tokens=25, total_tokens=145),
        )
        mock_create.side_effect = [first_completion, second_completion]

        response = self._post("for car toy")
        data = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["confidence"], 100.0)
        self.assertEqual(data["confidence_type"], "evidence")
        self.assertIn("Toy car", data["response"])
        self.assertIn("6 Piece", data["response"])
        mock_stock.assert_called_once_with("car toy", tenant_identifier="example.test")

        first_call_kwargs = mock_create.call_args_list[0].kwargs
        self.assertTrue(first_call_kwargs.get("tools"))
        tool_names = [t["function"]["name"] for t in first_call_kwargs["tools"]]
        self.assertIn("check_item_stock_and_rules", tool_names)
        mock_stock.assert_called_once()
