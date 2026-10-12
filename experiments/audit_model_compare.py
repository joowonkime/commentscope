"""Frozen, opt-in deployment comparison of two local auditors; no selector changes."""
import argparse
from collections import Counter
from contextlib import contextmanager
import hashlib
import html
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import time
from urllib.request import build_opener, ProxyHandler

from commentscope.factory import positional_support as p
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.storage import write_json_exclusive as write
from experiments import audit_repeatability_probe as prior
from experiments.grounded_core_probe import check_inputs

ORIGIN = Path('runs/audit-repeatability-20261012/plan.json')
FIXTURES = ['tests/fixtures/core-fidelity-cases.json','tests/fixtures/evidence-unit-cases.json']
CANDIDATE = {'name':'Qwen3-8B-Q4_K_M','repository':'Qwen/Qwen3-8B-GGUF',
             'revision':'7c41481f57cb95916b40956ab2f0b139b296d974',
             'path':'/home/taeng/.cache/commentscope-models/Qwen3-8B-Q4_K_M.gguf',
             'bytes':5027783488,
             'sha256':'d98cdcbd03e17ce47681435b5150e34c1417f50b5c0019dd560e4882c5745785'}
RUNTIME = {'context':4096,'gpu_layers':26,'threads':6,'parallel':1,'cache_prompt':False,
           'template_kwargs':{'enable_thinking':False},'temperature':0,'seed':407,'max_tokens':900,
           'max_seconds_per_model':900,'retries':0,'repairs':0}
CODE = [*prior.CODE,'experiments/audit_model_compare.py']


def file_hash(path):
    with Path(path).open('rb') as f: return hashlib.file_digest(f,'sha256').hexdigest()


def audit_request(original, target):
    schema = p.audit_schema(original)
    req = {'system':p.AUDIT+'\n\nRequired JSON output schema:\n'+json.dumps(schema,ensure_ascii=False,sort_keys=True,separators=(',',':')),
           'data':{'SOURCE':p.parts(original),'TARGET':target},'schema':schema}
    prior.source(req)
    return req


def make_cases(old, fidelity, eligibility):
    rows = []
    for c in old['cases']:
        rows.append({'id':'repeat:'+c['id'],'cohort':'repeatability_controls','request':c['request'],
                     'expected':c['expected']=='support'})
    for c in fidelity['cases']:
        rows.append({'id':'fidelity:'+c['id'],'cohort':'fidelity_controls',
                     'request':audit_request(c['source'],c['target']),'expected':c['expected']})
    for c in eligibility['cases']:
        rows.append({'id':'eligibility:'+c['id'],'cohort':'eligibility_controls',
                     'request':audit_request(c['source'],c['source']),'expected':c['expected']})
    requests = {}
    for row in rows:
        req = row.pop('request'); prior.source(req); rid = digest(req)
        requests[rid] = req; row['request_id'] = rid
    return rows,[{'id':k,'request':v} for k,v in sorted(requests.items())]


def make_plan():
    old = read_json(ORIGIN); check_inputs(old)
    rows,requests = make_cases(old,*(read_json(f) for f in FIXTURES))
    if len(rows)!=40 or len(requests)!=39: raise ValueError('Expected 40 labels / 39 unique requests')
    baseline = {'name':'Qwen3-4B-Instruct-2507-Q4_K_M',
                'revision':'a06e946bb6b655725eafa393f4a9745d460374c9',
                'path':old['runtime']['model'],'sha256':old['runtime']['model_sha256']}
    for model in [baseline,CANDIDATE]:
        if file_hash(model['path']) != model['sha256']: raise ValueError('Model checksum changed')
    if Path(CANDIDATE['path']).stat().st_size != CANDIDATE['bytes']: raise ValueError('Model size changed')
    return {'artifact_kind':'audit-model-comparison-0.1','expires_at':old['expires_at'],
            'inputs':{str(f):sha(f) for f in [ORIGIN,*FIXTURES]},
            'code_sha256':{f:sha(f) for f in dict.fromkeys(CODE)},
            'server':{'path':str(prior.SERVER),'sha256':file_hash(prior.SERVER),'libraries':prior.LIBS},
            'models':{'baseline':baseline,'candidate':CANDIDATE},'model_order':['baseline','candidate'],
            'runtime':RUNTIME,'rows':rows,'requests':requests,'max_calls_per_model':39,'max_calls_total':78,
            'criteria':{'zero_errors':True,'zero_negative_support_in_every_cohort':True,
                        'positive_kept_at_least_baseline_in_every_cohort':True,
                        'repeatability_positive_kept_at_least':9,
                        'meaning':'Only qualifies for a subsequent full-pipeline trial, never production approval.'},
            'limitations':['Known assistant development labels, not independent gold or unseen accuracy.',
                           'Different model training and native templates; not a parameter-count-only ablation.',
                           'Matched deployment settings differ from historical 8192-context/full-GPU tests.',
                           'Temperature0 retained for control, not the model card recommended general sampling.',
                           'Provisional audit only: no NLI/guards, clustering or agent promotion.'],
            'quality_gate_passed':False,'agents':[]}


def command(plan, name):
    runtime = plan['runtime']
    return [plan['server']['path'],'-m',plan['models'][name]['path'],
            '--host','127.0.0.1','--port','8091','-c',str(runtime['context']),
            '--no-context-shift','-ngl',str(runtime['gpu_layers']),'-t',str(runtime['threads']),
            '--parallel','1','--no-cache-prompt','--jinja',
            '--chat-template-kwargs',json.dumps(runtime['template_kwargs'],sort_keys=True)]


@contextmanager
def owned_server(plan, name, directory):
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        probe.bind(('127.0.0.1',8091))
    directory.mkdir(parents=True,exist_ok=False)
    env = {k:v for k,v in os.environ.items() if not k.startswith('LLAMA_ARG_')}
    env['LD_LIBRARY_PATH'] = plan['server']['libraries']
    with (directory/'server.log').open('x') as log:
        proc = subprocess.Popen(command(plan,name),env=env,stdout=log,stderr=subprocess.STDOUT)
        started = time.perf_counter()
        try:
            opener = build_opener(ProxyHandler({}))
            while True:
                if proc.poll() is not None: raise RuntimeError('Owned server failed; inspect its private log')
                try:
                    with opener.open('http://127.0.0.1:8091/health',timeout=1) as response:
                        if json.load(response).get('status')=='ok': break
                except OSError: pass
                if time.perf_counter()-started>60: raise TimeoutError('Server startup budget')
                time.sleep(.2)
            maps = Path(f'/proc/{proc.pid}/maps').read_text()
            libraries = sorted({line.split()[-1] for line in maps.splitlines()
                                if '/' in line and any(s in line for s in ['libggml','libcuda','libcublas'])})
            write(directory/'runtime.json',{'pid':proc.pid,'command':command(plan,name),
                  'startup_seconds':time.perf_counter()-started,
                  'loaded_library_sha256':{f:file_hash(f) for f in libraries if Path(f).is_file()}})
            yield proc
        finally:
            if proc.poll() is None:
                proc.send_signal(signal.SIGINT)
                try: proc.wait(timeout=15)
                except subprocess.TimeoutExpired: proc.kill(); proc.wait(timeout=5)
            write(directory/'stopped.json',{'pid':proc.pid,'returncode':proc.returncode})


def summarize(plan, records):
    models = {}
    for name in plan['model_order']:
        model = records[name]; cohorts = {}
        for cohort in sorted({r['cohort'] for r in plan['rows']}):
            rows = [r for r in plan['rows'] if r['cohort']==cohort]
            state = lambda r:model[r['request_id']]['decision']['state']
            cohorts[cohort] = {'positive':sum(r['expected'] for r in rows),
                              'positive_kept':sum(r['expected'] and state(r)=='support' for r in rows),
                              'negative':sum(not r['expected'] for r in rows),
                              'negative_false_support':sum(not r['expected'] and state(r)=='support' for r in rows),
                              'negative_rejected':sum(not r['expected'] and state(r)=='not_supported' for r in rows),
                              'negative_uncertain':sum(not r['expected'] and state(r)=='uncertain' for r in rows),
                              'errors':sum(state(r)=='error' for r in rows)}
        models[name] = {'cohorts':cohorts,'fresh_calls':len(model),
                        'states':dict(Counter(a['decision']['state'] for a in model.values())),
                        'inference_seconds':sum(a['result']['seconds'] for a in model.values()),
                        'errors':sum(bool(a['decision']['errors']) for a in model.values())}
    baseline = models['baseline']['cohorts']; candidate = models['candidate']['cohorts']
    checks = {'zero_errors':models['candidate']['errors']==0,
              'zero_negative_support_in_every_cohort':all(c['negative_false_support']==0 for c in candidate.values()),
              'positive_kept_at_least_baseline_in_every_cohort':all(candidate[k]['positive_kept']>=baseline[k]['positive_kept'] for k in baseline),
              'repeatability_positive_kept_at_least_9':candidate['repeatability_controls']['positive_kept']>=9}
    return {'models':models,'candidate_trial_checks':checks,'candidate_eligible_for_full_pipeline_trial':all(checks.values()),
            'quality_gate_passed':False,'agents':[],'decision_scope':'provisional_audit_only',
            'unique_requests':len(plan['requests']),'label_rows':len(plan['rows'])}


def load_records(plan, directory):
    if read_json(directory/'started.json')['plan_sha256']!=sha(directory/'plan.json'):
        raise ValueError('Started plan changed')
    records = {}
    for name in plan['model_order']:
        md = directory/name
        if read_json(md/'stopped.json')['returncode']!=0: raise ValueError('Unclean server exit')
        if read_json(md/'runtime.json')['command']!=command(plan,name): raise ValueError('Runtime command changed')
        if len(list(md.glob('attempt-*.json')))!=len(plan['requests']): raise ValueError('Incomplete attempts')
        records[name] = {}
        for seq,c in enumerate(plan['requests']):
            row = read_json(md/f'attempt-{seq:03}.json'); a = row['attempt']
            if (row['attempt_sha256']!=digest(a) or a['model']!=name or a['sequence']!=seq
                    or a['request_sha256']!=c['id'] or a['result_sha256']!=digest(a['result'])
                    or a['decision']!=prior.decision(c['request'],a['result'])):
                raise ValueError('Attempt changed')
            records[name][c['id']] = a
    return records


def render(plan, report, records):
    esc = lambda x:html.escape(str(x),quote=True)
    page = ['<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
            '<title>로컬 판정기 모델 비교</title><style>body{font:16px/1.7 system-ui;max-width:1100px;margin:auto;padding:24px}pre,blockquote{white-space:pre-wrap;overflow-wrap:anywhere}article{border-top:1px solid #aaa}</style>',
            '<h1>같은 요청으로 4B와 8B 판정기 비교</h1><p>후보/프롬프트/스키마 고정. 개발 사례이며 독립 gold가 아닙니다. 잠정 감사만 측정하며 agent0개.</p>',
            '<pre>'+esc(json.dumps(report,ensure_ascii=False,indent=2))+'</pre>']
    for c in plan['requests']:
        labels = [r for r in plan['rows'] if r['request_id']==c['id']]
        page += ['<article><h2>'+esc(', '.join(r['id'] for r in labels))+'</h2>',
                 '<p>원문</p><blockquote>'+esc(prior.source(c['request']))+'</blockquote>',
                 '<p>판정 대상</p><blockquote>'+esc(c['request']['data']['TARGET'])+'</blockquote>']
        for name in plan['model_order']:
            row = records[name][c['id']]
            page += ['<h3>'+esc(name)+' / '+esc(row['decision']['state'])+'</h3><pre>'+esc(json.dumps(row['result']['output'],ensure_ascii=False,indent=2))+'</pre>']
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
        print({'requests':len(plan['requests']),'plan_sha256':sha(directory/'plan.json')}); return
    plan = read_json(directory/'plan.json'); check_inputs(plan)
    if plan['runtime']!=RUNTIME or plan['models']['candidate']!=CANDIDATE:
        raise ValueError('Frozen deployment changed')
    rows,requests = make_cases(read_json(ORIGIN),*(read_json(f) for f in FIXTURES))
    if rows!=plan['rows'] or requests!=plan['requests'] or plan['model_order']!=['baseline','candidate']:
        raise ValueError('Frozen evaluation changed')
    if args.phase=='run':
        if (directory/'started.json').exists(): raise ValueError('Do not resume a partial comparison; use a new run directory')
        for m in [plan['server'],*plan['models'].values()]:
            if file_hash(m['path'])!=m['sha256']: raise ValueError('Runtime bytes changed')
        write(directory/'started.json',{'plan_sha256':sha(directory/'plan.json')})
        for name in plan['model_order']:
            with owned_server(plan,name,directory/name):
                started = time.perf_counter()
                for seq,c in enumerate(plan['requests']):
                    if seq>=plan['max_calls_per_model'] or time.perf_counter()-started>RUNTIME['max_seconds_per_model']:
                        raise RuntimeError('Inference budget reached; partial output preserved')
                    a = {'model':name,'sequence':seq,**prior.fresh(c)}
                    write(directory/name/f'attempt-{seq:03}.json',{'attempt':a,'attempt_sha256':digest(a)})
                    print(name,seq+1,a['decision'],round(a['result']['seconds'],2),flush=True)
    records = load_records(plan,directory); report = summarize(plan,records)
    if args.phase=='verify':
        if read_json(directory/'report.json')!=report: raise ValueError('Report changed')
        print({'new_model_calls':0,'attempts':sum(len(v) for v in records.values()),'report_sha256':sha(directory/'report.json')})
    else:
        write(directory/'report.json',report)
        with (directory/'overview.html').open('x',encoding='utf-8') as f: f.write(render(plan,report,records))
        print(json.dumps(report,ensure_ascii=False),flush=True)


if __name__=='__main__': main()
