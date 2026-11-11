"""General planning contracts and execution gates, independent of question keywords."""
from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import patch
from django.test import SimpleTestCase, override_settings
from assistant.local_engine import LocalAnswer, normalize_query_text
from assistant.query_planner import plan_question, PlanningValidationError
from assistant.query_service import _format_schema_context


def proposal():
    return {
        'intent': 'aggregate', 'resolved_question': 'Total recorded amount',
        'analysis_contract': {
            'goal': 'Measure recorded value', 'entity': 'records',
            'metric': 'Sum of recorded amount', 'grain': 'One total',
            'scope': 'All stored records; no date restriction requested',
            'context_used': [], 'assumptions': [], 'ambiguities': [],
            'requirements': [{'requirement': 'Total recorded amount', 'status': 'supported',
                              'plan_indexes': [0], 'limitation': ''}],
        },
        'plans': [{'base_table': 'records', 'select': [
            {'table': 'records', 'column': 'amount', 'alias': 'total', 'aggregate': 'SUM'}]}],
    }


def reply(value, tokens=10, **message_fields):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
        content=json.dumps(value), **message_fields), finish_reason='stop')],
        usage=SimpleNamespace(prompt_tokens=tokens, completion_tokens=tokens))


APPROVED = {'verdict': 'approve', 'issues': [], 'clarification': ''}


@override_settings(SUPPORT_DISABLE_MODEL_CALLS=False)
class PlanningContractTests(SimpleTestCase):
    @patch('assistant.query_planner.client.chat.completions.create')
    def test_approved_plan_uses_independent_review_and_accounts_both_calls(self, provider):
        provider.side_effect = [reply(proposal()), reply(APPROVED)]
        result = plan_question('Total recorded amount', 'records: amount (decimal)')
        self.assertEqual(result['query_review']['verdict'], 'approve')
        self.assertEqual(result['usage']['prompt_tokens'], 20)
        self.assertEqual(result['usage']['completion_tokens'], 20)
        review_request = json.loads(provider.call_args.kwargs['messages'][1]['content'])
        self.assertEqual(review_request['question'], 'Total recorded amount')
        self.assertNotIn('results', review_request)
        self.assertEqual(provider.call_args.kwargs['response_format']['type'], 'json_schema')

    @patch('assistant.query_planner.client.chat.completions.create')
    def test_wrong_metric_scope_join_or_predicate_fails_closed(self, provider):
        for issue in ('Different metric from the current request', 'Missing time restriction',
                      'Header amounts are multiplied by the join', 'Threshold direction is reversed',
                      'Unconverted currencies were summed', 'Only a page was used for a full total'):
            with self.subTest(issue=issue):
                provider.reset_mock()
                provider.side_effect = [reply(proposal()), reply({'verdict': 'revise', 'issues': [issue], 'clarification': ''})]
                with self.assertRaisesRegex(PlanningValidationError, issue):
                    plan_question('The current analytical question', 'verified schema')
                self.assertEqual(provider.call_count, 2)

    @patch('assistant.query_planner.client.chat.completions.create')
    def test_review_ambiguity_returns_clarification_without_plans(self, provider):
        provider.side_effect = [reply(proposal()), reply({
            'verdict': 'clarify', 'issues': ['Metric has multiple meanings'],
            'clarification': 'Which business measure do you mean?',
        })]
        result = plan_question('Which entities are performing well?', 'verified schema')
        self.assertEqual(result['plans'], [])
        self.assertEqual(result['clarification'], 'Which business measure do you mean?')
        self.assertEqual(result['analysis_contract']['requirements'][0]['plan_indexes'], [])

    @patch('assistant.query_planner.client.chat.completions.create')
    def test_optional_reporting_preferences_cannot_bypass_review(self, provider):
        candidate = proposal()
        candidate['plans'] = []
        candidate['clarification'] = 'Which metric and period?'
        candidate['analysis_contract']['requirements'][0].update(
            status='needs_clarification', plan_indexes=[], limitation='Metric and period omitted')
        provider.side_effect = [reply(candidate), reply({
            'verdict': 'revise', 'issues': ['Use a disclosed conventional reporting basis; these preferences do not block useful analysis.'],
            'clarification': '',
        })]
        with self.assertRaisesRegex(PlanningValidationError, 'disclosed conventional'):
            plan_question('Show the leading products', 'verified schema')
        self.assertEqual(provider.call_count, 2)

    @patch('assistant.query_planner.client.chat.completions.create')
    def test_disclosed_defaults_are_not_blocking_ambiguities(self, provider):
        candidate = proposal()
        candidate['analysis_contract']['assumptions'] = ['Use recorded activity as the exploratory measure.']
        provider.side_effect = [reply(candidate), reply(APPROVED)]
        result = plan_question('Show overall activity', 'verified schema')
        self.assertTrue(result['plans'])
        self.assertNotIn('clarification', result)
        self.assertEqual(result['analysis_contract']['ambiguities'], [])

    @patch('assistant.query_planner.client.chat.completions.create')
    def test_invalid_schema_and_coverage_never_reach_review(self, provider):
        invalid = []
        value = proposal(); del value['analysis_contract']; invalid.append(value)
        value = proposal(); value['plans'][0]['select'][0]['aggregate'] = 'MADE_UP'; invalid.append(value)
        value = proposal(); value['analysis_contract']['requirements'][0]['plan_indexes'] = [4]; invalid.append(value)
        value = proposal(); value['analysis_contract']['requirements'][0]['plan_indexes'] = []; invalid.append(value)
        value = proposal(); value['analysis_contract']['ambiguities'] = ['Unresolved measure']; invalid.append(value)
        value = proposal(); value['plans'].append(deepcopy(value['plans'][0])); invalid.append(value)
        value = proposal(); value['schema_tables'] = ['another_table']; invalid.append(value)
        for value in invalid:
            with self.subTest(value=value):
                provider.reset_mock(); provider.side_effect = None; provider.return_value = reply(value)
                with self.assertRaises(PlanningValidationError):
                    plan_question('Calculate the requested result', 'schema')
                self.assertEqual(provider.call_count, 1)

    @patch('assistant.query_planner.client.chat.completions.create')
    def test_review_unavailable_does_not_release_candidate(self, provider):
        provider.side_effect = [reply(proposal()), RuntimeError('Unavailable')]
        with self.assertRaises(PlanningValidationError) as caught:
            plan_question('Total amount', 'schema')
        self.assertEqual(caught.exception.usage['prompt_tokens'], 10)

    @patch('assistant.query_planner.client.chat.completions.create')
    def test_approval_with_unresolved_issues_is_rejected(self, provider):
        provider.side_effect = [reply(proposal()), reply({'verdict': 'approve', 'issues': ['Unknown denominator'], 'clarification': ''})]
        with self.assertRaises(PlanningValidationError):
            plan_question('Calculate a ratio', 'schema')

    @patch('assistant.query_planner.client.chat.completions.create')
    def test_refusal_cannot_be_interpreted_as_a_plan(self, provider):
        provider.return_value = reply(proposal(), refusal='Refused')
        with self.assertRaises(PlanningValidationError):
            plan_question('Question', 'schema')
        self.assertEqual(provider.call_count, 1)

    @patch('assistant.query_planner.client.chat.completions.create')
    def test_discovery_skips_review_but_clarification_is_reviewed(self, provider):
        for field, value in [('clarification', 'Which measure do you mean?'), ('schema_tables', ['records'])]:
            candidate = proposal()
            candidate['plans'] = []
            candidate[field] = value
            candidate['analysis_contract']['requirements'][0].update(status='needs_clarification', plan_indexes=[], limitation='Need more evidence')
            provider.reset_mock()
            provider.side_effect = [reply(candidate), reply(APPROVED)] if field == 'clarification' else [reply(candidate)]
            result = plan_question('A new request', 'schema')
            self.assertEqual(result['plans'], [])
            self.assertEqual(provider.call_count, 2 if field == 'clarification' else 1)


@override_settings(SUPPORT_DISABLE_MODEL_CALLS=True)
class PlanningExecutionTests(SimpleTestCase):
    @patch('assistant.local_engine.query_service.get_business_schema_context', return_value='records schema')
    @patch('assistant.local_engine.query_service.query_business_data')
    @patch('assistant.local_engine.plan_question')
    def test_semantic_rejection_is_repaired_before_any_database_read(self, planner, query, schema):
        fixed = proposal(); fixed['query_review'] = APPROVED
        planner.side_effect = [PlanningValidationError('The current metric was replaced'), fixed]
        query.return_value = {'results': [{'total': 73}], 'query_audit': {'selected_fields': fixed['plans'][0]['select']}}
        answer = LocalAnswer('apptimate_test', {}, 'Total recorded amount', previous_questions=['Another question'])
        result = answer.run()
        self.assertEqual(query.call_count, 1)
        self.assertEqual(planner.call_count, 2)
        self.assertEqual(planner.call_args.args[0], 'Total recorded amount')
        self.assertIn('The current metric was replaced', planner.call_args.args[3])
        self.assertIn('| 73 |', result['response'])
        self.assertEqual(result['analysis_contract']['scope'], fixed['analysis_contract']['scope'])

    @patch('assistant.local_engine.query_service.get_business_schema_context', return_value='records schema')
    @patch('assistant.local_engine.query_service.query_business_data')
    @patch('assistant.local_engine.plan_question', side_effect=PlanningValidationError('Unsupported interpretation'))
    def test_repeated_rejection_is_bounded_and_never_queries(self, planner, query, schema):
        result = LocalAnswer('apptimate_test', {}, 'Calculate a business measure').run()
        self.assertEqual(planner.call_count, 4)
        query.assert_not_called()
        self.assertNotEqual(result['answer_status'], 'answered')
        self.assertEqual(result['data_pages'], [])

    @patch('assistant.local_engine.query_service.get_business_schema_context', return_value='records schema')
    @patch('assistant.local_engine.query_service.query_business_data')
    @patch('assistant.local_engine.plan_question')
    def test_new_metric_clarification_does_not_reuse_old_result(self, planner, query, schema):
        candidate = proposal(); candidate['plans'] = []; candidate['clarification'] = 'Which measure should be used?'
        planner.return_value = candidate
        state = {'last_query': {'base_table': 'old'}, 'next_offset': 50, 'query_pages': [{'title': 'Old result'}]}
        result = LocalAnswer('apptimate_test', {}, 'Which items are at risk?', previous_questions=['Which items are in demand?'], state=state).run()
        self.assertEqual(result['answer_status'], 'needs_clarification')
        query.assert_not_called()
        self.assertNotIn('last_query', state)
        self.assertEqual(planner.call_args.args[0], 'Which items are at risk?')

    @patch('assistant.local_engine.query_service.get_business_schema_context', return_value='records schema')
    @patch('assistant.local_engine.query_service.expand_business_schema_context', return_value='expanded schema')
    @patch('assistant.local_engine.query_service.query_business_data')
    @patch('assistant.local_engine.plan_question')
    def test_model_paraphrase_cannot_replace_original_during_discovery(self, planner, query, expand, schema):
        candidate = proposal()
        planner.side_effect = [{'plans': [], 'schema_tables': ['records'], 'resolved_question': 'An entirely different request'}, candidate]
        query.return_value = {'results': [], 'query_audit': {'selected_fields': candidate['plans'][0]['select']}}
        original = 'Compute the specified metric for the current period'
        LocalAnswer('apptimate_test', {}, original).run()
        self.assertEqual([call.args[0] for call in planner.call_args_list], [original, original])
        self.assertEqual(query.call_args.kwargs['user_question'], original)

    @patch('assistant.local_engine.query_service.get_business_schema_context', return_value='records schema')
    @patch('assistant.local_engine.query_service.expand_business_schema_context', return_value='expanded schema')
    @patch('assistant.local_engine.query_service.query_business_data')
    @patch('assistant.local_engine.plan_question')
    def test_repair_replaces_rows_from_previous_proposal(self, planner, query, expand, schema):
        initial = proposal()
        initial['plans'].append(deepcopy(initial['plans'][0]))
        initial['plans'][1]['select'][0]['column'] = 'missing'
        repaired = proposal(); repaired['query_review'] = APPROVED
        planner.side_effect = [initial, repaired]
        fields = repaired['plans'][0]['select']
        query.side_effect = [
            {'results': [{'total': 11}], 'query_audit': {'selected_fields': fields}},
            {'error': 'Unknown column'},
            {'results': [{'total': 22}], 'query_audit': {'selected_fields': fields}},
        ]
        result = LocalAnswer('apptimate_test', {}, 'Total recorded amount').run()
        self.assertEqual(query.call_count, 3)
        self.assertNotIn('| 11 |', result['response'])
        self.assertIn('| 22 |', result['response'])
        self.assertEqual(len(result['data_pages']), 1)

    @patch('assistant.local_engine.query_service.get_business_schema_context', return_value='records schema')
    @patch('assistant.local_engine.query_service.query_business_data')
    @patch('assistant.local_engine.plan_question', side_effect=PlanningValidationError('Service unavailable', retryable=False))
    def test_service_failure_stops_without_repeating_the_model_loop(self, planner, query, schema):
        result = LocalAnswer('apptimate_test', {}, 'Total recorded amount').run()
        planner.assert_called_once()
        query.assert_not_called()
        self.assertEqual(result['answer_status'], 'lookup_failed')

    def test_normalization_does_not_rewrite_business_words_or_identifiers(self):
        for text in ('sealed items', 'items is rick now', 'SKU RICK-100', 'Unsealed container'):
            self.assertEqual(normalize_query_text(text), text)

    def test_schema_context_exposes_keys_and_distinguishes_inferred_joins(self):
        schema = {'tables': {'headers': {'id': 'int'}, 'lines': {'header_id': 'int'}},
                  'relationships': {('lines', 'header_id', 'headers', 'id')},
                  'indexes': {'headers': {'PRIMARY': {'unique': True, 'columns': ['id']}}}}
        context = _format_schema_context(schema, ['headers', 'lines'])
        self.assertIn('PRIMARY', context)
        self.assertIn('cardinality and business meaning are not proven', context)
        schema['declared_relationships'] = schema['relationships']
        self.assertIn('declared foreign key', _format_schema_context(schema, ['headers', 'lines']))

    def test_discount_less_than_18_percentage_heals_and_compiles_with_sqlalchemy(self):
        from assistant.domain_schema import repair_and_heal_plan
        from assistant.pipeline_audit import evaluate_query
        from assistant.query_planner import _normalize_block_enums
        from assistant.query_service import validate_plan_compilation

        schema = {
            'tables': {
                'inventory_items': {'id': 'int', 'organization_id': 'int', 'name': 'varchar', 'sku': 'varchar', 'status': 'varchar', 'deleted_at': 'datetime'},
                'inventory_item_variants': {
                    'id': 'int', 'organization_id': 'int', 'item_id': 'int', 'sku': 'varchar',
                    'variant_name': 'varchar', 'sale_price': 'decimal', 'min_sales_price': 'decimal',
                    'cost_price': 'decimal', 'status': 'varchar', 'deleted_at': 'datetime',
                },
            },
            'relationships': {('inventory_item_variants', 'item_id', 'inventory_items', 'id')},
            'declared_relationships': {('inventory_item_variants', 'item_id', 'inventory_items', 'id')},
            'application_relationships': set(),
            'indexes': {
                'inventory_items': {'PRIMARY': {'unique': True, 'columns': ['id']}},
                'inventory_item_variants': {'PRIMARY': {'unique': True, 'columns': ['id']}},
            },
        }
        raw_plan = {
            'base_table': 'inventory_item_variants',
            'select': [
                {'table': 'inventory_item_variants', 'column': 'sku', 'alias': 'sku'},
                {'table': 'inventory_item_variants', 'column': 'variant_name', 'alias': 'variant_name'},
                {'table': 'inventory_item_variants', 'column': 'sale_price', 'alias': 'sale_price'},
                {'table': 'inventory_item_variants', 'column': 'cost_price', 'alias': 'cost_price'},
                {'table': 'inventory_item_variants', 'column': 'discount', 'alias': 'discount'},
            ],
            'filters': [
                {'table': 'inventory_item_variants', 'column': 'discount', 'operator': '<', 'value': 18},
            ],
        }
        _normalize_block_enums(raw_plan)
        healed = repair_and_heal_plan(raw_plan, schema, 'list me the items have discount less than 18 percentage')
        eval_res = evaluate_query(healed, schema, review=APPROVED)
        self.assertTrue(eval_res['passed'], eval_res)
        self.assertEqual(eval_res['score'], 100)
        comp = validate_plan_compilation(healed, schema)
        self.assertTrue(comp['valid'], comp)
        self.assertIn('NULLIF', comp['sql'])

    def test_filter_referencing_calculated_select_alias_does_not_fail_schema_check(self):
        from assistant.domain_schema import repair_and_heal_plan
        from assistant.pipeline_audit import evaluate_query
        from assistant.query_planner import _normalize_block_enums
        from assistant.query_service import validate_plan_compilation

        schema = {
            'tables': {
                'inventory_item_variants': {
                    'id': 'int', 'organization_id': 'int', 'item_id': 'int', 'sku': 'varchar',
                    'variant_name': 'varchar', 'sale_price': 'decimal', 'cost_price': 'decimal', 'deleted_at': 'datetime',
                },
            },
            'relationships': set(),
            'declared_relationships': set(),
            'application_relationships': set(),
            'indexes': {'inventory_item_variants': {'PRIMARY': {'unique': True, 'columns': ['id']}}},
        }
        plan = {
            'base_table': 'inventory_item_variants',
            'select': [
                {'table': 'inventory_item_variants', 'column': 'sku', 'alias': 'sku'},
                {
                    'expression': {
                        'operator': '/',
                        'left': {
                            'operator': '-',
                            'left': {'table': 'inventory_item_variants', 'column': 'cost_price'},
                            'right': {'table': 'inventory_item_variants', 'column': 'sale_price'},
                        },
                        'right': {'table': 'inventory_item_variants', 'column': 'cost_price'},
                    },
                    'alias': 'discount',
                },
            ],
            'filters': [
                {'column': 'discount', 'operator': '<', 'value': 18},
                {'table': 'inventory_item_variants', 'column': 'deleted_at', 'operator': 'IS NULL', 'value': None},
            ],
        }
        _normalize_block_enums(plan)
        self.assertNotIn('table', plan['filters'][0])
        self.assertEqual(plan['filters'][0]['alias'], 'discount')
        healed = repair_and_heal_plan(plan, schema, 'list me the items have discount less than 18 percentage')
        # Scale should be aligned to * 100 because filter value is 18
        self.assertIn('100', json.dumps(healed['select'][1]['expression']))
        eval_res = evaluate_query(healed, schema, review=APPROVED)
        self.assertTrue(eval_res['passed'], eval_res)
        comp = validate_plan_compilation(healed, schema)
        self.assertTrue(comp['valid'], comp)

    def test_sql_aggregate_strings_in_column_are_unwrapped_cleanly(self):
        from assistant.domain_schema import repair_and_heal_plan
        from assistant.pipeline_audit import evaluate_query
        from assistant.query_planner import _normalize_block_enums
        from assistant.query_service import validate_plan_compilation

        schema = {
            'tables': {
                'construction_fuel_logs': {'id': 'int', 'organization_id': 'int', 'volume': 'decimal', 'rate': 'decimal', 'log_date': 'date'},
                'core_organization_mutation_locks': {'id': 'int', 'organization_id': 'int'},
            },
            'relationships': set(),
            'declared_relationships': set(),
            'application_relationships': set(),
            'indexes': {
                'construction_fuel_logs': {'PRIMARY': {'unique': True, 'columns': ['id']}},
                'core_organization_mutation_locks': {'PRIMARY': {'unique': True, 'columns': ['id']}},
            },
        }
        fuel_plan = {
            'base_table': 'construction_fuel_logs',
            'select': [{'table': 'construction_fuel_logs', 'column': 'SUM(volume)', 'alias': 'total_fuel'}],
        }
        _normalize_block_enums(fuel_plan)
        fuel_plan = repair_and_heal_plan(fuel_plan, schema, 'how much fuel log until now')
        self.assertEqual(fuel_plan['select'][0]['column'], 'volume')
        self.assertEqual(fuel_plan['select'][0]['aggregate'], 'SUM')
        self.assertTrue(evaluate_query(fuel_plan, schema, review=APPROVED)['passed'])
        self.assertTrue(validate_plan_compilation(fuel_plan, schema)['valid'])

        lock_plan = {
            'base_table': 'core_organization_mutation_locks',
            'select': [{'table': 'core_organization_mutation_locks', 'column': 'COUNT(*)', 'alias': 'lock_count'}],
        }
        _normalize_block_enums(lock_plan)
        lock_plan = repair_and_heal_plan(lock_plan, schema, 'how much fuel locked yet')
        self.assertEqual(lock_plan['select'][0]['column'], 'id')
        self.assertEqual(lock_plan['select'][0]['aggregate'], 'COUNT')
        self.assertTrue(evaluate_query(lock_plan, schema, review=APPROVED)['passed'])
        self.assertTrue(validate_plan_compilation(lock_plan, schema)['valid'])

    def test_relevant_tables_includes_fuel_logs_and_discount_tables(self):
        from assistant.query_service import _relevant_tables

        schema = {
            'tables': {
                'inventory_items': {'id': 'int', 'name': 'varchar', 'sku': 'varchar'},
                'inventory_item_variants': {'id': 'int', 'item_id': 'int', 'sale_price': 'decimal', 'cost_price': 'decimal'},
                'sales_price_rules': {'id': 'int', 'item_id': 'int', 'markdown_percentage': 'decimal', 'rate': 'decimal'},
                'sales_price_lists': {'id': 'int', 'name': 'varchar'},
                'construction_fuel_logs': {'id': 'int', 'volume': 'decimal', 'rate': 'decimal', 'log_date': 'date'},
                'crm_quotations': {'id': 'int', 'status': 'varchar'},
            },
            'relationships': {
                ('inventory_item_variants', 'item_id', 'inventory_items', 'id'),
                ('sales_price_rules', 'item_id', 'inventory_items', 'id'),
            },
        }
        disc_ctx = _relevant_tables(schema, 'list me the items have discount less than 18 percentage', limit=10)
        self.assertIn('inventory_item_variants', disc_ctx)
        self.assertIn('sales_price_rules', disc_ctx)

        fuel_ctx = _relevant_tables(schema, 'how much fuel log until now', limit=10)
        self.assertIn('construction_fuel_logs', fuel_ctx)

    def test_reserved_stock_detail_query_enriches_item_and_variant_names_and_moves_ungrouped_having(self):
        from assistant.domain_schema import repair_and_heal_plan
        from assistant.pipeline_audit import evaluate_query
        from assistant.query_service import validate_plan_compilation

        schema = {
            'tables': {
                'inventory_stock_balances': {
                    'id': 'int', 'organization_id': 'int', 'item_id': 'int', 'variant_id': 'int',
                    'qty_on_hand': 'decimal', 'qty_allocated': 'decimal', 'qty_available': 'decimal',
                },
                'inventory_items': {'id': 'int', 'organization_id': 'int', 'name': 'varchar', 'sku': 'varchar', 'deleted_at': 'datetime'},
                'inventory_item_variants': {'id': 'int', 'organization_id': 'int', 'item_id': 'int', 'variant_name': 'varchar', 'deleted_at': 'datetime'},
            },
            'relationships': {
                ('inventory_stock_balances', 'item_id', 'inventory_items', 'id'),
                ('inventory_stock_balances', 'variant_id', 'inventory_item_variants', 'id'),
                ('inventory_item_variants', 'item_id', 'inventory_items', 'id'),
            },
            'declared_relationships': {
                ('inventory_stock_balances', 'item_id', 'inventory_items', 'id'),
                ('inventory_stock_balances', 'variant_id', 'inventory_item_variants', 'id'),
                ('inventory_item_variants', 'item_id', 'inventory_items', 'id'),
            },
            'application_relationships': set(),
            'indexes': {
                'inventory_stock_balances': {'PRIMARY': {'unique': True, 'columns': ['id']}},
                'inventory_items': {'PRIMARY': {'unique': True, 'columns': ['id']}},
                'inventory_item_variants': {'PRIMARY': {'unique': True, 'columns': ['id']}},
            },
        }
        plan = {
            'base_table': 'inventory_stock_balances',
            'select': [
                {'table': 'inventory_stock_balances', 'column': 'item_id', 'alias': 'item_id'},
                {'table': 'inventory_stock_balances', 'column': 'variant_id', 'alias': 'variant_id'},
                {'table': 'inventory_stock_balances', 'column': 'qty_on_hand', 'alias': 'qty_on_hand'},
                {'table': 'inventory_stock_balances', 'column': 'qty_allocated', 'alias': 'qty_allocated'},
                {'table': 'inventory_stock_balances', 'column': 'qty_available', 'alias': 'qty_available'},
            ],
            'filters': [
                {
                    'table': 'inventory_stock_balances',
                    'column': 'qty_on_hand',
                    'operator': '>',
                    'value': {'table': 'inventory_stock_balances', 'column': 'qty_available'},
                },
            ],
            'having': [
                {'alias': 'qty_allocated', 'operator': '>', 'value': 0},
            ],
        }
        healed = repair_and_heal_plan(
            plan,
            schema,
            'which items currently have reserved stock where quantity on hand is greater than available quantity?',
        )
        self.assertEqual(healed.get('having') or [], [])
        self.assertTrue(
            any(
                f.get('table') == 'inventory_stock_balances' and f.get('column') == 'qty_allocated' and f.get('operator') == '>' and f.get('value') == 0
                for f in healed.get('filters', [])
            )
        )
        sel_aliases = [s.get('alias') for s in healed.get('select', [])]
        self.assertIn('item_name', sel_aliases)
        self.assertIn('sku', sel_aliases)
        self.assertIn('variant_name', sel_aliases)
        self.assertTrue(evaluate_query(healed, schema, review=APPROVED)['passed'])
        comp = validate_plan_compilation(healed, schema)
        self.assertTrue(comp['valid'])
        self.assertNotIn('organization_id', comp['sql'])

    def test_discount_expression_enforces_positive_genuine_discount_guard(self):
        from assistant.domain_schema import repair_and_heal_plan

        schema = {
            'tables': {
                'inventory_item_variants': {
                    'id': 'int', 'item_id': 'int', 'sku': 'varchar', 'variant_name': 'varchar',
                    'cost_price': 'decimal', 'sale_price': 'decimal', 'deleted_at': 'datetime',
                },
            },
            'relationships': set(),
        }
        plan = {
            'base_table': 'inventory_item_variants',
            'select': [
                {'table': 'inventory_item_variants', 'column': 'sku', 'alias': 'sku'},
                {
                    'expression': {
                        'operator': '*',
                        'left': {
                            'operator': '/',
                            'left': {
                                'operator': '-',
                                'left': {'table': 'inventory_item_variants', 'column': 'cost_price'},
                                'right': {'table': 'inventory_item_variants', 'column': 'sale_price'},
                            },
                            'right': {'table': 'inventory_item_variants', 'column': 'cost_price'},
                        },
                        'right': 100,
                    },
                    'alias': 'discount_percentage',
                },
            ],
            'filters': [
                {'alias': 'discount_percentage', 'operator': '<', 'value': 18},
            ],
        }
        healed = repair_and_heal_plan(plan, schema, 'list me the items have discount less than 18 percentage')
        has_sale_lt_cost = any(
            f.get('table') == 'inventory_item_variants'
            and f.get('column') == 'sale_price'
            and f.get('operator') == '<'
            and isinstance(f.get('value'), dict)
            and f['value'].get('column') == 'cost_price'
            for f in healed.get('filters', [])
        )
        self.assertTrue(has_sale_lt_cost)

    def test_overstocks_followup_classification_and_generic_answer_signature(self):
        from assistant.local_engine import LocalAnswer, classify_query

        cls_res = classify_query('I have asked for the overstocks no', history=())
        self.assertEqual(cls_res['classification'], 'database')

        why_res = classify_query(
            'so why you have said for the question which items currently have reserved stock where quantity on hand is greater than available quantity? as answer Apptimate Assist Found 1 matching record(s)',
            history=(),
        )
        self.assertEqual(why_res['classification'], 'database_explanation')

        ans = LocalAnswer('apptimate_infinity', None, 'I have asked for the overstocks no')
        ans.generic_answer('I have asked for the overstocks no')
        self.assertEqual(ans.status, 'needs_clarification')
        self.assertTrue(bool(ans.parts))

    def test_confidence_computed_from_pipeline_audit_and_explanation(self):
        from assistant.local_engine import LocalAnswer
        from assistant.pipeline_audit import evaluate_retrieval

        r_eval = evaluate_retrieval(
            'which items currently have reserved stock',
            ['inventory_stock_balances', 'inventory_items'],
            used_tables=['inventory_stock_balances', 'inventory_items'],
        )
        db_ans = LocalAnswer('apptimate_infinity', None, 'which items currently have reserved stock')
        db_ans.search_type = 'database'
        db_ans._remember_audit(
            {'base_table': 'inventory_stock_balances'},
            {'results': [{'item_id': 20}], 'row_count': 1, 'compiled_sql': 'SELECT 1'},
            r_eval,
            {'score': 100, 'threshold': 85, 'passed': True, 'checks': []},
        )
        db_payload = db_ans.payload()
        self.assertEqual(db_payload['confidence'], 99.7)
        self.assertIn('Query Correctness 100/100', db_payload['confidence_basis'])

        exp_ans = LocalAnswer(
            'apptimate_infinity',
            None,
            'so why you have said for the question which items currently have reserved stock',
            state={'last_audit': db_ans.state['last_audit'], 'audit_history': db_ans.state['audit_history']},
        )
        exp_ans.database_explanation_reply(exp_ans.question)
        exp_payload = exp_ans.payload()
        self.assertEqual(exp_payload['confidence'], 99.4)
        self.assertIn('Query Correctness: 100/100', exp_payload['confidence_basis'])
