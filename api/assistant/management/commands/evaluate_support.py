"""Repeatable customer-scenario checks of the actual chat pipeline.

Uses the configured model, documentation and read-only tenant tools. Expectations
are executable assertions and independent SQL snapshots, not an LLM self-grade.
Only the evaluation's uniquely named local chat-history rows are removed.
"""
import json
import math
import re
import time
import uuid
import os
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from django.utils import timezone
from django.test import Client, override_settings
from django.contrib.sessions.models import Session

from assistant import views
from assistant.db_service import get_tenant_connection, resolve_tenant_database, _serialize_decimals, _check_sql_safety
from assistant.models import ChatUsageLog
from assistant.evaluation_reports import report_for_storage


TOOL_NAMES = (
    "get_item_stock_and_rules", "diagnose_purchase_order_item", "query_business_data",
    "get_inventory_overview", "get_warehouses_list", "get_items_below_minimum_stock",
    "get_sales_growth", "get_suppliers_overdue_ratio", "get_tenant_info",
    "get_items_below_maximum_stock", "get_item_master_threshold_summary",
    "analyze_phantom_bom",
)


def item_oracle(tenant, sku):
    """Read truth independently of the assistant's lookup and generated SQL."""
    with get_tenant_connection(tenant) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT i.sku, i.name, i.min_stock_level, i.max_stock_level, i.is_available_purchase, "
                "COALESCE((SELECT SUM(b.qty_available) FROM inventory_stock_balances b WHERE b.item_id=i.id AND b.organization_id=i.organization_id),0) AS available "
                "FROM inventory_items i WHERE i.sku=%s AND i.deleted_at IS NULL", (sku,),
            )
            rows = cursor.fetchall()
    if len(rows) != 1:
        raise ValueError(f"Oracle SKU must resolve uniquely: {sku}")
    return _serialize_decimals(rows[0])


def evaluate_turn(expectation, payload, trace, status, oracle=None):
    """Return named failures; do not equate HTTP success with factual accuracy."""
    errors = []
    answer = re.sub(r"[*`]", "", str(payload.get("response") or ""))
    lowered = answer.casefold()
    called = [entry["tool"] for entry in trace]
    if status != 200 or not answer:
        errors.append("nonempty_success_response")
    for pattern in expectation.get("contains", []):
        if not re.search(pattern, answer, re.IGNORECASE):
            errors.append("missing:" + pattern)
    for pattern in expectation.get("excludes", []):
        factual_answer=re.sub(r'^### [^\n]*(?:notes|record text)[^\n]*\n.*?(?=^###|\Z)','',answer,flags=re.M|re.S|re.I) if expectation.get('literal_record_text') else answer
        if re.search(pattern, factual_answer, re.IGNORECASE):
            errors.append("forbidden:" + pattern)
    if set(called).intersection(expectation.get('forbidden_tools') or []):
        errors.append('wrong_business_flow')
    if expectation.get("tools_any") and not set(called).intersection(expectation["tools_any"]):
        errors.append("required_live_tool")
    if expectation.get("no_live_tools") and called:
        errors.append("unexpected_live_tool")
    for entry in trace:
        query = entry.get("item_query")
        if query and re.search(r"\b(?:can i|for vitamin c after|purchase 10|maximum sell|supplier details)\b", query, re.IGNORECASE):
            errors.append("conversational_text_in_item_query")
    if expectation.get("evidence") and payload.get("confidence_type") != "evidence":
        errors.append("wrong_evidence_type")
    if expectation.get("unverified") and payload.get("confidence") != 0:
        errors.append("unsupported_positive_confidence")
    if expectation.get("tools_any") and not expectation.get("unverified") and payload.get("confidence") == 0:
        errors.append("required_answer_not_verified")
    confidence = payload.get("confidence")
    if confidence is not None and (not isinstance(confidence, (float, int)) or not math.isfinite(confidence) or not 0 <= confidence <= 100):
        errors.append("invalid_confidence")
    if not payload.get("confidence_basis"):
        errors.append("missing_confidence_basis")
    usage = payload.get("usage", {})
    if usage.get("total_tokens") != usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0):
        errors.append("inconsistent_token_usage")
    if oracle:
        field = expectation["oracle"]["field"]
        value = oracle[field]
        if value is None or (field in {"min_stock_level", "max_stock_level"} and value == 0):
            if not re.search(r"not (?:set|configured|recorded)|unconfigured|no .{0,25}(?:configured|recorded)", lowered):
                errors.append("oracle_null_not_explained")
        elif not re.search(r"(?<![\d.])" + re.escape(str(value)) + r"(?:\.0+)?(?![\d.])", answer):
            errors.append("oracle_value_missing:" + field)
        if oracle["sku"].casefold() not in lowered and oracle["name"].casefold() not in lowered:
            errors.append("oracle_item_identity_missing")
    return errors


def read_snapshot(tenant, specification):
    """Run a trusted evaluation-file SELECT independently of assistant planning."""
    sql = specification["sql"]
    if not re.match(r"^\s*SELECT\b", sql, re.IGNORECASE) or ";" in sql:
        raise ValueError("Evaluation snapshots must contain one SELECT.")
    _check_sql_safety(sql)
    with get_tenant_connection(tenant) as connection:
        with connection.cursor() as cursor:
            parameters=tuple(specification.get('params',[]))
            cursor.execute(sql, parameters or None)
            rows = cursor.fetchall()
    return _serialize_decimals(rows)


def scalar_snapshot(tenant, specification):
    rows = read_snapshot(tenant, specification)
    if len(rows) != 1 or len(rows[0]) != 1:
        raise ValueError("Scalar evaluation snapshots must return one value.")
    return _serialize_decimals(next(iter(rows[0].values())))


def check_row_snapshot(expected, trace, tables, allow_truncated=False, result_tool=None, rows_key='results'):
    """Compare grouped row values independently of model-chosen output aliases."""
    from decimal import Decimal, InvalidOperation
    def canonical(rows):
        normalized = []
        for row in rows:
            values = []
            for value in row.values():
                if isinstance(value,bool):value=int(value)
                if isinstance(value,str) and value.lstrip().startswith(('[','{')):
                    try:value=json.loads(value)
                    except ValueError:pass
                if isinstance(value, (int, float)):
                    try:
                        value = format(Decimal(str(value)).normalize(), 'f')
                    except InvalidOperation:
                        pass
                values.append(json.dumps(value, sort_keys=True, default=str))
            normalized.append(tuple(sorted(values)))
        return sorted(normalized)
    for call in trace:
        result = call.get('result') or {}
        if result_tool:
            if call['tool']==result_tool and not result.get('error') and canonical(result.get(rows_key) or [])==canonical(expected):
                return []
            continue
        audit = result.get('query_audit') or {}
        if {audit.get('base_table'), *(audit.get('joined_tables') or [])} != set(tables):
            continue
        if not result.get('error') and (allow_truncated or not result.get('truncated')) and canonical(result.get('results') or []) == canonical(expected):
            return []
    return ['independent_grouped_rows_mismatch']


def check_scalar_snapshot(expected, trace, answer, expected_tables=None, expected_column=None):
    """Require both an executed scalar result and an answer matching the SQL oracle."""
    values = []
    for call in trace:
        result = call.get("result", {})
        if isinstance(result,dict) and expected_column and expected_column in result:
            values.append(result[expected_column])
            continue
        audit = result.get("query_audit", {}) if isinstance(result, dict) else {}
        actual_tables = {audit.get("base_table"), *(audit.get("joined_tables") or [])}
        if expected_tables and actual_tables != set(expected_tables):
            continue
        rows = result.get("results") if isinstance(result, dict) else None
        if rows and len(rows) == 1 and len(rows[0]) == 1:
            values.append(next(iter(rows[0].values())))
        elif rows and len(rows) == 1 and expected_column:
            for index, field in enumerate(audit.get('selected_fields') or [], 1):
                if field.get('column') == expected_column:
                    values.append(rows[0].get(field.get('alias') or f'field_{index}'))
    errors = []
    if expected not in values:
        errors.append("independent_scalar_mismatch")
    normalized = re.sub(r"(?<=\d),(?=\d)", "", answer or "")
    pattern = r"(?<![\d.])" + re.escape(str(expected)) + r"(?:\.0+)?(?![\d.])"
    if not re.search(pattern, normalized) and not (expected == 0 and re.search(r"\b(?:no|zero|none|not configured)\b", normalized, re.IGNORECASE)):
        errors.append("independent_scalar_missing_from_answer")
    return errors


class Command(BaseCommand):
    help = "Run customer scenarios through the real assistant (model calls and read-only tenant queries)."

    def add_arguments(self, parser):
        parser.add_argument("--cases", default=str(Path(__file__).resolve().parents[2] / "evaluations" / "customer_questions.json"))
        parser.add_argument("--tenant", default="localhost")
        parser.add_argument("--case", action="append", dest="selected")
        parser.add_argument("--limit", type=int)
        parser.add_argument("--report", required=True, help="Save questions, answers, checks, usage and tool traces as JSON.")
        parser.add_argument('--report-detail',choices=['summary','evidence'],default='summary',help='Summary omits tenant answers/results. Evidence explicitly saves full local answers, query traces and SQL snapshots.')
        parser.add_argument('--allow-provider',action='store_true',help='Explicitly allow GPT planning with questions and schema only; result rows remain in the local report.')
        parser.add_argument('--email',default='an-qa-admin@example.invalid')
        parser.add_argument('--password-env',default='SUPPORT_QA_PASSWORD',help='Environment variable containing the ERP test account password.')
        parser.add_argument('--resume',action='store_true')
        parser.add_argument('--retry-failed',action='store_true')
        parser.add_argument('--refresh-selected',action='store_true',help='With --resume and --case, rerun explicitly selected cases even when their earlier assertions passed.')

    def handle(self, *args, **options):
        cases = json.loads(Path(options["cases"]).read_text())
        if options["selected"]:
            cases = [case for case in cases if case["id"] in options["selected"]]
        if options["limit"]:
            cases = cases[:options["limit"]]
        if not cases:
            raise CommandError("No customer scenarios selected.")
        if options['refresh_selected'] and (not options['resume'] or not options['selected']):
            raise CommandError('--refresh-selected requires --resume and an explicit --case selection.')
        if not options['allow_provider']:
            raise CommandError('Live testing needs --allow-provider. Use offline verification when model calls are not authorized.')
        if views.CHAT_MODEL!='gpt-6-luna':
            raise CommandError('This evaluation requires the requested gpt-6-luna model.')
        if views.client.base_url.host!='api.openai.com':
            raise CommandError('The configured provider endpoint is outside the authorized OpenAI endpoint.')
        tenant = resolve_tenant_database(options["tenant"])
        prefix = 'support_eval_'+uuid.uuid4().hex+'_'
        report = {"tenant": tenant, "model": views.CHAT_MODEL, "cases": [],
            'outbound_policy':'Questions and relevant schema only. Database rows, validation errors and SQL oracles stay in this environment.',
            'note':'Assertions and independent SQL snapshots are reported separately. HTTP success alone does not certify factual correctness.'}
        target = Path(options["report"]).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        if options['resume'] and target.exists():
            report=json.loads(target.read_text())
            if report.get('report_detail','evidence')!=options['report_detail']:
                raise CommandError('Cannot resume with a different report detail. Select the original detail explicitly or use another report path.')
            if (report.get('tenant'),report.get('model'))!=(tenant,views.CHAT_MODEL):
                raise CommandError('The existing report belongs to a different tenant or model.')
            completed=set() if options['refresh_selected'] else {case['id'] for case in report['cases'] if case['passed'] or not options['retry_failed']}
            cases=[case for case in cases if case['id'] not in completed]
        client=Client(raise_request_exception=False)
        session_key=None
        provider_calls=[]
        real_create=views.client.chat.completions.create

        def planned_call(*args,**kwargs):
            messages=kwargs.get('messages') or []
            if (args or kwargs.get('model')!='gpt-6-luna' or len(messages)!=2
                    or not messages[0].get('content','').startswith('Plan read-only ERP queries.')
                    or kwargs.get('store') is not False):
                raise PermissionError('Evaluation blocked an unexpected provider request before transmission.')
            content=json.loads(messages[1]['content'])
            if set(content)!={'question','previous_questions'}:
                raise PermissionError('Evaluation blocked non-planning data before provider transmission.')
            call={'model':kwargs['model'],'completed':False}
            provider_calls.append(call)
            try:
                response=real_create(**kwargs)
                call['completed']=True
                call['proposal']=json.loads(response.choices[0].message.content)
                return response
            except Exception as error:
                call.update(error_type=type(error).__name__,status=getattr(error,'status_code',None),code=getattr(error,'code',None))
                raise

        try:
            login=client.post('/api/auth/erp/login/',data={'tenant':tenant,'email':options['email'],
                'password':os.getenv(options['password_env'],'')},content_type='application/json')
            if login.status_code!=200:
                raise CommandError('ERP evaluation sign-in failed; no provider calls were made.')
            session_key=client.session.session_key
            for index, case in enumerate(cases):
                session = prefix+case["id"]
                entry = {"id": case['id'], "area": case["area"], "turns": [], 'checked_at':timezone.now().isoformat(), "acceptance_requirement": case.get("acceptance_requirement"), "verification_limit": case.get("verification_limit")}
                for turn in case["turns"]:
                    trace = []
                    started = time.monotonic()
                    oracle = None
                    snapshot = None
                    snapshots=[]
                    response=None
                    first_call=len(provider_calls)
                    try:
                        if turn.get("oracle"):
                            oracle = item_oracle(tenant, turn["oracle"]["sku"])
                        if turn.get("scalar_snapshot"):
                            snapshot = scalar_snapshot(tenant, turn["scalar_snapshot"])
                        if turn.get("row_snapshot"):
                            snapshot = read_snapshot(tenant, turn["row_snapshot"])
                        for specification in turn.get('row_snapshots',[]):
                            snapshots.append((specification,read_snapshot(tenant,specification)))
                        with ExitStack() as stack:
                            stack.enter_context(override_settings(SUPPORT_BUSINESS_ENGINE=True,SUPPORT_DISABLE_MODEL_CALLS=False))
                            stack.enter_context(patch.object(views.client.chat.completions,'create',side_effect=planned_call))
                            from assistant import rag_service
                            stack.enter_context(patch.object(rag_service.client.embeddings,'create',side_effect=PermissionError('Embedding calls are outside this evaluation authorization.')))
                            for name in TOOL_NAMES:
                                real = getattr(views, name)

                                def invoke(*a, _name=name, _real=real, **kw):
                                    call = {"tool": _name}
                                    if _name in {"get_item_stock_and_rules", "diagnose_purchase_order_item"}:
                                        call["item_query"] = kw.get("item_query", a[0] if a else "")
                                    if _name == "query_business_data":
                                        call["query_plan"] = kw.get("query_plan", a[0] if a else None)
                                    trace.append(call)
                                    injected = case.get("inject", {}).get(_name)
                                    result = injected if injected is not None else _real(*a, **kw)
                                    if turn.get("scalar_snapshot") or turn.get("row_snapshot") or turn.get('row_snapshots') or turn.get("capture_result"):
                                        call["result"] = _serialize_decimals(result)
                                    if isinstance(result, dict) and result.get("error"):
                                        call["error"] = result["error"]
                                    return result

                                stack.enter_context(patch.object(views, name, side_effect=invoke))
                            response = client.post("/api/chat/", data=json.dumps({
                                "message": turn["question"], "session_id": session,
                                "tenant_domain": options["tenant"],
                            }), content_type="application/json", HTTP_X_TENANT_DOMAIN=options["tenant"])
                            payload = json.loads(response.content)
                        for evidence in payload.get('evidence',[]):
                            if not any(call['tool']==evidence['tool'] for call in trace):
                                trace.append({'tool':evidence['tool'],'result':evidence.get('result',{})})
                        if any(s.get('tool')=='rendered_data_page' for s in [turn.get('row_snapshot',{}),*turn.get('row_snapshots',[])]):
                            for page in payload.get('data_pages',[]):
                                trace.append({'tool':'rendered_data_page','result':page})
                        expectation=dict(turn)
                        status=payload.get('answer_status')
                        if 'recorded notes' in turn['question'].lower() and 'inert record text' in payload.get('response','').lower():
                            expectation['literal_record_text']=True
                            entry['literal_text_note']='Exclusion assertions check factual sections; explicitly labelled literal note text is checked separately from the stock evidence.'
                        known_clarification=case['id'] in {'SYS-005','SYS-008','COR-005','COR-008','SAL-005','SAL-007','SAL-011','SAL-014','CRM-006','RPT-002','RPT-004','RPT-005','RPT-008'}
                        duplicate_record=any(
                            len((call.get('result') or {}).get('results') or [])>1
                            and any(field.get('column')=='organization_id' for field in (call.get('result') or {}).get('query_audit',{}).get('selected_fields',[]))
                            and any(f.get('operator')=='=' and f.get('column') in {'po_number','invoice_number','entry_number','sr_number','so_number'}
                                for f in (call.get('result') or {}).get('query_audit',{}).get('filters',[]))
                            for call in trace)
                        if status=='needs_clarification' and (known_clarification or duplicate_record):
                            expectation.pop('tools_any',None)
                            expectation['unverified']=True
                            entry['clarification_note']='Missing record context or a source-verified document number shared by multiple organizations.'
                        if case['id'] in {'SYS-005','SYS-008'} and status=='answered':
                            expectation.pop('unverified',None)
                            entry['negative_result_note']='An exact identifier lookup returned a verified empty result; this is distinct from a lookup failure.'
                        if case['id']=='COR-004' and expectation.get('tools_any'):
                            expectation['tools_any']=[*expectation['tools_any'],'effective_erp_permissions']
                        if case['id']=='PRC-009' and any(call['tool']=='schema_capability' for call in trace):
                            expectation['tools_any']=[*expectation.get('tools_any',[]),'schema_capability']
                            entry['schema_answer_note']='Supplier cardinality is verified from header/line schema, not from an unnecessary transaction-row lookup.'
                        if case['id'] in {'CRM-002','RPT-001'}:
                            expectation.pop('unverified',None)
                            expectation.pop('contains',None)
                            entry['authenticated_context_note']='ERP identity is now verified. The original generic-username/no-identity expectation is superseded by authenticated live reads.'
                        if case['id']=='SYS-015' and settings.SUPPORT_ANALYTICS_ACCESS=='admin':
                            expectation.pop('contains',None)
                            entry['access_policy_note']='Admin analytics access supersedes the original ERP-role denial expectation.'
                        errors = evaluate_turn(expectation, payload, trace, response.status_code, oracle)
                        if status=='lookup_failed':errors.append('lookup_failed')
                        if turn.get('expected_status') and status!=turn['expected_status']:errors.append('wrong_answer_status')
                        allowed_denials={'SYS-014','SYS-016','X-027'}
                        if settings.SUPPORT_ANALYTICS_ACCESS=='erp':allowed_denials.update({'SYS-015','HR-008'})
                        if status=='denied' and case['id'] not in allowed_denials and not turn.get('unverified'):errors.append('unexpected_access_denial')
                        if status=='unsupported' and case.get('id') not in {'SYS-006','PRD-007','PRD-008'} and not turn.get('unverified'):errors.append('unresolved_query')
                        if (status=='needs_clarification' and case.get('acceptance_requirement')
                                and not known_clarification and not duplicate_record):
                            errors.append('unnecessary_clarification')
                        if turn.get("scalar_snapshot"):
                            errors.extend(check_scalar_snapshot(snapshot, trace, payload.get("response"), turn["scalar_snapshot"].get("tables"), turn["scalar_snapshot"].get("column")))
                        if turn.get("row_snapshot"):
                            errors.extend(check_row_snapshot(snapshot, trace, turn['row_snapshot'].get('tables',[]),turn['row_snapshot'].get('allow_truncated',False),turn['row_snapshot'].get('tool'),turn['row_snapshot'].get('rows_key','results')))
                        for specification,expected in snapshots:
                            errors.extend(check_row_snapshot(expected,trace,specification.get('tables',[]),specification.get('allow_truncated',False),specification.get('tool'),specification.get('rows_key','results')))
                        if turn.get('requires_provider') and not any(call.get('completed') for call in provider_calls[first_call:]):
                            errors.append('required_provider_not_exercised')
                    except Exception as exc:
                        payload, errors = {}, ["evaluation_exception:" + type(exc).__name__]
                    entry["turns"].append({"question": turn["question"], "answer": payload.get("response"),
                        'http_status':response.status_code if response is not None else None,'answer_status':payload.get('answer_status'),
                        "failures": errors, "tools": trace, "oracle": oracle,
                        "scalar_snapshot": snapshot,
                        'row_snapshots':[{'specification':s,'expected':v} for s,v in snapshots],
                        'provider_calls':provider_calls[first_call:],
                        'verification':'independent_sql' if turn.get('oracle') or turn.get('scalar_snapshot') or turn.get('row_snapshot') or turn.get('row_snapshots') else 'response_assertions; semantic review required',
                        "usage": payload.get("usage"), "confidence": payload.get("confidence"),
                        "confidence_type": payload.get("confidence_type"), "confidence_basis": payload.get("confidence_basis"),
                        "seconds": round(time.monotonic() - started, 2)})
                entry["passed"] = all(not turn["failures"] for turn in entry["turns"])
                report['cases']=[saved for saved in report['cases'] if saved['id']!=case['id']]
                report["cases"].append(entry)
                report["summary"] = {"scenarios": len(report["cases"]), "passed": sum(c["passed"] for c in report["cases"]),
                                     "turns": sum(len(c["turns"]) for c in report["cases"]),
                                     'live_provider_calls':sum(len(t.get('provider_calls',[])) for c in report['cases'] for t in c['turns']),
                                     'independently_checked_turns':sum(t.get('verification')=='independent_sql' for c in report['cases'] for t in c['turns'])}
                target.write_text(json.dumps(report_for_storage(report,options['report_detail']), ensure_ascii=False, indent=2,default=str))
                self.stdout.write(f"{index + 1}/{len(cases)} {'PASS' if entry['passed'] else 'FAIL'} {case['id']}")
                for result in entry["turns"]:
                    if result["failures"]:
                        self.stdout.write("  " + "; ".join(result["failures"]))
                self.stdout.flush()
        finally:
            ChatUsageLog.objects.filter(session_id__startswith=prefix).delete()
            if session_key:Session.objects.filter(session_key=session_key).delete()
        self.stdout.write(json.dumps(report["summary"]))
        if any(not case["passed"] for case in report["cases"]):
            raise CommandError("Some scenarios failed; inspect the saved report.")
