"""Prepare thread-separated evaluation assets and a cached V0; no model calls.

This is evaluation preparation, not a completed V0/V1/V2 experiment or agent factory.
"""
import argparse
from collections import Counter, defaultdict
import html
import json
from pathlib import Path
import unicodedata

from commentscope.factory import raw_candidates as raw
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha, average_linkage
from commentscope.ingestion import load_snapshot
from commentscope.storage import write_json_exclusive as write
from experiments import raw_candidates_probe as prior

VERSION = 'factory-evaluation-kit-0.1'
SEED = 'factory-reset-20261013-v1'
THRESHOLD = .45
CODE = [*prior.CODE, 'experiments/factory_evaluation_kit.py']


def components(rows):
    """Partition grouping only: preserve distinct comment identities and vote counts."""
    ids = [r['source_id'] for r in rows]
    if len(ids)!=len(set(ids)): raise ValueError('Duplicate source IDs')
    parents = {sid:sid for sid in ids}
    def find(sid):
        parents.setdefault(sid,sid)
        while parents[sid]!=sid:
            parents[sid]=parents[parents[sid]];sid=parents[sid]
        return sid
    def union(a,b):
        a,b=find(a),find(b)
        parents[max(a,b)]=min(a,b)
    texts = {}
    for r in rows:
        sid=r['source_id']
        if r['parent_id']:union(sid,r['parent_id'])
        text=' '.join(unicodedata.normalize('NFC',r['text']).split())
        if text:
            if text in texts:union(sid,texts[text])
            else:texts[text]=sid
    grouped=defaultdict(list)
    for sid in ids:grouped[find(sid)].append(sid)
    return {sid:'T'+digest(sorted(members))[:24] for members in grouped.values() for sid in members}


def split_sources(sources, groups, development_ids, reserve_count):
    ids={s['source_id'] for s in sources};development=set(development_ids)
    if (len(development)!=len(development_ids) or not development<=ids
            or type(reserve_count) is not int or reserve_count<0):raise ValueError('Invalid split inputs')
    dev_groups={groups[s] for s in development}
    available=[s for s in ids if groups[s] not in dev_groups]
    ordered=sorted(available,key=lambda s:(digest([SEED,'reserve',s]),s))
    if len(ordered)<reserve_count:raise ValueError('Insufficient thread-separated reserve; do not shrink silently')
    reserve=set(ordered[:reserve_count]);reserve_groups={groups[s] for s in reserve}
    assignments={s:('development' if groups[s] in dev_groups else 'reserve' if groups[s] in reserve_groups else 'unused') for s in sorted(ids)}
    return {'development_ids':sorted(development),'reserve_ids':sorted(reserve),
            'component_by_source':{s:groups[s] for s in sorted(ids)},'partition_by_source':assignments,
            'partition_population':dict(Counter(assignments.values())),
            'selected_counts':{'development':len(development),'reserve':len(reserve)},
            'reserve_is_unseen':False,
            'exposure_note':'Same corpus previously processed in full. Reserved for the next comparison, not independent unseen holdout. Full prior human/assistant exposure is not certified.'}


def calibration_ids(sources, count=12):
    buckets=defaultdict(list)
    for s in sources:
        length='short' if len(s['text'])<=80 else 'long' if len(s['text'])>400 else 'medium'
        buckets[(bool(s['parent_id']),length)].append(s['source_id'])
    queues={k:sorted(v,key=lambda sid:(digest([SEED,'calibration',sid]),sid)) for k,v in sorted(buckets.items())}
    chosen=[]
    for rank in range(max(map(len,queues.values()),default=0)):
        for ids in queues.values():
            if rank<len(ids) and len(chosen)<count:chosen.append(ids[rank])
    return chosen


def baseline(registry, vectors):
    active=[s for s in registry['sources'] if s['indexable']]
    groups, normalized=average_linkage(vectors,THRESHOLD)
    if len(normalized)!=len(active):raise ValueError('Vector/source mismatch')
    clusters=[]
    for number, group in enumerate(groups,1):
        # Deterministic medoid, exact quote only. It is NOT a shared claim.
        representative=min(group,key=lambda i:(-sum(sum(a*b for a,b in zip(normalized[i],normalized[j])) for j in group),active[i]['source_id']))
        clusters.append({'id':f'V0-C{number:03d}','members':[active[i]['source_id'] for i in group],
                         'representative_id':active[representative]['source_id'],
                         'representative_quote':active[representative]['text'],
                         'common_claim':None,'support_count':None,'status':'candidate_unreviewed'})
    members=[s for g in clusters for s in g['members']]
    if sorted(members)!=sorted(s['source_id'] for s in active):raise ValueError('Non-exhaustive baseline partition')
    return {'variant':'V0','algorithm':'deterministic_cosine_average_linkage','distance_threshold':THRESHOLD,
            'clusters':clusters,'source_count':len(registry['sources']),'indexed_sources':len(active),
            'unindexed_ids':[s['source_id'] for s in registry['sources'] if not s['indexable']],
            'candidate_groups_ge3':sum(len(g['members'])>=3 for g in clusters),
            'source_coverage_in_ge3_candidates':len({s for g in clusters if len(g['members'])>=3 for s in g['members']}),
            'semantic_precision':None,'valid_perspective_coverage':None,'quality_gate_passed':False,'agents':[],
            'new_embedding_calls':0,'new_generative_calls':0,
            'scope':'Cached-vector candidate baseline only; cluster size and similarity are not support or agent approval.'}


def prepare(snapshot_path, development_plan, vectors_path, reserve_count=64):
    old=read_json(development_plan);prior.check(old)
    loaded=load_snapshot(snapshot_path)
    if sha(snapshot_path)!=old['inputs'][old['snapshot']]:raise ValueError('Snapshot differs from development corpus')
    stored=read_json(vectors_path);prior.validate_vectors(stored,prior.vector_contract(old))
    full=raw.registry(loaded.snapshot)
    rows=[{'source_id':c.comment_id,'text':c.text_original,'parent_id':c.parent_id} for c in loaded.snapshot.comments]
    groups=components(rows);dev=old['registry']
    splits=split_sources(full['sources'],groups,[s['source_id'] for s in dev['sources']],reserve_count)
    selected=calibration_ids(dev['sources'])
    lookup={s['source_id']:s for s in dev['sources']}
    inputs={str(p):sha(p) for p in [snapshot_path,development_plan,vectors_path]}
    plan={'artifact_kind':VERSION,'expires_at':loaded.snapshot.usage.expires_at,
          'snapshot':str(snapshot_path),'development_plan':str(development_plan),'vectors':str(vectors_path),
          'inputs':inputs,'code_sha256':{p:sha(p) for p in dict.fromkeys(CODE)},
          'seed':SEED,'split':splits,'calibration_ids':selected,'embedding':old['embedding'],
          'context_policy':'Full own comment only in first matched comparison; retain reply links, do not import parent claims. Parent-aware evaluation is a separate future variant.',
          'variant_status':{'V0':'cached_candidate_baseline','V1':'adapter_and_budget_not_frozen','V2':'requires_frozen_V1_and_auditor'},
          'comparison_ready':False,'quality_gate_passed':False,'agents':[],
          'stop_rule':'Do not run or tune V1/V2 before policy calibration, shared output metrics, implementation hashes and call/time budgets are frozen.'}
    packet={'artifact_kind':'factory-policy-calibration-0.1','independent_gold':False,'runtime_input':False,
            'selection':'Deterministic length x reply round-robin from development pool; no model-output or label selection.',
            'items':[{'id':f'K{i:02d}',**lookup[sid],'assessment':None,'user_feedback':None} for i,sid in enumerate(selected,1)]}
    return plan,baseline(dev,stored['vectors']),packet


def render(plan, report, packet):
    esc=lambda v:html.escape(str(v),quote=True)
    page=['<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
          '<title>실제 데이터 평가 준비</title><style>body{font:16px/1.7 system-ui;max-width:1050px;margin:auto;padding:24px}pre,blockquote{white-space:pre-wrap;overflow-wrap:anywhere}article{border-top:1px solid #aaa}table{border-collapse:collapse}td,th{padding:8px;border:1px solid #aaa}</style>',
          '<h1>실제 데이터 평가 준비</h1><p>개발 표본과 예약 표본을 분리했습니다. 과거 노출이 없는 holdout을 보장하지 않습니다. 모델 호출0, agent0, V1/V2 미실행입니다.</p>',
          '<p>판정 보조 문서: <a href="assistant-calibration.html">assistant의 12개 원문 검토</a>. 아래 군집은 근거 승인 전 후보입니다.</p>',
          '<pre>'+esc(json.dumps({'split':plan['split']['selected_counts'],'partition_population':plan['split']['partition_population'],
                                'V0_groups':len(report['clusters']),'V0_groups_ge3':report['candidate_groups_ge3'],
                                'V0_candidate_coverage':report['source_coverage_in_ge3_candidates']},ensure_ascii=False,indent=2))+'</pre>',
          '<h2>정책 보정 사례</h2><p>먼저 원문에 해석 가능한 주장이 있는지, 질문/동의/농담과 섞였는지, 어떤 부분이 문맥 의존인지 구분합니다. 주장에 동의하거나 사실 여부를 판정하는 작업이 아닙니다.</p>']
    for c in packet['items']:
        page+=['<article id="'+esc(c['id'])+'"><h3>'+esc(c['id'])+'</h3><p>'+esc(c['source_id'])+'</p><blockquote>'+esc(c['text'])+'</blockquote><p>부모 ID: '+esc(c['parent_id'])+' · 원문 자체만 검토</p></article>']
    page+=['<h2>V0 후보 군집</h2><p>대표 인용은 medoid 원문입니다. 모든 member의 공통 주장이나 지지 수가 아닙니다. 전체 member 원문은 baseline.json/기존 registry로 추적합니다.</p>']
    for g in report['clusters']:
        page+=['<article><h3>'+esc(g['id'])+' · '+str(len(g['members']))+'개 후보</h3><blockquote>'+esc(g['representative_quote'])+'</blockquote><pre>'+esc('\n'.join(g['members']))+'</pre></article>']
    return '\n'.join(page+['</html>'])


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--snapshot',type=Path,default=Path('data/ubi-research-20261010.json'))
    ap.add_argument('--development-plan',type=Path,default=Path('runs/raw-candidates-20261012/plan.json'))
    ap.add_argument('--vectors',type=Path,default=Path('runs/raw-candidates-20261012/vectors.json'))
    ap.add_argument('--reserve-count',type=int,default=64)
    ap.add_argument('--run-dir',type=Path,required=True)
    ap.add_argument('--phase',choices=['prepare','verify'],required=True)
    args=ap.parse_args();root=args.run_dir
    if args.phase=='verify':
        old=read_json(root/'plan.json')
        if any(sha(p)!=h for field in ['inputs','code_sha256'] for p,h in old[field].items()):raise ValueError('Frozen preparation changed')
        plan,report,packet=prepare(old['snapshot'],old['development_plan'],old['vectors'],len(old['split']['reserve_ids']))
        if plan!=old or report!=read_json(root/'baseline.json') or packet!=read_json(root/'calibration.json'):
            raise ValueError('Evaluation kit replay changed')
        if (root/'overview.html').read_text(encoding='utf-8')!=render(plan,report,packet):raise ValueError('Rendered evidence changed')
        print({'verified':True,'new_model_calls':0,'plan_sha256':sha(root/'plan.json')});return
    plan,report,packet=prepare(args.snapshot,args.development_plan,args.vectors,args.reserve_count)
    write(root/'plan.json',plan);write(root/'baseline.json',report);write(root/'calibration.json',packet)
    with (root/'overview.html').open('x',encoding='utf-8') as f:f.write(render(plan,report,packet))
    print({'selected':plan['split']['selected_counts'],'population':plan['split']['partition_population'],
           'groups':len(report['clusters']),'groups_ge3':report['candidate_groups_ge3'],
           'calibration_cases':len(packet['items']),'new_model_calls':0,'plan_sha256':sha(root/'plan.json')})


if __name__=='__main__':main()
