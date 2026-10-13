"""Frozen whole-corpus retrieval component test, NOT a fresh product run.

Every previous nominated core is included, regardless of its outcome. Historical
membership decisions are read only for post-inference comparison, never ranking.
New embedding/NLI calls use the existing cumulative ledger, with no LLM server.
"""
import argparse
from pathlib import Path
import time

from commentscope.cluster_baseline import MODEL, REVISION
from commentscope.factory import source_index, support_retrieval
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.factory.fact_checks import live
from commentscope.ingestion import load_snapshot, normalize_snapshot
from commentscope.providers import fresh_embedding, target_ranking_nli
from commentscope.providers.budget import InferenceBudget
from commentscope.storage import write_json_exclusive as write
from experiments.fresh_grounded_pipeline import Runner
from experiments.scoped_discovery_probe import code_hashes

VERSION = 'whole-corpus-support-component-0.1'


def union(directory, source):
    """Deterministic nomination replay; no new inference or quality approval."""
    if directory.exists(): raise ValueError('Never overwrite a replay')
    prior = read_json(source/'plan.json'); live(prior['expires_at'])
    completed = read_json(source/'completed.json'); baseline = Path(prior['source'])
    if (prior['artifact_kind'] != VERSION or completed['plan_sha256'] != sha(source/'plan.json')
            or completed['retrieval_sha256'] != sha(source/'retrieval.json')):
        raise ValueError('Completed retrieval binding changed')
    if any(sha(p) != h for p, h in prior['inputs'].items()): raise ValueError('Baseline inputs changed')
    files = [source/n for n in ('plan.json', 'retrieval.json', 'completed.json')]
    plan = {'artifact_kind': support_retrieval.UNION_VERSION, 'source': str(source),
            'inputs': {str(p): sha(p) for p in files}, 'code_sha256': code_hashes(),
            'new_inference_calls': 0, 'fresh_analysis': False, 'quality_gate_passed': False}
    write(directory/'plan.json', plan)
    populations = read_json(baseline/'core-populations.json')
    proposals = [p for values in populations['proposals'].values() for p in values]
    merged = support_retrieval.union_nominations(proposals, read_json(source/'retrieval.json'))
    write(directory/'nominations.json', merged)
    lookup = {p['id']: p for p in merged['proposals']}
    # Every original is retained, regardless of positive/negative/unknown labels.
    assert all(p['sources'].items() <= lookup[p['id']]['sources'].items() for p in proposals)
    historical = read_json(baseline/'core-verdicts.json'); positive = retained = 0
    for family, rows in populations['rows'].items():
        for row in rows:
            if historical[family][row['id']] == 'supported':
                positive += 1
                retained += row['source_id'] in lookup[row['candidate_id']]['sources']
    from commentscope.factory.automatic_contract import digest
    unique = {(digest(p['claims']['C']), sid) for p in merged['proposals'] for sid in p['sources']}
    report = {'artifact_kind': support_retrieval.UNION_VERSION, 'plan_sha256': sha(directory/'plan.json'),
              'candidates': len(proposals), 'prior_nominations': sum(len(p['sources']) for p in proposals),
              'union_nominations': sum(len(p['sources']) for p in merged['proposals']),
              'unique_core_source_pairs': len(unique), 'max_sources_per_candidate': max(len(p['sources']) for p in merged['proposals']),
              'historical_model_supported': positive, 'historical_supported_retained': retained,
              'nominations_sha256': sha(directory/'nominations.json'), 'new_inference_calls': 0,
              'fresh_analysis': False, 'quality_gate_passed': False, 'semantic_membership_executed': False}
    write(directory/'completed.json', report); print(report, flush=True)


def prepare(directory, source):
    if directory.exists(): raise ValueError('Never overwrite a component attempt')
    old = read_json(source/'plan.json'); live(old['expires_at'])
    if old['artifact_kind'] != 'fresh-product-graph-pipeline-0.2':
        raise ValueError('Explicit known baseline required')
    files = [source/name for name in ('plan.json', 'source-analysis.json', 'unit-candidates.json',
             'core-populations.json', 'core-verdicts.json', 'review.json')]
    files.append(Path(old['snapshot']))
    populations = read_json(source/'core-populations.json')['proposals']
    proposals = [p for values in populations.values() for p in values]
    if len(proposals) > support_retrieval.LIMITS['candidates']: raise ValueError('Candidate capacity')
    plan = {'artifact_kind': VERSION, 'source': str(source), 'snapshot': old['snapshot'],
            'expires_at': old['expires_at'], 'inputs': {str(p): sha(p) for p in files},
            'code_sha256': code_hashes(), 'model_files': old['model_files'], 'budget': old['budget'],
            'limits': {'analysis_seconds': 900, 'call_seconds': 300},
            'retrieval_limits': support_retrieval.LIMITS.copy(), 'candidate_ids': [p['id'] for p in proposals],
            'metrics': ['all_candidate_source_counts', 'new_sources_outside_discovery',
                        'historical_model_supported_pairs_retained_not_accuracy',
                        'nli_errors_and_unranked_sources', 'whole_component_elapsed'],
            'cached_discovery': True, 'fresh_analysis': False, 'quality_gate_passed': False,
            'runtime_reference_labels': False}
    write(directory/'plan.json', plan)
    print({'prepared': True, 'candidates': len(proposals), 'max_seconds': 900}, flush=True)


def run(directory):
    started = time.monotonic(); plan = read_json(directory/'plan.json'); live(plan['expires_at'])
    if plan['artifact_kind'] != VERSION or plan['retrieval_limits'] != support_retrieval.LIMITS:
        raise ValueError('Frozen retrieval configuration changed')
    for field in ('inputs', 'code_sha256', 'model_files'):
        if any(sha(p) != h for p, h in plan[field].items()): raise ValueError('Frozen file changed')
    source = Path(plan['source']); populations = read_json(source/'core-populations.json')
    proposals = [p for values in populations['proposals'].values() for p in values]
    if [p['id'] for p in proposals] != plan['candidate_ids']: raise ValueError('Population changed')
    analysis = read_json(source/'source-analysis.json')
    units = [u for r in analysis['records'] for u in r['units']]
    cache = read_json(source/'unit-candidates.json')
    budget = InferenceBudget(Path(plan['budget']['ledger']), plan['budget']['cycle_id'])
    runner = Runner(directory, plan, budget); runner.started = started
    write(directory/'started.json', {'plan_sha256': runner.plan_sha, 'budget_before': budget.summary()})
    try:
        path = directory/'fresh-groups.json'
        req = {'system': fresh_embedding.VERSION, 'data': {'snapshot': plan['snapshot'],
               'snapshot_sha256': sha(plan['snapshot']), 'output': str(path)}, 'schema': {}, 'max_tokens': 1}
        embedded = runner.call('source-index', req, provider=fresh_embedding.generate)
        if embedded['sha256'] != sha(path): raise ValueError('Embedding artifact changed')
        raw = read_json(path); index = raw['source_index']
        loaded = load_snapshot(plan['snapshot'])
        rows = sorted((c for c in normalize_snapshot(loaded.snapshot) if c.duplicate_of is None and c.text_analysis),
                      key=lambda c: c.comment_id)
        sources = {sid: row['text'] for sid, row in raw['sources'].items()}
        source_index.validate(index, rows, loaded.sha256, MODEL, REVISION, sources=sources)
        scheduled = support_retrieval.schedule(proposals, units, cache, index, sources)
        write(directory/'schedule.json', scheduled)
        req = {'system': target_ranking_nli.VERSION, 'data': {'pairs': scheduled['pairs']}, 'schema': {}, 'max_tokens': 1}
        result = runner.call('support-ranking', req, provider=target_ranking_nli.generate)
        assembled = support_retrieval.assemble(proposals, units, cache, index, sources, scheduled, result)
        write(directory/'retrieval.json', assembled)
        # Post-hoc historical comparison only. It never enters inference/selection.
        historical = read_json(source/'core-verdicts.json')
        selected = {p['id']: set(p['sources']) for p in assembled['proposals']}
        discovery = {r['source_id'] for r in analysis['records']}
        comparisons = []
        for family, prior in populations['proposals'].items():
            for p in prior:
                positives = {r['source_id'] for r in populations['rows'][family]
                             if r['candidate_id'] == p['id'] and historical[family][r['id']] == 'supported'}
                chosen = selected[p['id']]
                comparisons.append({'candidate_id': p['id'], 'prior_sources': len(p['sources']),
                    'new_sources': len(chosen), 'historical_model_supported': sorted(positives),
                    'historical_supported_retained': sorted(positives & chosen),
                    'historical_supported_not_retrieved': sorted(positives - chosen),
                    'outside_discovery': sorted(chosen - discovery)})
        report = {'artifact_kind': VERSION, 'plan_sha256': runner.plan_sha,
            'elapsed_seconds': time.monotonic()-started, 'canonical_search_count': len(rows),
            'candidates': len(proposals), 'nli_pairs': len(scheduled['pairs']), 'nli_errors': len(assembled['pair_errors']),
            'unranked_sources': sum(not r['ranking_complete'] for c in assembled['rankings'] for r in c['rows']),
            'comparisons': comparisons, 'retrieval_sha256': sha(directory/'retrieval.json'),
            'budget_after': budget.summary(), 'fresh_analysis': False, 'quality_gate_passed': False,
            'semantic_membership_executed': False, 'runtime_reference_labels': False}
        write(directory/'completed.json', report)
        print({k: v for k, v in report.items() if k not in ('budget_after', 'comparisons')}, flush=True)
    except BaseException as exc:
        write(directory/'failed.json', {'exception_type': type(exc).__name__,
              'elapsed_seconds': time.monotonic()-started, 'budget_after': budget.summary(), 'quality_gate_passed': False})
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); sub = parser.add_subparsers(dest='action', required=True)
    p = sub.add_parser('prepare'); p.add_argument('directory', type=Path); p.add_argument('--source', type=Path, required=True)
    p = sub.add_parser('run'); p.add_argument('directory', type=Path)
    p = sub.add_parser('union'); p.add_argument('directory', type=Path); p.add_argument('--source', type=Path, required=True)
    args = parser.parse_args()
    if args.action == 'prepare': prepare(args.directory, args.source)
    elif args.action == 'union': union(args.directory, args.source)
    else: run(args.directory)
