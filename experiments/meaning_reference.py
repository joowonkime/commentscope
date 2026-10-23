"""Validate private, pre-output annotation parts and freeze a complete reference.

This is offline evaluation tooling, never a runtime eligibility filter. Draft
judgments are preserved; explicit revisions may be supplied before freezing.
Hashes prove identity, not semantic correctness or independent annotation.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from commentscope.factory import comment_utilization as utilization
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.factory.fact_checks import nonempty
from commentscope.ingestion import load_snapshot
from commentscope.storage import write_json_exclusive as write

VERSION = 'offline-meaning-reference-assembly-0.1'
PRIVATE_ROOT = Path('runs')


def assemble(snapshot_path, protocol_path, part_paths, resolution_path=None):
    loaded = load_snapshot(snapshot_path); snapshot = loaded.snapshot
    sources = utilization._canonical(snapshot); ids = list(sources)
    protocol = read_json(protocol_path)
    if (protocol.get('artifact_kind') != 'offline-meaning-reference-protocol-0.1'
            or protocol.get('goal_revision') != utilization.GOAL_REVISION
            or protocol.get('snapshot_file_sha256') != loaded.sha256
            or protocol.get('canonical_population') != len(ids)
            or not nonempty(protocol.get('evaluator'))):
        raise ValueError('Protocol must bind the actual snapshot and full canonical population')
    paths = list(part_paths)
    if not paths or len({str(p.resolve()) for p in paths}) != len(paths):
        raise ValueError('Distinct annotation parts required')
    indexed, provenance = {}, {str(protocol_path): sha(protocol_path)}
    for path in paths:
        part = read_json(path)
        if (part.get('artifact_kind') != 'offline-meaning-reference-part-0.1'
                or part.get('snapshot_file_sha256') != loaded.sha256
                or part.get('evaluator') != protocol['evaluator']):
            raise ValueError('Annotation part belongs to a different source or evaluator')
        bounds = part.get('canonical_indices')
        if (not isinstance(bounds, list) or len(bounds) != 2
                or any(type(i) is not int for i in bounds)
                or not 0 <= bounds[0] <= bounds[1] < len(ids)):
            raise ValueError('Invalid canonical part range')
        rows = part.get('rows')
        if not isinstance(rows, list) or len(rows) != bounds[1] - bounds[0] + 1:
            raise ValueError('Part must include its entire declared range')
        for index, row in enumerate(rows, bounds[0]):
            if (set(row) != {'source_id', 'eligibility', 'reason'} or row['source_id'] != ids[index]
                    or index in indexed or row['eligibility'] not in utilization.ELIGIBILITY
                    or not nonempty(row['reason'])):
                raise ValueError('Invalid, displaced, overlapping or unexplained judgment')
            indexed[index] = {**row, 'source_sha256': digest(sources[ids[index]])}
        provenance[str(path)] = sha(path)
    revisions = []
    if resolution_path is not None:
        revision = read_json(resolution_path)
        if (revision.get('artifact_kind') != 'offline-meaning-reference-revisions-0.1'
                or revision.get('snapshot_file_sha256') != loaded.sha256
                or revision.get('draft_inputs') != provenance
                or not isinstance(revision.get('rows'), list)):
            raise ValueError('Revisions must bind all original draft judgments')
        by_id = {r['source_id']: i for i, r in indexed.items()}; revised = set()
        for row in revision['rows']:
            if set(row) != {'source_id', 'previous_eligibility', 'eligibility', 'reason', 'source_sha256'}:
                raise ValueError('Unexpected revision fields')
            sid = row['source_id']
            if (sid not in by_id or sid in revised or row['eligibility'] not in utilization.ELIGIBILITY
                    or row['previous_eligibility'] != indexed[by_id[sid]]['eligibility']
                    or row['source_sha256'] != digest(sources[sid]) or not nonempty(row['reason'])):
                raise ValueError('Invalid, duplicate, stale or unexplained revision')
            revised.add(sid); revisions.append(row)
            indexed[by_id[sid]] = {k: v for k, v in row.items() if k != 'previous_eligibility'}
        provenance[str(resolution_path)] = sha(resolution_path)
    rows = [indexed[i] for i in sorted(indexed)]
    counts = Counter(r['eligibility'] for r in rows)
    missing = [i for i in range(len(ids)) if i not in indexed]
    complete = not missing and not counts['uncertain']
    report = {'artifact_kind': VERSION, 'snapshot_file_sha256': loaded.sha256,
              'canonical_population': len(ids), 'annotated': len(rows), 'missing_indices': missing,
              'eligibility_counts': {k: counts[k] for k in utilization.ELIGIBILITY},
              'uncertain_source_ids': [r['source_id'] for r in rows if r['eligibility'] == 'uncertain'],
              'inputs': provenance, 'revision_count': len(revisions), 'ready_to_freeze': complete,
              'runtime_input': False, 'independent_gold': False, 'quality_gate_passed': False}
    reference = None
    if complete:
        # Provenance identity is part of the reference digest pinned by the
        # future pipeline plan. No sample is silently promoted to full corpus.
        reference = utilization.freeze_reference(snapshot, rows, evaluator=protocol['evaluator'],
            protocol='Pre-output protocol/annotation inputs SHA256: ' + digest(provenance)
                     + '. Original text and available parent context only; offline, not independent gold.')
    return report, reference


def freeze(output, snapshot, protocol, parts, resolutions=None):
    if not output.resolve().is_relative_to(PRIVATE_ROOT.resolve()):
        raise ValueError('Research reference must remain private')
    if output.exists(): raise ValueError('Never overwrite a frozen reference')
    report, reference = assemble(snapshot, protocol, parts, resolutions)
    if reference is None: raise ValueError('Full population and resolution of uncertain judgments required')
    # New directory keeps a manifest and its reference together. Interrupted
    # writes are visible, not silently treated as a successful freeze.
    output.mkdir(parents=True)
    write(output/'reference.json', reference)
    write(output/'manifest.json', {**report, 'frozen_at': datetime.now(timezone.utc).isoformat(),
                                  'reference_sha256': digest(reference), 'reference_file_sha256': sha(output/'reference.json')})
    return reference


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('inspect', 'freeze'))
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--protocol', type=Path, required=True)
    parser.add_argument('--parts', type=Path, nargs='+', required=True)
    parser.add_argument('--resolutions', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.action == 'freeze':
        if args.output is None: parser.error('freeze requires --output')
        reference = freeze(args.output, args.snapshot, args.protocol, args.parts, args.resolutions)
        print({'frozen': True, 'reference_sha256': digest(reference), 'runtime_input': False})
    else:
        report, _ = assemble(args.snapshot, args.protocol, args.parts, args.resolutions)
        print({**report, 'missing_indices': {'count': len(report['missing_indices']),
                                          'next': report['missing_indices'][:10]}})
