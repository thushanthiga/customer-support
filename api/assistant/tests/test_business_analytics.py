from unittest.mock import patch
from django.test import SimpleTestCase
from assistant.business_recipes import answer_business_request
from assistant.local_engine import LocalAnswer

ADMIN={'tenant':'test','user_id':1,'super_admin':True,'permissions':[]}


@patch('assistant.query_service._schema_for',return_value={'tables':{},'relationships':set()})
class BusinessAnalyticsTests(SimpleTestCase):
    def test_inconsistent_ipc_amount_is_flagged_without_rewriting_its_stored_net(self,schema):
        answer=LocalAnswer('test',ADMIN,'Show approved IPCs, amounts paid, and outstanding by subcontractor.')
        with patch.object(answer,'query',side_effect=[{'results':[{'id':2,'certified_amount':0,'retention_deduction':50,'advance_deduction':100,'net_payable':850}]},{'results':[]}]):
            self.assertTrue(answer_business_request(answer))
        row=answer.data_pages[0]['rows'][0]
        self.assertEqual(row['net_after_recorded_deductions'],-150)
        self.assertEqual(row['stored_net_variance'],1000)
        self.assertEqual(row['net_payable'],850)
        self.assertIn('differs from the recorded deduction arithmetic',' '.join(answer.parts))

    def test_payslip_uses_payroll_period_and_does_not_invent_publication(self,schema):
        answer=LocalAnswer('test',ADMIN,'Has the payslip for employee EMP-123 been published for September 2026?')
        with patch.object(answer,'query',side_effect=[{'results':[{'id':9,'employee_code':'EMP-123'}]},
            {'results':[{'payroll_line_id':5,'run_id':7,'period_year':2026,'period_month':9,'run_status':'approved','is_held':0,'payslip_path':'slip.pdf'}]}]) as read:
            self.assertTrue(answer_business_request(answer))
        plan=read.call_args.args[0]
        self.assertIn({'table':'hr_payroll_runs','column':'period_year','operator':'=','value':2026},plan['filters'])
        self.assertIn({'table':'hr_payroll_runs','column':'period_month','operator':'=','value':9},plan['filters'])
        self.assertFalse(any(f['column']=='created_at' for f in plan['filters']))
        self.assertEqual(answer.data_pages[-1]['rows'][0]['payslip_file_recorded'],True)
        self.assertEqual(answer.status,'partial')

    def test_transformations_preserve_decimal_fine_weight_change(self,schema):
        answer=LocalAnswer('test',ADMIN,'What transformations lost or gained metal?')
        with patch.object(answer,'query',return_value={'results':[{'id':1,'status':'completed','source_total_fine_weight':77.922,'output_total_fine_weight':69.93}]}):
            self.assertTrue(answer_business_request(answer))
        self.assertEqual(answer.data_pages[-1]['rows'][0]['fine_weight_change'],-7.992)
        self.assertIsNone(answer.data_pages[-1]['rows'][0]['gross_weight_change'])

    def test_maintenance_distinguishes_due_from_overdue_and_missing_calendar_evidence(self,schema):
        answer=LocalAnswer('test',ADMIN,'Which equipment is allocated to PRJ-2026-009 and overdue for maintenance?')
        rows=[{'schedule_id':1,'interval_unit':'Km','current_reading':150,'last_service_reading':100,'interval_value':50},
            {'schedule_id':2,'interval_unit':'Km','current_reading':151,'last_service_reading':100,'interval_value':50},
            {'schedule_id':3,'interval_unit':'Days','current_reading':500,'last_service_reading':100,'interval_value':30}]
        with patch.object(answer,'query',side_effect=[{'results':[{'id':9}]},{'results':rows}]):
            self.assertTrue(answer_business_request(answer))
        result=answer.data_pages[-1]['rows']
        self.assertTrue(result[0]['due_now']);self.assertFalse(result[0]['overdue_by_reading'])
        self.assertTrue(result[1]['overdue_by_reading']);self.assertIsNone(result[2]['overdue_by_reading'])

    def test_approved_changes_do_not_drop_projects_with_no_changes(self,schema):
        answer=LocalAnswer('test',ADMIN,'Show approved change orders and revised contract value.')
        with patch.object(answer,'query',side_effect=[{'results':[{'project_id':1,'cost_impact':-0.01}]},
            {'results':[{'id':1,'contract_value':1000},{'id':2,'contract_value':2000}]},
            {'results':[{'project_id':1,'approved_change_orders':1,'approved_cost_impact':-0.01}]}]):
            self.assertTrue(answer_business_request(answer))
        rows=answer.data_pages[-1]['rows']
        self.assertEqual(rows[0]['calculated_revised_contract_value'],999.99)
        self.assertEqual(rows[1]['calculated_revised_contract_value'],2000)

    def test_no_po_for_exact_item_is_not_a_missing_receipt_schema(self,schema):
        answer=LocalAnswer('test',ADMIN,'Show the latest PO for SKU WIDGET-789 and its current receipt status.')
        with patch.object(answer,'query',side_effect=[{'results':[{'id':9,'sku':'WIDGET-789'}]},{'results':[]}]):
            self.assertTrue(answer_business_request(answer))
        self.assertIn('No recorded PO contains this item',' '.join(answer.parts))
        self.assertNotIn('no receipt-status field',' '.join(answer.parts))
        self.assertEqual(answer.status,'answered')

    def test_jewelry_received_lines_include_stock_posted_on_approval(self,schema):
        answer=LocalAnswer('test',ADMIN,'For received jewelry items, show PO, receipt, supplier invoice, and remaining payment.')
        with patch.object(answer,'query',return_value={'results':[]}) as read:
            self.assertTrue(answer_business_request(answer))
        self.assertIn({'table':'jewelry_goods_receipt_notes','column':'status','operator':'IN','value':['approved','completed']},read.call_args.args[0]['filters'])
