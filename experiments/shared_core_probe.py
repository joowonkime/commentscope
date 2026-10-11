"""Frozen-case common-core discovery, with separate temporal and source support checks."""
import argparse
import html
import json
from importlib.metadata import version
from pathlib import Path

from commentscope.agents.profiles import require_live
from commentscope.factory.automatic import Calls, local_provider
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.factory import shared_core, temporal_guard, claim_frame
from commentscope.providers.local_nli import LocalNLI, MODEL, REVISION, THRESHOLD
from commentscope.storage import write_json_exclusive
from experiments.claim_frame_probe import prepare_cases
from experiments.claim_support_probe import CachedScores


def render(report):
    esc = lambda v: html.escape(str(v), quote=True)
    parts = ['<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
             '<title>시점 보존과 공통 주장 탐색</title><style>body{font:16px/1.6 system-ui;max-width:1100px;margin:auto;padding:20px}pre,blockquote{white-space:pre-wrap;overflow-wrap:anywhere}article{border-top:1px solid #999;padding:16px}</style>',
             '<h1>시점 보존과 공통 주장 탐색</h1><p>비공개 개발 평가. 모델 제안과 자동 검사 결과이며 독립 gold/품질 승인이 아닙니다.</p>',
             '<pre>'+esc(json.dumps(report['summary'],ensure_ascii=False,indent=2))+'</pre>']
    for row in report['results']:
        parts.append('<article><h2>'+esc(row['id'])+'</h2><p>기대: '+esc(row['expected'])+'</p>')
        for key in ['anchor','member']:
            parts.append('<h3>'+key+'</h3><blockquote>'+esc(shared_core.source(row[key]))+'</blockquote><p>'+esc(row[key]['statement'])+'</p>')
        parts.append('<p>자동 공통 주장: '+esc(row['trace']['selected_core'])+'</p>')
        parts.append('<details><summary>모든 제안·검사·거절 사유</summary><pre>'+esc(json.dumps(row['trace'],ensure_ascii=False,indent=2))+'</pre></details></article>')
    return '\n'.join(parts+['</html>'])


def has_errors(value):
    if isinstance(value,dict):
        return bool(value.get('errors')) or any(has_errors(v) for k,v in value.items() if k!='attempts')
    if isinstance(value,list): return any(has_errors(v) for v in value)
    return False


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['snapshot','baseline_report','reference_evaluation']: parser.add_argument(name)
    parser.add_argument('--run-dir',type=Path,required=True)
    parser.add_argument('--fixtures',default='tests/fixtures/claim-frame-cases.json')
    args=parser.parse_args()
    if any((args.run_dir/p).exists() for p in ['report.json','overview.html']): parser.error('Completed output exists')
    baseline,cases=prepare_cases(args.snapshot,args.baseline_report,args.reference_evaluation,args.fixtures)
    manifest={'artifact_kind':'shared-core-diagnostic-0.1','expires_at':baseline['expires_at'],
              'snapshot_sha256':sha(args.snapshot),'baseline_sha256':sha(args.baseline_report),
              'reference_sha256':sha(args.reference_evaluation),'fixture_sha256':sha(args.fixtures),
              'cases':cases,'model':baseline['model'],'nli_model':MODEL,'nli_revision':REVISION,'threshold':THRESHOLD,
              'runtime_config':{'torch':version('torch'),'transformers':version('transformers'),'device':'cpu','threads':6},
              'code_sha256':{p:sha(p) for p in [__file__,'src/commentscope/factory/shared_core.py',
                  'src/commentscope/factory/temporal_guard.py','src/commentscope/factory/claim_frame.py',
                  'src/commentscope/factory/automatic.py','src/commentscope/providers/local_nli.py',
                  'experiments/claim_frame_probe.py','experiments/claim_support_probe.py']},
              'prompt_sha256':{'proposal':digest(shared_core.SYSTEM),'temporal':digest({k:claim_frame.TASK_SYSTEMS[k] for k in temporal_guard.FIELDS})},
              'next_stage_criterion':'All frozen synthetic and real development positives/negatives correct, no changed expected labels; assistant inspects new cores before fresh integration. Not independent gold.',
              'accepted_perspectives':0,'human_handling':False,'independent_gold':False,'service_time_input':False,
              'protocol_change':'Discover a common core instead of accepting the old anchor verbatim. Prior experiments unchanged.'}
    calls=Calls(args.run_dir/'llm',manifest,local_provider)
    model=None
    def score(a,b):
        nonlocal model
        if model is None: model=LocalNLI()
        return model.score(a,b)
    scores=CachedScores(args.run_dir/'nli',manifest,score)
    rows=[]
    for case in cases:
        trace=shared_core.discover(case['anchor'],case['member'],calls,scores)
        rows.append({**case,'trace':trace})
        print(json.dumps({'case':case['id'],'expected':case['expected'],'core':trace['selected_core'],
                          'blocked':trace['blocked_reasons']},ensure_ascii=False),flush=True)
    summary={}
    for kind in ['synthetic','real_development']:
        selected=[r for r in rows if r['kind']==kind]
        summary[kind]={'positive_total':sum(r['expected'] for r in selected),
                       'positive_kept':sum(r['expected'] and bool(r['trace']['selected_core']) for r in selected),
                       'negative_total':sum(not r['expected'] for r in selected),
                       'negative_blocked':sum(not r['expected'] and not r['trace']['selected_core'] for r in selected),
                       'cases_with_errors':sum(has_errors(r['trace']) for r in selected)}
    eligible=all(r['positive_kept']==r['positive_total'] and r['negative_blocked']==r['negative_total']
                 and not r['cases_with_errors'] for r in summary.values())
    report={**manifest,'results':rows,'summary':summary,'next_stage_eligible':eligible,
            'unique_nli_requests':len(scores.records),'new_llm_calls':calls.new_calls,
            'nli_inference_seconds':sum(r['seconds'] for r in scores.records.values()),
            'limitations':['Development cases already inspected; no independent gold',
                          'English-only NLI; passing Korean fixture is not multilingual validation',
                          'Lexical English condition guard is incomplete, not a general condition parser',
                          'Temporal/modality labels remain fallible; source/model judgments are not proof',
                          'Shorter supported candidate is a heuristic, not globally minimal common meaning',
                          'No new cluster or agent is generated by this pair experiment']}
    require_live(baseline['expires_at'])
    write_json_exclusive(args.run_dir/'report.json',report)
    with (args.run_dir/'overview.html').open('x',encoding='utf-8') as f: f.write(render(report))
    print(json.dumps({'summary':summary,'eligible':eligible}),flush=True)


if __name__=='__main__': main()
