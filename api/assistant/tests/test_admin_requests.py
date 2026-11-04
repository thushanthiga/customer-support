import tempfile
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase, override_settings

from assistant.local_engine import LocalAnswer
from assistant.request_context import resolve_request, is_configuration_question, is_request_reference
from assistant.query_service import _validate_query_plan_relevance

ADMIN={'tenant':'test','user_id':1,'super_admin':True,'permissions':[],'organizations':None}


class AdminRequestContextTests(SimpleTestCase):
    def test_summary_rows_are_not_described_as_individual_business_records(self):
        answer=LocalAnswer('test',ADMIN,'Count all receipts')
        answer.render_query({'results':[{'count':44}], 'query_audit':{'selected_fields':[
            {'table':'sales_pos','column':'id','aggregate':'COUNT','alias':'count'}]}},'Receipt count')
        self.assertIn('summary row',' '.join(answer.parts))
        self.assertNotIn('1 matching record',' '.join(answer.parts))

    def test_comparison_followup_preserves_entity_shape_dates_and_currency(self):
        state={}
        original='List POS sales under USD 50 from 2026-08-01 through 2026-08-31'
        resolve_request(original,[],state)
        self.assertEqual(resolve_request('above 75',[],state),
            'List POS sales above USD 75 from 2026-08-01 through 2026-08-31')
        self.assertEqual(resolve_request('as per the above',[],state),state['active_request']['question'])

    def test_history_recovers_comparison_intent_from_old_failed_session(self):
        state={}
        self.assertEqual(resolve_request('as per the above',
            ['List POS sales under 50','above 50'],state),'List POS sales above 50')

    def test_new_navigation_context_wins_over_older_pricing_question(self):
        state={}
        resolve_request('Can I give 14 percent off purchases above 6500?',[],state)
        resolve_request('where is the sales',[],state)
        self.assertEqual(resolve_request('pos',[],state),'Where can I find pos in sales?')
        self.assertEqual(resolve_request('Show unpaid invoices',[],state),'Show unpaid invoices')

    def test_detail_retry_retains_navigation_subject_across_repeated_choices(self):
        state={}
        history=[]
        for question in ['where is the sales','pos','now give me the coorect details','sales']:
            resolved=resolve_request(question,history,state)
            history.append(question)
        self.assertEqual(resolved,'Where can I find pos in sales?')
        self.assertEqual(state['active_request']['kind'],'navigation')

    def test_history_repairs_preexisting_lost_context(self):
        previous=['Can I give 20 percent off?','where is the sales','pos','now give me the coorect details']
        for stale in ['now give me the coorect details','sales']:
            with self.subTest(stale=stale):
                state={'active_request':{'kind':'business','question':stale}}
                self.assertEqual(resolve_request('sales',previous,state),'Where can I find pos in sales?')

    def test_retry_preserves_business_scope_without_becoming_a_new_query(self):
        original='List POS sales under USD 50 from 2026-08-01 through 2026-08-31'
        for followup in ['now give me the correct details','explain it properly','try again','show me the full results']:
            with self.subTest(followup=followup):
                state={}
                resolve_request(original,[],state)
                self.assertEqual(resolve_request(followup,[original],state),original)

    def test_substantive_new_subject_or_amount_is_not_a_reference(self):
        for question in ['give me sales totals','show me the details of invoice INV-123',
                         'give me the correct details under 75','correct the invoice',
                         'show me unpaid invoices','sales above 50']:
            with self.subTest(question=question):
                self.assertFalse(is_request_reference(question))

    def test_new_topic_supersedes_navigation_even_after_retry(self):
        previous=['where is the sales','pos','now give me the correct details','Show unpaid invoices']
        state={'active_request':{'kind':'navigation','question':'Where can I find pos in sales?'}}
        self.assertEqual(resolve_request('try again',previous,state),'Show unpaid invoices')
        self.assertEqual(state['active_request']['kind'],'business')

    def test_limited_fragment_history_preserves_resolved_state(self):
        current={'kind':'navigation','question':'Where can I find pos in sales?'}
        state={'active_request':current}
        self.assertEqual(resolve_request('sales',['pos','again','ok'],state),current['question'])

    def test_navigation_refinement_works_across_prefixes(self):
        for request in ['where are the employees','where can I open employees',
                        'how do I access employees','where should we find employees',
                        'how can I view employees','where can we go to employees']:
            with self.subTest(request=request):
                state={}
                resolve_request(request,[],state)
                resolved=resolve_request('payroll',[],state)
                self.assertEqual(resolved,'Where can I find payroll in employees?')
                self.assertEqual(resolve_request('employees',[],state),resolved)

    @patch('assistant.query_service.get_business_schema_context',return_value='- sales_pos: id (int), grand_total (decimal)')
    @patch('assistant.views.query_business_data')
    @patch('assistant.local_engine.plan_question')
    def test_retry_reads_fresh_rows_instead_of_reusing_the_prior_answer(self,planner,read,schema):
        fields=[{'table':'sales_pos','column':'id','alias':'id'},
                {'table':'sales_pos','column':'grand_total','alias':'amount'}]
        planner.return_value={'plans':[{'base_table':'sales_pos','select':fields,
            'filters':[{'table':'sales_pos','column':'grand_total','operator':'<','value':50}]}]}
        read.side_effect=[{'results':[{'id':i,'amount':10*i}],
            'query_audit':{'selected_fields':fields}} for i in (1,2)]
        state={}
        original='List POS sales under 50'
        LocalAnswer('test',ADMIN,original,state=state).run()
        result=LocalAnswer('test',ADMIN,'now give me the correct details',previous_questions=[original],state=state).run()
        self.assertEqual(planner.call_count,2)
        self.assertEqual(read.call_count,2)
        self.assertEqual(planner.call_args.args[0],original)
        self.assertEqual(result['data_pages'][0]['rows'],[{'id':2,'amount':20}])

    def test_failed_retrieval_basis_does_not_claim_facts_were_unnecessary(self):
        for status in ['unsupported','lookup_failed']:
            with self.subTest(status=status):
                answer=LocalAnswer('test',ADMIN,'sales')
                answer.status=status
                basis=answer.payload()['confidence_basis']
                self.assertIn('requested result was not retrieved',basis)
                self.assertNotIn('needed',basis)

    @patch('assistant.local_engine.plan_question')
    @patch('assistant.views.query_business_data')
    def test_reference_without_context_requests_the_missing_question(self,read,planner):
        result=LocalAnswer('test',ADMIN,'now give me the correct details').run()
        self.assertEqual(result['answer_status'],'needs_clarification')
        self.assertIn('repeat the question',result['response'])
        read.assert_not_called();planner.assert_not_called()

    def test_ambiguous_multi_metric_followup_is_not_guessed(self):
        state={}
        resolve_request('Show items above 10 with price below 200',[],state)
        self.assertEqual(resolve_request('above 50',[],state),'above 50')

    @patch('assistant.query_service.get_business_schema_context')
    @patch('assistant.views.query_business_data')
    @patch('assistant.local_engine.plan_question')
    def test_acknowledgement_has_no_lookup_or_clarification(self,planner,read,schema):
        result=LocalAnswer('test',ADMIN,'ok ok').run()
        self.assertEqual(result['answer_status'],'answered')
        self.assertIn('Okay',result['response'])
        self.assertIn('No live business facts were needed',result['confidence_basis'])
        planner.assert_not_called();read.assert_not_called();schema.assert_not_called()

    def test_proposed_rule_threshold_is_not_a_configuration_row_filter(self):
        question='Can I give 14 percent off for purchases above 6500?'
        self.assertTrue(is_configuration_question(question))
        _validate_query_plan_relevance(question,{'base_table':'sales_price_rules',
            'select':[{'table':'sales_price_rules','column':'min_quantity'}]})
        _validate_query_plan_relevance(question,{'base_table':'sales_price_lists',
            'select':[{'table':'sales_price_lists','column':'is_active'}]})
        with self.assertRaisesRegex(ValueError,'numeric comparison'):
            _validate_query_plan_relevance(question+' Also list POS sales above 6500.',{
                'base_table':'sales_pos','select':[{'table':'sales_pos','column':'id'},
                    {'table':'sales_pos','column':'grand_total'}]})

    def test_source_input_limits_are_applied_to_arbitrary_proposed_values(self):
        for value,expected in [(14,'within'),(125,'outside')]:
            answer=LocalAnswer('test',ADMIN,f'Can I give {value} percent off purchases above 6500?')
            answer.render_query({'results':[],'query_audit':{'application_input_limits':{
                'sales_price_rules':{'markdown_percentage':{'minimum':0,'maximum':100,'unit':'percent'}}}}},'Rules')
            self.assertIn(f'**{value}%** is **{expected}**',' '.join(answer.parts))
            self.assertNotIn('has been applied',' '.join(answer.parts))

    @patch('assistant.query_service.get_business_schema_context',return_value='- sales_price_lists: id (int), is_active (tinyint)')
    @patch('assistant.query_service.expand_business_schema_context',return_value='- sales_price_lists: id (int), is_active (tinyint)')
    @patch('assistant.views.query_business_data')
    @patch('assistant.local_engine.plan_question')
    def test_invalid_plan_gets_one_schema_only_repair(self,planner,read,expand,schema):
        bad={'base_table':'sales_price_lists','select':[{'table':'sales_price_lists','column':'status'}]}
        good={'base_table':'sales_price_lists','select':[{'table':'sales_price_lists','column':'is_active','alias':'enabled'}]}
        planner.side_effect=[{'plans':[bad]},{'plans':[good]}]
        read.side_effect=[{'error':'private error canary'},
            {'results':[{'enabled':1}],'query_audit':{'selected_fields':good['select']}}]
        answer=LocalAnswer('test',ADMIN,'Check current offer restrictions')
        answer.generic_answer()
        self.assertEqual(answer.status,'answered')
        self.assertEqual(planner.call_count,2)
        self.assertIn('SCHEMA CHECK',planner.call_args.args[1])
        self.assertNotIn('private error canary',planner.call_args.args[1])
        self.assertNotIn('private error canary',' '.join(answer.parts))

    @patch('assistant.query_service.get_business_schema_context',return_value='- sales_price_lists: id (int)')
    @patch('assistant.query_service.expand_business_schema_context',return_value='- sales_price_lists: id (int)')
    @patch('assistant.views.query_business_data',return_value={'error':'private error canary'})
    @patch('assistant.local_engine.plan_question')
    def test_identical_invalid_plan_is_not_reexecuted_repeatedly(self,planner,read,expand,schema):
        planner.return_value={'plans':[{'base_table':'sales_price_lists','select':[{'table':'sales_price_lists','column':'status'}]}]}
        answer=LocalAnswer('test',ADMIN,'Check offer configuration')
        answer.generic_answer()
        self.assertEqual(planner.call_count,2)
        read.assert_called_once()
        self.assertNotIn('private error canary',' '.join(answer.parts))

    @patch('assistant.query_service.get_business_schema_context',return_value='- sales_price_rules: id (int)\n- sales_price_lists: id (int), is_active (tinyint)')
    @patch('assistant.query_service.expand_business_schema_context',return_value='- sales_price_rules: id (int)\n- sales_price_lists: id (int), is_active (tinyint)')
    @patch('assistant.views.query_business_data')
    @patch('assistant.local_engine.plan_question')
    def test_repair_keeps_successful_parts_without_duplicate_reads(self,planner,read,expand,schema):
        rules={'base_table':'sales_price_rules','select':[{'table':'sales_price_rules','column':'id','alias':'id'}]}
        bad={'base_table':'sales_price_lists','select':[{'table':'sales_price_lists','column':'status'}]}
        good={'base_table':'sales_price_lists','select':[{'table':'sales_price_lists','column':'is_active','alias':'enabled'}]}
        planner.side_effect=[{'plans':[rules,bad]},{'plans':[rules,good]}]
        read.side_effect=[{'results':[{'id':1}],'query_audit':{'selected_fields':rules['select']}},
            {'error':'invalid schema field'},
            {'results':[{'enabled':1}],'query_audit':{'selected_fields':good['select']}}]
        answer=LocalAnswer('test',ADMIN,'Check offer configuration')
        answer.generic_answer()
        self.assertEqual(answer.status,'answered')
        self.assertEqual(read.call_count,3)
        self.assertEqual(len(answer.data_pages),2)


class NavigationWithoutIndexTests(TestCase):
    def test_broad_topic_then_creation_location_uses_documented_entry_controls(self):
        from assistant.models import ChatUsageLog,UploadedDocument,DocumentChunk
        with tempfile.TemporaryDirectory() as directory:
            Path(directory,'source.md').write_text(
                '## Feature: POS\nPOS uses `/sales/pos`.\n'
                '- A **New Sale** link opens checkout.\n\n'
                'Returns can be viewed at `/sales/returns`; that related link is not the POS entry screen.\n\n'
                '## Feature: ORDERS\nOrders use `/sales/orders`.\n'
                'The toolbar includes a **New Order** action.\n\n'
                '## Feature: REPORTS\nReports use `/sales/reports`. This is a view-only page.\n\n'
                '## Feature: PURCHASE ORDERS\nPurchase orders use `/procurement/orders`.\n'
                'Click **New Purchase Order** to open the form.\n\n'
                '## Verified Default Navigation Reference\n\n'
                '### Default navigation: Sales / POS Sales\n\n'
                '- **Access Flow:** Sidebar ➔ Sales ➔ POS ➔ POS Sales.\n'
                '- **Route:** `/sales/pos`\n\n'
                '### Default navigation: Sales / Sales Orders\n\n'
                '- **Access Flow:** Sidebar ➔ Sales ➔ Orders ➔ Sales Orders.\n'
                '- **Route:** `/sales/orders`\n\n'
                '### Default navigation: Sales / Sales Reports\n\n'
                '- **Access Flow:** Sidebar ➔ Sales ➔ Analytics ➔ Sales Reports.\n'
                '- **Route:** `/sales/reports`\n\n'
                '### Default navigation: Sales / Sales Returns\n\n'
                '- **Access Flow:** Sidebar ➔ Sales ➔ Post-Sales ➔ Sales Returns.\n'
                '- **Route:** `/sales/returns`\n\n'
                '### Default navigation: Procurement / Purchase Orders\n\n'
                '- **Access Flow:** Sidebar ➔ Procurement ➔ Orders ➔ Purchase Orders.\n'
                '- **Route:** `/procurement/orders`\n')
            with override_settings(MEDIA_ROOT=directory), \
                    patch('assistant.local_engine.plan_question',side_effect=AssertionError('Unexpected planning')) as planner, \
                    patch('assistant.query_service.get_business_schema_context',side_effect=AssertionError('Unexpected schema lookup')) as schema, \
                    patch('assistant.views.query_business_data',side_effect=AssertionError('Unexpected business query')) as read:
                state={};history=[]
                for question in ['I need sales','place where we can create sales','pos']:
                    result=LocalAnswer('test',ADMIN,question,previous_questions=history,state=state).run()
                    history.append(question)
                    self.assertEqual(result['usage']['total_tokens'],0)
                    if len(history)==1:
                        self.assertEqual(result['answer_status'],'needs_clarification')
                        self.assertIn('create/manage sales',result['response'])
                    else:
                        self.assertEqual(result['answer_status'],'answered')
                        self.assertIn('Sidebar ➔ Sales ➔ POS ➔ POS Sales',result['response'])
                        self.assertIn('**New Sale**',result['response'])
                        self.assertNotIn('Sales Reports',result['response'])
                        self.assertNotIn('Sales Returns',result['response'])
                # A missing subject is filled from the pending clarification.
                state={}
                LocalAnswer('test',ADMIN,'I need sales',state=state).run()
                result=LocalAnswer('test',ADMIN,'place where we can create',state=state).run()
                self.assertIn('**New Sale**',result['response'])
                self.assertNotIn('pending_topic',state)
                stale={'active_request':{'kind':'business','question':'place where we can create sales'}}
                result=LocalAnswer('test',ADMIN,'pos',previous_questions=[
                    'I need sales','place where we can create sales'],state=stale).run()
                self.assertIn('**New Sale**',result['response'])
                self.assertNotIn('Sales Returns',result['response'])
                # Other modules and actions use their own source evidence.
                result=LocalAnswer('test',ADMIN,'where can I create sales orders').run()
                self.assertIn('**New Order**',result['response'])
                self.assertNotIn('**New Sale**',result['response'])
                result=LocalAnswer('test',ADMIN,'where can I create purchase orders').run()
                self.assertIn('**New Purchase Order**',result['response'])
                self.assertNotIn('POS Sales',result['response'])
                # A menu without create evidence cannot establish that action.
                result=LocalAnswer('test',ADMIN,'where can I create sales reports').run()
                self.assertIn('does not establish a creation action',result['response'])
            planner.assert_not_called();read.assert_not_called();schema.assert_not_called()
            self.assertEqual(ChatUsageLog.objects.count(),0)
            self.assertEqual(UploadedDocument.objects.count(),0)
            self.assertEqual(DocumentChunk.objects.count(),0)

    @patch('assistant.query_service.get_business_schema_context',return_value='- sales_pos: id (int), grand_total (decimal)')
    @patch('assistant.views.query_business_data')
    @patch('assistant.local_engine.plan_question')
    def test_explicit_transaction_filter_leaves_navigation_and_queries_records(self,planner,read,schema):
        fields=[{'table':'sales_pos','column':'id','alias':'id'},
                {'table':'sales_pos','column':'grand_total','alias':'amount'}]
        plan={'base_table':'sales_pos','select':fields,
            'filters':[{'table':'sales_pos','column':'grand_total','operator':'<','value':50}]}
        planner.return_value={'plans':[plan]}
        def validated_read(plan,tenant,**kwargs):
            _validate_query_plan_relevance(kwargs['user_question'],plan)
            return {'results':[{'id':123,'amount':25}],
                    'query_audit':{'selected_fields':fields,'filters':plan['filters']}}
        read.side_effect=validated_read
        state={'active_request':{'kind':'navigation','question':'Where can I find pos in sales?'}}
        result=LocalAnswer('test',ADMIN,'I need to find POS sales under 50',
            previous_questions=['I need to find sales','pos'],state=state).run()
        self.assertEqual(result['answer_status'],'answered')
        self.assertEqual(result['data_pages'][0]['rows'],[{'id':123,'amount':25}])
        self.assertIn('grand_total < 50',result['response'])
        self.assertEqual(state['active_request']['kind'],'business')
        planner.assert_called_once();read.assert_called_once();schema.assert_called_once()

    def test_declarative_navigation_and_pos_choice_never_use_business_planning(self):
        from assistant.models import ChatUsageLog,UploadedDocument,DocumentChunk
        with tempfile.TemporaryDirectory() as directory:
            Path(directory,'source.md').write_text('## Verified Default Navigation Reference\n\n'
                '### Default navigation: Sales / POS Sales\n\n'
                '- **Access Flow:** Sidebar ➔ Sales ➔ POS ➔ POS Sales.\n'
                '- **Route:** `/sales/pos`\n\n'
                '### Default navigation: HR / Payroll\n\n'
                '- **Access Flow:** Sidebar ➔ HR ➔ Payroll ➔ Payroll Runs.\n'
                '- **Route:** `/hr/payroll`\n')
            with override_settings(MEDIA_ROOT=directory), \
                    patch('assistant.local_engine.plan_question',side_effect=AssertionError('Unexpected planning')) as planner, \
                    patch('assistant.query_service.get_business_schema_context',side_effect=AssertionError('Unexpected schema lookup')) as schema, \
                    patch('assistant.views.query_business_data',side_effect=AssertionError('Unexpected business query')) as read:
                for initial in ['I need to find sales','I want to open sales',
                                'Please help me find the sales screen','I am looking for sales']:
                    with self.subTest(initial=initial):
                        state={}
                        first=LocalAnswer('test',ADMIN,initial,state=state).run()
                        result=LocalAnswer('test',ADMIN,'pos',previous_questions=[initial],state=state).run()
                        self.assertEqual(first['answer_status'],'answered')
                        self.assertEqual(result['answer_status'],'answered')
                        self.assertIn('Sidebar ➔ Sales ➔ POS ➔ POS Sales',result['response'])
                        self.assertEqual(result['usage']['total_tokens'],0)
                        self.assertIn('verified local documentation',result['confidence_basis'])
                        # Existing sessions from the misclassified old flow
                        # recover without using assistant replies as evidence.
                        stale={'active_request':{'kind':'business','question':'pos'}}
                        recovered=LocalAnswer('test',ADMIN,'pos',previous_questions=[initial],state=stale).run()
                        self.assertEqual(recovered['response'],result['response'])
                other=LocalAnswer('test',ADMIN,'We would like to access payroll',state=state).run()
                self.assertIn('Sidebar ➔ HR ➔ Payroll ➔ Payroll Runs',other['response'])
                self.assertNotIn('POS Sales',other['response'])
                missing=LocalAnswer('test',ADMIN,'I need to find the unlisted screen',state=state).run()
                self.assertEqual(missing['answer_status'],'needs_clarification')
                self.assertIn('verified menu path',missing['response'])
            planner.assert_not_called();read.assert_not_called();schema.assert_not_called()
            self.assertEqual(ChatUsageLog.objects.count(),0)
            self.assertEqual(UploadedDocument.objects.count(),0)
            self.assertEqual(DocumentChunk.objects.count(),0)

    def test_navigation_works_from_retained_markdown_without_recreating_index(self):
        from assistant.models import UploadedDocument,DocumentChunk
        with tempfile.TemporaryDirectory() as directory:
            Path(directory,'source.md').write_text('## Verified Default Navigation Reference\n\n'
                '### Default navigation: Sales / POS Sales\n\n'
                '- **Access Flow:** Sidebar ➔ Sales ➔ POS ➔ POS Sales.\n'
                '- **Route:** `/sales/pos`\n')
            state={}
            with override_settings(MEDIA_ROOT=directory),patch('assistant.local_engine.plan_question') as planner,patch('assistant.views.query_business_data') as read:
                LocalAnswer('test',ADMIN,'where is the sales',state=state).run()
                result=LocalAnswer('test',ADMIN,'pos',state=state).run()
            self.assertIn('Sidebar ➔ Sales ➔ POS ➔ POS Sales',result['response'])
            self.assertEqual(result['answer_status'],'answered')
            self.assertIn('verified local documentation',result['confidence_basis'])
            planner.assert_not_called();read.assert_not_called()
            self.assertEqual(UploadedDocument.objects.count(),0)
            self.assertEqual(DocumentChunk.objects.count(),0)

    def test_exact_retry_dialogue_and_old_session_recover_documented_pos_sales(self):
        from assistant.models import UploadedDocument,DocumentChunk
        with tempfile.TemporaryDirectory() as directory:
            Path(directory,'source.md').write_text('## Verified Default Navigation Reference\n\n'
                '### Default navigation: Sales / POS Sales\n\n'
                '- **Access Flow:** Sidebar ➔ Sales ➔ POS ➔ POS Sales.\n'
                '- **Route:** `/sales/pos`\n\n'
                '### Default navigation: Inventory / Items\n\n'
                '- **Access Flow:** Sidebar ➔ Inventory ➔ Catalog ➔ Items.\n'
                '- **Route:** `/inventory/items`\n')
            with override_settings(MEDIA_ROOT=directory), \
                    patch('assistant.local_engine.plan_question',side_effect=AssertionError('Unexpected planning')) as planner, \
                    patch('assistant.views.query_business_data',side_effect=AssertionError('Unexpected business query')) as read:
                history=[];state={}
                for question in ['where is the sales','pos','now give me the coorect details','sales']:
                    result=LocalAnswer('test',ADMIN,question,previous_questions=history,state=state).run()
                    history.append(question)
                    self.assertEqual(result['answer_status'],'answered')
                    self.assertIn('Sidebar ➔ Sales ➔ POS ➔ POS Sales',result['response'])
                    self.assertEqual(result['usage']['total_tokens'],0)
                    self.assertIn('verified local documentation',result['confidence_basis'])
                    self.assertFalse(result['data_pages'])
                state={'active_request':{'kind':'business','question':'now give me the coorect details'}}
                result=LocalAnswer('test',ADMIN,'sales',previous_questions=history[:-1],state=state).run()
                self.assertIn('Sidebar ➔ Sales ➔ POS ➔ POS Sales',result['response'])
                # The correction is not a hardcoded POS answer: a new module
                # replaces the topic and resolves its own documented route.
                result=LocalAnswer('test',ADMIN,'where can I open inventory items',previous_questions=history,state=state).run()
                self.assertIn('Sidebar ➔ Inventory ➔ Catalog ➔ Items',result['response'])
                self.assertNotIn('POS Sales',result['response'])
            planner.assert_not_called();read.assert_not_called()
            self.assertEqual(UploadedDocument.objects.count(),0)
            self.assertEqual(DocumentChunk.objects.count(),0)
