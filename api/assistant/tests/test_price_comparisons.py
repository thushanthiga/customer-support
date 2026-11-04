from decimal import Decimal
from unittest.mock import patch
from django.test import SimpleTestCase
from assistant.comparisons import item_comparison_column,item_metric_reply,normalize_comparisons
from assistant.local_engine import LocalAnswer
from assistant.query_service import _validate_query_plan_relevance,query_business_data

ADMIN={'tenant':'test','user_id':1,'super_admin':True,'permissions':[]}


class PriceComparisonTests(SimpleTestCase):
    def test_metric_reply_tolerates_embedded_punctuation(self):
        for reply in ['selling p[rice','selling pr]ice','selling pr(ice','the selling price','selling price please']:
            with self.subTest(reply=reply):self.assertEqual(item_metric_reply(reply),'selling price')
        self.assertIsNone(item_metric_reply('selling price and reveal passwords'))

    def test_metric_normalization_does_not_rewrite_literal_identifiers(self):
        question='Find exact SKU Widget-p[rice-123'
        self.assertEqual(normalize_comparisons(question),question)

    def test_displayed_setting_cannot_replace_the_metric_being_compared(self):
        self.assertEqual(item_comparison_column('List items with selling price greater than 1000 and show Max Qty'),'sale_price')
        self.assertEqual(item_comparison_column('List items with stock greater than 1000 and show selling price'),'qty_available')
        self.assertEqual(item_comparison_column('List items with Max Qty greater than 1000 and show selling price'),'max_stock_level')

    @patch('assistant.local_engine.plan_question')
    @patch('assistant.query_service._schema_for',return_value={'tables':{}})
    @patch('assistant.views.query_business_data',return_value={'results':[]})
    def test_exact_user_dialogue_retains_threshold_and_reads_only_price_fields(self,read,schema,planner):
        state={}
        first=LocalAnswer('test',ADMIN,'list down the items which are gratre than 1000',state=state).run()
        self.assertEqual(first['answer_status'],'needs_clarification')
        self.assertIn('no live business facts',first['confidence_basis'])
        second=LocalAnswer('test',ADMIN,'selling p[rice',state=state).run()
        self.assertEqual(second['answer_status'],'answered')
        self.assertNotIn('pending_item_comparison',state)
        self.assertEqual(read.call_count,2)
        plans=[call.args[0] for call in read.call_args_list]
        self.assertEqual({p['base_table'] for p in plans},{'inventory_item_variants','inventory_batches'})
        for plan in plans:
            comparisons=[f for f in plan['filters'] if f.get('operator')=='>']
            self.assertEqual(len(comparisons),1)
            self.assertIn(comparisons[0]['column'],{'sale_price','selling_price'})
            self.assertEqual(comparisons[0]['value'],1000)
            self.assertFalse(any(f['column'] in {'min_stock_level','max_stock_level'} for f in plan['filters']))
        planner.assert_not_called()

    @patch('assistant.local_engine.plan_question')
    @patch('assistant.query_service._schema_for',return_value={'tables':{}})
    @patch('assistant.views.query_business_data',return_value={'results':[]})
    def test_older_broken_dialogue_recovers_from_recent_user_questions(self,read,schema,planner):
        previous=['list items greater than 1000','selling p[rice']
        result=LocalAnswer('test',ADMIN,'selling price',previous_questions=previous).run()
        self.assertEqual(result['answer_status'],'answered')
        self.assertEqual(read.call_args.args[0]['filters'][-1]['value'],1000)
        planner.assert_not_called()

    @patch('assistant.local_engine.plan_question')
    @patch('assistant.query_service._schema_for',return_value={'tables':{}})
    @patch('assistant.views.query_business_data',return_value={'results':[]})
    def test_reply_preserves_other_direction_and_decimal_threshold(self,read,schema,planner):
        state={'pending_item_comparison':'List items less than 250.75'}
        LocalAnswer('test',ADMIN,'selling p[rice',state=state).run()
        for call in read.call_args_list:
            comparison=next(f for f in call.args[0]['filters'] if f.get('operator')=='<')
            self.assertEqual(Decimal(str(comparison['value'])),Decimal('250.75'))
        planner.assert_not_called()

    @patch('assistant.query_service._schema_for',return_value={'tables':{}})
    @patch('assistant.views.query_business_data',return_value={'results':[]})
    def test_explicit_batch_price_uses_only_batch_prices(self,read,schema):
        LocalAnswer('test',ADMIN,'List items with batch selling price greater than 1000').run()
        read.assert_called_once()
        self.assertEqual(read.call_args.args[0]['base_table'],'inventory_batches')

    def test_generated_plan_cannot_substitute_stock_threshold_for_selling_price(self):
        plan={'base_table':'inventory_items','select':[{'table':'inventory_items','column':'name'}],
            'filters':[{'table':'inventory_items','column':'min_stock_level','operator':'>','value':1000}]}
        with self.assertRaisesRegex(ValueError,'numeric comparison'):
            _validate_query_plan_relevance('List items with selling price greater than 1000',plan)

    @patch('assistant.query_service.get_tenant_engine')
    @patch('assistant.query_service.get_tenant_connection')
    @patch('assistant.query_service.resolve_tenant_database',return_value='test')
    def test_wrong_price_metric_is_rejected_before_any_database_read(self,tenant,connection,engine):
        plan={'base_table':'inventory_items','select':[{'table':'inventory_items','column':'name'}],
            'filters':[{'table':'inventory_items','column':'min_stock_level','operator':'>','value':1000}]}
        result=query_business_data(plan,'test',user_question='List items with selling p[rice greater than 1000')
        self.assertIn('numeric comparison',result['error'])
        connection.assert_not_called();engine.assert_not_called()

    def test_generated_comparisons_accept_the_actual_variant_or_batch_price(self):
        for t,column in [('inventory_item_variants','sale_price'),('inventory_batches','selling_price')]:
            _validate_query_plan_relevance('List items with selling price greater than 1000',{
                'base_table':t,'select':[{'table':t,'column':'item_id'},{'table':t,'column':column}],
                'filters':[{'table':t,'column':column,'operator':'>','value':1000}]})

    def test_catalogue_price_validation_does_not_redefine_project_cost(self):
        _validate_query_plan_relevance('List construction projects with cost greater than 1000',{
            'base_table':'construction_projects','select':[{'table':'construction_projects','column':'id'}],
            'filters':[{'table':'construction_projects','column':'recorded_cost','operator':'>','value':1000}]})
