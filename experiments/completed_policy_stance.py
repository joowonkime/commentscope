"""Read-only receipt for the actual original-only stance nomination census."""
import json
from pathlib import Path
import sqlite3
from contextlib import closing
from commentscope.factory import policy_stance_hypotheses as stance
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json,sha


def load(directory,*,deployment,sources):
    directory=Path(directory);plan=read_json(directory/'plan.json');done=read_json(directory/'completed.json')
    if (plan['artifact_kind']!='policy-value-nomination-census-20261023-v1' or
            plan['deployment']!=deployment or done['plan_sha256']!=sha(directory/'plan.json') or
            done['record_sha256']!=sha(directory/'artifacts/record.json') or
            done['report_sha256']!=sha(directory/'report.json')):raise ValueError('Completed nomination identity changed')
    if read_json(directory/'resources/finished.json')['observer_stopped'] is not True:
        raise RuntimeError('Nomination auxiliary resource observer still live')
    boundaries=['src/commentscope/providers/evidence_nli.py','src/commentscope/providers/local_nli.py',
        'src/commentscope/factory/policy_stance_hypotheses.py','src/commentscope/factory/minimal_claims.py',
        'src/commentscope/factory/position_frames.py']
    for path in boundaries:
        if sha(path)!=plan['code_sha256'][path]:raise ValueError('Nomination provider/parser changed: '+path)
    record=stance.validate(read_json(directory/'artifacts/record.json'))
    if record['sources']!=sources or digest(sources)!=plan['sources_sha256']:raise ValueError('Every exact original required')
    request=stance.invocation(sources,record['topic'],record['alias'])
    if request!=plan['request'] or digest(request)!=plan['request_sha256']:raise ValueError('Nomination request changed')
    request_path=directory/'calls/0001-policy-value-census.request.json'
    result_path=directory/'calls/0001-policy-value-census.result.json'
    packet=read_json(request_path);response=read_json(result_path)
    if (packet['request']!=request or packet['plan_sha256']!=sha(directory/'plan.json') or
            packet['request_sha256']!=digest(request) or response!=record['response']):
        raise ValueError('Actual nomination call artifacts changed')
    ledger=Path(plan['budget']['ledger']).resolve()
    with closing(sqlite3.connect(ledger.as_uri()+'?mode=ro',uri=True)) as db:
        rows=db.execute('SELECT id,state,request_json,response_json FROM calls WHERE plan_sha=? AND request_sha=?',
            (sha(directory/'plan.json'),digest(request))).fetchall()
    if len(rows)!=1 or rows[0][1]!='ok' or json.loads(rows[0][2])!=request or json.loads(rows[0][3])!=response:
        raise ValueError('Unique actual completed ledger classifier response required')
    paths=[directory/p for p in ['plan.json','completed.json','artifacts/record.json','report.json',
        'resources/finished.json','calls/0001-policy-value-census.request.json','calls/0001-policy-value-census.result.json']]
    proof={'source_directory':str(directory),'files_sha256':{str(p):sha(p) for p in paths},
        'ledger':str(ledger),'ledger_call_id':rows[0][0],'request_sha256':digest(request),
        'model_nominees_are_not_votes':True,'new_model_calls':0}
    return record,request,response,proof
