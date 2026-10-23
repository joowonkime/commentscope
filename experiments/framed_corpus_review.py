"""Offline review packets for a completed whole-corpus membership map.

No model calls, output repairs or automatic semantic verdicts. This can inspect
the final membership map while Agent preparation continues, without changing
the running plan. A packet covers ALL candidates and ALL counted support edges;
partial reviews remain partial and never approve Agents or the MVP.
"""
import argparse
from collections import Counter
from copy import deepcopy
from pathlib import Path

from commentscope.factory import comment_utilization as utilization
from commentscope.factory import position_frames, stance_membership as stance
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.ingestion import load_snapshot
from commentscope.storage import write_json_exclusive as write

VERSION = 'whole-corpus-offline-review-0.1'
PRIVATE_ROOT = Path('runs')


def private(path):
    if not path.resolve().is_relative_to(PRIVATE_ROOT.resolve()):
        raise ValueError('Research review artifacts must remain private')


def packet(snapshot, reference, records, candidates, memberships, expected_reference_sha256):
    utilization._validate_reference(snapshot, reference, expected_reference_sha256)
    if reference['scope'] != 'full_corpus':
        raise ValueError('Whole-corpus review requires the pre-run full reference')
    mapped = stance.assemble_map(snapshot, records, candidates, memberships)
    opinion = mapped['opinion_map']
    sources = {sid: position_frames.source_packet(snapshot, sid) for sid in utilization._canonical(snapshot)}
    lookup = {p['id']: p for p in opinion['perspectives']}
    # Verdicts are intentionally blank. A model support edge is a review task,
    # not a reviewer-supported label. Full parent context remains available.
    template = {'map_sha256': digest(opinion), 'evaluator': 'assistant_offline_not_independent_human_gold',
        'clusters': [{'perspective_id': p['id'], 'claim_sha256': digest(p['claim']),
                      'verdict': None, 'reason': ''} for p in opinion['perspectives']],
        'supports': [{'perspective_id': r['perspective_id'], 'source_id': r['canonical_source_id'],
                      'claim_sha256': digest(lookup[r['perspective_id']]['claim']),
                      'source_sha256': digest(sources[r['canonical_source_id']]['text']),
                      'verdict': None, 'reason': ''}
                     for r in opinion['assessments'] if r['relation'] == 'supported']}
    return {'artifact_kind': VERSION + '-packet', 'snapshot_sha256': digest(snapshot.to_dict()),
            'reference_sha256': digest(reference), 'map_sha256': digest(opinion),
            'sources': sources, 'opinion_map': opinion, 'review_template': template,
            'denominator': {'scope': reference['scope'], 'eligibility_counts': dict(Counter(r['eligibility'] for r in reference['rows'])),
                            'protocol': reference['protocol'],
                            'note': 'Inclusion is not support. Conservatively included ambiguous comments receive no credit without reviewed coherent contribution.'},
            'runtime_input': False, 'independent_gold': False, 'quality_gate_passed': False}


def review(snapshot, reference, prepared, parts):
    """Combine hash-bound completed judgments; missing rows remain unreviewed."""
    if (prepared['artifact_kind'] != VERSION + '-packet'
            or prepared['snapshot_sha256'] != digest(snapshot.to_dict())
            or prepared['reference_sha256'] != digest(reference)):
        raise ValueError('Review packet belongs to a different source/reference')
    merged = {k: deepcopy(v) for k, v in prepared['review_template'].items() if k not in ('clusters', 'supports')}
    merged.update(clusters=[], supports=[])
    evaluator = None
    for part in parts:
        if (set(part) != {'artifact_kind', 'packet_sha256', 'evaluator', 'clusters', 'supports'}
                or part['artifact_kind'] != VERSION + '-part' or part['packet_sha256'] != digest(prepared)
                or not isinstance(part['evaluator'], str) or not part['evaluator'].strip()
                or not isinstance(part['clusters'], list) or not isinstance(part['supports'], list)):
            raise ValueError('Invalid or changed review part')
        if evaluator is not None and evaluator != part['evaluator']:
            raise ValueError('Do not silently combine different evaluator protocols')
        evaluator = part['evaluator']
        merged['clusters'].extend(deepcopy(part['clusters']))
        merged['supports'].extend(deepcopy(part['supports']))
    if evaluator is not None: merged['evaluator'] = evaluator
    opinion = prepared['opinion_map']
    perspectives = [{k: p[k] for k in ('id', 'claim', 'upstream_agent_state')} for p in opinion['perspectives']]
    lookup = {p['id']: p for p in perspectives}
    originals = utilization._canonical(snapshot)
    assessments = [{'perspective_id': r['perspective_id'], 'source_id': r['canonical_source_id'],
                    'claim_sha256': digest(lookup[r['perspective_id']]['claim']),
                    'source_sha256': digest(originals[r['canonical_source_id']]),
                    'relation': r['relation'], 'evidence_ref': ref}
                   for r in opinion['assessments'] for ref in r['evidence_refs']]
    result = utilization.evaluate(snapshot, reference, perspectives, assessments, merged,
                                  expected_reference_sha256=prepared['reference_sha256'])
    result.update(packet_sha256=digest(prepared), runtime_input=False, independent_gold=False,
                  score_interpretation='Verified contribution lower bound under the fixed inclusion reference, not exact semantic census.',
                  reviewed_cluster_count=len(merged['clusters']),
                  total_cluster_count=len(perspectives), review_part_count=len(parts),
                  review_parts_sha256=[digest(p) for p in parts])
    return result


def load_run(directory):
    private(directory)
    plan_path = directory/'plan.json'; plan = read_json(plan_path)
    if (plan['artifact_kind'] != 'frozen-whole-framed-corpus-pipeline-0.1'
            or plan['runtime_reference_labels'] is not False
            or read_json(directory/'started.json')['plan_sha256'] != sha(plan_path)):
        raise ValueError('Unknown or changed started pipeline plan')
    for field in ('inputs', 'code_sha256'):
        if any(sha(p) != h for p, h in plan[field].items()):
            raise ValueError('Pinned pipeline inputs/code changed')
    snapshot = load_snapshot(Path(plan['snapshot']))
    if snapshot.sha256 != plan['snapshot_file_sha256']:
        raise ValueError('Snapshot changed')
    reference = read_json(plan['reference']['path'])
    paths = [directory/'artifacts'/f'{name}.json' for name in ('frames', 'candidates', 'memberships', 'map')]
    if any(not p.is_file() for p in paths):
        raise ValueError('Final membership map not available; never promote a frame prefix to whole-corpus output')
    records, candidates, memberships, saved_map = [read_json(p) for p in paths]
    rebuilt = stance.assemble_map(snapshot.snapshot, records, candidates, memberships)
    if saved_map != rebuilt:
        raise ValueError('Saved membership map differs from full source-bound reconstruction')
    prepared = packet(snapshot.snapshot, reference, records, candidates, memberships, plan['reference']['sha256'])
    bindings = {str(p): sha(p) for p in [plan_path, directory/'started.json', *paths,
                                       Path(plan['snapshot']), Path(plan['reference']['path'])]}
    return snapshot.snapshot, reference, prepared, bindings


def prepare(directory, run_directory):
    private(directory)
    if directory.exists(): raise ValueError('Never overwrite a review packet')
    _, _, prepared, bindings = load_run(run_directory)
    write(directory/'packet.json', prepared)
    write(directory/'manifest.json', {'artifact_kind': VERSION, 'run_directory': str(run_directory),
          'inputs': bindings, 'review_code_sha256': sha(__file__), 'packet_sha256': digest(prepared)})
    template = prepared['review_template']
    write(directory/'part-template.json', {'artifact_kind': VERSION + '-part', 'packet_sha256': digest(prepared),
          **{k: template[k] for k in ('evaluator', 'clusters', 'supports')}})
    return {'clusters': len(template['clusters']), 'counted_support_relations': len(template['supports']),
            'canonical_population': len(prepared['sources']), 'semantic_verdicts': 0, 'new_model_calls': 0}


def evaluate(directory, part_paths, output):
    private(directory); private(output)
    manifest = read_json(directory/'manifest.json')
    if (manifest['artifact_kind'] != VERSION or manifest['review_code_sha256'] != sha(__file__)
            or any(sha(p) != h for p, h in manifest['inputs'].items())):
        raise ValueError('Frozen review inputs/code changed')
    snapshot, reference, rebuilt, _ = load_run(Path(manifest['run_directory']))
    prepared = read_json(directory/'packet.json')
    if prepared != rebuilt or digest(prepared) != manifest['packet_sha256']:
        raise ValueError('Review packet changed')
    result = review(snapshot, reference, prepared, [read_json(p) for p in part_paths])
    result['review_files_sha256'] = {str(p): sha(p) for p in part_paths}
    write(output, result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    p = sub.add_parser('prepare'); p.add_argument('directory', type=Path); p.add_argument('--run', type=Path, required=True)
    p = sub.add_parser('evaluate'); p.add_argument('directory', type=Path)
    p.add_argument('--parts', type=Path, nargs='*', default=[]); p.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.action == 'prepare': print(prepare(args.directory, args.run))
    else:
        report = evaluate(args.directory, args.parts, args.output)
        print({k: report[k] for k in ('correct_comment_utilization', 'support_counts', 'corpus_clustering_target_met', 'mvp_acceptance')})
