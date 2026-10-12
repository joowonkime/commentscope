"""Three-arm eligibility ablation with unchanged local 4B and frozen labels."""
import argparse
from collections import Counter
import html
import json
from pathlib import Path
import time

from commentscope.agents.runtime import request
from commentscope.factory import source_eligibility as e, positional_support as p
from commentscope.factory.automatic import local_provider
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.storage import write_json_exclusive as write
from experiments import audit_model_compare as m
from experiments.grounded_core_probe import check_inputs

ORIGIN = Path('runs/audit-model-comparison-20261012/plan.json')
FIXTURES = ['tests/fixtures/evidence-unit-cases.json','tests/fixtures/source-eligibility-contrast-cases.json']
ARMS = ['joint','eligibility_with_target','source_only']
CODE = [*m.CODE,'src/commentscope/factory/source_eligibility.py','experiments/source_eligibility_probe.py']


def cases():
    rows = []
    for name,path in zip(['legacy','new_contrast'],FIXTURES):
        rows += [{**c,'id':name+':'+c['id'],'cohort':name} for c in read_json(path)['cases']]
    return sorted(rows,key=lambda c:c['id'])


def requests_for(case):
    original = case['source']
    source_only = e.request_for(original)
    with_target = e.request_for(original)
    with_target['data']['TARGET'] = original
    return {'joint':m.audit_request(original,original),
            'eligibility_with_target':with_target,'source_only':source_only}


def make_plan():
    old = read_json(ORIGIN); check_inputs(old); rows = cases()
    if len(rows)!=32 or len({c['source'] for c in rows})!=32: raise ValueError('Expected 32 unique sources')
    return {'artifact_kind':'source-eligibility-probe-0.1','expires_at':old['expires_at'],
            'inputs':{str(f):sha(f) for f in [ORIGIN,*FIXTURES]},
            'code_sha256':{f:sha(f) for f in dict.fromkeys(CODE)},
            'server':old['server'],'models':{'baseline':old['models']['baseline']},'runtime':old['runtime'],
            'arms':ARMS,'cases':rows,'requests':{c['id']:requests_for(c) for c in rows},
            'max_calls':96,'max_calls_per_arm':32,'max_seconds_per_arm':600,
            'criteria':{'legacy_positive_kept':8,'new_contrast_positive_kept_minimum':7,
                        'negative_eligible':0,'errors':0,
                        'scope':'Source-only may qualify for a subsequent real-data check, not service filtering or agent approval.'},
            'limitations':['All expectations are assistant development labels, not independent human gold.',
                           'New contrast examples were written before inference but informed by known failures.',
                           'Joint vs dedicated changes task wording and schema together, not a pure target-removal effect.',
                           'Dedicated with/without TARGET differs only by that input field; both instruct ignoring TARGET.',
                           'Only two Korean examples, not multilingual quality validation.',
                           'Source eligibility is not individual-claim eligibility or fidelity.'],
            'quality_gate_passed':False,'agents':[]}


def interpret(case, arm, result):
    if arm!='joint': return e.interpret(result)
    errors = list(result['errors'])
    if not errors: errors += p.validate_audit(result['output'],case['source'])
    narrowed = {'errors':errors,'output':None if errors else {'eligibility':result['output']['eligibility']}}
    decision = e.interpret(narrowed)
    decision['joint_projection'] = 'error' if errors else p.project(result['output'])
    return decision


def fresh(case, arm, req, provider=local_provider):
    seen = []
    def capture(*args):
        raw = provider(*args); seen.append(raw); return raw
    result = request(req['system'],req['data'],req['schema'],capture)
    return {'request_sha256':digest(req),'result':result,'result_sha256':digest(result),
            'response':seen[0] if seen else None,'decision':interpret(case,arm,result)}


def summarize(plan, records):
    arms = {}
    for arm in plan['arms']:
        results = records[arm]; cohorts = {}
        for cohort in ['legacy','new_contrast']:
            rows = [c for c in plan['cases'] if c['cohort']==cohort]
            state = lambda c:results[c['id']]['decision']['state']
            cohorts[cohort] = {'positive':sum(c['expected'] for c in rows),
                'positive_kept':sum(c['expected'] and state(c)=='eligible' for c in rows),
                'negative':sum(not c['expected'] for c in rows),
                'negative_eligible':sum(not c['expected'] and state(c)=='eligible' for c in rows),
                'negative_excluded':sum(not c['expected'] and state(c)=='excluded' for c in rows),
                'negative_context_dependent':sum(not c['expected'] and state(c)=='context_dependent' for c in rows),
                'negative_uncertain':sum(not c['expected'] and state(c)=='uncertain' for c in rows),
                'errors':sum(state(c)=='error' for c in rows)}
        arms[arm] = {'cohorts':cohorts,'fresh_calls':len(results),
                     'states':dict(Counter(a['decision']['state'] for a in results.values())),
                     'inference_seconds':sum(a['result']['seconds'] for a in results.values()),
                     'completion_tokens':sum((a['result']['usage'] or {}).get('completion_tokens',0) for a in results.values())}
    changes = {}
    for left,right in [('joint','eligibility_with_target'),('eligibility_with_target','source_only')]:
        changes[left+'__'+right] = [c['id'] for c in plan['cases'] if records[left][c['id']]['decision']['label']!=records[right][c['id']]['decision']['label']]
    source = arms['source_only']['cohorts']; criteria = plan['criteria']
    checks = {'legacy_positive_kept':source['legacy']['positive_kept']>=criteria['legacy_positive_kept'],
              'new_contrast_positive_kept':source['new_contrast']['positive_kept']>=criteria['new_contrast_positive_kept_minimum'],
              'zero_negative_eligible':all(c['negative_eligible']==0 for c in source.values()),
              'zero_errors':all(c['errors']==0 for c in source.values())}
    return {'arms':arms,'label_changes':changes,'source_only_checks':checks,
            'eligible_for_real_data_trial':all(checks.values()),'quality_gate_passed':False,'agents':[],
            'decision_scope':'source_eligibility_not_fidelity_or_agent_approval'}


def load_records(plan, directory):
    if read_json(directory/'started.json')['plan_sha256']!=sha(directory/'plan.json'): raise ValueError('Started plan changed')
    records = {}
    for arm in plan['arms']:
        ad = directory/arm
        if read_json(ad/'stopped.json')['returncode']!=0: raise ValueError('Unclean server exit')
        if read_json(ad/'runtime.json')['command']!=m.command(plan,'baseline'): raise ValueError('Runtime changed')
        if len(list(ad.glob('attempt-*.json')))!=len(plan['cases']): raise ValueError('Incomplete attempt set')
        records[arm] = {}
        for seq,c in enumerate(plan['cases']):
            wrapper = read_json(ad/f'attempt-{seq:03}.json'); a = wrapper['attempt']
            if (wrapper['attempt_sha256']!=digest(a) or a['arm']!=arm or a['sequence']!=seq or a['case']!=c['id']
                    or a['request_sha256']!=digest(plan['requests'][c['id']][arm])
                    or a['result_sha256']!=digest(a['result']) or a['decision']!=interpret(c,arm,a['result'])):
                raise ValueError('Attempt changed')
            records[arm][c['id']] = a
    return records


def render(plan, report, records):
    esc = lambda v:html.escape(str(v),quote=True)
    page = ['<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
            '<title>원문 자격 검사 분리 비교</title><style>body{font:16px/1.7 system-ui;max-width:1100px;margin:auto;padding:24px}pre,blockquote{white-space:pre-wrap;overflow-wrap:anywhere}article{border-top:1px solid #aaa}</style>',
            '<h1>원문 자격 검사 분리 비교</h1><p>4B 고정, 32원문 × 3조건 = 96회. assistant 개발 라벨이며 agent 승인이나 독립 정확도 평가가 아닙니다.</p>',
            '<pre>'+esc(json.dumps(report,ensure_ascii=False,indent=2))+'</pre>']
    for c in plan['cases']:
        page += ['<article><h2>'+esc(c['id'])+'</h2><blockquote>'+esc(c['source'])+'</blockquote><p>독립 주장 기대: '+esc(c['expected'])+'</p>']
        for arm in plan['arms']:
            a = records[arm][c['id']]
            page += ['<h3>'+esc(arm)+': '+esc(a['decision']['state'])+'</h3><pre>'+esc(json.dumps(a['result']['output'],ensure_ascii=False,indent=2))+'</pre>']
        page.append('</article>')
    return '\n'.join(page+['</html>'])


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--run-dir',type=Path,required=True)
    ap.add_argument('--phase',choices=['plan','run','verify'],required=True)
    ap.add_argument('--diagnostic-only',action='store_true',required=True)
    args = ap.parse_args(); directory = args.run_dir
    if args.phase=='plan':
        plan = make_plan(); write(directory/'plan.json',plan)
        print({'cases':len(plan['cases']),'calls':plan['max_calls'],'plan_sha256':sha(directory/'plan.json')}); return
    plan = read_json(directory/'plan.json'); check_inputs(plan)
    if (plan['arms']!=ARMS or plan['cases']!=cases() or plan['runtime']!=m.RUNTIME
            or plan['requests']!={c['id']:requests_for(c) for c in plan['cases']}):
        raise ValueError('Frozen experiment changed')
    if args.phase=='run':
        if (directory/'started.json').exists(): raise ValueError('No partial-run resume; preserve it and create a new plan')
        for model in [plan['server'],plan['models']['baseline']]:
            if m.file_hash(model['path'])!=model['sha256']: raise ValueError('Runtime bytes changed')
        write(directory/'started.json',{'plan_sha256':sha(directory/'plan.json')})
        for arm in plan['arms']:
            with m.owned_server(plan,'baseline',directory/arm):
                started = time.perf_counter()
                for seq,c in enumerate(plan['cases']):
                    if seq>=plan['max_calls_per_arm'] or time.perf_counter()-started>plan['max_seconds_per_arm']:
                        raise RuntimeError('Budget reached; preserve partial outputs')
                    a = {'arm':arm,'case':c['id'],'sequence':seq,**fresh(c,arm,plan['requests'][c['id']][arm])}
                    write(directory/arm/f'attempt-{seq:03}.json',{'attempt':a,'attempt_sha256':digest(a)})
                    print(arm,seq+1,c['id'],a['decision']['state'],round(a['result']['seconds'],2),flush=True)
    records = load_records(plan,directory); report = summarize(plan,records)
    if args.phase=='verify':
        if read_json(directory/'report.json')!=report: raise ValueError('Report changed')
        print({'new_model_calls':0,'replayed_attempts':96,'report_sha256':sha(directory/'report.json')})
    else:
        write(directory/'report.json',report)
        with (directory/'overview.html').open('x',encoding='utf-8') as f: f.write(render(plan,report,records))
        print(json.dumps(report,ensure_ascii=False),flush=True)


if __name__=='__main__': main()
