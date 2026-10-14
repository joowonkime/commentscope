"""Fresh local audit calls: cache on/off x blocked/interleaved, never response replay."""
import argparse
from collections import Counter
from contextlib import contextmanager
import html
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import time
from urllib.request import build_opener, ProxyHandler

from commentscope.agents.runtime import request
from commentscope.factory import positional_support as p
from commentscope.factory.automatic import local_provider
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.storage import write_json_exclusive as write
from experiments.grounded_core_probe import check_inputs

ROOT = Path('/home/taeng/.local/opt/commentscope-llama')
SERVER = ROOT/'llama-b11541/llama-server'
MODEL = Path('/home/taeng/.cache/commentscope-models/Qwen3-4B-Instruct-2507-Q4_K_M.gguf')
LIBS = str(ROOT/'cudart-llama-b11541-bin-ubuntu-cuda-12.8-x64')+':'+str(SERVER.parent)
ARMS = [{'id':f'cache-{cache}-{order}', 'cache':cache, 'order':order}
        for cache in ['on','off'] for order in ['blocked','interleaved']]
REPEATS = 3
CODE = ['experiments/audit_repeatability_probe.py', 'src/commentscope/agents/runtime.py',
        'src/commentscope/providers/local_llama.py', 'src/commentscope/factory/automatic.py',
        'src/commentscope/factory/positional_support.py', 'src/commentscope/factory/grounded_core.py',
        'src/commentscope/factory/automatic_contract.py', 'src/commentscope/storage.py',
        'experiments/grounded_core_probe.py']


def source(req):
    original = ''.join(s['text'] for s in req['data']['SOURCE'])
    if (set(req) != {'system','data','schema'} or set(req['data']) != {'SOURCE','TARGET'}
            or req['data']['SOURCE'] != p.parts(original) or req['schema'] != p.audit_schema(original)):
        raise ValueError('Request contract changed')
    expected = p.AUDIT+'\n\nRequired JSON output schema:\n'+json.dumps(
        req['schema'],ensure_ascii=False,sort_keys=True,separators=(',',':'))
    if req['system'] != expected: raise ValueError('Audit prompt changed or repair request')
    return original


def checkpoint(path):
    v = read_json(path)
    if path.name != 'call-'+digest(v['request'])+'.json' or digest(v['result']) != v['result_sha256']:
        raise ValueError('Historical checkpoint changed')
    source(v['request'])
    return v


def make_plan():
    a = Path('runs/extractive-candidates-20261012')
    b = Path('runs/component-isolation-20261012')
    c = Path('runs/positional-support-20261012')
    old = read_json(a/'plan.json'); check_inputs(old)
    inputs = {str(a/'plan.json'):sha(a/'plan.json')}
    cases = []
    for path in sorted((a/'llm').glob('call-*.json')):
        other = b/'llm'/path.name
        if not other.exists(): continue
        v = checkpoint(path); previous = checkpoint(other)
        if v['request'] != previous['request']: raise ValueError('Request collision')
        inputs.update({str(f):sha(f) for f in [path,other]})
        cases.append({'id':digest(v['request']), 'request':v['request'],
                      'expected':'support', 'label_origin':'assistant_development_not_gold',
                      'historical':[{'path':str(f),'result':w['result']} for f,w in [(path,v),(other,previous)]]})
    if len(cases) != 10: raise ValueError('Expected exactly ten shared requests')
    targets = ['A user arrived at a platform shortly after viewing an AI-generated video.',
               'People who sit idle for a month are likely to begin engaging in productive activities.']
    for target in targets:
        matches = []
        for path in sorted((c/'llm').glob('call-*.json')):
            v = read_json(path)
            if v['request']['data'].get('TARGET') == target and set(v['request']['data']) == {'SOURCE','TARGET'}:
                matches.append((path,checkpoint(path)))
        if len(matches) != 1: raise ValueError('Expected unique frozen negative audit')
        path,v = matches[0]; inputs[str(path)] = sha(path)
        cases.append({'id':digest(v['request']),'request':v['request'],
                      'expected':'not_supported','label_origin':'assistant_development_not_gold',
                      'historical':[{'path':str(path),'result':v['result']}]})
    return {'artifact_kind':'audit-repeatability-0.1','expires_at':old['expires_at'],
            'inputs':inputs,'code_sha256':{f:sha(f) for f in CODE},
            'runtime':{'server':str(SERVER),'server_sha256':sha(SERVER),
                       'model':str(MODEL),'model_sha256':sha(MODEL),'libraries':LIBS},
            'arms':ARMS,'repeats':REPEATS,'cases':cases,'max_calls':144,
            'policy':'Fresh process per arm; fixed arm order; no warmup, repairs, retries or response caching. Incomplete run is not resumable.',
            'criteria':'Compare per-case raw/structured/provisional state variation; report known negative support separately. No automatic promotion.',
            'limitations':['One process per arm, three repetitions, not population accuracy or causal proof.',
                           'Provisional host projection excludes NLI and evidence guards.',
                           'Historical outputs have different preceding request histories.'],
            'quality_gate_passed':False,'agents':[]}


def schedule(cases, order, repeats=REPEATS):
    if order == 'blocked': return [(c['id'],r) for c in cases for r in range(repeats)]
    if order == 'interleaved': return [(c['id'],r) for r in range(repeats) for c in cases]
    raise ValueError('Unknown order')


def decision(req, result):
    errors = list(result['errors'])
    if not errors: errors += p.validate_audit(result['output'],source(req))
    return {'errors':errors,'state':'error' if errors else p.project(result['output'])}


def fresh(case, provider=local_provider):
    req = case['request']; source(req)
    response = []
    def capture(system,data,schema):
        raw = provider(system,data,schema); response.append(raw); return raw
    result = request(req['system'],req['data'],req['schema'],capture)
    return {'request_sha256':digest(req),'result':result,'result_sha256':digest(result),
            'response':response[0] if response else None,'decision':decision(req,result)}


def command(plan, arm):
    r = plan['runtime']
    return [r['server'],'-m',r['model'],'--host','127.0.0.1','--port','8091',
            '-c','8192','--no-context-shift','-ngl','99','-t','6','--parallel','1',
            '--cache-prompt' if arm['cache']=='on' else '--no-cache-prompt']


@contextmanager
def server(plan, arm, directory):
    # Fail closed on an occupied port. Never signal an existing user's server.
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        probe.bind(('127.0.0.1',8091))
    env = os.environ.copy()
    env = {k:v for k,v in env.items() if not k.startswith('LLAMA_ARG_')}
    env['LD_LIBRARY_PATH'] = plan['runtime']['libraries']
    directory.mkdir(parents=True,exist_ok=False)
    with (directory/'server.log').open('x') as log:
        process = subprocess.Popen(command(plan,arm),env=env,stdout=log,stderr=subprocess.STDOUT)
        started = time.perf_counter()
        try:
            opener = build_opener(ProxyHandler({}))
            while True:
                if process.poll() is not None: raise RuntimeError('Owned server failed to start')
                try:
                    with opener.open('http://127.0.0.1:8091/health',timeout=1) as response:
                        if json.load(response).get('status') == 'ok': break
                except OSError: pass
                if time.perf_counter()-started > 30: raise TimeoutError('Server readiness')
                time.sleep(.2)
            maps = Path(f'/proc/{process.pid}/maps').read_text()
            libraries = sorted({line.split()[-1] for line in maps.splitlines()
                                if '/' in line and any(s in line for s in ['libggml','libcuda','libcublas'])})
            write(directory/'runtime.json',{'pid':process.pid,'command':command(plan,arm),
                  'startup_seconds':time.perf_counter()-started,'loaded_libraries':libraries,
                  'library_sha256':{f:sha(f) for f in libraries if Path(f).is_file()}})
            yield
        finally:
            if process.poll() is None:
                process.send_signal(signal.SIGINT)
                try: process.wait(timeout=15)
                except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
            write(directory/'stopped.json',{'pid':process.pid,'returncode':process.returncode})


def summarize(plan, attempts):
    rows = []
    for arm in plan['arms']:
        details = []
        for case in plan['cases']:
            group = [a for a in attempts if a['arm']==arm['id'] and a['case']==case['id']]
            states = [a['decision']['state'] for a in group]
            outputs = [a['result']['output'] for a in group]
            fields = ['assertion','eligibility',*p.FIELDS,'evidence']
            details.append({'case':case['id'],'expected':case['expected'],'states':states,
                'raw_variants':len({a['result']['raw'] for a in group}),
                'structured_variants':len({digest(o) for o in outputs}),
                'changed_fields':[f for f in fields if len({digest(o.get(f) if isinstance(o,dict) else None) for o in outputs})>1],
                'state_variants':len(set(states)),
                'historical_states':[decision(case['request'],h['result'])['state'] for h in case['historical']]})
        selected = [a for a in attempts if a['arm']==arm['id']]
        rows.append({'arm':arm['id'],'calls':len(selected),'cases':details,
                     'structured_varying_cases':sum(d['structured_variants']>1 for d in details),
                     'state_varying_cases':sum(d['state_variants']>1 for d in details),
                     'states':dict(Counter(a['decision']['state'] for a in selected)),
                     'negative_support_calls':sum(d['states'].count('support') for d in details if d['expected']=='not_supported'),
                     'positive_support_calls':sum(d['states'].count('support') for d in details if d['expected']=='support'),
                     'inference_seconds':sum(a['result']['seconds'] for a in selected),
                     'cached_tokens':[((a['result']['usage'] or {}).get('prompt_tokens_details') or {}).get('cached_tokens') for a in selected]})
    return {'arms':rows,'fresh_calls':len(attempts),'quality_gate_passed':False,'agents':[],
            'decision_scope':'provisional_audit_only_not_full_support'}


def load_attempts(plan, directory):
    if read_json(directory/'started.json')['plan_sha256'] != sha(directory/'plan.json'):
        raise ValueError('Started plan changed')
    rows = []; cases = {c['id']:c for c in plan['cases']}
    for arm in plan['arms']:
        ad = directory/arm['id']
        if not (ad/'stopped.json').exists(): raise ValueError('Incomplete arm')
        expected = schedule(plan['cases'],arm['order'],plan['repeats'])
        if len(list(ad.glob('attempt-*.json'))) != len(expected): raise ValueError('Wrong attempt count')
        for seq,(cid,repeat) in enumerate(expected):
            row = read_json(ad/f'attempt-{seq:03}.json')
            body = row['attempt']
            if (digest(body)!=row['attempt_sha256'] or body['arm']!=arm['id'] or body['sequence']!=seq
                    or body['case']!=cid or body['repeat']!=repeat or body['request_sha256']!=digest(cases[cid]['request'])
                    or body['result_sha256']!=digest(body['result'])
                    or body['decision']!=decision(cases[cid]['request'],body['result'])):
                raise ValueError('Attempt changed')
            rows.append(body)
    return rows


def render(plan, report):
    esc = lambda v:html.escape(str(v),quote=True)
    page = ['<!doctype html><html lang="ko"><meta charset="utf-8"><title>새 추론 반복성 검증</title>',
            '<style>body{font:16px/1.6 system-ui;max-width:1100px;margin:auto;padding:24px}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style>',
            '<h1>새 추론 반복성 검증</h1><p>동일 요청 12개 × 3회 × 4설정. 판정 일관성은 의미 정확성이 아닙니다. 잠정 감사만 비교하며 새 agent 0개입니다.</p>']
    for arm in report['arms']:
        page.append('<h2>'+esc(arm['arm'])+'</h2><pre>'+esc(json.dumps(arm,ensure_ascii=False,indent=2))+'</pre>')
    for case in plan['cases']:
        page.append('<details><summary>'+esc(case['request']['data']['TARGET'])+'</summary><pre>'+esc(json.dumps(case,ensure_ascii=False,indent=2))+'</pre></details>')
    return '\n'.join(page+['</html>'])


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--run-dir',type=Path,required=True)
    ap.add_argument('--phase',choices=['plan','run','verify'],required=True)
    ap.add_argument('--diagnostic-only',action='store_true',required=True)
    args = ap.parse_args(); directory = args.run_dir
    if args.phase == 'plan':
        plan = make_plan(); write(directory/'plan.json',plan)
        print({'plan_sha256':sha(directory/'plan.json'),'calls':plan['max_calls']}); return
    plan = read_json(directory/'plan.json'); check_inputs(plan)
    if plan['arms']!=ARMS or plan['repeats']!=REPEATS or len(plan['cases'])!=12 or plan['max_calls']!=144:
        raise ValueError('Frozen protocol changed')
    for c in plan['cases']: source(c['request'])
    if args.phase == 'run':
        if (directory/'started.json').exists(): raise ValueError('Never resume an incomplete context history; use a new run directory')
        for kind in ['model','server']:
            if sha(plan['runtime'][kind])!=plan['runtime'][kind+'_sha256']: raise ValueError('Runtime changed')
        write(directory/'started.json',{'plan_sha256':sha(directory/'plan.json')})
        cases = {c['id']:c for c in plan['cases']}
        for arm in plan['arms']:
            with server(plan,arm,directory/arm['id']):
                for seq,(cid,repeat) in enumerate(schedule(plan['cases'],arm['order'],plan['repeats'])):
                    body = {'arm':arm['id'],'sequence':seq,'case':cid,'repeat':repeat,**fresh(cases[cid])}
                    write(directory/arm['id']/f'attempt-{seq:03}.json',{'attempt':body,'attempt_sha256':digest(body)})
                    print(arm['id'],seq+1,body['decision'],flush=True)
    attempts = load_attempts(plan,directory); report = summarize(plan,attempts)
    if args.phase == 'verify':
        if read_json(directory/'report.json') != report: raise ValueError('Report changed')
        print({'new_model_calls':0,'replayed_attempts':len(attempts),'report_sha256':sha(directory/'report.json')})
    else:
        write(directory/'report.json',report)
        with (directory/'overview.html').open('x') as f: f.write(render(plan,report))
        print({'fresh_calls':len(attempts),'report_sha256':sha(directory/'report.json')})


if __name__ == '__main__': main()
