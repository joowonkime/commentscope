"""Cached source-first target-selection ablation. Not fresh timing or agent approval.

Reuses unchanged medoid membership records, ranks existing units with pinned NLI,
and tests at most one alternative per group with the unchanged membership LLM.
No reference labels, quote repair, extraction retries, or typing changes.
"""
import argparse
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import time

from commentscope.factory import target_ranking as ranking, membership_policy
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.factory.fact_checks import live
from commentscope.factory.scoped_discovery import verdict
from commentscope.providers import target_ranking_nli as provider
from commentscope.providers.budget import InferenceBudget
from commentscope.storage import write_json_exclusive as write
from experiments.audit_model_compare import file_hash, owned_server, command
from experiments.fresh_grounded_pipeline import Runner, source_rows
from experiments.scoped_discovery_probe import code_hashes

VERSION='cached-existing-target-probe-0.1'


def choose(proposals, baseline_rows, baseline_actual, alternatives, alternative_rows, alternative_actual):
    for rows,actual in ((baseline_rows,baseline_actual),(alternative_rows,alternative_actual)):
        if (len({r['id'] for r in rows})!=len(rows) or set(actual)!={r['id'] for r in rows}
                or len({(r['candidate_id'],r['source_id']) for r in rows})!=len(rows)):
            raise ValueError('Unique source relations and complete decisions required')
    counts=Counter(r['candidate_id'] for r in baseline_rows if baseline_actual[r['id']]=='supported')
    counts.update(r['candidate_id'] for r in alternative_rows if alternative_actual[r['id']]=='supported')
    all_rows=[('B',r,baseline_actual) for r in baseline_rows]+[('A',r,alternative_actual) for r in alternative_rows]
    selected=[];rows=[];actual={};comparisons=[]
    for p in proposals:
        candidates=[p]+[a for a in alternatives if a['parent_candidate_id']==p['id']]
        best=min(candidates,key=lambda a:(-counts[a['id']],a['id']!=p['id'],a['id']))
        comparisons.append({'candidate_id':p['id'],'baseline_support_count':counts[p['id']],
                            'options':{a['id']:counts[a['id']] for a in candidates},'selected':best['id']})
        if counts[best['id']]<3:continue
        # Keep candidate identity stable for downstream comparisons; no text edit.
        selected.append({**deepcopy(best),'id':p['id'],'selected_variant':best['id']})
        for prefix,row,decisions in all_rows:
            if row['candidate_id']!=best['id']:continue
            rid=prefix+'-'+row['id']
            rows.append({**deepcopy(row),'id':rid,'candidate_id':p['id']})
            actual[rid]=decisions[row['id']]
    return {'proposals':selected,'rows':rows,'actual':actual,'comparisons':comparisons,
            'typing_required':True,'quality_gate_passed':False,'qualified_agents':0}


def prepare(directory,source):
    if directory.exists():raise ValueError('Never overwrite an attempt')
    original=read_json(source/'plan.json');completed=read_json(source/'completed.json');live(original['expires_at'])
    if original['candidate_algorithm']!='source-first-medoid-candidates-0.1':raise ValueError('Expected source-first baseline')
    if any(completed[k+'_sha256']!=sha(source/(k+'.json')) for k in ('bundle','compiled')):
        raise ValueError('Completed source outputs changed')
    proposals=read_json(source/'proposals.json')['proposals']
    units=[u for r in read_json(source/'source-analysis.json')['records'] for u in r['units']]
    scheduled=ranking.schedule(proposals,units)
    rows=read_json(source/'source-requests.json');actual=read_json(source/'source-verdicts.json')
    policy=membership_policy.from_rows(rows)
    if policy!=original['membership_policy']:raise ValueError('Baseline policy changed')
    files=[source/n for n in ('plan.json','completed.json','bundle.json','compiled.json','proposals.json',
                             'source-analysis.json','source-requests.json','source-verdicts.json')]
    old_requests=sorted((source/'calls').glob('*-membership.request.json'))
    for row,path in zip(rows,old_requests,strict=True):
        req=read_json(path);result_path=path.with_name(path.name.replace('.request.','.result.'));result=read_json(result_path)
        if (req['request']!=row['request'] or req['request_sha256']!=digest(row['request'])
                or req['plan_sha256']!=sha(source/'plan.json') or verdict(result)!=actual[row['id']]
                or (not result['errors'] and json.loads(result['raw'])!=result['output'])):
            raise ValueError('Baseline membership replay binding changed')
        files.extend([path,result_path])
    deployment=deepcopy(original['deployments']['membership'])
    runtime=source/'membership-server'/'runtime.json';stopped=runtime.with_name('stopped.json')
    if read_json(runtime)['command']!=command(deployment,'baseline') or read_json(stopped)['returncode']!=0:
        raise ValueError('Baseline runtime mismatch or unclean exit')
    files.extend([runtime,stopped])
    plan={'artifact_kind':VERSION,'source':str(source),'expires_at':original['expires_at'],
          'inputs':{str(p):sha(p) for p in files},'code_sha256':code_hashes(),
          'model_files':original['model_files'],'deployment':deployment,'membership_policy':policy,
          'proposals':proposals,'units':units,'scheduled':scheduled,'baseline_rows':rows,'baseline_actual':actual,
          'budget':original['budget'],'limits':{'analysis_seconds':900,'call_seconds':90,'ranking_seconds':300,'new_membership_rows':40},
          'ranking_request':{'system':provider.VERSION,'data':{'pairs':scheduled['pairs']},'schema':{},'max_tokens':1},
          'runtime_reference_labels':False,'fresh_analysis':False,'quality_gate_passed':False}
    write(directory/'plan.json',plan)
    print({'prepared':True,'ranking_pairs':len(scheduled['pairs']),'groups':len(scheduled['eligible']),
           'cached_baseline_relations':len(rows),'max_new_membership':40},flush=True)


def execute(directory):
    started=time.monotonic();plan=read_json(directory/'plan.json');live(plan['expires_at'])
    if plan['artifact_kind']!=VERSION:raise ValueError('Unknown trial')
    for key in ('inputs','code_sha256','model_files'):
        if any(sha(p)!=h for p,h in plan[key].items()):raise ValueError('Frozen input/code/model changed')
    for info in (plan['deployment']['server'],plan['deployment']['models']['baseline']):
        if file_hash(info['path'])!=info['sha256']:raise ValueError('Deployment changed')
    budget=InferenceBudget(Path(plan['budget']['ledger']),plan['budget']['cycle_id'])
    runner=Runner(directory,plan,budget);runner.started=started
    write(directory/'started.json',{'plan_sha256':runner.plan_sha,'budget_before':budget.summary(),'fresh_analysis':False})
    try:
        result=runner.call('target-ranking',plan['ranking_request'],provider=provider.generate,maximum=plan['limits']['ranking_seconds'])
        ranked=ranking.assemble(plan['proposals'],plan['units'],plan['scheduled'],result)
        write(directory/'ranking.json',ranked)
        rows=source_rows(ranked['alternatives'],plan['membership_policy'])
        if len(rows)>plan['limits']['new_membership_rows']:raise ValueError('Alternative membership budget exceeded')
        write(directory/'alternative-requests.json',rows)
        actual={}
        if rows:
            with owned_server(plan['deployment'],'baseline',directory/'membership-server'):
                for row in rows:actual[row['id']]=verdict(runner.call('membership',row['request']))
        write(directory/'alternative-verdicts.json',actual)
        selected=choose(plan['proposals'],plan['baseline_rows'],plan['baseline_actual'],ranked['alternatives'],rows,actual)
        write(directory/'selection.json',selected)
        report={'artifact_kind':VERSION,'elapsed_seconds':time.monotonic()-started,'fresh_analysis':False,
                'baseline_relations_reused':len(plan['baseline_rows']),'new_membership_relations':len(rows),
                'ranking_pairs':len(plan['scheduled']['pairs']),'ranking_errors':len(ranked['pair_errors']),
                'comparisons':selected['comparisons'],'candidates_ge3':len(selected['proposals']),
                'quality_gate_passed':False,'qualified_agents':0,'typing_required':True,
                'selection_sha256':sha(directory/'selection.json'),'budget_after':budget.summary()}
        write(directory/'completed.json',report)
        print({k:v for k,v in report.items() if k!='budget_after'},flush=True)
    except BaseException as exc:
        write(directory/'failed.json',{'exception_type':type(exc).__name__,'budget_after':budget.summary(),'quality_gate_passed':False})
        raise


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('phase',choices=['prepare','run']);p.add_argument('directory',type=Path)
    p.add_argument('--source',type=Path);a=p.parse_args()
    if a.phase=='prepare' and a.source is None:p.error('prepare requires --source')
    if a.phase=='prepare':prepare(a.directory,a.source)
    else:execute(a.directory)
