from unittest.mock import patch
from django.test import SimpleTestCase
from assistant.local_engine import LocalAnswer

ADMIN={'tenant':'test','user_id':1,'super_admin':True,'permissions':[]}


class AnalyticsContinuationTests(SimpleTestCase):
    def test_saved_sales_report_asks_for_report_context_before_broad_invoice_reads(self):
        with patch('assistant.views.query_business_data') as read,patch('assistant.local_engine.plan_question') as planner:
            result=LocalAnswer('test',ADMIN,'Compare a saved sales report with the source invoice total.').run()
        self.assertEqual(result['answer_status'],'needs_clarification')
        self.assertIn('report name or ID',result['response'])
        read.assert_not_called();planner.assert_not_called()

    def test_invalid_date_does_not_become_an_http_500(self):
        with patch('assistant.views.query_business_data') as read:
            result=LocalAnswer('test',ADMIN,'Show stock movements from 2026-02-30 through 2026-03-02.').run()
        self.assertEqual(result['answer_status'],'needs_clarification');read.assert_not_called()
    def test_new_completed_lookup_clears_pagination_from_an_older_question(self):
        state={'last_query':{'base_table':'inventory_items'},'query_pages':[
            {'title':'Old stock','plan':{'base_table':'inventory_items'},'next_offset':500}]}
        answer=LocalAnswer('test',ADMIN,'A new completed lookup',state=state)
        with patch('assistant.views.query_business_data',return_value={'results':[],'next_offset':None}):
            answer.query({'base_table':'finance_invoices','select':[{'table':'finance_invoices','column':'id'}]})
        self.assertEqual(state['query_pages'],[])
        with patch('assistant.views.query_business_data') as read:
            result=LocalAnswer('test',ADMIN,'next page',state=state).run()
        read.assert_not_called();self.assertIn('no next page',result['response'])

    def test_two_partial_datasets_require_a_specific_continuation(self):
        state={'last_query':{'base_table':'finance_invoices'},'query_pages':[
            {'title':'Received quantity','plan':{'base_table':'receipts'},'next_offset':500},
            {'title':'Outstanding AP','plan':{'base_table':'finance_invoices'},'next_offset':500}]}
        answer=LocalAnswer('test',ADMIN,'next page',state=state)
        with patch('assistant.views.query_business_data') as read:
            result=answer.run()
        read.assert_not_called()
        self.assertEqual(result['answer_status'],'needs_clarification')
        self.assertIn('Received quantity',result['response'])
        self.assertIn('Outstanding AP',result['response'])

    def test_named_continuation_preserves_other_pending_dataset(self):
        state={'last_query':{'base_table':'finance_invoices'},'query_pages':[
            {'title':'Received quantity','plan':{'base_table':'receipts','select':[{'table':'receipts','column':'id','alias':'id'}]},'next_offset':500},
            {'title':'Outstanding AP','plan':{'base_table':'finance_invoices'},'next_offset':500}]}
        answer=LocalAnswer('test',ADMIN,'next page for Received quantity',state=state)
        with patch('assistant.views.query_business_data',return_value={'results':[],'truncated':False}) as read:
            answer.run()
        self.assertEqual(read.call_args.args[0]['base_table'],'receipts')
        self.assertEqual(read.call_args.args[0]['offset'],500)
        self.assertEqual([x['title'] for x in state['query_pages']],['Outstanding AP'])

    def test_zero_stock_is_filtered_before_paging_and_preserves_unknown_stock(self):
        answer=LocalAnswer('test',ADMIN,'Show items with no stock, including any that do not track stock.')
        with patch('assistant.views.query_business_data',return_value={'results':[]}) as read:
            answer.run()
        plan=read.call_args.args[0]
        self.assertEqual(plan['having_logic'],'OR')
        self.assertEqual(plan['having'],[{'alias':'available','operator':'<=','value':0},{'alias':'available','operator':'IS NULL'}])
        self.assertIn('has_stocks',[f.get('column') for f in plan['select']])

    def test_calculated_null_is_not_presented_as_zero(self):
        answer=LocalAnswer('test',ADMIN,'Compute amount')
        answer.render_query({'results':[{'ratio':None}],'query_audit':{'selected_fields':[{'alias':'ratio','expression':{'operator':'/'}}]}},'Ratio')
        self.assertIn('undefined division',' '.join(answer.parts))
        self.assertNotIn('| 0 |',' '.join(answer.parts))
