from unittest.mock import patch
from types import SimpleNamespace

from django.test import Client, RequestFactory, SimpleTestCase, TestCase, override_settings

from assistant.erp_access import can_read, enforce_tenant, is_analytics_admin, analytics_admin_access, organization_conditions, principal_from_request, principal_scope, public_schema, redact
from assistant.local_engine import LocalAnswer, period
from assistant.query_planner import plan_question
from assistant.query_service import _validate_query_plan_relevance


ADMIN={'tenant':'apptimate_test','user_id':7,'name':'QA Admin','super_admin':True,'permissions':[],'organizations':None}
VIEWER={**ADMIN,'user_id':8,'name':'QA Viewer','super_admin':False,'permissions':['inventory.item.view','hr.leave.view'],'organizations':[22]}


class LocalAccessTests(SimpleTestCase):
    @override_settings(SUPPORT_BUSINESS_ENGINE=True, SUPPORT_ANALYTICS_ACCESS='admin')
    @patch('assistant.erp_access.bridge',return_value=VIEWER)
    def test_local_viewer_gets_admin_analytics_without_changing_erp_role(self,bridge):
        request=RequestFactory().get('/api/chat/')
        request.session={'erp_identity':{'tenant':'apptimate_test','user_id':8}}
        principal=principal_from_request(request,'apptimate_test')
        self.assertFalse(principal['super_admin'])
        self.assertTrue(is_analytics_admin(principal))
        self.assertEqual(principal['permissions'],VIEWER['permissions'])
        with principal_scope(principal):
            for module in ['hr_payroll_lines','finance_invoices','sales_orders','report_definitions']:
                self.assertTrue(can_read(module))
            self.assertEqual(organization_conditions('hr_payroll_lines',{}, {}, {},str),[])
            with self.assertRaises(PermissionError):enforce_tenant('apptimate_other')

    @override_settings(SUPPORT_BUSINESS_ENGINE=True, SUPPORT_ANALYTICS_ACCESS='erp')
    @patch('assistant.erp_access.bridge',return_value=VIEWER)
    def test_erp_policy_can_still_apply_original_grants(self,bridge):
        request=RequestFactory().get('/api/chat/')
        request.session={'erp_identity':{'tenant':'apptimate_test','user_id':8}}
        principal=principal_from_request(request,'apptimate_test')
        self.assertFalse(is_analytics_admin(principal))
        self.assertFalse(can_read('hr_payroll_lines',principal))

    @override_settings(SUPPORT_BUSINESS_ENGINE=False, SUPPORT_ANALYTICS_ACCESS='admin')
    def test_admin_policy_applies_only_to_business_engine(self):
        self.assertFalse(analytics_admin_access())

    def test_chat_tenant_cannot_override_session_tenant(self):
        with principal_scope(VIEWER), self.assertRaises(PermissionError):enforce_tenant('apptimate_other')

    def test_payroll_salary_and_bank_tables_need_payroll_grant(self):
        for table in ['hr_payroll_lines','hr_employee_salary','hr_employee_bank_details','hr_fnf_settlements']:
            self.assertFalse(can_read(table,VIEWER),table)

    def test_public_schema_removes_payroll_table_and_salary_field(self):
        with principal_scope(VIEWER):
            schema=public_schema({'tables':{'hr_payroll_lines':{'id':'int'},'hr_employee_experiences':{'id':'int','last_salary':'decimal'}},'relationships':set()})
        self.assertNotIn('hr_payroll_lines',schema['tables'])
        self.assertNotIn('last_salary',schema['tables']['hr_employee_experiences'])

    def test_recursive_secret_redaction_preserves_business_values(self):
        value=redact({'meta':'{"api_key":"do-not-show","quantity":9,"nested":{"password":"hidden"}}'})
        self.assertEqual(value['meta']['quantity'],9)
        self.assertEqual(value['meta']['api_key'],'[redacted]')
        self.assertEqual(value['meta']['nested']['password'],'[redacted]')

    def test_server_organization_scope_is_separate_from_user_filters(self):
        with principal_scope(VIEWER):
            conditions=organization_conditions('inventory_items',{'inventory_items':'inventory_items'},
                {'inventory_items':'t0'},{'tables':{'inventory_items':{'organization_id':'int'}},'relationships':set()},lambda x:':authorized_org')
        self.assertEqual(conditions,['t0.`organization_id` IN (:authorized_org)'])

    def test_child_inherits_scope_through_verified_parent_fk(self):
        with principal_scope(VIEWER):
            conditions=organization_conditions('lines',{'lines':'lines'},{'lines':'t0'},
                {'tables':{'lines':{'header_id':'int'},'headers':{'organization_id':'int'}},
                 'relationships':{('lines','header_id','headers','id')}},lambda x:':org')
        self.assertIn('EXISTS (SELECT 1 FROM `headers`',conditions[0])
        self.assertIn('t0.`header_id`=org_scope_0.`id`',conditions[0])

    def test_unscopable_business_table_is_not_assumed_global(self):
        with principal_scope(VIEWER),self.assertRaises(PermissionError):
            organization_conditions('private_rows',{'private_rows':'private_rows'},{'private_rows':'t0'},
                {'tables':{'private_rows':{'id':'int'}},'relationships':set()},str)


class LocalAnswerTests(SimpleTestCase):
    def answer(self,question,previous=()):return LocalAnswer('apptimate_test',ADMIN,question,previous_questions=previous)

    def test_clarification_has_no_fabricated_confidence_percentage(self):
        answer=self.answer('Unspecified request')
        answer.status='needs_clarification'
        result=answer.payload()
        self.assertIsNone(result['confidence'])
        self.assertIn('no live business facts',result['confidence_basis'])

    def test_diagnostics_explain_only_executed_tables_source_rules_once(self):
        answer=self.answer('Why is this business operation blocked?')
        result={'results':[],'query_audit':{'application_rules':{
            'source_table':'VerifiedSource.php: A recorded minimum is a quantity, not a monetary amount.'}}}
        answer.render_query(result,'Settings')
        answer.render_query(result,'Settings continued')
        text=' '.join(answer.parts)
        self.assertEqual(text.count('A recorded minimum is a quantity'),1)
        self.assertNotIn('VerifiedSource.php',text)
        self.assertNotIn('is the cause',text)

    @patch('assistant.business_recipes.answer_business_request',return_value=False)
    @patch('assistant.query_service.get_business_schema_context',return_value='- inventory_items: id (int), name (text), sku (text)')
    @patch('assistant.views.query_business_data')
    @patch('assistant.local_engine.plan_question')
    def test_new_item_questions_use_generated_plans_and_fresh_result_rows(self,planner,query,context,recipes):
        question='Which items matching UnseenProduct are there?'
        plan={'base_table':'inventory_items','select':[{'table':'inventory_items','column':'name','alias':'name'}],
              'filters':[{'table':'inventory_items','column':'name','operator':'LIKE','value':'%UnseenProduct%'}]}
        planner.return_value={'plans':[plan],'usage':{'prompt_tokens':10,'completion_tokens':5,'source':'provider','model':'gpt-6-luna'}}
        for current_name in ('UnseenProduct First','UnseenProduct Newly Added'):
            query.return_value={'results':[{'name':current_name}],'query_audit':{'selected_fields':plan['select']}}
            result=self.answer(question).run()
            self.assertEqual(result['answer_status'],'answered')
            self.assertIn(current_name,result['response'])
            self.assertEqual(result['usage']['source'],'provider')
            self.assertEqual(planner.call_args.args[0],question)
        self.assertEqual(query.call_count,2)
        self.assertNotIn('UnseenProduct First',result['response'])

    @patch('assistant.views.get_item_master_threshold_summary',return_value={
        'max_items':[{'sku':'WIDGET-123','value':7}], 'max_qty_configured':1,
        'min_items':[], 'min_qty_configured':0})
    @patch('assistant.views.get_item_stock_and_rules')
    def test_hyphenated_master_configuration_uses_live_settings_not_catalog(self,stock,summary):
        for question in (
            'is there anything configured on backend as item-master maximum:',
            'What is item-master maximum?',
            'Is there any item-master minimum quantity?',
        ):
            with self.subTest(question=question):
                summary.reset_mock()
                result=self.answer(question).run()
                self.assertEqual(result['answer_status'],'answered')
                summary.assert_called_once_with(tenant_identifier='apptimate_test')
                self.assertIn('Configured on **1 active item(s)**',result['response'])
                self.assertIn('Not configured on any active items',result['response'])
                self.assertNotIn('catalog match',result['response'])
        stock.assert_not_called()

    @patch('assistant.query_service._schema_for',return_value={'tables':{}})
    def test_failed_document_read_is_not_reported_as_a_missing_document(self,schema):
        from assistant.business_recipes import answer_business_request
        answer=self.answer('After TRF-20260708-001, how much is available at the destination for sale?')
        with patch.object(answer,'query',return_value={'error':'Database read unavailable'}):
            self.assertTrue(answer_business_request(answer))
        self.assertEqual(answer.status,'lookup_failed')
        self.assertNotIn('No inventory stock transfers record matched',' '.join(answer.parts))

    @patch('assistant.query_service._schema_for',return_value={'tables':{}})
    def test_till_display_name_is_resolved_when_it_differs_from_the_code(self,schema):
        from assistant.business_recipes import answer_business_request
        answer=self.answer('How much margin did T1 make on USD sales yesterday, and what is its USD closing balance?')
        row={'id':3,'name':'T1','terminal_code':'T-01'}
        with patch.object(answer,'query',side_effect=[{'results':[]},{'results':[row]},{'results':[row]},{'results':[]},{'results':[]}]) as query:
            self.assertTrue(answer_business_request(answer))
        self.assertEqual(query.call_args_list[0].args[0]['filters'][0]['column'],'terminal_code')
        self.assertEqual(query.call_args_list[1].args[0]['filters'][0]['column'],'name')
        self.assertEqual(answer.status,'partial')

    @patch('assistant.views.get_item_stock_and_rules',return_value={'found':True,'items':[{'item_name':'Widget','sku':'WIDGET-123','stock_levels':{'max_stock_level':4}}]})
    def test_item_setting_route_supports_arbitrary_skus(self,stock):
        result=self.answer('What is the Max Qty for WIDGET-123?').run()
        stock.assert_called_once_with('WIDGET-123',tenant_identifier='apptimate_test')
        self.assertIn('Max Qty: **4**',result['response'])

    def test_specific_serial_history_does_not_become_screen_help(self):
        from assistant.rag_service import is_serial_screen_location_question
        self.assertFalse(is_serial_screen_location_question('Where is serial number IPH15-SN-001 registered, and which recorded receipt or sale used it?'))
        self.assertTrue(is_serial_screen_location_question('where in sales items inventory exactly are serial numbers placed'))

    def test_serial_screen_guidance_requires_matching_documentation(self):
        from assistant.rag_service import format_verified_serial_locations
        self.assertIsNone(format_verified_serial_locations('Unrelated serial fields'))
        answer=format_verified_serial_locations('Sidebar ➔ Inventory ➔ Catalog ➔ Items. Registered serial numbers')
        self.assertIn('Serials',answer)
        self.assertNotIn('POS',answer)

    @patch('assistant.local_engine.plan_question')
    @patch('assistant.views.get_item_stock_and_rules',return_value={'found':False})
    def test_misspelled_watch_availability_uses_catalog_resolver(self,stock,planner):
        result=self.answer('i need watch is there availabe l').run()
        stock.assert_called_once_with('watch',tenant_identifier='apptimate_test')
        self.assertEqual(result['answer_status'],'needs_clarification')
        self.assertNotIn('Load Test',result['response'])
        planner.assert_not_called()

    @patch('assistant.query_service.expand_business_schema_context',return_value='- inventory_items: id (int), name (text)')
    @patch('assistant.query_service.get_business_schema_context',return_value='- inventory_stock_balances: item_id (int)')
    @patch('assistant.views.query_business_data',return_value={'results':[],'query_audit':{}})
    @patch('assistant.local_engine.plan_question')
    def test_schema_discovery_then_execution_keeps_result_rows_out_of_planner(self,planner,query,context,expand):
        planner.side_effect=[{'plans':[],'schema_tables':['inventory_items']},
            {'plans':[{'base_table':'inventory_items','select':[{'table':'inventory_items','column':'id'}]}]}]
        answer=self.answer('Show item names')
        answer.generic_answer()
        self.assertEqual(answer.status,'answered')
        expand.assert_called_once_with('apptimate_test',['inventory_stock_balances','inventory_items'])
        self.assertEqual(planner.call_count,2)
        self.assertEqual(planner.call_args.args[3],[])
        query.assert_called_once()

    @patch('assistant.query_service.get_business_schema_context',return_value='- inventory_items: id (int)')
    @patch('assistant.views.query_business_data',return_value={'results':[]})
    @patch('assistant.local_engine.plan_question')
    def test_repeated_schema_request_gets_explicit_feedback(self,planner,query,context):
        planner.side_effect=[{'plans':[],'schema_tables':['inventory_items']},
            {'plans':[{'base_table':'inventory_items','select':[{'table':'inventory_items','column':'id'}]}]}]
        answer=self.answer('Show item names')
        answer.generic_answer()
        self.assertIn('already fully described',planner.call_args.args[3][0])
        self.assertEqual(answer.status,'answered')

    @patch('assistant.local_engine.plan_question')
    @patch('assistant.views.query_business_data')
    def test_typo_item_comparison_asks_for_metric_before_any_read(self,query,planner):
        result=self.answer('list down the items which are gratre than 1000').run()
        self.assertEqual(result['answer_status'],'needs_clarification')
        self.assertIn('stock quantity',result['response'])
        self.assertIn('selling price',result['response'])
        query.assert_not_called();planner.assert_not_called()

    @patch('assistant.local_engine.plan_question')
    @patch('assistant.views.query_business_data',return_value={'results':[]})
    def test_comparison_metric_followup_retains_threshold_and_sums_stock(self,query,planner):
        state={}
        LocalAnswer('apptimate_test',ADMIN,'list items gratre than 1000',state=state).run()
        result=LocalAnswer('apptimate_test',ADMIN,'stock quantity',state=state).run()
        plan=query.call_args.args[0]
        self.assertEqual(plan['having'],[{'alias':'qty_available','operator':'>','value':1000}])
        self.assertEqual(plan['select'][-1]['aggregate'],'SUM')
        self.assertEqual(plan['select'][-1]['column'],'qty_available')
        self.assertEqual(result['answer_status'],'answered')
        planner.assert_not_called()

    @patch('assistant.local_engine.plan_question')
    @patch('assistant.views.get_item_stock_and_rules')
    def test_min_qty_uses_verified_item_lookup_for_assistant_admin(self,stock,planner):
        stock.return_value={'found':True,'items':[{'item_name':'Part A','sku':'AN-QA-PART-A','stock_levels':{'min_stock_level':5}}]}
        principal={**VIEWER,'analytics_admin':True}
        answer=LocalAnswer('apptimate_test',principal,'What is Min Qty for AN-QA-PART-A?').run()
        self.assertEqual(answer['answer_status'],'answered')
        self.assertIn('Min Qty: **5**',answer['response'])
        stock.assert_called_once()
        planner.assert_not_called()

    @patch('assistant.query_service.get_business_schema_context')
    def test_typo_followup_explains_previous_result_instead_of_permission_denial(self,schema):
        answer=LocalAnswer('apptimate_test',ADMIN,'what is thos',previous_questions=['List inventory items'],state={
            'last_query':{'base_table':'inventory_items','select':[{'column':'sku'},{'column':'name'}],
                'filters':[{'column':'status','operator':'=','value':'active'}]},
            'last_query_summary':{'row_count':9,'truncated':False}})
        result=answer.run()
        self.assertEqual(result['answer_status'],'answered')
        self.assertIn('Inventory Items',result['response'])
        self.assertIn('9 rows',result['response'])
        self.assertIn('status = active',result['response'])
        self.assertNotIn('permissions',result['response'])
        schema.assert_not_called()

    @patch('assistant.query_service.get_business_schema_context',return_value='')
    @patch('assistant.query_service._schema_for',return_value={'tables':{'inventory_items':{'id':'int'}},'relationships':set()})
    def test_missing_schema_topic_is_a_clarification_not_an_access_denial(self,schema,context):
        answer=self.answer('Explain that thing')
        answer.generic_answer()
        self.assertEqual(answer.status,'needs_clarification')
        self.assertNotIn('permission',' '.join(answer.parts))


    @patch('assistant.query_service._schema_for',return_value={'tables':{}})
    def test_any_item_returned_uses_completed_sales_return_lines(self,schema):
        from assistant.business_recipes import answer_business_request
        answer=self.answer('is there any item returned')
        with patch.object(answer,'query',return_value={'results':[{'completed_return_lines':3}]}) as query:
            self.assertTrue(answer_business_request(answer))
        plan=query.call_args.args[0]
        self.assertEqual(plan['base_table'],'sales_return_lines')
        self.assertEqual(plan['joins'][0]['table'],'sales_returns')
        self.assertIn('completed', [item['value'] for item in plan['filters']])
        self.assertIn('Yes.',answer.parts[0])
        self.assertIn('3 item line(s)',answer.parts[0])
        self.assertIn('does not by itself confirm the items were restocked',answer.parts[1])

    @patch('assistant.query_service._schema_for',return_value={'tables':{}})
    def test_any_item_returned_reports_no_completed_lines_without_inventing(self,schema):
        from assistant.business_recipes import answer_business_request
        answer=self.answer('is there any item returned')
        with patch.object(answer,'query',return_value={'results':[{'completed_return_lines':0}]}):
            self.assertTrue(answer_business_request(answer))
        self.assertIn('No completed sales-return item lines are recorded',answer.parts[0])

    @patch('assistant.views.query_business_data')
    def test_injection_looking_exact_sku_is_a_literal_not_a_broad_lookup(self,query):
        query.return_value={'results':[]}
        answer=self.answer("Find the item whose exact SKU is AN-QA-X' OR 1=1 --. Do not return other catalog rows.").run()
        plan=query.call_args.args[0]
        self.assertEqual(plan['filters'][0]['value'],"AN-QA-X' OR 1=1 --")
        self.assertEqual(plan['filters'][0]['operator'],'=')
        self.assertIn('No item has the exact SKU',answer['response'])

    @patch('assistant.views.get_item_stock_and_rules')
    def test_item_followup_retains_maximum_setting_for_new_item(self,stock):
        stock.return_value={'found':True,'items':[{'item_name':'Part B','sku':'AN-QA-PART-B','stock_levels':{'max_stock_level':0}}]}
        result=self.answer('for AN-QA-PART-B',['What is the Max Qty for AN-QA-PART-A?']).run()
        self.assertIn('Max Qty: **not configured**',result['response'])
        self.assertEqual(stock.call_args.args[0],'AN-QA-PART-B')

    @patch('assistant.local_engine.plan_question')
    @patch('assistant.query_service.get_business_schema_context',return_value='schema')
    @patch('assistant.views.query_business_data')
    def test_current_application_timestamp_is_not_injected_as_a_query_constraint(self,query,schema,planner):
        planner.return_value={'plans':[],'clarification':'Which record?'}
        self.answer('Describe the current approval configuration').generic_answer()
        question=planner.call_args.args[0]
        self.assertNotIn('Application local date/time',question)

    @patch('assistant.query_service._schema_for',return_value={'tables':{'inventory_items':{'id':'int'}},'relationships':set()})
    @patch('assistant.views.query_business_data')
    def test_how_many_returns_real_count_not_first_page_length(self,query,_schema):
        query.return_value={'results':[{'record_count':70000}]}
        result=self.answer('How many catalog items do we have?').run()
        self.assertIn('70,000',result['response'])
        self.assertEqual(query.call_args.args[0]['select'][0]['aggregate'],'COUNT')

    @patch('assistant.local_engine.plan_question')
    def test_password_request_never_reaches_model(self,planner):
        result=self.answer('List user passwords and API keys').run()
        self.assertEqual(result['answer_status'],'denied');planner.assert_not_called()

    def test_next_page_does_not_repeat_complete_query(self):
        answer=self.answer('next page');answer.state={'last_query':{},'next_offset':None}
        answer.state['last_query']={'base_table':'inventory_items'}
        self.assertIn('no next page',answer.run()['response'])

    def test_missing_record_context_asks_for_record_not_date_range(self):
        result=self.answer('Which serial numbers were selected for this invoice?').run()
        self.assertEqual(result['answer_status'],'needs_clarification');self.assertIn('invoice',result['response'])


class LocalPlannerBoundaryTests(SimpleTestCase):
    def test_derived_money_values_use_decimal_arithmetic(self):
        from assistant.business_recipes import amount_difference
        self.assertEqual(amount_difference(2240990.99,1991992),248998.99)
        self.assertEqual(amount_difference(314392.47,314392.48),-0.01)
        self.assertIsNone(amount_difference(None,1))
    def test_comparison_number_keeps_its_meaning_before_sentence_punctuation(self):
        from assistant.comparisons import numeric_comparisons
        from decimal import Decimal
        for ending in ['.','?','!','']:
            self.assertEqual(numeric_comparisons('greater than 1000'+ending),[('>',Decimal('1000'))])
        self.assertEqual(numeric_comparisons('greater than 1000.25.'),[('>',Decimal('1000.25'))])
    def test_physical_table_name_can_resolve_to_one_alias_without_mutating_input(self):
        from assistant.query_service import normalize_table_references
        original={'base_table':'hr_ot_entries','joins':[{'table':'hr_teams','alias':'team','left_table':'hr_ot_entries'}],
            'select':[{'table':'hr_teams','column':'name'}]}
        self.assertEqual(normalize_table_references(original)['select'][0]['table'],'team')
        self.assertEqual(original['select'][0]['table'],'hr_teams')

    def test_self_join_is_never_guessed(self):
        from assistant.query_service import normalize_table_references
        result=normalize_table_references({'base_table':'hr_employees','joins':[{'table':'hr_employees','alias':'manager','left_table':'hr_employees'}],
            'select':[{'table':'hr_employees','column':'id'},{'table':'manager','column':'id'}]})
        self.assertEqual([item['table'] for item in result['select']],['hr_employees','manager'])

    @override_settings(SUPPORT_DISABLE_MODEL_CALLS=True)
    @patch('assistant.views.client.chat.completions.create')
    def test_offline_verification_cannot_contact_the_model(self,create):
        with self.assertRaisesRegex(RuntimeError,'disabled'):plan_question('Question','schema')
        create.assert_not_called()

    @override_settings(SUPPORT_DISABLE_MODEL_CALLS=False)
    @patch('assistant.views.client.chat.completions.create')
    def test_openai_planner_uses_requested_model_and_reports_provider_usage(self,create):
        create.return_value=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"plans":[]}'))],
            usage=SimpleNamespace(prompt_tokens=12,completion_tokens=3))
        result=plan_question('Which items have stock greater than 1000?','inventory_items: id, sku')
        self.assertEqual(create.call_args.kwargs['model'],'gpt-6-luna')
        self.assertEqual(create.call_args.kwargs['reasoning_effort'],'none')
        self.assertFalse(create.call_args.kwargs['store'])
        self.assertEqual(result['usage']['source'],'provider')
        self.assertEqual(result['usage']['model'],'gpt-6-luna')

    @override_settings(SUPPORT_DISABLE_MODEL_CALLS=False)
    @patch('assistant.views.client.chat.completions.create')
    def test_database_errors_never_leave_the_environment(self,create):
        import json
        create.return_value=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"plans":[]}'))],usage=None)
        plan_question('Count items','inventory_items: id',history=['Show items'],failures=['private database result canary'])
        outgoing=create.call_args.kwargs['messages']
        self.assertNotIn('private database result canary',json.dumps(outgoing))
        self.assertEqual(set(json.loads(outgoing[1]['content'])),{'question','previous_questions'})

    def test_pagination_completeness_wording_is_not_a_business_comparison(self):
        _validate_query_plan_relevance('List all inventory serial numbers, and tell me whether this is the complete list if the row limit is exceeded.',
            {'base_table':'inventory_serial_numbers','select':[{'table':'inventory_serial_numbers','column':'serial_number'}]})

    def test_real_above_comparison_is_still_required(self):
        with self.assertRaisesRegex(ValueError,'greater-than'):
            _validate_query_plan_relevance('Show inventory items above the maximum stock level',
                {'base_table':'inventory_items','select':[{'table':'inventory_items','column':'id'}]})

    def test_bare_document_number_cannot_return_unfiltered_records(self):
        with self.assertRaisesRegex(ValueError,'specific record identifier'):
            _validate_query_plan_relevance('Show sales returns for PINV-2026-0001',
                {'base_table':'sales_return_lines','select':[{'table':'sales_return_lines','column':'return_quantity'}]})


@override_settings(SUPPORT_BUSINESS_ENGINE=True,SUPPORT_ANALYTICS_ACCESS='admin')
class ProviderBusinessEndpointTests(TestCase):
    @patch('assistant.views.resolve_tenant_database',return_value='apptimate_test')
    @patch('assistant.erp_access.bridge',return_value=VIEWER)
    @patch('assistant.local_engine.LocalAnswer.run')
    def test_provider_mode_keeps_authenticated_admin_engine_and_usage_history(self,run,bridge,tenant):
        from assistant.models import ChatUsageLog
        run.return_value={'response':'Verified local answer','answer_status':'answered',
            'usage':{'prompt_tokens':12,'completion_tokens':3,'total_tokens':15,'source':'provider','model':'gpt-6-luna'},
            'retrieved_references':[{'section_title':'Serial locations'}]}
        client=Client();session=client.session
        session['erp_identity']={'tenant':'apptimate_test','user_id':8};session.save()
        response=client.post('/api/chat/',data={'message':'Show business records','tenant_domain':'apptimate_test','session_id':'provider-session'},content_type='application/json')
        self.assertEqual(response.status_code,200)
        record=ChatUsageLog.objects.get(session_id='provider-session')
        self.assertEqual(record.user_id,'erp:apptimate_test:8')
        self.assertEqual(record.token_source,'provider')
        self.assertEqual(record.model_name,'gpt-6-luna')
        self.assertEqual(record.retrieved_chunks,[{'section_title':'Serial locations'}])
        history=client.get('/api/history/',{'session_id':'provider-session'}).json()
        self.assertEqual(history['history'][1]['metrics']['tokenSource'],'provider')
        self.assertEqual(history['history'][1]['metrics']['modelName'],'gpt-6-luna')
