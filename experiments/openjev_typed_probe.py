"""Separate, pre-frozen typed-routing check; not a rewrite of direct-NLI results."""
import argparse
import html
from importlib.metadata import version
import json
from pathlib import Path

from commentscope.factory.claim_clusters import read_json, sha
from commentscope.providers import local_nli, local_openjev, typed_routing as routing
from commentscope.storage import write_json_exclusive
from experiments.claim_support_probe import CachedScores
from experiments.openjev_probe import check_plan

CODE = ['experiments/openjev_typed_probe.py', 'src/commentscope/providers/typed_routing.py',
        'src/commentscope/providers/local_openjev.py', 'src/commentscope/providers/local_nli.py',
        'experiments/claim_support_probe.py', 'experiments/openjev_probe.py']
FIXTURE = 'tests/fixtures/evidence-unit-cases.json'


def summary(cases, traces):
    output = {}
    for split in ['development', 'transfer']:
        rows = [c for c in cases if c['split'] == split]
        r = lambda c: traces[c['id']]
        output[split] = {'positive_total': sum(c['expected'] for c in rows),
                         'negative_total': sum(not c['expected'] for c in rows),
                         'routing_positive_kept': sum(c['expected'] and r(c)['selected'] == 'substantive' for c in rows),
                         'routing_negative_correct': sum(not c['expected'] and r(c)['selected'] in ['non_substantive', 'context_dependent'] for c in rows),
                         'strict_positive_kept': sum(c['expected'] and r(c)['strict_eligible'] for c in rows),
                         'strict_negative_not_approved': sum(not c['expected'] and not r(c)['errors'] and not r(c)['strict_eligible'] for c in rows),
                         'errors': sum(bool(r(c)['errors']) for c in rows),
                         'unresolved_routes': sum(r(c)['selected'] is None for c in rows)}
    return output


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base-plan', type=Path, required=True)
    p.add_argument('--run-dir', type=Path, required=True)
    p.add_argument('--phase', choices=['plan', 'deberta', 'openjev', 'report', 'verify'], required=True)
    p.add_argument('--diagnostic-only', action='store_true', required=True)
    args = p.parse_args(); path = args.run_dir/'plan.json'
    base = read_json(args.base_plan); check_plan(base)
    if args.phase == 'plan':
        plan = {'artifact_kind': 'openjev-typed-routing-0.1', 'expires_at': base['expires_at'],
                'inputs': {str(args.base_plan): sha(args.base_plan), FIXTURE: sha(FIXTURE)},
                'code_sha256': {f: sha(f) for f in CODE}, 'models': base['models'],
                'cases': [{**c, 'task': 'eligibility', 'target': 'typed options'} for c in read_json(FIXTURE)['cases']],
                'hypotheses': routing.hypotheses(), 'independent_gold': False, 'quality_gate_passed': False,
                'policy': 'Routing=argmax of normalized entailment; strict=positive option share AND absolute entailment >=.8. Neither is service approval.',
                'limitations': ['Separate input formulation experiment; do not overwrite direct-NLI comparison',
                                'No hard prefilter, cluster approval, calibrated-confidence or commercial-Jev claim',
                                'Original labels fixed before any OpenJev outputs; DeBERTa direct-NLI failure already observed']}
        write_json_exclusive(path, plan); print({'cases':len(plan['cases']), 'requests_per_model':len(plan['cases'])*3}); return
    plan = read_json(path); check_plan(plan)
    if args.phase in ['deberta', 'openjev']:
        name = args.phase; directory = args.run_dir/name
        if (directory/'report.json').exists(): p.error('Completed output exists')
        manifest = {'expires_at': plan['expires_at'], 'plan_sha256': sha(path), 'model': plan['models'][name],
                    'runtime': {'torch': version('torch'), 'transformers': version('transformers'), 'device': 'cpu', 'dtype': 'float32', 'threads': 6}}
        model = None
        def score(a, b):
            nonlocal model
            if model is None:
                model = local_nli.LocalNLI() if name == 'deberta' else local_openjev.LocalOpenJev(device='cpu')
            return model.score(a, b)
        cached = CachedScores(directory, manifest, score)
        traces = {}
        for c in plan['cases']:
            traces[c['id']] = routing.combine({label: cached(c['source'], target) for label, target in plan['hypotheses'].items()})
            print(json.dumps({'case':c['id'], 'selected':traces[c['id']]['selected']}), flush=True)
        check_plan(plan)
        write_json_exclusive(directory/'report.json', {'manifest':manifest, 'traces':traces,
                             'summary':summary(plan['cases'], traces)})
    else:
        models = {n:read_json(args.run_dir/n/'report.json') for n in ['deberta', 'openjev']}
        for name, m in models.items():
            if m['manifest']['plan_sha256'] != sha(path) or m['manifest']['model'] != plan['models'][name]:
                raise ValueError('Model manifest changed')
            def forbidden(*unused): raise RuntimeError('Replay attempted inference')
            cached = CachedScores(args.run_dir/name,m['manifest'],forbidden)
            traces = {c['id']:routing.combine({label:cached(c['source'],t) for label,t in plan['hypotheses'].items()}) for c in plan['cases']}
            if traces != m['traces'] or summary(plan['cases'],traces) != m['summary']: raise ValueError('Replay changed')
        report = {**plan, 'results':models}
        if args.phase == 'verify':
            if read_json(args.run_dir/'report.json') != report: raise ValueError('Report changed')
            print({'verified':True, 'new_model_calls':0}); return
        write_json_exclusive(args.run_dir/'report.json',report)
        esc = lambda x:html.escape(str(x),quote=True)
        page = '<!doctype html><html lang="ko"><meta charset="utf-8"><title>OpenJev 사전 분류 비교</title><style>body{font:16px/1.7 system-ui;max-width:1000px;margin:auto;padding:20px}pre,blockquote{white-space:pre-wrap;overflow-wrap:anywhere}</style><h1>OpenJev 사전 분류 비교</h1><p>독립 gold/서비스 승인 아님. 상대 점수와 절대 지지를 구분합니다.</p>'
        for n,m in models.items():page += '<h2>'+esc(n)+'</h2><pre>'+esc(json.dumps(m['summary'],ensure_ascii=False,indent=2))+'</pre>'
        for c in plan['cases']:
            page += '<h2>'+esc(c['id'])+'</h2><blockquote>'+esc(c['source'])+'</blockquote><p>실질 주장 기대: '+esc(c['expected'])+'</p>'
            for n,m in models.items():
                t=m['traces'][c['id']]
                page += '<p>'+esc(n)+': '+esc(t['selected'])+' / strict '+esc(t['strict_eligible'])+'</p><pre>'+esc(json.dumps(t['option_scores']))+'</pre>'
        with (args.run_dir/'overview.html').open('x',encoding='utf-8') as f:f.write(page+'</html>')
        print(json.dumps({n:m['summary'] for n,m in models.items()}),flush=True)


if __name__ == '__main__':main()
