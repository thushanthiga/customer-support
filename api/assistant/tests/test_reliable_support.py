"""Current MCP-backed support engine regression tests; no live services."""
import json
from types import SimpleNamespace
from unittest.mock import patch
from django.test import SimpleTestCase, override_settings
from assistant.local_engine import LocalAnswer, classify_query, lookup_item_details
from assistant.query_service import query_business_data
from assistant.query_planner import plan_question


@override_settings(SUPPORT_DISABLE_MODEL_CALLS=True)
class ReliableSupportTests(SimpleTestCase):
    def answer(self, question='List invoices'):
        return LocalAnswer('apptimate_test', {}, question)

    def result(self, rows, **extra):
        return {'results': rows, 'query_audit': {'selected_fields': [
            {'column': 'amount', 'alias': 'amount', 'aggregate': 'SUM'}]}, **extra}

    def test_unknown_amount_is_not_zero(self):
        answer = self.answer()
        answer.render_query(self.result([{'amount': None}]))
        self.assertIn('not recorded', answer.payload()['response'])
        self.assertNotIn('| 0 |', answer.payload()['response'])

    def test_all_returned_rows_are_visible(self):
        answer = self.answer()
        answer.render_query(self.result([{'amount': i} for i in range(500)]))
        self.assertIn('| 499 |', answer.payload()['response'])
        self.assertEqual(len(answer.data_pages[0]['rows']), 500)

    def test_page_has_explicit_scope_and_can_continue(self):
        answer = self.answer()
        plan = {'base_table': 'finance_invoices', 'select': [{'column': 'amount'}]}
        answer.render_query(self.result([{'amount': 12}], truncated=True, next_offset=50), 'Invoices', plan)
        payload = answer.payload()
        self.assertEqual(payload['answer_status'], 'partial')
        self.assertIn('next page for Invoices', payload['response'])
        self.assertIn('not population totals', payload['response'])
        self.assertEqual(answer.state['query_pages'][0]['next_offset'], 50)

    def test_empty_result_does_not_prove_never_sold(self):
        answer = self.answer('Has this item ever sold?')
        answer.render_query(self.result([]))
        self.assertIn('checked scope', answer.payload()['response'])
        self.assertNotIn('never sold', answer.payload()['response'])

    def test_verified_result_does_not_claim_perfect_confidence(self):
        answer = self.answer()
        answer.evidence.append({'tool': 'mcp:run_select', 'result': self.result([{'amount': 4}])})
        self.assertIsNone(answer.payload()['confidence'])

    @patch('assistant.local_engine.client.chat.completions.create')
    def test_offline_routing_never_calls_provider(self, provider):
        classify_query('What happened to invoice INV-23?')
        provider.assert_not_called()

    def test_mixed_question_routes_both_sources(self):
        self.assertEqual(classify_query('Check outstanding invoices and show me how to record a payment')['classification'], 'hybrid')

    @patch('assistant.local_engine.LocalAnswer.documentation_answer', return_value=False)
    def test_missing_documentation_returns_actionable_answer(self, documentation):
        result = self.answer('How do I configure a new payment gateway?').run()
        self.assertEqual(result['answer_status'], 'unsupported')
        self.assertIn('screen name', result['response'])

    @patch('assistant.local_engine.LocalAnswer.documentation_answer')
    @patch('assistant.local_engine.LocalAnswer.generic_answer')
    def test_documentation_cannot_hide_failed_live_query(self, database, documentation):
        answer = self.answer('Check outstanding invoices and show me how to record a payment')
        def failed():
            answer.status = 'lookup_failed'
        def documented(question):
            answer.status = 'answered'
            return True
        database.side_effect = failed
        documentation.side_effect = documented
        self.assertEqual(answer.run()['answer_status'], 'partial')
        database.assert_called_once()
        documentation.assert_called_once()

    @patch('assistant.local_engine.query_service.query_business_data', return_value={'error': 'Read unavailable'})
    def test_failed_lookup_is_not_catalog_absence(self, query):
        result = lookup_item_details('Widget', 'apptimate_test')
        self.assertEqual(result['error'], 'Read unavailable')
        self.assertNotIn('stock_on_hand', result)
        query.assert_called_once()

    @patch('assistant.local_engine.query_service.get_business_schema_context', return_value='invoice schema')
    @patch('assistant.local_engine.plan_question')
    @patch('assistant.local_engine.query_service.query_business_data')
    @patch('assistant.local_engine.client.chat.completions.create')
    def test_analytics_values_never_pass_through_model_narration(self, provider, query, planner, schema):
        plan = {'base_table': 'finance_invoices', 'select': [
            {'table': 'finance_invoices', 'column': 'amount', 'alias': 'amount', 'aggregate': 'SUM'}]}
        planner.return_value = {'plans': [plan], 'missing_capability': 'Latest invoice per supplier cannot be established by this plan.'}
        query.return_value = self.result([{'amount': '1234567890123456.99'}])
        result = self.answer().run()
        self.assertIn('1234567890123456.99', result['response'])
        self.assertEqual(result['answer_status'], 'partial')
        provider.assert_not_called()


class AnalyticsCompilerTests(SimpleTestCase):
    schema = {'tables': {'finance_invoices': {'id': 'int', 'amount': 'decimal', 'date': 'date'}}, 'relationships': set()}

    def execute(self, plan):
        with patch('assistant.query_service.resolve_tenant_database', return_value='apptimate_test'), \
             patch('assistant.query_service._schema_for', return_value=self.schema), \
             patch('assistant.erp_access.enforce_tenant'), \
             patch('assistant.erp_access.public_schema', side_effect=lambda value: value), \
             patch('assistant.erp_access.organization_conditions', return_value=[]), \
             patch('assistant.mcp_client.mcp_run_select', return_value={'rows': [{'total': None}], 'has_more': False}) as run:
            result = query_business_data(plan, 'apptimate_test')
        return result, run

    def test_large_population_aggregates_before_output_page_limit(self):
        result, run = self.execute({'base_table': 'finance_invoices', 'select': [
            {'table': 'finance_invoices', 'column': 'amount', 'aggregate': 'SUM', 'alias': 'total'}], 'limit': 500})
        self.assertNotIn('error', result)
        sql = run.call_args.kwargs['sql']
        self.assertIn('SUM(t0.`amount`)', sql)
        self.assertNotIn('LIMIT', sql)
        self.assertNotIn('COALESCE', sql)
        self.assertEqual(run.call_args.kwargs['page_size'], 500)
        self.assertIsNone(result['results'][0]['total'])

    def test_large_result_page_is_bounded(self):
        result, run = self.execute({'base_table': 'finance_invoices', 'select': [
            {'table': 'finance_invoices', 'column': 'id', 'alias': 'id'}], 'limit': 1000000})
        self.assertNotIn('error', result)
        self.assertEqual(run.call_args.kwargs['page_size'], 500)

    def test_user_filter_values_are_bound(self):
        result, run = self.execute({'base_table': 'finance_invoices', 'select': [
            {'table': 'finance_invoices', 'column': 'id', 'alias': 'id'}],
            'filters': [{'table': 'finance_invoices', 'column': 'amount', 'operator': '>', 'value': 1234}]})
        self.assertNotIn('error', result)
        self.assertNotIn('1234', run.call_args.kwargs['sql'])
        self.assertIn(1234, run.call_args.kwargs['params'].values())

    def test_invalid_column_never_executes(self):
        result, run = self.execute({'base_table': 'finance_invoices', 'select': [
            {'table': 'finance_invoices', 'column': 'invented', 'alias': 'value'}]})
        self.assertIn('error', result)
        run.assert_not_called()

    @override_settings(SUPPORT_DISABLE_MODEL_CALLS=False)
    @patch('assistant.query_planner.client.chat.completions.create')
    def test_retry_receives_actual_validation_feedback(self, provider):
        from assistant.query_planner import PlanningValidationError
        provider.return_value = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"plans": []}'))], usage=None)
        with self.assertRaises(PlanningValidationError):
            plan_question('Total invoices', 'verified schema', failures=['Unknown column: revenue'])
        request = json.loads(provider.call_args.kwargs['messages'][1]['content'])
        self.assertEqual(request['validation_feedback'], ['Unknown column: revenue'])

    def test_seasonal_restocking_synthesis_and_chaining(self):
        plan_0 = {
            'base_table': 'sales_goods_issue_note_lines',
            'select': [
                {'table': 'inventory_items', 'column': 'id', 'alias': 'item_id'},
                {'table': 'inventory_items', 'column': 'name', 'alias': 'item_name'},
                {'table': 'inventory_items', 'column': 'sku', 'alias': 'sku'},
                {'table': 'sales_goods_issue_notes', 'column': 'dispatch_date', 'alias': 'dispatch_month'},
                {'table': 'sales_goods_issue_note_lines', 'column': 'dispatch_quantity', 'aggregate': 'SUM', 'alias': 'total_units_sold'},
                {'table': 'sales_goods_issue_notes', 'column': 'id', 'aggregate': 'COUNT', 'distinct': True, 'alias': 'sales_frequency'},
            ],
            'joins': [
                {'table': 'sales_goods_issue_notes', 'left_table': 'sales_goods_issue_note_lines', 'left_column': 'goods_issue_note_id', 'right_column': 'id'},
                {'table': 'inventory_items', 'left_table': 'sales_goods_issue_note_lines', 'left_column': 'item_id', 'right_column': 'id'},
            ],
            'group_by': [
                {'table': 'inventory_items', 'column': 'id'},
                {'table': 'inventory_items', 'column': 'name'},
                {'table': 'inventory_items', 'column': 'sku'},
                {'table': 'sales_goods_issue_notes', 'column': 'dispatch_date'},
            ],
        }
        plan_1 = {
            'base_table': 'inventory_items',
            'select': [
                {'table': 'inventory_items', 'column': 'id', 'alias': 'item_id'},
                {'table': 'inventory_items', 'column': 'name', 'alias': 'item_name'},
                {'table': 'inventory_items', 'column': 'sku', 'alias': 'sku'},
                {'table': 'inventory_stock_balances', 'column': 'qty_available', 'aggregate': 'SUM', 'coalesce': 0, 'alias': 'available_quantity'},
            ],
            'joins': [
                {'table': 'inventory_stock_balances', 'left_table': 'inventory_items', 'left_column': 'id', 'right_column': 'item_id'},
            ],
            'group_by': [
                {'table': 'inventory_items', 'column': 'id'},
                {'table': 'inventory_items', 'column': 'name'},
                {'table': 'inventory_items', 'column': 'sku'},
            ],
        }

        reply_0 = {
            'results': [
                {'item_id': 101, 'item_name': 'Munchee 50g', 'sku': 'BIS-BRN-01', 'dispatch_month': 202608, 'total_units_sold': 30, 'sales_frequency': 13},
                {'item_id': 102, 'item_name': 'Batch without variant', 'sku': 'BLO-BRN-09', 'dispatch_month': 202608, 'total_units_sold': 10, 'sales_frequency': 2},
                {'item_id': 103, 'item_name': 'Kurthi set', 'sku': 'BLO-BRN-13', 'dispatch_month': 202608, 'total_units_sold': 2, 'sales_frequency': 2},
                {'item_id': 104, 'item_name': 'A-batch', 'sku': 'batch-100', 'dispatch_month': 202607, 'total_units_sold': 11, 'sales_frequency': 2},
                {'item_id': 104, 'item_name': 'A-batch', 'sku': 'batch-100', 'dispatch_month': 202608, 'total_units_sold': 2, 'sales_frequency': 2},
            ],
            'query_audit': {'selected_fields': plan_0['select']},
            'compiled_sql': 'SELECT ... FROM sales_goods_issue_note_lines ...',
        }

        reply_1 = {
            'results': [
                {'item_id': 101, 'item_name': 'Munchee 50g', 'sku': 'BIS-BRN-01', 'available_quantity': 0},
                {'item_id': 102, 'item_name': 'Batch without variant', 'sku': 'BLO-BRN-09', 'available_quantity': 0},
                {'item_id': 103, 'item_name': 'Kurthi set', 'sku': 'BLO-BRN-13', 'available_quantity': 1},
                {'item_id': 104, 'item_name': 'A-batch', 'sku': 'batch-100', 'available_quantity': 319},
            ],
            'query_audit': {'selected_fields': plan_1['select']},
            'compiled_sql': 'SELECT ... FROM inventory_items WHERE id IN (101, 102, 103, 104) ...',
        }

        candidate = {
            'plans': [plan_0, plan_1],
            'query_review': {'verdict': 'approve'},
            'analysis_contract': {
                'goal': 'Review sales over time for seasonal demand patterns and compare with available stock.',
                'entity': 'Inventory items',
                'metric': 'Units sold, sales frequency, and available stock',
                'scope': 'All recorded dispatch history and current stock balances',
                'requirements': [{'status': 'supported'}, {'status': 'supported'}],
            },
        }

        executed_plans = []
        def mock_query(plan, *args, **kwargs):
            executed_plans.append(plan)
            if len(executed_plans) == 1:
                return reply_0
            return reply_1

        with patch('assistant.local_engine.query_service.get_business_schema_context', return_value='schema'), \
             patch('assistant.local_engine.query_service._schema_for', return_value={'tables': {}}), \
             patch('assistant.local_engine.plan_question', return_value=candidate), \
             patch.object(LocalAnswer, 'query', side_effect=mock_query):
            ans = LocalAnswer('apptimate_test', {}, 'what is the seasonal things need to be restore')
            result = ans.run()

        self.assertEqual(len(executed_plans), 2)
        chained_filters = executed_plans[1].get('filters', [])
        id_filter = next((f for f in chained_filters if f.get('column') == 'id'), None)
        self.assertIsNotNone(id_filter)
        self.assertEqual(id_filter['operator'], 'IN')
        self.assertEqual(set(id_filter['value']), {101, 102, 103, 104})

        self.assertIn('Seasonal Restocking & Inventory Assessment', result['response'])
        self.assertIn('August 2026', result['response'])

        self.assertIn('Immediate Restock Needed', result['response'])
        self.assertIn('Munchee 50g', result['response'])
        self.assertIn('Batch without variant', result['response'])
        self.assertIn('0 Available Stock', result['response'])

        self.assertIn('Kurthi set', result['response'])
        self.assertIn('A-batch', result['response'])

        self.assertIn('Comprehensive Restocking Assessment Table', result['response'])
        self.assertEqual(len(result['data_pages']), 2)

        audit_occurrences = result['response'].count('### 🔍 Technical Execution & Pipeline Audit')
        self.assertEqual(audit_occurrences, 1)

    def test_invoice_creation_classification_and_retrieval(self):
        from assistant.local_engine import classify_query
        from assistant import doc_retrieval
        from assistant.prompts import build_support_prompt

        # 1. Classification is fast-path document
        cls = classify_query("why I am not able to create invoices")
        self.assertEqual(cls["classification"], "document")

        # 2. Heuristic queries expand to fulfillment and dispatch
        queries = doc_retrieval._heuristic_queries("why I am not able to create invoices")
        self.assertTrue(any("Dispatch Goods & Generate Invoice" in q for q in queries))

        # 3. Prompt explicitly instructs authoritative expert tone and forbids disclaimers
        prompt = build_support_prompt("apptimate_infinity", "apptimate_infinity", "", "")
        self.assertIn("NEVER use meta-language or disclaimers", prompt)
        self.assertIn("Dispatch Goods & Generate Invoice", prompt)
        self.assertIn("Sales Orders", prompt)
        self.assertIn("/sales/invoices", prompt)
        self.assertIn("You ARE the authoritative ERP support assistant", prompt)
