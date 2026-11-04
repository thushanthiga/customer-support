"""Boundary and failure scenarios independent of external model availability."""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings

from assistant.db_service import get_item_stock_and_rules
from assistant.models import ChatUsageLog, DocumentChunk, UploadedDocument
from assistant.query_service import (
    classify_customer_purchase_channel,
    is_purchase_order_diagnostic_question,
    parse_customer_purchase_request,
    query_business_data,
)
from assistant.rag_service import retrieve_navigation_chunks, format_verified_navigation_answer
from assistant.views import (
    _classify_purchase_channel_answer,
    _customer_sale_stock_answer,
    _detect_conversational_followup_intent,
    _inherited_purchase_channel_request,
    chat_query,
)


class PurchaseEligibilityScenarios(SimpleTestCase):
    def test_unqualified_customer_buy_wording_is_clarified_instead_of_assumed_to_be_a_purchase_order(self):
        for question in ("Can I buy 19 vitamin C?", "Can I purchase Vitamin C?"):
            with self.subTest(question=question):
                self.assertEqual(classify_customer_purchase_channel(question), "ambiguous")
                self.assertFalse(is_purchase_order_diagnostic_question(question))

    def test_purchase_request_parser_keeps_quantity_unit_and_catalog_item_separate(self):
        self.assertEqual(
            parse_customer_purchase_request("Can I buy 19 pieces of Vitamin C?"),
            {"quantity": "19", "unit": "pieces", "item_query": "Vitamin C"},
        )

    def test_customer_sale_parser_keeps_sell_quantity_and_item_without_customer_suffix(self):
        question = "Can I sell 20 watches to a single customer?"
        self.assertEqual(
            parse_customer_purchase_request(question),
            {"quantity": "20", "unit": None, "item_query": "watches"},
        )
        self.assertEqual(classify_customer_purchase_channel(question), "customer_sale")

    def test_explicit_sale_and_supplier_context_route_to_their_own_flow(self):
        sale_question = "Can I buy 19 vitamin C at checkout?"
        supplier_question = "Can I buy 19 vitamin C from supplier Acme?"
        self.assertEqual(classify_customer_purchase_channel(sale_question), "customer_sale")
        self.assertFalse(is_purchase_order_diagnostic_question(sale_question))
        self.assertEqual(classify_customer_purchase_channel(supplier_question), "supplier_order")
        self.assertTrue(is_purchase_order_diagnostic_question(supplier_question))

    def test_explicit_new_operations_override_purchase_history(self):
        prior = [SimpleNamespace(user_message="Can I purchase 10 vitamin c?", confidence_basis="live tenant data")]
        for question in ("Can I sell vitamin C?", "Is Vitamin C in stock?", "What is a purchase order?", "Where is category?"):
            with self.subTest(question=question):
                self.assertFalse(_detect_conversational_followup_intent(question, prior)[1])
        self.assertEqual(_detect_conversational_followup_intent("for toy car", prior), (True, False))
        supplier_po = [SimpleNamespace(
            user_message="Can I create a purchase order for 10 vitamin c from a supplier?",
            confidence_basis="live tenant data",
        )]
        self.assertEqual(_detect_conversational_followup_intent("for toy car", supplier_po), (True, True))

    def test_customer_sale_clarification_inherits_original_request_through_a_thanks_turn(self):
        logs = [
            SimpleNamespace(user_message="Can I buy 10 water bottle?"),
            SimpleNamespace(user_message="thanks"),
        ]

        channel = _classify_purchase_channel_answer("for customer sale")
        request = _inherited_purchase_channel_request(channel, logs)

        self.assertEqual(channel, "customer_sale")
        self.assertEqual(request, {"quantity": "10", "unit": None, "item_query": "water bottle"})

    def test_customer_sale_answer_does_not_add_stock_across_separate_locations(self):
        result = {
            "items": [{
                "item_name": "Water Bottle",
                "status": "active",
                "is_available_sell": True,
                "has_variants": False,
                "has_stocks": True,
                "tracking_type": "none",
                "unit": "Piece",
                "stock_summary": {"total_available": 10},
                "warehouses_with_stock": [
                    {"warehouse_name": "Store A", "warehouse_is_active": True,
                     "qty_available": 5, "qty_available_without_batch": 5},
                    {"warehouse_name": "Store B", "warehouse_is_active": True,
                     "qty_available": 5, "qty_available_without_batch": 5},
                ],
            }],
        }

        answer, _basis = _customer_sale_stock_answer(
            result, {"item_query": "water bottle", "quantity": "10", "unit": None}
        )

        self.assertIn("don't see **10 Piece available at one location**", answer)
        self.assertNotIn("Yes—", answer)

    def test_customer_sale_answer_requires_variant_or_serial_selection_when_needed(self):
        request = {"item_query": "water bottle", "quantity": "10", "unit": None}
        variant_result = {
            "items": [{
                "item_name": "Water Bottle",
                "status": "active",
                "is_available_sell": True,
                "has_stocks": True,
                "has_variants": True,
                "tracking_type": "none",
                "unit": "Piece",
                "variants": [{"variant_name": "Blue", "stock_summary": {"total_available": 12}}],
            }],
        }
        serial_result = {
            "items": [{
                "item_name": "Water Bottle",
                "status": "active",
                "is_available_sell": True,
                "has_stocks": True,
                "has_variants": False,
                "tracking_type": "serial",
                "unit": "Piece",
            }],
        }

        variant_answer, _ = _customer_sale_stock_answer(variant_result, request)
        serial_answer, _ = _customer_sale_stock_answer(serial_result, request)

        self.assertIn("specific variant", variant_answer)
        self.assertIn("serial tracking", serial_answer)


class NavigationEntityScenarios(TestCase):
    def test_form_fields_and_filters_do_not_establish_management_destinations(self):
        doc = UploadedDocument.objects.create(title="Current help", file_path="/tmp/help.md", original_filename="help.md")
        DocumentChunk.objects.create(document=doc, chunk_index=0, section_title="Items",
            section_hierarchy=["Feature: INVENTORY ITEMS"],
            content="Access Flow: Sidebar ➔ Inventory ➔ Catalog ➔ Items. Add Item has Category, Brand and Warehouse fields.")
        for subject in ("catogory", "brand", "warehouse"):
            with self.subTest(subject=subject):
                context, refs = retrieve_navigation_chunks(f"where can i add {subject}")
                self.assertEqual((context, refs), ("", []))
                self.assertIsNone(format_verified_navigation_answer(
                    "Sidebar ➔ Inventory ➔ Catalog ➔ Items. Select Category.", f"where is {subject}"))


class QueryComparisonScenarios(SimpleTestCase):
    def run_plan(self, filters=None, having=None):
        connection, cursor = MagicMock(), MagicMock()
        connection.__enter__.return_value = connection
        connection.execute.return_value.mappings.return_value.all.return_value = []
        schema = {"tables": {"inventory_items": {"id": "int", "name": "varchar", "reorder_point": "decimal", "min_stock_level": "decimal"}}, "relationships": set()}
        plan = {"base_table": "inventory_items", "select": [
            {"table": "inventory_items", "column": "reorder_point", "alias": "reorder"},
            {"table": "inventory_items", "column": "min_stock_level", "alias": "minimum"},
        ], "filters": filters or [], "having": having or []}
        with patch("assistant.query_service.resolve_tenant_database", return_value="apptimate_test"), \
             patch("assistant.query_service._schema_for", return_value=schema), \
             patch("assistant.query_service.get_tenant_engine") as engine:
            engine.return_value.connect.return_value.__enter__.return_value = connection
            result = query_business_data(plan, tenant_identifier="example.test")
        return result, connection

    def test_column_comparison_uses_validated_identifiers_not_a_string_literal(self):
        result, cursor = self.run_plan(filters=[{"table": "inventory_items", "column": "min_stock_level", "operator": "<",
            "value": {"table": "inventory_items", "column": "reorder_point"}}])
        self.assertNotIn("error", result)
        self.assertIn("t0.`min_stock_level` < t0.`reorder_point`", str(cursor.execute.call_args.args[0]))

    def test_having_can_compare_two_selected_values(self):
        result, cursor = self.run_plan(having=[{"alias": "minimum", "operator": "<", "value": {"alias": "reorder"}}])
        self.assertNotIn("error", result)
        self.assertIn("`minimum` < `reorder`", str(cursor.execute.call_args.args[0]))

    def test_having_column_reference_uses_its_selected_unaggregated_alias(self):
        result, cursor = self.run_plan(having=[{'alias': 'minimum', 'operator': '<',
            'value': {'table': 'inventory_items', 'column': 'reorder_point'}}])
        self.assertNotIn('error', result)
        self.assertIn('`minimum` < `reorder`', str(cursor.execute.call_args.args[0]))

    def test_arbitrary_sql_or_unselected_aliases_are_rejected(self):
        for value in ({"alias": "missing"}, {"sql": "SELECT password FROM users"}, {"alias": "reorder; DROP TABLE x"}):
            with self.subTest(value=value):
                result, cursor = self.run_plan(having=[{"alias": "minimum", "operator": "<", "value": value}])
                self.assertIn("error", result)
                cursor.execute.assert_not_called()


class QuantityExtractionScenarios(SimpleTestCase):
    @patch("assistant.db_service._resolve_items_fuzzy")
    @patch("assistant.db_service.get_tenant_connection")
    @patch("assistant.db_service.resolve_tenant_database", return_value="apptimate_test")
    def test_zero_and_null_settings_survive_without_running_pricing_queries(self, _tenant, get_connection, resolve):
        resolve.return_value = [{"id": 1, "sku": "T-1", "name": "Item", "status": "active", "is_available_sell": True,
            "has_variants": False, "is_discountable": False, "tracking_type": "none", "has_stocks": False}]
        connection, cursor = MagicMock(), MagicMock()
        connection.__enter__.return_value = connection
        connection.cursor.return_value.__enter__.return_value = cursor
        cursor.fetchone.side_effect = [
            {"organization_id": 1, "min_stock_level": 0, "max_stock_level": None, "reorder_point": None,
             "reorder_qty": 0, "unit": "Pieces", "is_available_purchase": True},
            {"total_available": 0, "total_on_hand": 0},
        ]
        cursor.fetchall.return_value = []
        get_connection.return_value = connection
        result = get_item_stock_and_rules("Item", "example.test")
        self.assertTrue(result["found"])
        item = result["items"][0]
        self.assertEqual(item["stock_levels"]["min_stock_level"], 0)
        self.assertIsNone(item["stock_levels"]["max_stock_level"])
        self.assertFalse(item["has_stocks"])
        self.assertFalse(item["pricing_checked"])
        self.assertNotIn("sales_price_rules", " ".join(call.args[0] for call in cursor.execute.call_args_list))
        stock_query = next(
            call for call in cursor.execute.call_args_list
            if "AS total_available" in call.args[0] and "inventory_stock_balances" in call.args[0]
        )
        self.assertIn("organization_id = %s", stock_query.args[0])
        self.assertEqual(stock_query.args[1], (1, 1))
        warehouse_query = next(
            call for call in cursor.execute.call_args_list
            if "qty_available_without_batch" in call.args[0]
        )
        self.assertIn("w.organization_id = %s", warehouse_query.args[0])
        self.assertIn("w.deleted_at IS NULL", warehouse_query.args[0])


@override_settings(ENABLE_ANSWER_VALIDATION=False)
class LiveEvidenceScenarios(TestCase):
    @patch("assistant.views.resolve_tenant_database", return_value="apptimate_test")
    @patch("assistant.views.get_business_schema_context", return_value="")
    @patch("assistant.views.client.chat.completions.create")
    def test_model_cannot_claim_live_settings_without_calling_a_tool(self, completion, _schema, _tenant):
        completion.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=None, content="There are 189 units available."))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15))
        request = RequestFactory().post("/api/chat/", data=json.dumps({"message": "Is Vitamin C in stock?", "username": "tester"}), content_type="application/json")
        result = json.loads(chat_query(request).content)
        self.assertNotIn("189", result["response"])
        self.assertEqual(result["confidence"], 0.0)
        self.assertEqual(result["confidence_type"], "evidence")
        self.assertIn("No live tenant data", result["confidence_basis"])


class SaleAnswerBoundaryScenarios(SimpleTestCase):
    def answer(self, quantity='10', unit=None, **changes):
        item = {
            'item_name': 'Watch', 'sku': 'W-1', 'status': 'active',
            'is_available_sell': True, 'has_stocks': True, 'has_variants': False,
            'tracking_type': 'none', 'unit': 'Piece',
            'warehouses_with_stock': [{'warehouse_name': 'Store A', 'warehouse_is_active': True,
                'qty_available': 10, 'qty_available_without_batch': 10}],
        }
        item.update(changes)
        return _customer_sale_stock_answer({'items': [item]}, {'quantity': quantity, 'unit': unit, 'item_query': 'watch'})[0]

    def test_exact_stock_boundary_and_generic_units(self):
        for unit in (None, 'units', 'pieces', 'pcs'):
            with self.subTest(unit=unit):
                self.assertTrue(self.answer(unit=unit).startswith('Yes'))
        self.assertFalse(self.answer(quantity='11').startswith('Yes'))

    def test_nonpositive_quantities_do_not_get_a_positive_sale_answer(self):
        for quantity in ('0', '-2', '0.0'):
            with self.subTest(quantity=quantity):
                self.assertIn('greater than zero', self.answer(quantity=quantity))

    def test_units_that_need_conversion_are_not_compared(self):
        self.assertIn('unit conversion', self.answer(unit='boxes'))

    def test_disabled_or_unknown_eligibility_cannot_be_overridden_by_stock(self):
        for changes in ({'status': 'inactive'}, {'is_available_sell': False}, {'is_available_sell': None},
                        {'has_stocks': None}, {'tracking_type': None}, {'has_variants': None}):
            with self.subTest(changes=changes):
                self.assertFalse(self.answer(**changes).startswith('Yes'))

    def test_inactive_or_unknown_locations_do_not_prove_sellable_stock(self):
        for active in (False, None):
            with self.subTest(active=active):
                answer = self.answer(warehouses_with_stock=[{'warehouse_name': 'Closed store',
                    'warehouse_is_active': active, 'qty_available': 100}])
                self.assertFalse(answer.startswith('Yes'))

    def test_non_stock_item_is_not_blocked_by_zero_stock(self):
        self.assertIn('non-stock item', self.answer(has_stocks=False, warehouses_with_stock=[]))

    def test_conversational_sale_parser_handles_units_and_filler(self):
        for question, quantity, item in (
            ('Could we please sell 10 pieces of watches?', '10', 'watches'),
            ('Can I sell vitamin C instead?', None, 'vitamin C'),
            ('Can I sell -2 watches?', '-2', 'watches'),
        ):
            with self.subTest(question=question):
                parsed = parse_customer_purchase_request(question)
                self.assertEqual(parsed['item_query'], item)
                self.assertEqual(parsed['quantity'], quantity)
                self.assertEqual(classify_customer_purchase_channel(question), 'customer_sale')

    def test_supplier_qualifiers_and_quantity_are_not_catalog_search_terms(self):
        for question in ('Can I purchase 10 vitamin C from a supplier?',
                         'Can I buy 10 vitamin C from supplier Acme?',
                         'Can I buy 10 vitamin C for our inventory?'):
            with self.subTest(question=question):
                self.assertEqual(parse_customer_purchase_request(question)['item_query'], 'vitamin C')
                self.assertEqual(classify_customer_purchase_channel(question), 'supplier_order')


class EvaluationEvidenceTests(SimpleTestCase):
    def test_zero_master_threshold_is_checked_as_unconfigured(self):
        from assistant.management.commands.evaluate_support import evaluate_turn
        errors = evaluate_turn(
            {'oracle': {'field': 'max_stock_level'}},
            {'response': 'Watch (W-1): Max Qty is not configured.', 'confidence': 100,
             'confidence_basis': 'Read configured item setting.',
             'usage': {'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0}},
            [], 200, {'sku': 'W-1', 'name': 'Watch', 'max_stock_level': 0},
        )
        self.assertEqual(errors, [])


@override_settings(ENABLE_ANSWER_VALIDATION=False)
class UnreviewedEvidenceTests(TestCase):
    @patch('assistant.views.resolve_tenant_database', return_value='apptimate_test')
    @patch('assistant.views.get_business_schema_context', return_value='customer schema')
    @patch('assistant.views.retrieve_relevant_chunks', return_value=('', []))
    @patch('assistant.views.query_business_data', return_value={'results': [{'count': 12}], 'truncated': False})
    @patch('assistant.views.client.chat.completions.create')
    def test_successful_query_without_answer_review_is_not_scored_as_certain(self, completion, _query, _docs, _schema, _tenant):
        tool = SimpleNamespace(id='q1', function=SimpleNamespace(name='query_business_data',
            arguments=json.dumps({'query_plan': {'base_table': 'core_parties', 'select': [
                {'table': 'core_parties', 'column': 'id', 'aggregate': 'COUNT', 'alias': 'count'}]}})))
        completion.side_effect = [
            SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[tool], content=None))],
                usage=SimpleNamespace(prompt_tokens=5, completion_tokens=5, total_tokens=10)),
            SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=None, content='There are 12 active customers.'))],
                usage=SimpleNamespace(prompt_tokens=5, completion_tokens=5, total_tokens=10)),
        ]
        request = RequestFactory().post('/api/chat/', content_type='application/json',
            data=json.dumps({'message': 'How many active customers do we have?', 'username': 'quality-test'}),
            HTTP_X_TENANT_DOMAIN='example.test')
        payload = json.loads(chat_query(request).content)
        self.assertIn('12 active customers', payload['response'])
        self.assertIsNone(payload['confidence'])
        self.assertIn('not independently reviewed', payload['confidence_basis'])


class IndependentScalarChecks(SimpleTestCase):
    def test_same_count_from_the_wrong_table_is_not_accepted(self):
        from assistant.management.commands.evaluate_support import check_scalar_snapshot
        trace = [{'result': {'results': [{'total': 0}], 'query_audit': {'base_table': 'sales_orders'}}}]
        self.assertIn('independent_scalar_mismatch', check_scalar_snapshot(0, trace, 'No records', ['finance_invoices']))

    def test_correct_table_and_count_accept_zero_and_thousands_separators(self):
        from assistant.management.commands.evaluate_support import check_scalar_snapshot
        for value, answer in [(0, 'No finance invoices.'), (1234, '1,234 finance invoices.')]:
            trace = [{'result': {'results': [{'total': value}], 'query_audit': {'base_table': 'finance_invoices'}}}]
            self.assertEqual(check_scalar_snapshot(value, trace, answer, ['finance_invoices']), [])

    def test_grouped_snapshot_retains_association_between_currency_and_total(self):
        from assistant.management.commands.evaluate_support import check_row_snapshot
        expected = [{'currency': 'USD', 'total': 10}, {'currency': 'LKR', 'total': 20}]
        trace = [{'result': {'results': [{'c': 'USD', 'n': 20}, {'c': 'LKR', 'n': 10}],
                            'query_audit': {'base_table': 'finance_invoices'}}}]
        self.assertIn('independent_grouped_rows_mismatch', check_row_snapshot(expected, trace, ['finance_invoices']))
        trace[0]['result']['results'] = [{'c': 'USD', 'n': 10}, {'c': 'LKR', 'n': 20}]
        self.assertEqual(check_row_snapshot(expected, trace, ['finance_invoices']), [])
