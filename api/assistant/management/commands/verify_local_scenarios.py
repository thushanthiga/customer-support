"""Local database/tool verification. Never invokes the answer model."""
import json
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from assistant import db_service, query_service, views


class Command(BaseCommand):
    help = 'Verify payroll/BOM fixtures and replay recorded catalogue SELECT plans locally without model calls.'

    def add_arguments(self, parser):
        parser.add_argument('--tenant', required=True)
        parser.add_argument('--qa-dir', default=str(Path(__file__).resolve().parents[4] / 'QA'))
        parser.add_argument('--report',help='Optional report path; no report is written when omitted.')
        parser.add_argument('--report-detail',choices=['summary','evidence'],default='summary')

    def handle(self, *args, **options):
        if db_service.MYSQL_HOST not in {'localhost', '127.0.0.1', '::1'}:
            raise CommandError('This verification command only supports the local database host.')
        qa = Path(options['qa_dir']).resolve()
        manifest = json.loads((qa / 'payroll-bom-fixtures.json').read_text())
        tenant = db_service.resolve_tenant_database(options['tenant'])
        checks = []
        targeted = []

        def check(name, condition, evidence=None):
            checks.append({'check': name, 'passed': bool(condition), 'evidence': evidence})

        with patch.object(views.client.chat.completions, 'create', side_effect=AssertionError('Model calls forbidden in local verification')):
            with db_service.get_tenant_connection(tenant) as connection:
                with connection.cursor() as cursor:
                    def read(sql, values=()):
                        db_service._check_sql_safety(sql)
                        cursor.execute(sql, values)
                        return cursor.fetchall()

                    runs = read('SELECT id, status, total_gross, total_deductions, total_net FROM hr_payroll_runs WHERE id IN (%s,%s) AND organization_id=%s',
                        (manifest['approved_payroll_run_id'], manifest['draft_payroll_run_id'], manifest['organization_id']))
                    by_id = {row['id']: row for row in runs}
                    check('both_payroll_runs_belong_to_fixture_organization', len(by_id) == 2)
                    approved = by_id.get(manifest['approved_payroll_run_id'], {})
                    draft = by_id.get(manifest['draft_payroll_run_id'], {})
                    check('approved_payroll_state', approved.get('status') == 'approved')
                    check('draft_payroll_state', draft.get('status') == 'draft')
                    for actual, expected in [('total_gross', 'gross'), ('total_deductions', 'deductions'), ('total_net', 'net')]:
                        check('approved_' + actual, approved.get(actual) == manifest['payroll_expected'][expected], approved.get(actual))
                    lines = read('SELECT employee_id, gross, total_deductions, net_pay, present_days, lop_days, is_held FROM hr_payroll_lines WHERE run_id=%s',
                        (manifest['approved_payroll_run_id'],))
                    check('approved_payroll_has_exact_employees', sorted(row['employee_id'] for row in lines) == sorted(manifest['employee_ids']))
                    for line_field, run_field in [('gross', 'total_gross'), ('total_deductions', 'total_deductions'), ('net_pay', 'total_net')]:
                        total = sum((row[line_field] for row in lines), Decimal('0'))
                        check('line_reconciliation_' + run_field, total == approved.get(run_field), total)
                    check('line_net_equals_gross_less_deductions', all(row['gross'] - row['total_deductions'] == row['net_pay'] for row in lines))
                    held = read('SELECT is_held FROM hr_payroll_lines WHERE run_id=%s', (manifest['draft_payroll_run_id'],))
                    check('draft_line_is_held', len(held) == 1 and held[0]['is_held'] == 1)
                    attendance = read('SELECT employee_id, COUNT(*) AS days, SUM(worked_minutes) AS minutes, SUM(ot_minutes) AS overtime FROM hr_attendance_days WHERE organization_id=%s AND work_date BETWEEN %s AND %s AND status=%s GROUP BY employee_id',
                        (manifest['organization_id'], '2026-09-01', '2026-09-30', 'P'))
                    check('attendance_exact_employee_scope', sorted(row['employee_id'] for row in attendance) == sorted(manifest['employee_ids']))
                    check('attendance_present_days_and_minutes', all(row['days'] == 18 and row['minutes'] == 8640 and row['overtime'] == 0 for row in attendance), attendance)
                    check('payroll_attendance_matches_present_days', {row['employee_id']: row['present_days'] for row in lines} == {row['employee_id']: row['days'] for row in attendance})
                    stock = read('SELECT item_id, SUM(qty_available) AS available FROM inventory_stock_balances WHERE organization_id=%s AND warehouse_id=%s GROUP BY item_id',
                        (manifest['organization_id'], manifest['warehouse_id']))
                    stock_by_id = {row['item_id']: row['available'] for row in stock}
                    for suffix, expected in manifest['component_expected'].items():
                        check('balance_' + suffix, stock_by_id.get(manifest['item_ids'][suffix]) == expected['available'])
                    opening = read("SELECT item_id, SUM(quantity) AS quantity FROM inventory_stock_ledger WHERE organization_id=%s AND warehouse_id=%s AND reference_type=%s AND item_id IN (%s,%s) GROUP BY item_id",
                        (manifest['organization_id'], manifest['warehouse_id'], 'OpeningStock', manifest['item_ids']['PART-A'], manifest['item_ids']['PART-B']))
                    check('opening_ledger_matches_available_balances', {row['item_id']: row['quantity'] for row in opening} == stock_by_id)
                    duplicate = read('SELECT item_id, COUNT(*) AS line_count FROM production_phantom_bom_materials WHERE phantom_bom_id=%s AND deleted_at IS NULL GROUP BY item_id', (manifest['exception_bom_id'],))
                    check('duplicate_component_fixture', any(row['item_id'] == manifest['item_ids']['PART-A'] and row['line_count'] == 2 for row in duplicate))
                    deleted = read('SELECT deleted_at FROM inventory_items WHERE id=%s', (manifest['item_ids']['DELETED'],))
                    check('soft_deleted_component_fixture', len(deleted) == 1 and deleted[0]['deleted_at'] is not None)
                    notes = read('SELECT id FROM core_entity_notes WHERE id=%s AND note LIKE %s',
                        (manifest['inert_injection_note_id'], 'AN-QA-INERT-CANARY.%'))
                    check('inert_injection_note_exists', len(notes) == 1)

            bom = db_service.analyze_phantom_bom('AN-QA-KIT', tenant, quantity=manifest['demand'], warehouse_id=manifest['warehouse_id'])
            check('bom_tool_success', bom.get('found') and not bom.get('error'), bom)
            components = {row['sku']: row for row in bom.get('components', [])}
            for suffix, expected in manifest['component_expected'].items():
                row = components.get('AN-QA-' + suffix, {})
                for metric in ('required', 'available', 'shortage'):
                    check('bom_' + suffix + '_' + metric, row.get(metric) == expected[metric], row.get(metric))
            check('bom_does_not_claim_production_or_cost', bom.get('production_execution_verified') is False and bom.get('cost_verified') is False)
            selected = db_service.analyze_phantom_bom('AN-QA-KIT', tenant, quantity=manifest['demand'], bom_id=manifest['bom_id'])
            check('explicit_bom_id_preserves_requirements', selected.get('components') == bom.get('components'))
            wrong_bom = db_service.analyze_phantom_bom('AN-QA-KIT', tenant, quantity=5, bom_id=manifest['exception_bom_id'])
            check('another_items_bom_id_is_rejected', wrong_bom.get('error_type') == 'validation')
            invalid = db_service.analyze_phantom_bom('AN-QA-KIT', tenant, quantity=5, warehouse_id=0)
            check('invalid_warehouse_is_not_zero_stock', invalid.get('error_type') == 'validation')
            exceptional = db_service.analyze_phantom_bom('AN-QA-EXCEPTION-KIT', tenant, quantity=5)
            rendered = views._format_bom_analysis(exceptional, 'component availability and cost')
            check('exceptional_bom_reports_duplicates', 'duplicate' in rendered)
            check('exceptional_bom_does_not_confirm_invalid_components', 'not confirmed' in rendered and 'inactive, deleted or missing' in rendered)
            parents = db_service.analyze_phantom_bom('AN-QA-PART-A', tenant, mode='where_used')
            check('component_where_used_has_both_parents', {'AN-QA-KIT', 'AN-QA-EXCEPTION-KIT'} <= {row['sku'] for row in parents.get('parents', [])})
            for quantity in (0, -1, 'NaN', 'Infinity'):
                check('invalid_demand_' + str(quantity), 'error' in db_service.analyze_phantom_bom('AN-QA-KIT', tenant, quantity=quantity))

            # Hand-authored replacement plans and independent SQL oracles for
            # the outstanding business questions. These verify data access,
            # not the wording of an answer that has not been regenerated.
            targeted_path = Path(__file__).resolve().parents[2] / 'evaluations/local_catalogue_rechecks.json'
            if targeted_path.exists():
                for case in json.loads(targeted_path.read_text()):
                    result = query_service.query_business_data(case['query_plan'], tenant, user_question=case['question'])
                    with db_service.get_tenant_connection(tenant) as connection:
                        with connection.cursor() as cursor:
                            db_service._check_sql_safety(case['oracle_sql'])
                            cursor.execute(case['oracle_sql'], tuple(case.get('params', [])))
                            expected = db_service._serialize_decimals(cursor.fetchall())
                    canonical = lambda rows: sorted(json.dumps(row, sort_keys=True, default=str) for row in rows)
                    success = (not result.get('error') and canonical(result.get('results') or []) == canonical(expected)
                        and result.get('truncated') == case.get('expected_truncated', False))
                    targeted.append({'id': case['id'], 'catalogue_ids': case['catalogue_ids'], 'scope': case['scope'],
                        'passed': success, 'error': result.get('error'), 'row_count': result.get('row_count'),
                        'truncated': result.get('truncated'), 'query_audit': result.get('query_audit')})

            # Preserve all original probes. Replaying a model-selected plan
            # checks the tool, not the semantic correctness of a new answer.
            latest = {}
            for stage in ('shard', 'recheck', 'final', 'outstanding', 'closeout'):
                for path in sorted(qa.glob(f'catalogue-164-{stage}-*.json')):
                    for case in json.loads(path.read_text())['cases']:
                        latest[case['id']] = {**case, 'source_report': path.name}
            catalogue = json.loads((Path(__file__).resolve().parents[2] / 'evaluations/catalogue_164_questions.json').read_text())
            replay = []
            for specification in catalogue:
                case = latest.get(specification['id'], {})
                entry = {'id': specification['id'], 'baseline_response_probe_passed': case.get('passed'),
                         'source_report': case.get('source_report'), 'queries': []}
                sources = []
                for turn in case.get('turns', []):
                    for call in turn.get('tools', []):
                        if call['tool'] != 'query_business_data' or not call.get('query_plan'):
                            continue
                        resolved = views._trusted_query_records(sources)
                        result = query_service.query_business_data(call['query_plan'], tenant,
                            user_question=turn['question'], resolved_records=resolved or None)
                        baseline = call.get('result', {})
                        entry['queries'].append({'accepted': not bool(result.get('error')),
                            'previously_accepted': not bool(baseline.get('error')),
                            'error': result.get('error'), 'row_count': result.get('row_count'),
                            'truncated': result.get('truncated'),
                            'same_rows_as_baseline': None if baseline.get('error') or result.get('error') else result.get('results') == baseline.get('results'),
                            'query_plan': call['query_plan']})
                        sources.append({'tool': call['tool'], 'result': result})
                entry['local_status'] = ('no_generic_plan_to_replay' if not entry['queries'] else
                    'all_recorded_plans_accepted' if all(row['accepted'] for row in entry['queries']) else 'contains_rejected_plans')
                replay.append(entry)
                self.stdout.write(f"{entry['id']}: {entry['local_status']}")

        report = {'mode': 'local_only_no_model_calls', 'time': timezone.now().isoformat(), 'tenant': tenant,
            'fixture_checks': db_service._serialize_decimals(checks), 'targeted_local_rechecks': targeted, 'catalogue_replay': replay,
            'summary': {'fixture_checks': len(checks), 'fixture_passed': sum(row['passed'] for row in checks),
                'catalogue_cases_recorded': len(replay), 'catalogue_cases_with_generic_plans': sum(bool(row['queries']) for row in replay),
                'targeted_checks': len(targeted), 'targeted_passed': sum(row['passed'] for row in targeted),
                'accepted_plans': sum(q['accepted'] for row in replay for q in row['queries']),
                'rejected_plans': sum(not q['accepted'] for row in replay for q in row['queries'])},
            'limitations': ['Local plan replay does not generate or certify model answers.',
                'Original role, cross-tenant, workflow and temporal acceptance requirements need separate evidence.',
                'Previous response probes are a consolidated baseline, not one final run after all code changes.']}
        if options['report']:
            from assistant.evaluation_reports import report_for_storage
            target=Path(options['report']).resolve()
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_text(json.dumps(report_for_storage(report,options['report_detail']),indent=2,default=str)+'\n')
        self.stdout.write(json.dumps(report['summary']))
        if any(not row['passed'] for row in [*checks, *targeted]):
            raise CommandError('Some local fixture checks failed; inspect the saved report.')
