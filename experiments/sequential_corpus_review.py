"""Offline review of the sequential whole-corpus execution contract.

The packet/verdict schema and utilization arithmetic are the existing shared
evaluation, not a new metric. This loader never opens model weights, performs
inference, modifies runtime output, or pre-fills semantic review verdicts.
"""
import argparse
from pathlib import Path

from commentscope.factory import stance_membership as stance
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.ingestion import load_snapshot
from commentscope.storage import write_json_exclusive as write
from experiments import framed_corpus_review as common
from experiments import sequential_corpus_pipeline as pipeline

VERSION = 'sequential-whole-corpus-offline-review-0.1'


def review_code():
    return {str(p): sha(p) for p in (Path(__file__), Path(common.__file__), Path(pipeline.__file__))}


def load_run(directory):
    pipeline.private(directory)
    path = directory/'plan.json'; plan = read_json(path)
    pipeline.validate_contract(plan)
    if read_json(directory/'started.json')['plan_sha256'] != sha(path):
        raise ValueError('Unknown or changed started pipeline plan')
    for field in ('inputs', 'code_sha256'):
        if any(sha(p) != h for p, h in plan[field].items()):
            raise ValueError('Pinned pipeline inputs/code changed')
    loaded = load_snapshot(Path(plan['snapshot'])); snapshot = loaded.snapshot
    if (loaded.sha256 != plan['snapshot_file_sha256']
            or len(pipeline.corpus.sources(snapshot)) != plan['canonical_population']
            or snapshot.usage.expires_at != plan['expires_at']):
        raise ValueError('Snapshot population changed')
    reference = read_json(plan['reference']['path'])
    pipeline.reference_check(snapshot, reference, plan['reference']['sha256'])
    paths = [directory/'artifacts'/f'{name}.json' for name in ('frames', 'candidates', 'memberships', 'map')]
    if any(not p.is_file() for p in paths):
        raise ValueError('Final membership map required; a frame prefix is not the whole output')
    records, candidates, memberships, saved_map = [read_json(p) for p in paths]
    if saved_map != stance.assemble_map(snapshot, records, candidates, memberships):
        raise ValueError('Saved map differs from original-source reconstruction')
    prepared = common.packet(snapshot, reference, records, candidates, memberships, plan['reference']['sha256'])
    bindings = {str(p): sha(p) for p in [path, directory/'started.json', *paths,
                                       Path(plan['snapshot']), Path(plan['reference']['path'])]}
    return snapshot, reference, prepared, bindings


def prepare(directory, run_directory):
    pipeline.private(directory)
    if directory.exists(): raise ValueError('Never overwrite a review packet')
    _, _, prepared, bindings = load_run(run_directory)
    write(directory/'packet.json', prepared)
    write(directory/'manifest.json', {'artifact_kind': VERSION, 'run_directory': str(run_directory),
          'inputs': bindings, 'review_code_sha256': review_code(), 'packet_sha256': digest(prepared)})
    template = prepared['review_template']
    write(directory/'part-template.json', {'artifact_kind': common.VERSION + '-part',
          'packet_sha256': digest(prepared), **{k: template[k] for k in ('evaluator', 'clusters', 'supports')}})
    return {'clusters': len(template['clusters']), 'counted_support_relations': len(template['supports']),
            'canonical_population': len(prepared['sources']), 'semantic_verdicts': 0, 'new_model_calls': 0}


def evaluate(directory, part_paths, output):
    pipeline.private(directory); pipeline.private(output)
    manifest = read_json(directory/'manifest.json')
    if (manifest['artifact_kind'] != VERSION or manifest['review_code_sha256'] != review_code()
            or any(sha(p) != h for p, h in manifest['inputs'].items())):
        raise ValueError('Frozen review inputs/code changed')
    snapshot, reference, rebuilt, _ = load_run(Path(manifest['run_directory']))
    prepared = read_json(directory/'packet.json')
    if prepared != rebuilt or digest(prepared) != manifest['packet_sha256']:
        raise ValueError('Review packet changed')
    result = common.review(snapshot, reference, prepared, [read_json(p) for p in part_paths])
    result.update(review_files_sha256={str(p): sha(p) for p in part_paths},
                  execution_version=pipeline.VERSION, review_loader_version=VERSION)
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
        result = evaluate(args.directory, args.parts, args.output)
        print({k: result[k] for k in ('correct_comment_utilization', 'support_counts', 'corpus_clustering_target_met', 'mvp_acceptance')})
