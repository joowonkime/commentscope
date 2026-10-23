"""Reusable raw-source candidate front end; no generative model or agent approval."""
import argparse
import html
from importlib.metadata import version
import json
from pathlib import Path
import time

from commentscope.agents.profiles import require_live
from commentscope.factory import raw_candidates as raw
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json,sha,embed,MODEL,REVISION
from commentscope.ingestion import load_snapshot
from commentscope.storage import write_json_exclusive

CODE=['experiments/raw_candidates_probe.py','src/commentscope/factory/raw_candidates.py',
      'src/commentscope/factory/automatic_contract.py','src/commentscope/factory/claim_clusters.py',
      'src/commentscope/cluster_baseline.py','src/commentscope/ingestion/normalize.py',
      'src/commentscope/storage.py']


def make_plan(snapshot_path,limit,reference_path=None):
    snapshot=load_snapshot(snapshot_path).snapshot
    if type(limit) is not int or not 1<=limit<=1000:raise ValueError('Limit must be1..1000')
    value=raw.registry(snapshot)
    canonical={r['source_id']:r for r in value['sources']}
    inputs={str(snapshot_path):sha(snapshot_path)}
    included=[];references=[]
    if reference_path:
        ref=read_json(reference_path);inputs[str(reference_path)]=sha(reference_path)
        if ref['inputs'][str(snapshot_path)]!=sha(snapshot_path):raise ValueError('Reference snapshot changed')
        for c in ref['cases']:
            if c['split'].startswith('fixed_'):continue
            if c['id'] not in canonical or c['source']!=canonical[c['id']]['text']:
                raise ValueError('Reference source changed')
            included.append(c['id'])
        references=[{'pair_id':c['id'],'source_ids':[c[k]['source_comment_id'] for k in ['anchor','member']]}
                    for c in ref['known_pairs']]
    selected=sorted(set(included))
    if len(selected)>limit:raise ValueError('Limit smaller than reference pool')
    extra=sorted(set(canonical)-set(selected),key=lambda sid:(digest(['raw-pool-v1',sid]),sid))
    selected+=extra[:limit-len(selected)]
    value=raw.registry(snapshot,selected)
    # Keep selected canonical aliases for transparent support-denominator accounting.
    aliases=[cid for cid,target in raw.registry(snapshot)['aliases'].items() if target in selected]
    value=raw.registry(snapshot,[*selected,*aliases])
    return {'artifact_kind':'raw-candidates-probe-0.1','snapshot':str(snapshot_path),
            'source_kind':snapshot.source_kind,'expires_at':snapshot.usage.expires_at,
            'inputs':inputs,'code_sha256':{f:sha(f) for f in CODE},'registry':value,
            'reference_pairs_evaluation_only':references, 'embedding':{'model':MODEL,'revision':REVISION},
            'policy':{**raw.POLICY,'backend':'numpy'},'quality_gate_passed':False,'independent_gold':False,
            'criteria':'All selected canonical sources preserved; no parent concatenation; all supplied known source pairs exposed before support decisions; queue coverage measured separately, never tuned after outputs.',
            'limitations':['Retrieval exposure and queue priority are not semantic support or agent readiness',
                           'Known pairs are development controls with shared anchors, not independent gold',
                           'Hash-order extra sources are distractors, not an unbiased corpus quality sample',
                           'No common-claim generation, membership audit, support counting, or service-latency result']}


def check(plan):
    if plan['embedding']!={'model':MODEL,'revision':REVISION} or plan['policy']!={**raw.POLICY,'backend':'numpy'}:
        raise ValueError('Unsupported embedding or retrieval policy')
    for field in ['inputs','code_sha256']:
        if any(sha(p)!=h for p,h in plan[field].items()):raise ValueError('Frozen input/code changed')
    snapshot=load_snapshot(plan['snapshot']).snapshot
    if (plan['source_kind']!=snapshot.source_kind or plan['expires_at']!=snapshot.usage.expires_at):
        raise ValueError('Snapshot usage metadata changed')
    if snapshot.source_kind!='synthetic':require_live(snapshot.usage.expires_at)
    raw.validate_registry(plan['registry'],snapshot)


def evaluate(bundle,pairs):
    queued={tuple(sorted(p['source_ids'])) for p in bundle['queue']['pairs']}
    records=[]
    for p in pairs:
        a,b=p['source_ids'];rows=bundle['candidates'].get(a,[])
        ranks=[i+1 for i,r in enumerate(rows) if r['source_id']==b]
        records.append({**p,'both_sources_preserved':a in bundle['candidates'] and b in bundle['candidates'],
                        'directed_exposed':bool(ranks),'rank':ranks[0] if ranks else None,
                        'queued_undirected':tuple(sorted([a,b])) in queued})
    return {'known_pairs':len(records),'source_exposed':sum(p['directed_exposed'] for p in records),
            'queued_pairs':sum(p['queued_undirected'] for p in records),'records':records}


def vector_contract(plan):
    indexed=[r for r in plan['registry']['sources'] if r['indexable']]
    return {'embedding':plan['embedding'],'source_ids':[r['source_id'] for r in indexed],
            'texts':[r['text'] for r in indexed]}


def validate_vectors(stored,contract):
    if stored['input']!=contract or stored['vectors_sha256']!=digest(stored['vectors']):
        raise ValueError('Embedding cache input/result changed')
    raw.normalized_vectors(stored['vectors'],len(contract['texts']))


def render(report):
    esc=lambda x:html.escape(str(x),quote=True)
    page=['<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
          '<title>원문 검색 우선 후보</title><style>body{font:16px/1.7 system-ui;max-width:1000px;margin:auto;padding:20px}pre,blockquote{white-space:pre-wrap;overflow-wrap:anywhere}article{border-top:1px solid #aaa}</style>',
          '<h1>원문 검색 우선 후보</h1><p>검색 후보와 비교 대기 목록입니다. 지지 수 미산정, 공통 주장·agent 생성 및 의미 품질 승인이 아닙니다.</p>',
          '<pre>'+esc(json.dumps(report['bundle']['summary'],ensure_ascii=False,indent=2))+'</pre>',
          '<h2>개발 대조군</h2><pre>'+esc(json.dumps(report['evaluation'],ensure_ascii=False,indent=2))+'</pre>',
          '<h2>단계 시간</h2><pre>'+esc(json.dumps(report['measurements'],ensure_ascii=False,indent=2))+'</pre>']
    for p in report['bundle']['queue']['pairs']:
        packet=raw.source_packet(report['registry'],p)
        page+=['<article><h2>'+esc(p['pair_id'])+'</h2>']
        for s in packet['sources']:page+=['<p>'+esc(s['source_id'])+'</p><blockquote>'+esc(s['text'])+'</blockquote>']
        page+=['</article>']
    return '\n'.join(page+['</html>'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot',default='data/ubi-research-20261010.json')
    parser.add_argument('--limit',type=int,default=64)
    parser.add_argument('--reference-plan',type=Path)
    parser.add_argument('--run-dir',type=Path,required=True)
    parser.add_argument('--phase',choices=['plan','run','verify'],required=True)
    parser.add_argument('--diagnostic-only',action='store_true',required=True)
    args=parser.parse_args();directory=args.run_dir;path=directory/'plan.json'
    started=time.perf_counter()
    if args.phase=='plan':
        plan=make_plan(args.snapshot,args.limit,args.reference_plan);check(plan);write_json_exclusive(path,plan)
        print({'sources':len(plan['registry']['sources']),'references':len(plan['reference_pairs_evaluation_only']),
               'plan_sha256':sha(path)});return
    plan=read_json(path);check(plan)
    contract=vector_contract(plan);vp=directory/'vectors.json'
    if args.phase=='run' and (directory/'report.json').exists():parser.error('Completed output exists')
    embedding_started=time.perf_counter();cache_hit=vp.exists()
    if cache_hit:
        cached=read_json(vp);validate_vectors(cached,contract)
    else:
        if args.phase=='verify':raise RuntimeError('Replay cannot create embeddings')
        vectors=embed(contract['texts'])
        cached={'input':contract,'vectors':vectors,'vectors_sha256':digest(vectors),
                'runtime':{k:version(k) for k in ['torch','transformers','sentence-transformers','numpy']}}
        validate_vectors(cached,contract);write_json_exclusive(vp,cached)
    embedding_seconds=time.perf_counter()-embedding_started
    search_started=time.perf_counter()
    bundle=raw.build(plan['registry'],cached['vectors'],backend=plan['policy']['backend'],budget=plan['policy']['pair_budget'])
    candidate_seconds=time.perf_counter()-search_started
    evaluation=evaluate(bundle,plan['reference_pairs_evaluation_only'])
    report={'plan_sha256':sha(path),'registry':plan['registry'],'vectors_sha256':sha(vp),
            'bundle':bundle,'evaluation':evaluation}
    check(plan)
    if args.phase=='verify':
        old=read_json(directory/'report.json')
        if {k:v for k,v in old.items() if k!='measurements'}!=report:raise ValueError('Candidate replay changed')
        print({'verified':True,'new_generative_calls':0,'new_embedding_calls':0});return
    measured={'embedding_cache_hit':cache_hit,'embedding_load_infer_or_cache_read_seconds':embedding_seconds,
              'candidate_search_and_queue_seconds':candidate_seconds,
              'pipeline_until_report_seconds':time.perf_counter()-started,
              'new_generative_calls':0,'new_embedding_invocations':0 if cache_hit else 1,
              'runtime':cached['runtime'],'timing_scope':'Includes plan validation and vector cache IO; excludes interpreter startup, final report write, collection, common-claim/support/agent stages. Cached replay is not a fresh warm-inference benchmark.'}
    try:
        import resource
        measured['process_peak_rss_kib']=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    except ImportError:measured['process_peak_rss_kib']=None
    report['measurements']=measured
    write_json_exclusive(directory/'report.json',report)
    with (directory/'overview.html').open('x',encoding='utf-8') as f:f.write(render(report))
    print(json.dumps({'summary':bundle['summary'],'evaluation':evaluation,'measurements':measured}),flush=True)


if __name__=='__main__':main()
