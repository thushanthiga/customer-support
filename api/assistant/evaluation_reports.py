"""Evaluation artifacts are explicit diagnostics, never answer-cache inputs."""
from copy import deepcopy


def report_for_storage(report, detail='summary'):
    if detail not in {'summary','evidence'}:
        raise ValueError('Report detail must be summary or evidence.')
    saved=deepcopy(report)
    saved['report_detail']=detail
    if detail=='summary':
        for key in ('fixture_checks','targeted_local_rechecks'):
            if key in saved:
                saved[key]=[{k:v for k,v in item.items() if k in {'check','id','catalogue_ids','scope','passed','row_count','truncated'}} for item in saved[key]]
        for entry in saved.get('catalogue_replay',[]):
            entry['queries']=[{k:v for k,v in query.items() if k in {'accepted','previously_accepted','row_count','truncated','same_rows_as_baseline'}} for query in entry.get('queries',[])]
        for case in saved.get('cases',[]):
            safe=[]
            for turn in case.get('turns',[]):
                item={k:v for k,v in turn.items() if k in {'question','http_status','answer_status','failures',
                    'verification','usage','confidence','confidence_type','seconds'}}
                item['provider_calls']=[{k:v for k,v in call.items() if k in {'model','completed','error_type','status','code'}}
                    for call in turn.get('provider_calls',[])]
                safe.append(item)
            case['turns']=safe
        saved['storage_note']='Test status, questions, timings and usage only. Answers, result rows, SQL snapshots and model proposals were omitted. This file is not used by customer chat.'
    else:
        saved['storage_note']='Explicit local evidence report: may contain tenant answers and business result rows. This file is not used by customer chat.'
    return saved
