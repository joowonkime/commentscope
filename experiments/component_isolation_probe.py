"""Component intervention, not production: frozen spans/cores never reach runtime."""
import argparse
from collections import Counter
import html
import json
from pathlib import Path
import time

from commentscope.factory import positional_support as p, raw_support
from commentscope.factory.automatic import Calls, checked_call, local_provider
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.factory.shared_core import SCHEMA, validate_proposal, supported
from commentscope.providers.schema_visible import SchemaVisibleCalls
from commentscope.providers.local_nli import LocalNLI
from commentscope.providers.raw_nli import score_full
from commentscope.storage import write_json_exclusive
from experiments import positional_support_probe as previous
from experiments.raw_support_probe import source
from experiments.claim_support_probe import CachedScores
from experiments.grounded_core_probe import check_inputs, no_model

ORIGIN = Path('runs/positional-support-20261012')
CODE = [*previous.CODE, 'experiments/component_isolation_probe.py']


def bind_reference(sources, ranges):
    if len(sources) != 2 or len(ranges) != 2:
        raise ValueError('Exactly two source ranges required')
    spans = [p.bind(s['text'], r) for s, r in zip(sources, ranges)]
    if not all(spans):
        raise ValueError('Reference spans cannot be empty')
    return spans


def case_from(row, spec, registry, real):
    if real:
        sources = [registry[sid] for sid in row['trace']['source_ids']]
    else:
        sources = [source(row['id']+':'+side, row[key]) for side, key in [('a','left'), ('b','right')]]
    for s in sources:
        raw_support.validate_source(s)
    core = spec['reference_core']
    if not core or validate_proposal({'core': core}):
        raise ValueError('Invalid reference core')
    return {'id': row['id'], 'kind': 'real_development' if real else 'synthetic_development',
            'sources': sources, 'model_spans': row['trace'].get('aligned_spans'),
            'reference_spans': bind_reference(sources, spec['ranges']),
            'reference_core': core, 'reference_rationale': spec['rationale'],
            'reference_confidence': spec['confidence'],
            'reference_origin': 'assistant_predeclared_diagnostic_only',
            'historical_trace': row['trace']}


def make_plan(spec_path):
    old = read_json(ORIGIN/'plan.json'); check_inputs(old)
    report = read_json(ORIGIN/'report.json')
    if report['plan_sha256'] != sha(ORIGIN/'plan.json'):
        raise ValueError('Prior report binding changed')
    spec = read_json(spec_path)
    sources = {s['source_id']: s for s in report['registry']['sources']}
    pool = {r['id']: (r, False) for r in report['pair_controls'] if r['expected']}
    pool.update({r['id']: (r, True) for r in report['records']})
    if set(spec) != set(pool):
        raise ValueError('All six positive synthetic and three known real pairs required')
    cases = [case_from(row, spec[key], sources, real) for key, (row, real) in pool.items()]
    return {'artifact_kind': 'component-isolation-probe-0.1', 'expires_at': old['expires_at'],
            'inputs': {**old['inputs'], **{str(ORIGIN/f): sha(ORIGIN/f) for f in ['plan.json','report.json']},
                       str(spec_path): sha(spec_path)},
            'code_sha256': {f: sha(f) for f in dict.fromkeys(CODE)},
            'model': old['model'], 'nli': old['nli'], 'cases': cases,
            'stored_exact_controls': report['exact_controls'],
            'policy': {'max_llm_calls': 190, 'max_nli_calls': 190, 'agents': False, 'full_corpus': False},
            'criteria': 'Measure component failures without tuning; generated cores require separate source review. No promotion even if all diagnostic references pass.',
            'independent_gold': False, 'quality_gate_passed': False,
            'limitations': ['Reference spans/cores are assistant-selected interventions, not an automatic selector.',
                           'Known positive pairs only; negative safety is assessed separately on stored fixed decisions.',
                           'A compatible pair label does not certify every generated or reference core.',
                           'Repeated development data, shared sources, no independent accuracy estimate.']}


def proposal_inputs(case):
    """Only literal source text; diagnostic answers/labels cannot enter the proposal."""
    arms = {'full_source': [s['text'] for s in case['sources']]}
    for name, key in [('model_span', 'model_spans'), ('reference_span', 'reference_spans')]:
        spans = case[key]
        arms[name] = [s['text'] for s in spans] if spans and all(spans) else None
    return arms


def propose(texts, calls):
    if texts is None:
        return {'errors': [], 'output': {'core': ''}, 'attempts': [], 'status': 'no_alignment'}
    return checked_call(calls, raw_support.PROPOSE, {'LEFT': texts[0], 'RIGHT': texts[1]},
                        SCHEMA, validate_proposal)


def checks(sources, core, calls, scores):
    return [p.check(s, core, calls, scores) for s in sources] if core else []


def evaluate(case, calls, scores):
    generated = {}
    for arm, texts in proposal_inputs(case).items():
        value = propose(texts, calls)
        core = value['output']['core'] if not value['errors'] else ''
        generated[arm] = {'proposal': value, 'checks': checks(case['sources'], core, calls, scores)}
    core = case['reference_core']
    span_sources = [source(s['source_id'], span['text']) for s, span in zip(case['sources'], case['reference_spans'])]
    return {'id': case['id'], 'generated': generated,
            'fixed_reference': {'full_source': checks(case['sources'], core, calls, scores),
                                'reference_span': checks(span_sources, core, calls, scores)}}


def pair_pass(rows):
    return len(rows) == 2 and all(r['state'] == 'support' for r in rows)


def stored_ablation(rows):
    result = {}
    for split in sorted({r['split'] for r in rows}):
        group = [r for r in rows if r['split'] == split]
        def tally(pass_fn):
            return {'positive_total': sum(r['expected'] for r in group),
                    'positive_kept': sum(r['expected'] and pass_fn(r['decision']) for r in group),
                    'negative_total': sum(not r['expected'] for r in group),
                    'false_accepts': [r['id'] for r in group if not r['expected'] and pass_fn(r['decision'])]}
        result[split] = {
            'nli_only_counterfactual': tally(lambda d: bool(d['nli']) and supported(d['nli'])),
            'full_pipeline': tally(lambda d: d['state'] == 'support'),
            'non_support_reasons': dict(Counter(r['decision']['reason'] for r in group if r['decision']['state'] != 'support'))}
    return result


def summarize(records):
    return {'pairs': len(records),
            'generated_model_pair_passes': {arm: sum(pair_pass(r['generated'][arm]['checks']) for r in records)
                                           for arm in ['full_source','model_span','reference_span']},
            'fixed_reference_model_pair_passes': {arm: sum(pair_pass(r['fixed_reference'][arm]) for r in records)
                                                 for arm in ['full_source','reference_span']},
            'agents': 0, 'quality_gate_passed': False,
            'warning': 'Model agreement is not source-faithful generation quality; assistant review is separate.'}


def render(plan, report):
    esc = lambda x: html.escape(str(x), quote=True)
    page = ['<!doctype html><html lang="ko"><meta charset="utf-8"><title>논점 생성 단계 분리 진단</title>',
            '<style>body{font:16px/1.6 system-ui;max-width:1100px;margin:auto;padding:24px}pre,blockquote{white-space:pre-wrap;overflow-wrap:anywhere}article{border-top:1px solid #aaa}</style>',
            '<h1>논점 생성 단계 분리 진단</h1><p>미리 고른 근거와 기준 주장을 넣은 개발 진단입니다. 자동 서비스 성과나 독립 gold가 아닙니다.</p>',
            '<pre>'+esc(json.dumps(report['summary'], ensure_ascii=False, indent=2))+'</pre>']
    for case, row in zip(plan['cases'], report['records']):
        page.append('<article><h2>'+esc(case['id'])+'</h2>')
        for s in case['sources']:
            page.append('<blockquote>'+esc(s['text'])+'</blockquote>')
        page.append('<p>진단 기준 주장: '+esc(case['reference_core'])+'</p>')
        for arm, value in row['generated'].items():
            page.append('<h3>'+esc(arm)+'</h3><p>'+esc(value['proposal'].get('output'))+'</p><p>'+
                        esc([(x['state'],x['reason']) for x in value['checks']])+'</p>')
        page.append('<details><summary>고정 기준 주장과 전체 trace</summary><pre>'+
                    esc(json.dumps(row, ensure_ascii=False, indent=2))+'</pre></details></article>')
    return '\n'.join(page+['</html>'])


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--run-dir', type=Path, required=True)
    ap.add_argument('--phase', choices=['plan','run','verify'], required=True)
    ap.add_argument('--spec', type=Path)
    ap.add_argument('--diagnostic-only', action='store_true', required=True)
    args = ap.parse_args(); directory = args.run_dir; path = directory/'plan.json'
    if args.phase == 'plan':
        if not args.spec: ap.error('--spec is required for plan')
        plan = make_plan(args.spec); check_inputs(plan); write_json_exclusive(path, plan)
        print({'pairs':len(plan['cases']), 'plan_sha256':sha(path)}); return
    plan = read_json(path); check_inputs(plan); replay = args.phase == 'verify'
    if not replay and (directory/'report.json').exists(): ap.error('Completed output exists')
    start = time.perf_counter()
    prior_llm = len(list((directory/'llm').glob('call-*.json')))
    prior_nli = len(list((directory/'nli').glob('score-*.json')))
    def provider(*args):
        if prior_llm+raw.new_calls >= plan['policy']['max_llm_calls']: raise RuntimeError('LLM budget')
        return local_provider(*args)
    raw = Calls(directory/'llm', plan, no_model if replay else provider)
    calls = SchemaVisibleCalls(raw, [p.AUDIT, raw_support.PROPOSE])
    model = None; new_nli = 0
    def score(a,b):
        nonlocal model,new_nli
        if prior_nli+new_nli >= plan['policy']['max_nli_calls']: raise RuntimeError('NLI budget')
        if model is None: model = LocalNLI()
        new_nli += 1
        return score_full(model,a,b)
    scores = CachedScores(directory/'nli', plan, no_model if replay else score)
    records = []
    for case in plan['cases']:
        row = evaluate(case,calls,scores); records.append(row)
        if not replay: print(json.dumps({'case':case['id'],'summary':summarize([row])}),flush=True)
    report = {'plan_sha256':sha(path), 'records':records, 'summary':summarize(records),
              'stored_ablation':stored_ablation(plan['stored_exact_controls'])}
    check_inputs(plan)
    if replay:
        if read_json(directory/'report.json') != report: raise ValueError('Replay changed')
        print({'verified':True,'new_llm_calls':raw.new_calls,'new_nli_calls':new_nli}); return
    write_json_exclusive(directory/'report.json', report)
    write_json_exclusive(directory/'measurements.json', {'total_seconds':time.perf_counter()-start,
                         'new_llm_calls':raw.new_calls,'new_nli_calls':new_nli,
                         'nli_runtime':model.metadata if model else None,'scope':'Component diagnostic, not service latency'})
    with (directory/'overview.html').open('x',encoding='utf-8') as f: f.write(render(plan,report))
    print(json.dumps(report['summary']),flush=True)


if __name__ == '__main__': main()

