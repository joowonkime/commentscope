"""Read-only ledger receipts for the actual full-snapshot census partitions."""
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from commentscope.factory import policy_stance_hypotheses as stance,policy_stance_union as union
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json,sha
from experiments.completed_policy_stance import load as load_previous


def load(directory,*,deployment,sources):
    directory=Path(directory);plan=read_json(directory/'plan.json');done=read_json(directory/'completed.json')
    if (plan['artifact_kind']!='full-snapshot-policy-census-20261023-v2' or plan['deployment']!=deployment or
            done['plan_sha256']!=sha(directory/'plan.json') or
            done['report_sha256']!=sha(directory/'report.json') or
            done['combined_record_sha256']!=sha(directory/'artifacts/combined-record.json')):
        raise ValueError('Completed full census identity changed')
    # These executed classifier/parser boundaries must still match. Unrelated
    # Factory changes do not invalidate a physically completed NLI receipt.
    for path in ['src/commentscope/providers/evidence_nli.py','src/commentscope/providers/local_nli.py',
                 'src/commentscope/factory/policy_stance_hypotheses.py',
                 'src/commentscope/factory/policy_stance_union.py',
                 'src/commentscope/factory/minimal_claims.py','src/commentscope/factory/position_frames.py']:
        if sha(path)!=plan['code_sha256'][path]:raise ValueError('Census provider/parser changed: '+path)
    if read_json(directory/'all-sources.json')!=sources or [s['id'] for s in sources]!=plan['full_scope_ids']:
        raise ValueError('Every frozen full-snapshot original required')
    lookup={s['id']:s for s in sources}
    old_sources=[lookup[sid] for sid in plan['previous_scope_ids']]
    # The prior directory is itself bound by the expansion plan inputs.
    old_plans=[Path(p) for p in plan['inputs'] if p.endswith('M1-policy-stance-discovery-v1/plan.json')]
    if len(old_plans)!=1:raise ValueError('Exact previous census receipt required')
    old,req,res,old_proof=load_previous(old_plans[0].parent,deployment=deployment,sources=old_sources)
    if read_json(directory/'previous-record.json')!=old:raise ValueError('Previous census record changed')
    records=[old];batches=[(req,res)];receipts=[];paths=[directory/p for p in
        ['plan.json','completed.json','report.json','all-sources.json','artifacts/combined-record.json']]
    ledger=Path(plan['budget']['ledger']).resolve()
    with closing(sqlite3.connect(ledger.as_uri()+'?mode=ro',uri=True)) as db:
        for number,ids in enumerate(plan['source_batch_ids'],1):
            tag=f'{number:04}';prefix=tag+'-policy-value-census'
            record_path=directory/'artifacts'/('part-'+tag+'.json')
            request_path=directory/'calls'/(prefix+'.request.json');result_path=directory/'calls'/(prefix+'.result.json')
            finished=directory/'resources'/tag/'finished.json';part_path=directory/'part-completions'/(tag+'.json')
            part=read_json(part_path);record=stance.validate(read_json(record_path))
            request=stance.invocation([lookup[sid] for sid in ids],plan['topic'],plan['alias'])
            response=read_json(result_path);packet=read_json(request_path)
            if (record['sources']!=[lookup[sid] for sid in ids] or record['response']!=response or
                    request!=plan['requests'][number-1] or digest(request)!=plan['request_sha256'][number-1] or
                    packet['request']!=request or packet['request_sha256']!=digest(request) or
                    packet['plan_sha256']!=sha(directory/'plan.json') or
                    part['request_sha256']!=digest(request) or part['record_sha256']!=sha(record_path) or
                    part['result_sha256']!=sha(result_path) or done['part_record_sha256'][tag]!=sha(record_path)):
                raise ValueError('Actual census partition changed: '+tag)
            if read_json(finished)['observer_stopped'] is not True:raise RuntimeError('Census observer still live')
            rows=db.execute('SELECT id,state,request_json,response_json FROM calls WHERE plan_sha=? AND request_sha=?',
                (sha(directory/'plan.json'),digest(request))).fetchall()
            if (len(rows)!=1 or rows[0][1]!='ok' or json.loads(rows[0][2])!=request or json.loads(rows[0][3])!=response):
                raise ValueError('Unique completed actual census ledger response required')
            records.append(record);batches.append((request,response))
            receipts.append({'ledger_call_id':rows[0][0],'request_sha256':digest(request)})
            paths.extend([record_path,request_path,result_path,finished,part_path])
    combined=union.combine(records,sources)
    if read_json(directory/'artifacts/combined-record.json')!=combined:raise ValueError('Disjoint union changed')
    proof={'source_directory':str(directory),'files_sha256':{str(p):sha(p) for p in paths},
        'ledger':str(ledger),'new_partition_receipts':receipts,'previous_receipt':old_proof,
        'synthetic_joint_call':False,'model_nominees_are_not_votes':True,'new_model_calls':0}
    return combined,batches,proof
