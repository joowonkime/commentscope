"""Frozen, resumable raw-group discovery followed by independently frozen judging.

Uses cached whole-corpus candidate groups for development, NOT a first-run speed
claim. Offline references are never passed into model requests or compilation.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
from commentscope.agents.runtime import request
from commentscope.factory import scoped_discovery as core
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.factory.fact_checks import live
from commentscope.providers.budget import InferenceBudget
from commentscope.storage import write_json_exclusive as write
from experiments import fact_evidence_probe as base
from experiments.audit_model_compare import owned_server, file_hash


def code_hashes():
    return {str(p): sha(p) for root in ['src/commentscope','experiments'] for p in sorted(Path(root).rglob('*.py'))}


def validate(plan):
    live(plan['expires_at'])
    for field in ['inputs','code_sha256']:
        if any(sha(p) != h for p, h in plan[field].items()): raise ValueError('Frozen inputs/code changed')
    for info in [plan['server'],plan['models']['baseline']]:
        if file_hash(info['path']) != info['sha256']: raise ValueError('Model/runtime changed')


def prepare(directory, artifact):
    if directory.exists(): raise ValueError('Never overwrite a run')
    old = read_json('runs/fact-evidence-8b-20261013/plan.json')
    raw = read_json(artifact); live(raw['expires_at'])
    # Largest 20 buckets, stable ID tie break. No content-based manual selection.
    groups = sorted((g for g in raw['clusters'] if len(g['members']) >= 3), key=lambda g: (-len(g['members']),g['id']))[:20]
    rows = []
    for group in groups:
        sources = {sid: raw['sources'][sid]['text'] for sid in group['members']}
        req = core.proposal_request(sources)
        rows.append({'id': group['id'], 'sources': sources, 'request': req,
                     'request_sha256': digest(req), 'skipped': len(json.dumps(req).encode()) > 27000})
    plan = {'artifact_kind': core.VERSION, 'expires_at': raw['expires_at'],
            'inputs': {str(artifact): sha(artifact)}, 'code_sha256': code_hashes(),
            'rows': rows, 'server': old['server'], 'models': old['models'], 'runtime': old['runtime'],
            'model': old['model'], 'budget': {'cycle_id': base.CYCLE, 'timeout_seconds': 90},
            'criteria': {'relation_sample':100,'precision_min':.95,'positive_retention_min':.8,
                         'distinct_agents_min':2,'canonical_support_min':3},
            'membership_variants':['llm_only','nli_only','intersection'],
            'membership_selection':'Prefer llm_only if it passes; otherwise intersection if it passes; NLI alone is diagnostic, not author-assertion approval.',
            'cached_candidate_groups':True, 'first_run_timing':False, 'quality_gate_passed':False}
    write(directory/'plan.json', plan)
    print({'prepared':True,'groups':len(rows),'oversize':sum(r['skipped'] for r in rows)},flush=True)


def run_calls(directory, plan, rows, name):
    validate(plan)
    plan_sha = sha(directory/'plan.json')
    budget = InferenceBudget(base.DEFAULT_BUDGET,base.CYCLE)
    todo = [r for r in rows if not (directory/(r['id']+'.json')).exists()]
    if todo:
        attempt = 1
        while (directory/f'server-{name}-{attempt}').exists(): attempt += 1
        with owned_server(plan,'baseline',directory/f'server-{name}-{attempt}'):
            provider = budget.provider(plan_sha,timeout_seconds=90)
            for row in todo:
                req = row['request']
                if digest(req) != row['request_sha256']: raise ValueError('Request changed')
                result = ({'errors':['request_size_budget'],'output':None,'raw':None,'seconds':0,'usage':None}
                          if row.get('skipped') else request(req['system'],req['data'],req['schema'],
                                      lambda s,d,c:provider(s,d,c,max_tokens=req['max_tokens'])))
                write(directory/(row['id']+'.json'), {'request_sha256':digest(req),'result':result})
                print({'completed':row['id'],'errors':result['errors'],'seconds':round(result['seconds'],2)},flush=True)
    return {r['id']:read_json(directory/(r['id']+'.json')) for r in rows}


def discover(directory):
    plan = read_json(directory/'plan.json')
    records = run_calls(directory,plan,plan['rows'],'discovery')
    proposals = []; failed = []
    for row in plan['rows']:
        result = records[row['id']]['result']
        try:
            if result['errors']: raise ValueError('Model failed')
            claims = core.validate_proposal(result['output'],row['sources'])
            if claims: proposals.append({'id':row['id'],'claims':claims,'sources':row['sources']})
        except (KeyError,TypeError,ValueError) as exc:
            failed.append({'id':row['id'],'error':str(exc)})
    output = {'proposals':proposals,'failed':failed,'plan_sha256':sha(directory/'plan.json'),
              'records_sha256':{k:sha(directory/(k+'.json')) for k in records},'quality_gate_passed':False}
    write(directory/'discovery.json',output)
    print({'proposals':len(proposals),'failures':failed},flush=True)


def prepare_judgments(directory, source):
    if directory.exists(): raise ValueError('Never overwrite a run')
    prior = read_json(source/'plan.json'); validate(prior)
    proposals = read_json(source/'discovery.json')['proposals']
    rows = []
    # Interleave all proposal groups, deterministic source hash ordering. Fixed
    # first 100 core relations are reviewed BEFORE membership inference.
    queues = []
    for proposal in proposals:
        claim = proposal['claims']['C']
        queue = []
        for sid,text in sorted(proposal['sources'].items(),key=lambda x:digest(x[0])):
            req = core.judge_request(text,claim)
            queue.append({'candidate_id':proposal['id'],'source_id':sid,'text':text,
                          'claim':claim,'request':req,'request_sha256':digest(req)})
        queues.append(queue)
    while any(queues):
        for q in queues:
            if q:
                rows.append({'id':f'J{len(rows)+1:03}',**q.pop(0)})
    if len(rows) < 100: raise ValueError('Fewer than 100 source relations; cannot claim agreed gate')
    plan = {**deepcopy(prior),'artifact_kind':'scoped-source-membership-0.1',
            'inputs':{str(source/'plan.json'):sha(source/'plan.json'),str(source/'discovery.json'):sha(source/'discovery.json')},
            'code_sha256':code_hashes(),'rows':rows,'proposals':proposals,
            'evaluation_ids':[r['id'] for r in rows[:100]],'runtime_input_labels':False}
    write(directory/'plan.json',plan)
    write(directory/'evaluation-inputs.json',{'rows':[{k:r[k] for k in ['id','candidate_id','source_id','text','claim']} for r in rows[:100]],
                                             'runtime_input':False,'independent_gold':False})
    print({'prepared':True,'relations':len(rows),'fixed_evaluation':100},flush=True)


def judge(directory):
    plan = read_json(directory/'plan.json')
    # Labels must be frozen, but their contents are never used by run_calls.
    ref = read_json(directory/'references.json')
    if set(ref['labels']) != set(plan['evaluation_ids']) or ref.get('runtime_input') is not False:
        raise ValueError('Freeze exactly 100 offline references first')
    marker = directory/'reference-frozen.json'
    if not marker.exists(): write(marker,{'sha256':sha(directory/'references.json')})
    if read_json(marker)['sha256'] != sha(directory/'references.json'): raise ValueError('Reference changed')
    records = run_calls(directory,plan,plan['rows'],'judge')
    actual = {r['id']:core.verdict(records[r['id']]['result']) for r in plan['rows']}
    labels = ref['labels']
    accepted = [i for i in plan['evaluation_ids'] if actual[i]=='supported']
    positives = [i for i in plan['evaluation_ids'] if labels[i]=='supported']
    correct = sum(labels[i]=='supported' for i in accepted)
    precision = correct/len(accepted) if accepted else 0
    retention = correct/len(positives) if positives else 0
    write(directory/'report.json',{'actual':actual,'precision':precision,'positive_retention':retention,
          'accepted':len(accepted),'positive_reference':len(positives),'true_accepted':correct,
          'false_accepted':[i for i in accepted if labels[i]!='supported'],
          'missed_positive':[i for i in positives if actual[i]!='supported'],
          'development_gate_passed':precision>=.95 and retention>=.8,
          'independent_gold':False,'quality_gate_passed':False})
    print({k:v for k,v in read_json(directory/'report.json').items() if k!='actual'},flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run-dir',type=Path,required=True)
    p.add_argument('--source-dir',type=Path)
    p.add_argument('--artifact',type=Path,default=Path('artifacts/ubi-v0-20261010.json'))
    p.add_argument('--phase',choices=['prepare','discover','prepare-judgments','judge'],required=True)
    a=p.parse_args()
    if a.phase=='prepare': prepare(a.run_dir,a.artifact)
    elif a.phase=='discover': discover(a.run_dir)
    elif a.phase=='prepare-judgments': prepare_judgments(a.run_dir,a.source_dir)
    else: judge(a.run_dir)


if __name__=='__main__': main()
