"""Exercise actual HTTP answer generation using ERP sessions and localhost only."""
import json
import os
import socket
import time
import uuid
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from django.test import Client, override_settings
from django.utils import timezone

from assistant import views, rag_service
from assistant.models import ChatUsageLog
from assistant.evaluation_reports import report_for_storage


class Command(BaseCommand):
    help = 'Check local assistant endpoints with ERP sign-in and model calls disabled. Planner-dependent cases fail rather than contacting a provider.'

    def add_arguments(self, parser):
        parser.add_argument('--case', action='append', dest='selected')
        parser.add_argument('--report', required=True)
        parser.add_argument('--report-detail',choices=['summary','evidence'],default='summary')
        parser.add_argument('--limit', type=int)
        parser.add_argument('--resume', action='store_true')
        parser.add_argument('--reload-code', action='store_true', help='Reload local planner modules between cases during a repair run.')

    def handle(self, *args, **options):
        qa = Path(__file__).resolve().parents[4] / 'QA'
        manifest = json.loads((qa/'payroll-bom-fixtures.json').read_text())
        cases = json.loads((Path(__file__).resolve().parents[2]/'evaluations/catalogue_164_questions.json').read_text())
        if options['selected']:
            cases = [c for c in cases if c['id'] in options['selected']]
        if options['limit']:
            cases = cases[:options['limit']]
        target = Path(options['report']).resolve()
        run_prefix='local_eval_'+uuid.uuid4().hex+'_'
        report = {'time': timezone.localtime().isoformat(), 'mode':'local_only_actual_answers',
                  'analytics_access':settings.SUPPORT_ANALYTICS_ACCESS,
                  'model':views.CHAT_MODEL,'model_calls':'disabled; no on-device planner','cases':[]}
        if options['resume'] and target.exists():
            report=json.loads(target.read_text())
            if report.get('report_detail','evidence')!=options['report_detail']:
                raise CommandError('Resume requires the same report detail; use a new report path to change it.')
            if report.get('analytics_access','erp')!=settings.SUPPORT_ANALYTICS_ACCESS:
                raise CommandError('The saved report used a different analytics access policy. Use a new report path for this policy.')
            completed={case['id'] for case in report['cases']}
            cases=[case for case in cases if case['id'] not in completed]
        original_connect = socket.create_connection

        def local_connect(address, *a, **kw):
            if address[0] not in {'localhost','127.0.0.1','::1'}:
                raise AssertionError('External connections are forbidden in the local answer test.')
            return original_connect(address,*a,**kw)

        with override_settings(SUPPORT_DISABLE_MODEL_CALLS=True,SUPPORT_BUSINESS_ENGINE=True), ExitStack() as stack:
            erp_scoped=settings.SUPPORT_ANALYTICS_ACCESS=='erp'
            stack.enter_context(patch.object(views.client.chat.completions,'create',side_effect=AssertionError('Cloud generation forbidden')))
            stack.enter_context(patch.object(rag_service.client.embeddings,'create',side_effect=AssertionError('Cloud embeddings forbidden')))
            stack.enter_context(patch('socket.create_connection',side_effect=local_connect))
            clients={}
            for name in ('admin','viewer'):
                client=Client(raise_request_exception=False)
                response=client.post('/api/auth/erp/login/',data=json.dumps({'tenant':'apptimate_infinity',
                    'email':f'an-qa-{name}@example.invalid','password':os.getenv('SUPPORT_QA_PASSWORD','')}),content_type='application/json')
                if response.status_code!=200:
                    raise CommandError('Local synthetic ERP sign-in failed for '+name)
                clients[name]=client
            for index,case in enumerate(cases,1):
                if options['reload_code']:
                    import importlib
                    from assistant import query_planner, local_engine, business_recipes, query_service
                    for module in (query_service, query_planner, business_recipes, local_engine):
                        importlib.reload(module)
                role='viewer' if case['id'] in {'SYS-015','HR-008','X-019','RPT-007'} else 'admin'
                entry={'id':case['id'],'area':case['area'],'role':role,
                    'original_acceptance_requirement':case['acceptance_requirement'],'turns':[]}
                if not erp_scoped and case['id'] in {'SYS-015','HR-008'}:
                    entry['access_policy_note']='Local admin analytics authorizes business HR/payroll reads for every signed-in user; the original ERP-role denial expectation applies only in erp mode.'
                for turn in case['turns']:
                    started=time.monotonic()
                    response=clients[role].post('/api/chat/',data=json.dumps({'message':turn['question'],
                        'username':'spoofed-admin','session_id':run_prefix+case['id'],'tenant_domain':'apptimate_infinity'}),
                        content_type='application/json')
                    try:
                        payload=response.json()
                    except ValueError:
                        payload={'response':'The local endpoint returned an invalid response.','answer_status':'lookup_failed'}
                    errors=[]
                    if response.status_code!=200 or not payload.get('response'):errors.append('http_or_empty_answer')
                    if payload.get('answer_status')=='lookup_failed':errors.append('lookup_failed')
                    allowed_denials={'SYS-014','SYS-016','X-027'} | ({'SYS-015','HR-008'} if erp_scoped else set())
                    if payload.get('answer_status')=='denied' and case['id'] not in allowed_denials:errors.append('unexpected_access_denial')
                    if payload.get('answer_status')=='needs_clarification' and case['id'] not in {'SYS-005','SYS-008','COR-005','COR-008','SAL-005','SAL-007','SAL-011','SAL-014','CRM-006','RPT-002','RPT-004','RPT-005','RPT-008'}:errors.append('unnecessary_clarification')
                    if payload.get('answer_status')=='unsupported' and case['id'] not in {'SYS-006','PRD-007','PRD-008'}:errors.append('unresolved_query')
                    if __import__('re').search(r'\bhow many\b|^count\b',turn['question'],__import__('re').I) and not __import__('re').search(r'\bunits\b',turn['question'],__import__('re').I):
                        if not any(field.get('aggregate')=='COUNT' for src in payload.get('evidence',[]) for field in src.get('result',{}).get('query_audit',{}).get('selected_fields',[])):
                            errors.append('requested_count_not_answered')
                    if any(phrase in payload.get('response','').lower() for phrase in ["please try again shortly","i couldn't verify that answer","please narrow the request"]):errors.append('generic_unhelpful_refusal')
                    if payload.get('principal',{}).get('user_id') not in {None,manifest['assistant_'+role+'_user_id']}:errors.append('wrong_authenticated_identity')
                    if erp_scoped and role=='viewer' and any((src.get('result',{}).get('query_audit',{}).get('base_table') or '').startswith('hr_') for src in payload.get('evidence',[])):errors.append('protected_hr_query')
                    required_denials={'SYS-014'} | ({'SYS-015','HR-008'} if erp_scoped else set())
                    if case['id'] in required_denials and payload.get('answer_status')!='denied':errors.append('expected_permission_denial')
                    entry['turns'].append({'question':turn['question'],'http_status':response.status_code,
                        'seconds':round(time.monotonic()-started,2),'failures':errors,**payload})
                entry['passed']=all(not turn['failures'] for turn in entry['turns'])
                report['cases'].append(entry)
                report['summary']={'cases':len(report['cases']),'response_contract_passed':sum(c['passed'] for c in report['cases']),
                    'note':'Response contract checks are supplemented by per-case semantic review and independent SQL oracles; HTTP success alone is not acceptance.'}
                target.parent.mkdir(parents=True,exist_ok=True)
                target.write_text(json.dumps(report_for_storage(report,options['report_detail']),indent=2,default=str)+'\n')
                self.stdout.write(f"{index}/{len(cases)} {'PASS' if entry['passed'] else 'FAIL'} {case['id']} "+','.join(t.get('answer_status','unknown') for t in entry['turns']))
                self.stdout.flush()
        # Keep only the evaluation's own prefix, never user-created sessions.
        ChatUsageLog.objects.filter(session_id__startswith=run_prefix,user_id__startswith='erp:apptimate_infinity:').delete()
        if any(not c['passed'] for c in report['cases']):
            raise CommandError('Some local answers still need correction. Inspect the report.')
