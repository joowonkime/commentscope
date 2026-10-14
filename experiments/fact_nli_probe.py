"""Bounded NLI and unanimous cross-model comparison on the unchanged 40 cases."""
import argparse
from collections import Counter
import json
from pathlib import Path

from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.providers import evidence_nli as nli
from commentscope.providers.local_nli import MODEL, REVISION, THRESHOLD, decide
from commentscope.providers.budget import InferenceBudget
from commentscope.storage import write_json_exclusive as write
from experiments import fact_evidence_probe as base, fact_gate_probe as gate

VERSION = 'fact-nli-comparison-0.1'
MODEL_DIRECTORY = Path('/home/taeng/.cache/huggingface/hub/models--MoritzLaurer--DeBERTa-v3-base-mnli-fever-anli/snapshots')/REVISION


def prepare(directory, source_directory):
    if directory.exists(): raise ValueError('Never overwrite an attempt')
    gate.verify(source_directory)
    source = read_json(source_directory/'plan.json')
    request = {'system': nli.VERSION, 'schema': {}, 'max_tokens': 1,
               'data': {'cases': [{'id': r['id'], 'text': r['claim']['text'],
                                  'evidence': [{'id': e['id'], 'text': e['text']} for e in r['packet']['evidence']]}
                                 for r in source['rows']]}}
    plan = {'artifact_kind': VERSION, 'expires_at': source['expires_at'], 'source_directory': str(source_directory),
            'request': request, 'request_sha256': digest(request),
            'model': {'name': MODEL, 'revision': REVISION, 'threshold': THRESHOLD, 'device': 'cpu'},
            'inputs': {str(source_directory/p): sha(source_directory/p) for p in ['plan.json', 'completed.json', 'report.json']},
            'model_sha256': {str(p): sha(p) for p in sorted(MODEL_DIRECTORY.iterdir()) if p.is_file()},
            'code_sha256': {str(p): sha(p) for root in ['src/commentscope', 'experiments'] for p in sorted(Path(root).rglob('*.py'))},
            'budget': {'cycle_id': base.CYCLE, 'timeout_seconds': 240, 'batches': 1, 'forward_pairs': 110},
            'criteria': source['criteria'], 'scope': source['scope'], 'quality_gate_passed': False,
            'independent_gold': False, 'combination': 'Matching verdicts only; disagreement becomes insufficient. Errors never count as correct rejection.'}
    write(directory/'plan.json', plan)
    print({'prepared': True, 'cases': 40, 'pairs': 110, 'plan_sha256': sha(directory/'plan.json')}, flush=True)


def validate(plan):
    from commentscope.factory.fact_checks import live
    live(plan['expires_at'])
    if plan['artifact_kind'] != VERSION or digest(plan['request']) != plan['request_sha256']:
        raise ValueError('Plan changed')
    for field in ['inputs', 'model_sha256', 'code_sha256']:
        if any(sha(p) != h for p, h in plan[field].items()): raise ValueError('Frozen identity changed')


def summarize(plan, result):
    source = read_json(Path(plan['source_directory'])/'plan.json')
    old = read_json(Path(plan['source_directory'])/'report.json')
    lookup = {r['id']: r for r in result['results']}
    baseline = {r['id']: r['actual'] for r in old['rows']}
    if set(lookup) != {r['id'] for r in source['rows']} or len(result['results']) != 40:
        raise ValueError('Case inventory changed')
    for case in plan['request']['data']['cases']:
        row = lookup[case['id']]
        if [p['id'] for p in row['pairs']] != [p['id'] for p in case['evidence']]: raise ValueError('Evidence inventory changed')
        for pair in row['pairs']:
            if not pair['errors'] and pair['relation'] != decide(pair['scores'], THRESHOLD): raise ValueError('NLI decision changed')
        if any(row[k] != value for k, value in nli.aggregate(row['pairs']).items()): raise ValueError('Evidence aggregation changed')
    variants = {}
    for name in ['nli_only', 'unanimous_llm_nli']:
        rows = [{'id': r['id'], 'expected': r['expected'],
                 'actual': lookup[r['id']]['state'] if name == 'nli_only' else nli.unanimous(baseline[r['id']], lookup[r['id']]['state'])}
                for r in source['rows']]
        false_support = sum(r['expected'] != 'supported' and r['actual'] == 'supported' for r in rows)
        kept = sum(r['expected'] == 'supported' and r['actual'] == 'supported' for r in rows)
        errors = sum(r['actual'] in {'error', 'unassessed'} for r in rows)
        variants[name] = {'rows': rows, 'unsupported_false_support': false_support, 'supported_kept': kept, 'errors': errors,
                          'development_gate_passed': false_support == 0 and kept >= 8 and errors == 0,
                          'by_reference': {state: dict(Counter(r['actual'] for r in rows if r['expected'] == state))
                                           for state in ['supported', 'refuted', 'conflicting', 'insufficient']}}
    return {'variants': variants, 'forward_pairs': result['forward_pairs'], 'metadata': result['metadata'],
            'scope': plan['scope'], 'quality_gate_passed': False, 'independent_gold': False, 'agents': []}


def execute(directory):
    plan = read_json(directory/'plan.json'); validate(plan)
    budget = InferenceBudget(base.DEFAULT_BUDGET, base.CYCLE)
    write(directory/'started.json', {'plan_sha256': sha(directory/'plan.json'), 'budget_before': budget.summary()})
    result = budget.call(plan['request'], sha(directory/'plan.json'), timeout_seconds=plan['budget']['timeout_seconds'], provider=nli.generate)
    write(directory/'result.json', result)
    report = summarize(plan, result); report['budget_after'] = budget.summary()
    write(directory/'report.json', report)
    write(directory/'completed.json', {'plan_sha256': sha(directory/'plan.json'), 'report_sha256': sha(directory/'report.json'), 'result_sha256': sha(directory/'result.json')})
    print(json.dumps({name: {k: v for k, v in variant.items() if k != 'rows'} for name, variant in report['variants'].items()}, indent=2))


def verify(directory):
    plan = read_json(directory/'plan.json'); validate(plan)
    if read_json(directory/'completed.json') != {'plan_sha256': sha(directory/'plan.json'), 'report_sha256': sha(directory/'report.json'), 'result_sha256': sha(directory/'result.json')}:
        raise ValueError('Completed artifact changed')
    report = read_json(directory/'report.json')
    if any(report[k] != v for k, v in summarize(plan, read_json(directory/'result.json')).items()): raise ValueError('Report does not replay')
    print({'verified': True, 'new_model_calls': 0, 'cases': 40})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--source-dir', type=Path, default=Path('runs/fact-gate-40-20261013'))
    parser.add_argument('--phase', choices=['prepare', 'run', 'verify'], required=True)
    args = parser.parse_args()
    if args.phase == 'prepare': prepare(args.run_dir, args.source_dir)
    elif args.phase == 'run': execute(args.run_dir)
    else: verify(args.run_dir)


if __name__ == '__main__': main()
