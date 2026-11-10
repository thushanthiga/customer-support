from unittest.mock import MagicMock, patch
from django.test import SimpleTestCase, override_settings
from assistant.query_service import query_business_data


@override_settings(SUPPORT_BUSINESS_ENGINE=False, TIME_ZONE='Asia/Colombo')
class CalculatedQueryTests(SimpleTestCase):
    schema={'tables':{'finance_invoices':{'id':'int','amount_due':'decimal','amount_settled':'decimal','created_at':'datetime','status':'varchar'}},'relationships':set()}

    def execute(self,field,filters=(),**kwargs):
        conn=MagicMock()
        def fake_mcp_run_select(sql, database="", page_size=50, offset=0, include_total=False, params=None):
            conn.execute(sql, params)
            return {"rows": [], "has_more": False, "elapsed_ms": 1, "read_at": "2026-11-05T00:00:00"}
        plan={'base_table':'finance_invoices','select':[field],'filters':list(filters),**kwargs}
        with patch('assistant.query_service.resolve_tenant_database',return_value='test'), \
             patch('assistant.query_service._schema_for',return_value=self.schema), \
             patch('assistant.mcp_client.mcp_run_select', side_effect=fake_mcp_run_select):
            result=query_business_data(plan,'test')
        return result,conn

    def expression(self,operator='-',right=None):
        return {'expression':{'operator':operator,'left':{'table':'finance_invoices','column':'amount_due'},
            'right':right if right is not None else {'table':'finance_invoices','column':'amount_settled'}},'alias':'outstanding'}

    def test_decimal_json_does_not_silently_round_large_business_amounts(self):
        from decimal import Decimal
        from assistant.db_service import _serialize_decimals
        self.assertEqual(_serialize_decimals(Decimal('1234567890123456.99')),'1234567890123456.99')
        self.assertEqual(_serialize_decimals(Decimal('0.123456789012345678901')),'0.123456789012345678901')
        self.assertEqual(_serialize_decimals(Decimal('0.15')),0.15)

    def test_decimal_subtraction_is_compiled_from_verified_columns(self):
        result,conn=self.execute(self.expression())
        self.assertNotIn('error',result)
        self.assertIn('(t0.`amount_due` - t0.`amount_settled`)',str(conn.execute.call_args.args[0]))
        self.assertEqual(result['query_audit']['selected_fields'][0]['expression']['operator'],'-')

    def test_numeric_constants_are_bound_and_zero_division_is_null(self):
        result,conn=self.execute(self.expression('/',0))
        self.assertNotIn('error',result)
        self.assertIn('NULLIF(%(p0)s, 0)',str(conn.execute.call_args.args[0]))
        self.assertEqual(conn.execute.call_args.args[1]['p0'],0)

    def test_arithmetic_cannot_bypass_field_validation_or_inject_sql(self):
        for operand in [{'table':'finance_invoices','column':'password'},
                {'table':'unjoined','column':'id'}, {'table':'finance_invoices','column':'status'},
                '1; DROP TABLE finance_invoices',True,float('inf')]:
            with self.subTest(operand=operand):
                result,conn=self.execute(self.expression('*',operand))
                self.assertIn('error',result);conn.execute.assert_not_called()

    def test_day_filter_includes_entire_day_in_business_timezone(self):
        result,conn=self.execute({'table':'finance_invoices','column':'id'},[
            {'table':'finance_invoices','column':'created_at','operator':'BETWEEN','value':['2026-09-30','2026-09-30']}])
        self.assertNotIn('error',result)
        params=conn.execute.call_args.args[1]
        self.assertEqual(params['p0'],'2026-09-29 18:30:00')
        self.assertEqual(params['p1'],'2026-09-30 18:30:00')
        self.assertIn('t0.`created_at` < %(p1)s',str(conn.execute.call_args.args[0]))

    def test_explicit_timestamp_is_not_reinterpreted_as_a_whole_day(self):
        result,conn=self.execute({'table':'finance_invoices','column':'id'},[
            {'table':'finance_invoices','column':'created_at','operator':'<=','value':'2026-09-30 12:00:00'}])
        self.assertNotIn('error',result)
        self.assertEqual(conn.execute.call_args.args[1]['p0'],'2026-09-30 12:00:00')
        self.assertEqual(result['query_audit']['calendar_filters'],[])

    def test_timestamp_with_offset_is_compared_at_the_correct_utc_instant(self):
        result,conn=self.execute({'table':'finance_invoices','column':'id'},[
            {'table':'finance_invoices','column':'created_at','operator':'<=','value':'2026-10-23T12:00:00+05:30'}])
        self.assertNotIn('error',result)
        self.assertEqual(conn.execute.call_args.args[1]['p0'],'2026-10-23 06:30:00')

    def test_invalid_day_is_rejected_before_a_read(self):
        result,conn=self.execute({'table':'finance_invoices','column':'id'},[
            {'table':'finance_invoices','column':'created_at','operator':'=','value':'2026-02-30'}])
        self.assertIn('error',result);conn.execute.assert_not_called()

    def test_different_ungrouped_calculations_are_not_equivalent(self):
        result,conn=self.execute(self.expression(),group_by=[self.expression('+')],having=[],
            select=[self.expression(),{'table':'finance_invoices','column':'id','aggregate':'COUNT'}])
        self.assertIn('Missing grouping fields',result['error']);conn.execute.assert_not_called()

    def test_generic_config_values_are_scoped_to_public_base_currency_key(self):
        self.schema={'tables':{'core_config':{'id':'int','key':'varchar','value':'text'}},'relationships':set()}
        conn = MagicMock()
        def fake_mcp(sql, database="", page_size=50, offset=0, include_total=False, params=None):
            conn.execute(sql, params)
            return {"rows": [], "has_more": False, "elapsed_ms": 1, "read_at": "2026-11-05T00:00:00"}
        with patch('assistant.query_service.resolve_tenant_database',return_value='test'), \
             patch('assistant.query_service._schema_for',return_value=self.schema), \
             patch('assistant.mcp_client.mcp_run_select', side_effect=fake_mcp):
            result=query_business_data({'base_table':'core_config','select':[{'table':'core_config','column':'value'}]},'test')
        self.assertNotIn('error',result)
        self.assertIn('WHERE t0.`key` = %(p0)s',str(conn.execute.call_args.args[0]))
        self.assertEqual(conn.execute.call_args.args[1]['p0'],'base_currency')
