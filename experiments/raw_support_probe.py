"""Frozen raw candidate -> common claim -> source decisions diagnostic; never agents."""
import argparse
from collections import Counter
import html
import json
from pathlib import Path
import time

from commentscope.factory import raw_candidates, raw_support as support, grounded_core
from commentscope.factory.automatic import Calls, local_provider
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.ingestion import load_snapshot
from commentscope.providers.local_nli import LocalNLI, MODEL, REVISION, THRESHOLD
from commentscope.providers.raw_nli import score_full
from commentscope.providers.schema_visible import SchemaVisibleCalls
from commentscope.storage import write_json_exclusive
from experiments.claim_support_probe import CachedScores
from experiments.grounded_core_probe import check_inputs, no_model
from experiments import raw_candidates_probe as retrieval

RAW = Path('runs/raw-candidates-20261012')
REFERENCE = 'runs/openjev-comparison-20261012-cpu/plan.json'
FIXTURE = 'tests/fixtures/shared-core-transfer-cases.json'
CODE = ['experiments/raw_support_probe.py', 'src/commentscope/factory/raw_support.py',
        'src/commentscope/providers/raw_nli.py', 'src/commentscope/factory/grounded_core.py',
        'src/commentscope/factory/qualification_guards.py', 'src/commentscope/factory/shared_core.py',
        'src/commentscope/factory/automatic.py', 'src/commentscope/providers/schema_visible.py',
        'src/commentscope/providers/local_nli.py', 'src/commentscope/providers/local_llama.py',
        'src/commentscope/agents/runtime.py', 'experiments/claim_support_probe.py',
        'experiments/grounded_core_probe.py', *retrieval.CODE]
POLICY = {'pair_limit': 64, 'expansion_cores': 2, 'max_sources': 64, 'max_new_llm_calls': 900,
          'expansion_requires_no_fixed_false_accepts_or_errors': True, 'agents': False}


def source(sid, text):
    return {'source_id': sid, 'text': text, 'source_digest': digest(text)}


def make_plan():
    old = read_json(RAW/'plan.json'); retrieval.check(old)
    report = read_json(RAW/'report.json')
    if report['plan_sha256'] != sha(RAW/'plan.json') or report['registry'] != old['registry']:
        raise ValueError('Retrieval plan changed')
    vectors = read_json(RAW/'vectors.json'); retrieval.validate_vectors(vectors, retrieval.vector_contract(old))
    rebuilt = raw_candidates.build(old['registry'], vectors['vectors'], backend='numpy')
    if rebuilt != report['bundle'] or report['vectors_sha256'] != sha(RAW/'vectors.json'):
        raise ValueError('Retrieval replay changed')
    if len(old['registry']['sources']) > POLICY['max_sources']: raise ValueError('Diagnostic source limit')
    ref = read_json(REFERENCE)
    if ref['inputs'][old['snapshot']] != sha(old['snapshot']): raise ValueError('Reference snapshot changed')
    paths = [str(RAW/f) for f in ['plan.json', 'report.json', 'vectors.json']] + [REFERENCE, FIXTURE]
    model = read_json('runs/evidence-positions-20261012-gpu/plan.json')['model']
    return {'artifact_kind': 'raw-support-probe-0.1', 'expires_at': old['expires_at'],
            'inputs': {**old['inputs'], **{f: sha(f) for f in paths}},
            'code_sha256': {f: sha(f) for f in dict.fromkeys(CODE)}, 'model': model,
            'nli': {'model': MODEL, 'revision': REVISION, 'threshold': THRESHOLD,
                    'device': 'cpu', 'threads': 6, 'max_tokens': 512, 'language_scope': 'English only'},
            'snapshot': old['snapshot'], 'registry': old['registry'],
            'pairs': report['bundle']['queue']['pairs'],
            'exact_controls': [c for c in ref['cases'] if c['task'] == 'fidelity'],
            'pair_controls': read_json(FIXTURE)['cases'],
            'known_pairs_evaluation_only': old['reference_pairs_evaluation_only'],
            'policy': POLICY, 'quality_gate_passed': False, 'independent_gold': False,
            'criteria': 'Measure fixed positive retention and negative rejection separately from errors/deferred. No false accepts/errors before expanding up to two cores across this64-source pool. Always inspect every passing real pair before any agent work.',
            'limitations': ['Development controls, no independent gold or unseen corpus benchmark',
                           'One proposal per pair, one structural repair at most, no semantic retry',
                           'NLI/LLM agreement is fallible; no default promotion or agent approval',
                           'Only exact equal core strings merge; paraphrase duplicate groups unresolved',
                           'No collection, new model download, full1000 processing or paid API']}


def check_plan(plan):
    check_inputs(plan)
    if plan['policy'] != POLICY: raise ValueError('Policy changed')
    snapshot = load_snapshot(plan['snapshot']).snapshot
    if snapshot.usage.expires_at != plan['expires_at']: raise ValueError('Expiry changed')
    raw_candidates.validate_registry(plan['registry'], snapshot)
    old = read_json(RAW/'report.json')
    if plan['registry'] != old['registry'] or plan['pairs'] != old['bundle']['queue']['pairs']:
        raise ValueError('Frozen retrieval queue changed')


def metrics(rows, passing, error):
    return {'positive_total': sum(r['expected'] for r in rows),
            'positive_kept': sum(r['expected'] and passing(r) for r in rows),
            'negative_total': sum(not r['expected'] for r in rows),
            'negative_blocked': sum(not r['expected'] and not passing(r) and not error(r) for r in rows),
            'false_accepts': [r['id'] for r in rows if not r['expected'] and passing(r)],
            'false_rejections': [r['id'] for r in rows if r['expected'] and not passing(r)],
            'error_or_deferred': [r['id'] for r in rows if error(r)]}


def pair_error(trace):
    return trace['status'] in ('error', 'unchecked') or any(c['state'] in ('error', 'unchecked') for c in trace['checks'])


def may_expand(summaries):
    return all(not row['false_accepts'] and not row['error_or_deferred'] for row in summaries.values())


def assemble(registry, records, calls, scores, expand):
    groups = {}
    for record in records:
        trace = record['trace']; core = trace['selected_core']
        if not core: continue
        group = groups.setdefault(core, {})
        for decision in trace['checks']:
            sid = decision['source_id']
            if sid in group and group[sid] != decision: raise ValueError('Inconsistent same-source/core decision')
            group[sid] = decision
    result = []
    for i, (core, decisions) in enumerate(groups.items()):
        expanded = expand and i < POLICY['expansion_cores']
        if expanded:
            for s in registry['sources']:
                if s['source_id'] not in decisions:
                    decisions[s['source_id']] = support.check(s, core, calls, scores)
        result.append({**support.ledger(registry, core, list(decisions.values())), 'expanded': expanded})
    return result


def render(report):
    esc = lambda x: html.escape(str(x), quote=True)
    page = ['<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
            '<title>원문 기반 공통 주장과 지지 집계</title><style>body{font:16px/1.7 system-ui;max-width:1080px;margin:auto;padding:20px}pre,blockquote{white-space:pre-wrap;overflow-wrap:anywhere}article{border-top:1px solid #aaa}</style>',
            '<h1>원문 기반 공통 주장과 지지 집계</h1><p>모델 판정 개발 결과입니다. 품질 승인·전체 여론·agent가 아닙니다. 미검사는 비지지가 아닙니다.</p>',
            '<pre>'+esc(json.dumps(report['summary'], ensure_ascii=False, indent=2))+'</pre>']
    for group in report['ledgers']:
        page += ['<h2>'+esc(group['core'])+'</h2><pre>'+esc(json.dumps({k: group[k] for k in
                 ['counts', 'canonical_denominator', 'provisional_tier', 'expanded']}, ensure_ascii=False, indent=2))+'</pre>']
    sources = {s['source_id']: s['text'] for s in report['registry']['sources']}
    for row in report['records']:
        trace = row['trace']; page += ['<article><h2>'+esc(row['id'])+'</h2>']
        for sid in trace['source_ids']: page += ['<blockquote>'+esc(sources[sid])+'</blockquote>']
        page += ['<p>통과 주장: '+esc(trace['selected_core'])+'</p>',
                 '<details><summary>제안·원문별 판정</summary><pre>'+esc(json.dumps(trace, ensure_ascii=False, indent=2))+'</pre></details></article>']
    return '\n'.join(page+['</html>'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--phase', choices=['plan', 'run', 'verify'], required=True)
    parser.add_argument('--diagnostic-only', action='store_true', required=True)
    args = parser.parse_args(); directory = args.run_dir; path = directory/'plan.json'
    if args.phase == 'plan':
        plan = make_plan(); check_plan(plan); write_json_exclusive(path, plan)
        print({'exact_controls': len(plan['exact_controls']), 'pair_controls': len(plan['pair_controls']),
               'real_pairs': len(plan['pairs']), 'plan_sha256': sha(path)}); return
    plan = read_json(path); check_plan(plan); replay = args.phase == 'verify'
    if not replay and (directory/'report.json').exists(): parser.error('Completed output exists')
    started = time.perf_counter()
    prior_calls = len(list((directory/'llm').glob('call-*.json')))
    def provider(system, data, schema):
        if prior_calls + raw.new_calls >= POLICY['max_new_llm_calls']:
            raise RuntimeError('Hard total LLM budget reached')
        return local_provider(system, data, schema)
    raw = Calls(directory/'llm', plan, no_model if replay else provider)
    visible = SchemaVisibleCalls(raw, [support.PROPOSE, grounded_core.AUDIT_SYSTEM])
    def calls(system, data, schema):
        return visible(system, data, schema)
    model = None; new_scores = 0
    def score(a, b):
        nonlocal model, new_scores
        if model is None: model = LocalNLI()
        new_scores += 1
        return score_full(model, a, b)
    scores = CachedScores(directory/'nli', plan, no_model if replay else score)
    exact = []
    for c in plan['exact_controls']:
        decision = support.check(source(c['id'], c['source']), c['target'], calls, scores)
        exact.append({**c, 'decision': decision})
    controls = []
    for c in plan['pair_controls']:
        value = {'sources': [source(c['id']+':a', c['left']), source(c['id']+':b', c['right'])]}
        a, b = value['sources']
        pair = {'source_ids': [a['source_id'], b['source_id']],
                'pair_id': 'R'+digest([[s['source_id'], s['source_digest']] for s in [a,b]])[:20]}
        controls.append({**c, 'trace': support.discover(value, pair, calls, scores)})
    summaries = {split: metrics([r for r in exact if r['split'] == split],
                lambda r: r['decision']['state'] == 'support', lambda r: r['decision']['state'] in ('error','unchecked'))
                for split in sorted({r['split'] for r in exact})}
    summaries['pair_controls'] = metrics(controls, lambda r: bool(r['trace']['selected_core']), lambda r: pair_error(r['trace']))
    if not replay: print(json.dumps({'controls': summaries}), flush=True)
    control_seconds = time.perf_counter()-started
    records = []
    for pair in plan['pairs']:
        trace = support.discover(plan['registry'], pair, calls, scores)
        records.append({'id': pair['pair_id'], 'trace': trace})
        if not replay: print(json.dumps({'pair': pair['pair_id'], 'status': trace['status'], 'core': trace['selected_core']}), flush=True)
    discovery_seconds = time.perf_counter()-started-control_seconds
    expandable = may_expand(summaries)
    groups = assemble(plan['registry'], records, calls, scores, expandable)
    known = []
    by_pair = {tuple(sorted(r['trace']['source_ids'])): r['trace'] for r in records}
    for pair in plan['known_pairs_evaluation_only']:
        trace = by_pair.get(tuple(sorted(pair['source_ids'])))
        known.append({**pair, 'processed': trace is not None,
                      'selected_core': trace['selected_core'] if trace else None})
    summary = {'controls': summaries, 'pair_statuses': dict(Counter(r['trace']['status'] for r in records)),
               'known_pairs': known, 'expansion_gate_passed': expandable,
               'unique_exact_cores': len(groups), 'expanded_cores': sum(g['expanded'] for g in groups),
               'support_counts': [g['support_count'] for g in groups], 'agents': 0, 'quality_gate_passed': False}
    report = {'plan_sha256': sha(path), 'registry': plan['registry'], 'exact_controls': exact,
              'pair_controls': controls, 'records': records, 'ledgers': groups, 'summary': summary}
    check_plan(plan)
    if replay:
        if read_json(directory/'report.json') != report: raise ValueError('Support replay changed')
        print({'verified': True, 'new_llm_calls': raw.new_calls, 'new_nli_calls': new_scores}); return
    write_json_exclusive(directory/'report.json', report)
    measurements = {'control_seconds': control_seconds, 'discovery_seconds': discovery_seconds,
                    'total_until_report_seconds': time.perf_counter()-started, 'new_llm_calls': raw.new_calls,
                    'new_nli_calls': new_scores, 'nli_runtime': model.metadata if model else None,
                    'scope': 'Includes controls/cache IO/NLI loading; excludes GPU server startup, retrieval, collection and agent generation. Not service latency.'}
    write_json_exclusive(directory/'measurements.json', measurements)
    with (directory/'overview.html').open('x', encoding='utf-8') as f: f.write(render(report))
    print(json.dumps({'summary': summary, 'measurements': measurements}), flush=True)


if __name__ == '__main__': main()
