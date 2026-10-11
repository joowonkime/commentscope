"""Diagnostic-only source-bound claim reclustering and provisional profile assembly.

This is a functional test after FAILED quality gates, never quality promotion or a default factory.
"""
import argparse
import html
import json
from importlib.metadata import version
from pathlib import Path

from commentscope.agents.profiles import require_live
from commentscope.agents.runtime import AgentSession
from commentscope.factory.automatic import Calls,build_bundle,local_provider
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json,sha
from commentscope.factory import shared_core,temporal_guard,core_groups
from commentscope.ingestion import load_snapshot
from commentscope.providers.local_nli import LocalNLI,MODEL,REVISION,THRESHOLD
from commentscope.storage import write_json_exclusive
from experiments.claim_support_probe import CachedScores


def profiles(snapshot,units,assembly):
    require_live(snapshot.usage.expires_at)
    if assembly['unit_digest']!=digest(units):raise ValueError('Profile unit input changed')
    by_id={u['claim_id']:u for u in units};sources={s.comment_id:s for s in snapshot.comments}
    result=[]
    for group in assembly['groups']:
        cards=[]
        for uid in group['member_ids']:
            unit=by_id[uid];s=sources[unit['source_comment_id']]
            cards.append({'evidence_id':uid,'source_comment_id':s.comment_id,'original_text':s.text_original,
                          'source_url':s.source_url,'support_spans':unit['spans'],'allowed_claim':unit['statement'],
                          'reviewer_reading_ko':'','cautions_ko':'품질 기준 실패 후의 기능 진단용. 정식 서비스 관점 아님.',
                          'interpretation_origin':'automatic_model_not_human_review'})
        profile={'agent_id':f'A{len(result)+1:03d}','title':group['common_claim'],
                 'assertion_family':by_id[group['member_ids'][0]]['mode'],
                 'status':'auto_accepted_unvalidated','evidence':cards,'human_approved':False,
                 'constraints':['Represent the shared core; attribute additional details to each source separately.',
                                'Diagnostic prototype, not quality approval, population consensus or actual people.']}
        AgentSession(profile)  # Validate exact original offsets and distinct sources before publishing the diagnostic.
        result.append(profile)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('snapshot');parser.add_argument('baseline_report')
    parser.add_argument('--run-dir',type=Path,required=True)
    parser.add_argument('--diagnostic-only',action='store_true',required=True)
    parser.add_argument('--budget',type=int,default=64)
    args=parser.parse_args()
    if (args.run_dir/'report.json').exists():parser.error('Completed output exists')
    baseline=read_json(args.baseline_report)
    if baseline.get('artifact_kind')!='automatic-factory-0.2':parser.error('Only source-isolated0.2 extraction accepted')
    build_bundle(args.snapshot,baseline)
    snapshot=load_snapshot(args.snapshot).snapshot
    if baseline['summary']['selected_sources']>64:parser.error('Diagnostic integration limited to 64 source inputs')
    if not 1<=args.budget<=250:parser.error('Budget must be 1..250')
    manifest={'artifact_kind':'shared-core-integration-0.1','expires_at':baseline['expires_at'],
              'snapshot_sha256':sha(args.snapshot),'baseline_sha256':sha(args.baseline_report),
              'input_origin':'reuse validated existing source-only extracted claims; no new extraction/collection',
              'quality_gate_passed':False,'protocol_amendment':'Functional assembly diagnosis only after failed quality gates; no production promotion.',
              'budget':args.budget,'model':baseline['model'],'nli_model':MODEL,'nli_revision':REVISION,'threshold':THRESHOLD,
              'runtime':{'torch':version('torch'),'transformers':version('transformers'),'device':'cpu','threads':6},
              'code_sha256':{p:sha(p) for p in [__file__,'src/commentscope/factory/shared_core.py',
                  'src/commentscope/factory/temporal_guard.py','src/commentscope/factory/core_groups.py',
                  'src/commentscope/factory/automatic.py','src/commentscope/providers/local_nli.py',
                  'src/commentscope/factory/claim_frame.py','src/commentscope/agents/runtime.py']},
              'human_handling':False,'human_approved':False,'accepted_perspectives':0}
    calls=Calls(args.run_dir/'llm',manifest,local_provider)
    model=None
    def score(a,b):
        nonlocal model
        if model is None:model=LocalNLI()
        return model.score(a,b)
    scores=CachedScores(args.run_dir/'nli',manifest,score)
    count=0
    def discover(a,b):
        nonlocal count
        result=shared_core.discover(a,b,calls,scores);count+=1
        print(json.dumps({'decision':count,'kind':'seed','core':result['selected_core']}),flush=True)
        return result
    def attach(u,core):
        nonlocal count
        prepared=shared_core.prepare(u,calls,scores)
        frame=temporal_guard.classify(calls,[core])
        result={'prepared':prepared,'frame':frame,**shared_core.check_core(u,prepared,core,frame,scores)}
        count+=1
        print(json.dumps({'decision':count,'kind':'attach','allowed':result['allowed']}),flush=True)
        return result
    assembly=core_groups.assemble(baseline['units'],baseline['candidates'],discover,attach,budget=args.budget)
    # Recompute from existing exact requests with provider disabled; no second-model lottery.
    def forbidden(*args):raise ValueError('Replay attempted a model call')
    calls.provider=forbidden;scores.score=forbidden
    core_groups.replay(baseline['units'],baseline['candidates'],assembly,discover,attach)
    agents=profiles(snapshot,baseline['units'],assembly)
    require_live(baseline['expires_at'])
    if sha(args.snapshot)!=manifest['snapshot_sha256'] or sha(args.baseline_report)!=manifest['baseline_sha256']:
        raise ValueError('Input changed during integration')
    report={**manifest,'assembly':assembly,'profiles':agents,
            'summary':{'sources':baseline['summary']['selected_sources'],'claims':len(baseline['units']),
                       'decisions':len(assembly['decisions']),'agents':len(agents),
                       'represented_sources':len({e['source_comment_id'] for a in agents for e in a['evidence']}),
                       'unassigned_claims':len(assembly['unassigned_ids']),'budget_exhausted':assembly['budget_exhausted']},
            'limitations':['Quality gates failed; functional diagnostic only','Reused 64-source extraction, not a full new end-to-end run',
                          'No independent evaluation or automatic main/service promotion','Prototype temporal/scope/condition coverage is incomplete']}
    write_json_exclusive(args.run_dir/'report.json',report)
    esc=lambda v:html.escape(str(v),quote=True)
    page='<meta charset="utf-8"><title>공통 주장 기능 진단</title><h1>공통 주장 기능 진단 — 품질 미승인</h1><pre>'+esc(json.dumps(report['summary'],indent=2))+'</pre>'
    for a in agents:
        page+='<h2>'+esc(a['title'])+'</h2>'
        for e in a['evidence']:page+='<blockquote>'+esc(e['original_text'])+'</blockquote>'
    with (args.run_dir/'overview.html').open('x',encoding='utf-8') as f:f.write(page)
    print(report['summary'],flush=True)


if __name__=='__main__':main()
