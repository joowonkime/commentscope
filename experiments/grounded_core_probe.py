"""Staged diagnostic: retrieval ablation, exact fidelity, pairs, then bounded assembly.

Private artifacts only; default factory and quality approval remain unchanged.
"""
import argparse
import html
import json
from importlib.metadata import version
from pathlib import Path

from commentscope.agents.profiles import require_live
from commentscope.factory import candidate_search, grounded_core, core_groups
from commentscope.factory.automatic import Calls, build_bundle, local_provider
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.ingestion import load_snapshot
from commentscope.providers.local_nli import LocalNLI, MODEL, REVISION, THRESHOLD
from commentscope.storage import write_json_exclusive
from experiments.claim_frame_probe import prepare_cases, unit
from experiments.claim_support_probe import CachedScores
from experiments.shared_core_integration import profiles

CODE = [__file__, 'src/commentscope/factory/candidate_search.py', 'src/commentscope/factory/grounded_core.py',
        'src/commentscope/factory/core_groups.py', 'src/commentscope/factory/shared_core.py',
        'src/commentscope/factory/automatic.py', 'src/commentscope/factory/automatic_contract.py',
        'src/commentscope/providers/local_nli.py', 'src/commentscope/providers/local_llama.py',
        'src/commentscope/agents/runtime.py', 'experiments/claim_frame_probe.py',
        'experiments/claim_support_probe.py', 'experiments/shared_core_integration.py']
FIXTURES = ['tests/fixtures/claim-frame-cases.json', 'tests/fixtures/shared-core-transfer-cases.json',
            'tests/fixtures/core-fidelity-cases.json']


def no_model(*args):
    raise RuntimeError('Read-only replay cannot call a model')


def vectors_for(report_path, report):
    path = Path(report_path).parent/'embeddings.json'
    stored = read_json(path)
    if (stored['texts'] != [u['statement'] for u in report['units']] or
            stored['vectors_sha256'] != digest(stored['vectors'])):
        raise ValueError('Embedding inputs or vectors changed')
    return stored['vectors']


def summary(rows, decision):
    return {'positive_total': sum(r['expected'] for r in rows),
            'positive_kept': sum(bool(r['expected'] and decision(r)) for r in rows),
            'negative_total': sum(not r['expected'] for r in rows),
            'negative_blocked': sum(bool(not r['expected'] and not decision(r)) for r in rows),
            'false_acceptance_ids': [r['id'] for r in rows if not r['expected'] and decision(r)],
            'false_rejection_ids': [r['id'] for r in rows if r['expected'] and not decision(r)]}


def render(report, title):
    esc = lambda x: html.escape(str(x), quote=True)
    parts = ['<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
             '<title>'+esc(title)+'</title><style>body{font:16px/1.6 system-ui;max-width:1100px;margin:auto;padding:20px}pre,blockquote{white-space:pre-wrap;overflow-wrap:anywhere}article{border-top:1px solid #aaa}</style>',
             '<h1>'+esc(title)+'</h1><p>개발 진단용. 자동 결과와 사후 평가를 구분하며 정식 품질 승인이나 독립 gold가 아닙니다.</p>',
             '<pre>'+esc(json.dumps(report['summary'], ensure_ascii=False, indent=2))+'</pre>']
    for row in report.get('results', []):
        parts.append('<article><h2>'+esc(row['id'])+'</h2>')
        for k in ['anchor', 'member']:
            if k in row:
                parts.append('<blockquote>'+esc(grounded_core.source(row[k]))+'</blockquote><p>'+esc(row[k]['statement'])+'</p>')
        if 'source' in row:
            parts.append('<blockquote>'+esc(row['source'])+'</blockquote><p>'+esc(row['target'])+'</p>')
        parts.append('<p>기대: '+esc(row['expected'])+' / 결과: '+esc(row['trace'].get('selected_core', row['trace'].get('allowed')))+'</p>')
        parts.append('<details><summary>추적 기록</summary><pre>'+esc(json.dumps(row['trace'], ensure_ascii=False, indent=2))+'</pre></details></article>')
    for profile in report.get('profiles', []):
        parts.append('<article><h2>'+esc(profile['title'])+'</h2>')
        for e in profile['evidence']:
            parts.append('<blockquote>'+esc(e['original_text'])+'</blockquote><p>'+esc(e['allowed_claim'])+'</p>')
        parts.append('</article>')
    return '\n'.join(parts+['</html>'])


def check_inputs(manifest):
    require_live(manifest['expires_at'])
    for field in ('inputs', 'code_sha256'):
        if any(sha(p) != expected for p, expected in manifest[field].items()):
            raise ValueError('Frozen inputs or implementation changed')


def save(directory, name, report):
    check_inputs(report)
    write_json_exclusive(directory/(name+'.json'), report)
    with (directory/(name+'.html')).open('x', encoding='utf-8') as f:
        f.write(render(report, name))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['snapshot', 'baseline64', 'baseline_full', 'reference_evaluation']:
        parser.add_argument(name)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--phase', choices=['probe', 'integrate', 'verify'], required=True)
    parser.add_argument('--diagnostic-only', action='store_true', required=True)
    args = parser.parse_args()
    baseline = read_json(args.baseline64)
    build_bundle(args.snapshot, baseline)
    if baseline['artifact_kind'] != 'automatic-factory-0.2' or baseline['summary']['selected_sources'] > 64:
        parser.error('Only the source-isolated <=64-source diagnostic is supported')
    full, cases = prepare_cases(args.snapshot, args.baseline_full, args.reference_evaluation, FIXTURES[0])
    for c in read_json(FIXTURES[1])['cases']:
        cases.append({'id': c['id'], 'kind': 'transfer_development', 'expected': c['expected'],
                      'anchor': unit(c['id']+':a', c['left'], c.get('left_claim', c['left'])),
                      'member': unit(c['id']+':b', c['right'], c.get('right_claim', c['right']))})
    exact = read_json(FIXTURES[2])['cases']
    manifest = {'artifact_kind': 'grounded-core-diagnostic-0.1', 'expires_at': baseline['expires_at'],
                'inputs': {p: sha(p) for p in [args.snapshot, args.baseline64, args.baseline_full, args.reference_evaluation,
                                              *FIXTURES, str(Path(args.baseline64).parent/'embeddings.json'),
                                              str(Path(args.baseline_full).parent/'embeddings.json')]},
                'code_sha256': {p: sha(p) for p in CODE}, 'model': baseline['model'],
                'nli': {'model': MODEL, 'revision': REVISION, 'threshold': THRESHOLD},
                'runtime': {'torch': version('torch'), 'transformers': version('transformers'),
                            'device': 'cpu', 'threads': 6, 'temperature': 0, 'seed': 407, 'max_tokens': 900},
                'prompts': {'proposal': digest(grounded_core.PROPOSE_SYSTEM), 'audit': digest(grounded_core.AUDIT_SYSTEM)},
                'assembly_policy': {'budget': 64, 'seed_limit': 2, 'max_chars': 10000, 'cross_mode': True},
                'quality_gate_passed': False, 'human_handling': False, 'independent_gold': False,
                'protocol': 'Unchanged pair labels scored separately from exact-target fidelity. Bounded integration is diagnostic even if regressions fail; no default promotion or full1000 run.',
                'promotion': 'Requires no critical false acceptance in fixed checks, exact-core review, unused real evaluation and source-faithful agent answers; pair compatibility alone is insufficient.'}
    require_live(manifest['expires_at'])
    if args.phase == 'verify' and (not (args.run_dir/'llm'/'manifest.json').exists() or
                                 not (args.run_dir/'nli'/'manifest.json').exists()):
        parser.error('Replay requires existing checkpoints')
    calls = Calls(args.run_dir/'llm', manifest, no_model if args.phase == 'verify' else local_provider)
    model = None
    def score(a, b):
        nonlocal model
        if model is None: model = LocalNLI()
        return model.score(a, b)
    scores = CachedScores(args.run_dir/'nli', manifest, no_model if args.phase == 'verify' else score)
    candidates = candidate_search.search(baseline['units'], vectors_for(args.baseline64, baseline))
    if args.phase == 'probe':
        if (args.run_dir/'probe.json').exists(): parser.error('Completed probe exists')
        retrieval = {}
        # Same unit/embedding inputs in all ablations. Known pairs are evaluated in a
        # separate fixed distractor pool; not described as corpus-wide retrieval recall.
        full_vectors = dict(zip([u['claim_id'] for u in full['units']], vectors_for(args.baseline_full, full)))
        eval_units = {u['claim_id']: u for c in cases if c['kind'] == 'real_development' for u in (c['anchor'], c['member'])}
        eval_vectors = {u['claim_id']: v for u, v in zip(baseline['units'], vectors_for(args.baseline64, baseline))}
        # Shared IDs may contain revised0.2 claims: choose the exact full-report units for controls.
        pool = {u['claim_id']: u for u in baseline['units']}
        pool.update(eval_units)
        eval_vectors.update({uid: full_vectors[uid] for uid in eval_units})
        pool = list(pool.values())
        known = [c for c in cases if c['kind'] == 'real_development' and c['expected'] and
                 c['anchor']['source_comment_id'] != c['member']['source_comment_id']]
        for policy in candidate_search.POLICIES:
            links = candidate_search.search(baseline['units'], vectors_for(args.baseline64, baseline), policy)
            control = candidate_search.search(pool, [eval_vectors[u['claim_id']] for u in pool], policy)
            found = lambda c: any(r['claim_id'] == c['member']['claim_id'] for r in control[c['anchor']['claim_id']])
            retrieval[policy] = {**candidate_search.funnel(baseline['units'], links),
                                 'known_cross_source_total': len(known), 'known_cross_source_found': sum(found(c) for c in known),
                                 'missed_ids': [c['id'] for c in known if not found(c)], 'control_pool_claims': len(pool)}
        write_json_exclusive(args.run_dir/'retrieval.json', {**manifest, 'summary': retrieval, 'candidates': candidates})
        print(json.dumps({'retrieval': retrieval}), flush=True)
        rows = []
        for c in exact:
            trace = grounded_core.verify(c['source'], c['target'], calls, scores)
            rows.append({**c, 'kind': 'exact_target', 'trace': trace})
            print(json.dumps({'exact': c['id'], 'allowed': trace['allowed']}), flush=True)
        for c in cases:
            trace = grounded_core.discover(c['anchor'], c['member'], calls, scores)
            rows.append({**c, 'trace': trace})
            print(json.dumps({'case': c['id'], 'core': trace['selected_core']}), flush=True)
        summaries = {'retrieval': retrieval}
        for kind in ['exact_target', 'synthetic', 'real_development', 'transfer_development']:
            summaries[kind] = summary([r for r in rows if r['kind'] == kind],
                                      lambda r: r['trace'].get('allowed', bool(r['trace'].get('selected_core'))))
        summaries['real_nonself'] = summary([r for r in rows if r['kind'] == 'real_development' and
                                              r['anchor']['claim_id'] != r['member']['claim_id']],
                                             lambda r: bool(r['trace']['selected_core']))
        save(args.run_dir, 'probe', {**manifest, 'summary': summaries, 'results': rows,
                                    'new_llm_calls': calls.new_calls, 'unique_nli_requests': len(scores.records)})
        print(json.dumps(summaries), flush=True)
    else:
        def discover(a, b):
            result = grounded_core.discover(a, b, calls, scores)
            if args.phase != 'verify': print(json.dumps({'seed': a['claim_id'], 'core': result['selected_core']}), flush=True)
            return result
        def attach(u, core):
            prepared = grounded_core.prepare(u, calls, scores)
            return {'prepared': prepared, **grounded_core.check_core(u, prepared, core, calls, scores)}
        if args.phase == 'verify':
            report = read_json(args.run_dir/'probe.json')
            if any(report.get(k) != v for k, v in manifest.items()): raise ValueError('Probe manifest changed')
            expected_cases = [{**c, 'kind': 'exact_target'} for c in exact]+cases
            if [{k: v for k, v in c.items() if k != 'trace'} for c in report['results']] != expected_cases:
                raise ValueError('Probe case inventory changed')
            for c in report['results']:
                trace = (grounded_core.verify(c['source'], c['target'], calls, scores) if c['kind'] == 'exact_target'
                         else grounded_core.discover(c['anchor'], c['member'], calls, scores))
                if trace != c['trace']: raise ValueError('Probe replay changed')
            if (args.run_dir/'integration.json').exists():
                stored = read_json(args.run_dir/'integration.json')
                if any(stored.get(k) != v for k, v in manifest.items()): raise ValueError('Integration manifest changed')
                core_groups.replay(baseline['units'], candidates, stored['assembly'], discover, attach)
                snapshot = load_snapshot(args.snapshot).snapshot
                if profiles(snapshot, baseline['units'], stored['assembly']) != stored['profiles']:
                    raise ValueError('Profile replay changed')
            check_inputs(manifest)
            print(json.dumps({'replayed_cases': len(report['results']), 'new_model_calls': calls.new_calls}), flush=True)
            return
        if not (args.run_dir/'probe.json').exists(): parser.error('Run the fixed probe first')
        if (args.run_dir/'integration.json').exists(): parser.error('Completed integration exists')
        assembly = core_groups.assemble(baseline['units'], candidates, discover, attach, **manifest['assembly_policy'])
        calls.provider = no_model; scores.score = no_model
        core_groups.replay(baseline['units'], candidates, assembly, discover, attach)
        agents = profiles(load_snapshot(args.snapshot).snapshot, baseline['units'], assembly)
        result = {**manifest, 'assembly': assembly, 'profiles': agents,
                  'summary': {'sources': baseline['summary']['selected_sources'], 'claims': len(baseline['units']),
                              'decisions': len(assembly['decisions']), 'agents': len(agents),
                              'represented_sources': len({e['source_comment_id'] for a in agents for e in a['evidence']}),
                              'unassigned_claims': len(assembly['unassigned_ids']), 'budget_exhausted': assembly['budget_exhausted']},
                  'new_llm_calls': calls.new_calls, 'unique_nli_requests': len(scores.records)}
        save(args.run_dir, 'integration', result)
        print(json.dumps(result['summary']), flush=True)


if __name__ == '__main__': main()
