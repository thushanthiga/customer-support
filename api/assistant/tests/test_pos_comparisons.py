from decimal import Decimal
from unittest.mock import patch

from django.test import SimpleTestCase

from assistant.comparisons import normalize_comparisons, numeric_comparisons
from assistant.local_engine import LocalAnswer
from assistant.query_service import _validate_query_plan_relevance, has_requested_row_limit


ADMIN={'tenant':'test','user_id':1,'super_admin':True,'permissions':[]}


def receipt_plan(column='grand_total', operator='<', amount=50):
    return {'base_table':'sales_pos','select':[
        {'table':'sales_pos','column':'id','alias':'id'},
        {'table':'sales_pos','column':'pos_number','alias':'pos_number'},
        {'table':'sales_pos','column':'grand_total','alias':'grand_total'}],
        'filters':[{'table':'sales_pos','column':column,'operator':operator,'value':amount}]}


class PosComparisonTests(SimpleTestCase):
    def test_ambiguous_words_and_amounts_do_not_invent_row_limits(self):
        self.assertFalse(has_requested_row_limit('list me thre pos sales under 50 rupees'))
        self.assertFalse(has_requested_row_limit('List POS sales under 50 rupees'))
        for question in ('List three POS sales under 50','Show 5 receipts','List the latest POS sale','Top ten invoices'):
            self.assertTrue(has_requested_row_limit(question),question)
    def test_numeric_operand_typo_does_not_change_identifiers(self):
        text='Find SKU SO-5o in POS sales under 5o rupes'
        self.assertEqual(normalize_comparisons(text),'Find SKU SO-5o in POS sales under 50 rupes')
        self.assertEqual(numeric_comparisons(text),[('<',Decimal('50'))])
        self.assertEqual(numeric_comparisons('Show POS sales above Rs 1,0oo.5o'),[('>',Decimal('1000.50'))])
        self.assertEqual(normalize_comparisons('Find exact SKU Widget-5o'),'Find exact SKU Widget-5o')
        self.assertEqual(numeric_comparisons('under 5offers'),[])

    def test_individual_sale_list_requires_correct_metric_direction_and_limit(self):
        question='list me thre pos sales under 5o rupes'
        _validate_query_plan_relevance(question,receipt_plan())
        for plan in [receipt_plan('amount_tendered'),receipt_plan(operator='>'),
                     receipt_plan(operator='<='),receipt_plan(amount=500)]:
            with self.subTest(plan=plan),self.assertRaisesRegex(ValueError,'numeric comparison'):
                _validate_query_plan_relevance(question,plan)

    def test_terminal_aggregate_cannot_satisfy_a_receipt_list(self):
        plan=receipt_plan()
        plan['select']=[{'table':'sales_pos','column':'grand_total','aggregate':'SUM','alias':'amount'}]
        with self.assertRaisesRegex(ValueError,'transaction list'):
            _validate_query_plan_relevance('List POS sales under 50 rupees',plan)

    def test_receipt_identity_is_required_for_transaction_list(self):
        plan=receipt_plan();plan['select']=plan['select'][-1:]
        with self.assertRaisesRegex(ValueError,'identify individual POS'):
            _validate_query_plan_relevance('List POS sales under 50',plan)

    def test_requested_summary_still_allows_aggregation(self):
        plan={'base_table':'sales_pos','select':[
            {'table':'sales_pos','column':'terminal_id'},
            {'table':'sales_pos','column':'grand_total','aggregate':'SUM','alias':'amount'}],
            'group_by':[{'table':'sales_pos','column':'terminal_id'}]}
        _validate_query_plan_relevance('Show today\'s net POS sales by terminal',plan)
        _validate_query_plan_relevance('Show total POS sales',plan)

    @patch('assistant.query_service.get_business_schema_context',return_value='- sales_pos: id (int), pos_number (text), grand_total (decimal)')
    @patch('assistant.views.query_business_data')
    @patch('assistant.local_engine.plan_question')
    def test_exact_request_uses_planner_and_preserves_requested_rows(self,planner,read,schema):
        plan=receipt_plan();plan['limit']=3
        planner.return_value={'plans':[plan],'usage':{'prompt_tokens':10,'completion_tokens':5,'source':'provider','model':'gpt-6-luna'}}
        read.return_value={'results':[{'id':1,'pos_number':'TEST-RECEIPT','grand_total':25}],
            'query_audit':{'selected_fields':plan['select'],'filters':plan['filters']}}
        result=LocalAnswer('test',ADMIN,'list me thre pos sales under 5o rupes').run()
        planner.assert_called_once()
        self.assertEqual(planner.call_args.args[0],'list me thre pos sales under 50 rupes')
        read.assert_called_once()
        self.assertEqual(read.call_args.args[0]['limit'],50)
        self.assertEqual(result['data_pages'][0]['rows'][0]['grand_total'],25)
        self.assertNotIn('by terminal',result['response'])
        self.assertNotIn('return value',result['response'])
