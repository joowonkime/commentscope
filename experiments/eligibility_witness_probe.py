"""Frozen 48-source, two-arm local eligibility comparison; no production writes."""
import argparse
from collections import Counter
import html
import json
from pathlib import Path
import time

from commentscope.agents.runtime import request
from commentscope.factory import source_eligibility as baseline, eligibility_witness as witness
from commentscope.factory.automatic import local_provider
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.storage import write_json_exclusive as write
from experiments import source_eligibility_probe as prior
from experiments.grounded_core_probe import check_inputs

ORIGIN = Path('runs/source-eligibility-20261013/plan.json')
FIXTURE = 'tests/fixtures/eligibility-witness-cases.json'
ARMS = ['source_only', 'witness']
CODE = [*prior.CODE, 'src/commentscope/factory/eligibility_witness.py',
        'experiments/eligibility_witness_probe.py', 'tests/test_eligibility_witness.py']


def cases():
    rows = prior.cases() + [{**c, 'id':'witness_contrast:'+c['id'], 'cohort':'witness_contrast'}
                            for c in read_json(FIXTURE)['cases']]
    return sorted(rows, key=lambda c:c['id'])


def requests_for(case):
    return {'source_only':baseline.request_for(case['source']), 'witness':witness.request_for(case['source'])}


def make_plan():
    old = read_json(ORIGIN); check_inputs(old); rows = cases()
    if len(rows)!=48 or len({c['source'] for c in rows})!=48: raise ValueError('Expected 48 unique sources')
    return {'artifact_kind':'eligibility-witness-probe-0.1', 'expires_at':old['expires_at'],
            'inputs':{str(f):sha(f) for f in [ORIGIN,*prior.FIXTURES,FIXTURE]},
            'code_sha256':{f:sha(f) for f in dict.fromkeys(CODE)},
            'server':old['server'], 'models':old['models'], 'runtime':old['runtime'],
            'arms':ARMS, 'cases':rows, 'requests':{c['id']:requests_for(c) for c in rows},
            'max_calls':96, 'max_calls_per_arm':48, 'max_seconds_per_arm':900,
            'criteria':{'legacy_positive_kept':8, 'new_contrast_positive_kept':8,
                        'witness_contrast_positive_kept':8, 'negative_eligible':0, 'errors':0,
                        'required_text_retained':True,
                        'scope':'Only qualifies for a subsequent real-data trial, never agent approval.'},
            'limitations':['Assistant-authored development labels, not independent gold.',
                           'New contrasts were frozen before inference but informed by known failures.',
                           'Prompt, input positions and output structure change together; package comparison.',
                           'Valid offsets and graph structure do not prove semantic reference or endorsement.',
                           'One selected assertion is not exhaustive extraction or claim-level fidelity.',
                           'Over 128 whitespace tokens is deferred without truncation; no production filtering.'],
            'quality_gate_passed':False, 'agents':[]}


def interpret(case, arm, result):
    return baseline.interpret(result) if arm=='source_only' else witness.interpret(result,case['source'])


def fresh(case, arm, req, provider=local_provider):
    seen = []
    def capture(*args):
        raw = provider(*args); seen.append(raw); return raw
    result = request(req['system'],req['data'],req['schema'],capture)
    return {'request_sha256':digest(req), 'result':result, 'result_sha256':digest(result),
            'response':seen[0] if seen else None, 'decision':interpret(case,arm,result)}


def required_text_retained(case, decision):
    """Offline coverage check only: never sent to the model or used for host eligibility."""
    if 'required_text' not in case: return None
    spans = [decision.get('candidate'), decision.get('endorsement')]
    spans += [r['antecedent'] for r in decision.get('references',[])]
    return decision['state']=='eligible' and any(case['required_text'] in s['text'] for s in spans if s)


def summarize(plan, records):
    arms = {}
    for arm in plan['arms']:
        results = records[arm]; cohorts = {}
        for cohort in sorted({c['cohort'] for c in plan['cases']}):
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
        arms[arm] = {'cohorts':cohorts, 'fresh_calls':len(results),
                    'states':dict(Counter(a['decision']['state'] for a in results.values())),
                    'inference_seconds':sum(a['result']['seconds'] for a in results.values()),
                    'completion_tokens':sum((a['result']['usage'] or {}).get('completion_tokens',0) for a in results.values())}
    observed = arms['witness']['cohorts']; thresholds = plan['criteria']
    checks = {cohort+'_positive_kept':values['positive_kept']>=thresholds[cohort+'_positive_kept']
              for cohort,values in observed.items()}
    coverage = {c['id']:required_text_retained(c,records['witness'][c['id']]['decision'])
                for c in plan['cases'] if 'required_text' in c}
    checks.update(zero_negative_eligible=all(c['negative_eligible']==0 for c in observed.values()),
                  zero_errors=all(c['errors']==0 for c in observed.values()),
                  required_text_retained=all(coverage.values()))
    return {'arms':arms, 'witness_checks':checks, 'required_text_coverage':coverage,
            'state_changes':[c['id'] for c in plan['cases'] if records['source_only'][c['id']]['decision']['state']!=records['witness'][c['id']]['decision']['state']],
            'structural_abstentions':{c['id']:records['witness'][c['id']]['decision']['reasons']
                                     for c in plan['cases'] if records['witness'][c['id']]['decision']['reasons']},
            'eligible_for_real_data_trial':all(checks.values()), 'quality_gate_passed':False, 'agents':[],
            'decision_scope':'one_source_eligibility_not_fidelity_or_agent_approval'}


def load_records(plan, directory):
    if read_json(directory/'started.json')['plan_sha256']!=sha(directory/'plan.json'): raise ValueError('Started plan changed')
    records = {}
    for arm in plan['arms']:
        ad = directory/arm
        if read_json(ad/'stopped.json')['returncode']!=0: raise ValueError('Unclean server exit')
        if read_json(ad/'runtime.json')['command']!=prior.m.command(plan,'baseline'): raise ValueError('Runtime changed')
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
            '<title>원문 위치 근거 자격 검사</title><style>body{font:16px/1.7 system-ui;max-width:1100px;margin:auto;padding:24px}pre,blockquote{white-space:pre-wrap;overflow-wrap:anywhere}article{border-top:1px solid #aaa}</style>',
            '<h1>원문 위치 근거 자격 검사</h1><p>48개 합성 원문 × 2조건 = 96회. 개발 라벨이며 독립 gold나 agent 승인 검사가 아닙니다.</p>',
            '<pre>'+esc(json.dumps(report,ensure_ascii=False,indent=2))+'</pre>']
    for c in plan['cases']:
        page += ['<article><h2>'+esc(c['id'])+'</h2><blockquote>'+esc(c['source'])+'</blockquote><p>독립 주장 기대: '+esc(c['expected'])+'</p>']
        for arm in plan['arms']:
            a = records[arm][c['id']]
            page += ['<h3>'+esc(arm)+': '+esc(a['decision']['state'])+'</h3><pre>'+esc(json.dumps({'output':a['result']['output'],'host':a['decision']},ensure_ascii=False,indent=2))+'</pre>']
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
    if (plan['arms']!=ARMS or plan['cases']!=cases() or plan['runtime']!=prior.m.RUNTIME
            or plan['requests']!={c['id']:requests_for(c) for c in plan['cases']}):
        raise ValueError('Frozen experiment changed')
    if args.phase=='run':
        if (directory/'started.json').exists(): raise ValueError('No partial-run resume; preserve it and create a new plan')
        for model in [plan['server'],plan['models']['baseline']]:
            if prior.m.file_hash(model['path'])!=model['sha256']: raise ValueError('Runtime bytes changed')
        write(directory/'started.json',{'plan_sha256':sha(directory/'plan.json')})
        for arm in plan['arms']:
            with prior.m.owned_server(plan,'baseline',directory/arm):
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
        print({'new_model_calls':0,'replayed_attempts':sum(len(r) for r in records.values()),'report_sha256':sha(directory/'report.json')})
    else:
        write(directory/'report.json',report)
        with (directory/'overview.html').open('x',encoding='utf-8') as f: f.write(render(plan,report,records))
        print(json.dumps(report,ensure_ascii=False),flush=True)


if __name__=='__main__': main()
