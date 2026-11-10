"""Category regressions: approval integrity, preservation of scope, tenant isolation."""
from copy import deepcopy
from contextlib import ExitStack
from unittest.mock import patch, MagicMock
from django.test import SimpleTestCase, override_settings
from assistant.local_engine import LocalAnswer
from assistant.query_planner import PlanningValidationError
from assistant.query_integrity import validate_aggregate_grain
from assistant.db_service import resolve_tenant_database
from assistant.tests.test_planning_contract import proposal, APPROVED


@override_settings(SUPPORT_DISABLE_MODEL_CALLS=True)
class EvaluationSafetyTests(SimpleTestCase):
    def run_candidate(self, *, candidate=None, error=None, score=None, schema=None):
        with ExitStack() as stack:
            stack.enter_context(patch('assistant.local_engine.query_service.get_business_schema_context', return_value='- records: id (int), amount (decimal), name (varchar)'))
            stack.enter_context(patch('assistant.local_engine.query_service._schema_for', return_value=schema or {}))
            planner = stack.enter_context(patch('assistant.local_engine.plan_question'))
            planner.side_effect = error
            planner.return_value = candidate or proposal()
            query = stack.enter_context(patch('assistant.local_engine.query_service.query_business_data', return_value={'results': [], 'query_audit': {}}))
            if score is not None:
                stack.enter_context(patch('assistant.local_engine.evaluate_query', return_value={'passed': False,'score':score,'reasons':['Invalid scope'],'threshold':85}))
            result = LocalAnswer('apptimate_test', {}, 'Show recorded amounts').run()
            return result, query, planner

    def test_final_attempt_never_executes_review_rejected_candidate(self):
        candidate = proposal(); candidate['query_review'] = {'verdict':'revise','issues':['Wrong measure'],'clarification':''}
        result, query, planner = self.run_candidate(error=PlanningValidationError('Wrong measure', candidate=candidate))
        query.assert_not_called()
        self.assertNotEqual(result['answer_status'], 'answered')

    def test_final_attempt_never_bypasses_failed_deterministic_check(self):
        candidate = proposal(); candidate['query_review'] = APPROVED
        result, query, planner = self.run_candidate(candidate=candidate, score=40)
        query.assert_not_called()
        self.assertNotEqual(result['answer_status'], 'answered')

    def test_execution_preserves_reviewed_exact_filter(self):
        candidate = proposal(); candidate['query_review'] = APPROVED
        candidate['plans'][0]['filters'] = [{'table':'records','column':'name','operator':'=','value':'Acme'}]
        original = deepcopy(candidate)
        result, query, _ = self.run_candidate(candidate=candidate, schema={'tables':{'records':{'amount':'decimal','name':'varchar'}}})
        self.assertEqual(query.call_args.args[0]['filters'], original['plans'][0]['filters'])
        self.assertEqual(candidate, original)

    def test_execution_preserves_reviewed_limit(self):
        candidate = proposal(); candidate['query_review'] = APPROVED
        candidate['plans'][0]['select'][0].pop('aggregate')
        candidate['plans'][0]['limit'] = 7
        _, query, _ = self.run_candidate(candidate=candidate)
        self.assertEqual(query.call_args.args[0]['limit'], 7)

    def test_nonunique_join_is_never_assumed_unique_from_table_name(self):
        plan = {'base_table':'inventory_stock_balances','joins':[{'table':'inventory_item_replenishment_rules','left_table':'inventory_stock_balances','left_column':'item_id','right_column':'item_id'}],
                'select':[{'table':'inventory_stock_balances','column':'qty_available','aggregate':'SUM'}]}
        refs = {name:name for name in ('inventory_stock_balances','inventory_item_replenishment_rules')}
        with self.assertRaisesRegex(ValueError, 'double-count'):
            validate_aggregate_grain(plan, {'indexes':{}}, refs)

    def test_verified_unique_join_remains_usable(self):
        plan = {'base_table':'lines','joins':[{'table':'headers','left_table':'lines','left_column':'header_id','right_column':'id'}],
                'select':[{'table':'lines','column':'amount','aggregate':'SUM','alias':'total'}]}
        schema = {'indexes':{'headers':{'PRIMARY':{'unique':True,'columns':['id']}}}}
        self.assertEqual(validate_aggregate_grain(plan, schema, {'lines':'lines','headers':'headers'}), {'total':'lines'})

    @patch('assistant.db_service.ALLOW_DEFAULT_TENANT', True)
    @patch('assistant.db_service.get_root_connection')
    def test_registry_outage_does_not_switch_explicit_tenant(self, connect):
        connect.side_effect = OSError('Registry unavailable')
        with self.assertRaises(RuntimeError):
            resolve_tenant_database('customer.example.test')

    @patch('assistant.db_service.ALLOW_DEFAULT_TENANT', False)
    def test_localhost_with_port_cannot_bypass_disabled_default(self):
        with self.assertRaises(LookupError):
            resolve_tenant_database('localhost:3008')

    def test_multiple_results_preserve_unknowns_fractional_values_and_scope(self):
        candidate=proposal(); candidate['query_review']=APPROVED
        candidate['plans']=[
            {'base_table':'sales_order_lines','select':[{'table':'sales_order_lines','column':'quantity','alias':'total_units_sold'}]},
            {'base_table':'inventory_stock_balances','select':[{'table':'inventory_stock_balances','column':'qty_available','alias':'stock_quantity'}]}]
        replies=[{'results':[{'item_id':8,'total_units_sold':1.75,'sales_frequency':2}], 'query_audit':{'selected_fields':[]}},
                 {'results':[{'item_id':8,'stock_quantity':None}], 'truncated':True, 'next_offset':50,'query_audit':{'selected_fields':[]}}]
        for reply, plan in zip(replies, candidate['plans']):
            reply['query_audit']['selected_fields']=plan['select']
        with patch('assistant.local_engine.query_service.get_business_schema_context',return_value='schema'), \
             patch('assistant.local_engine.query_service._schema_for',return_value={'tables':{}}), \
             patch('assistant.local_engine.plan_question',return_value=candidate), \
             patch('assistant.local_engine.query_service.query_business_data',side_effect=replies):
            result=LocalAnswer('apptimate_test',{},'Show recorded sales and stock').run()
        self.assertEqual(result['answer_status'],'partial')
        self.assertEqual(len(result['data_pages']),2)
        self.assertIn('1.75',result['response'])
        self.assertIn('not recorded',result['response'])
        self.assertNotIn('Out of Stock (Urgent)',result['response'])

    def test_navigation_mentions_of_live_actions_are_not_mixed_requests(self):
        from assistant.local_engine import classify_query
        for question in ('How do I use the search and show balance controls?',
                         'How do I configure stock and revenue reports?',
                         'How do I use the compare and list options?'):
            with self.subTest(question=question):
                self.assertEqual(classify_query(question)['classification'],'document')

    def test_independent_live_clause_still_routes_to_both_sources(self):
        from assistant.local_engine import classify_query
        for question in ('Check outstanding invoices and show me how to record a payment',
                         'How do I record a payment and also list overdue invoices?'):
            with self.subTest(question=question):
                self.assertEqual(classify_query(question)['classification'],'hybrid')
