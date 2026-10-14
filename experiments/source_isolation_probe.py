"""Bounded local diagnostic; prior assignments are test cases, never repaired service input."""
import argparse
from collections import Counter
from pathlib import Path

from commentscope.factory.automatic import Calls, checked_call, local_provider, source_data, bind_claims, build_bundle
from commentscope.factory.automatic_contract import (EXTRACT, SOURCE_AUDIT, SOURCE_SCHEMA, digest,
    extraction_schema, segments, validate_extraction, validate_source, source_passed)
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.ingestion import load_snapshot
from commentscope.storage import write_json_exclusive


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('snapshot'); parser.add_argument('baseline_report')
    parser.add_argument('--run-dir', type=Path, required=True)
    args = parser.parse_args()
    if (args.run_dir/'report.json').exists(): parser.error('Completed output exists')
    baseline = read_json(args.baseline_report)
    build_bundle(args.snapshot, baseline)  # Validate original bindings; no modification.
    snapshot = load_snapshot(args.snapshot).snapshot
    sources = {s.comment_id: s for s in snapshot.comments}
    assigned = {i for g in baseline['groups'] for i in g['member_ids']}
    units = [u for u in baseline['units'] if u['claim_id'] in assigned]
    selected = {u['source_comment_id'] for u in units}
    # Fixed deterministic supplementary sample, not an independently held-out corpus.
    extra = sorted(set(baseline['selected_ids']) - selected,
                   key=lambda i: digest(['source-isolation-extra-0.1', i]))[:16]
    selected.update(extra)
    manifest = {'artifact_kind': 'source-isolation-diagnostic-0.1', 'snapshot_sha256': sha(args.snapshot),
                'baseline_sha256': sha(args.baseline_report), 'expires_at': snapshot.usage.expires_at,
                'source_ids': sorted(selected), 'baseline_claim_ids': sorted(assigned),
                'prompts': {'extract': digest(EXTRACT), 'source': digest(SOURCE_AUDIT)},
                'code_sha256': {p: sha(p) for p in ['src/commentscope/factory/automatic.py',
                    'src/commentscope/factory/automatic_contract.py', __file__]},
                'model': baseline['model'], 'purpose': 'offline_diagnostic_not_service_selection',
                'independent_gold': False, 'may_edit_baseline': False}
    calls = Calls(args.run_dir, manifest, local_provider)
    audits, records = [], []
    for unit in units:
        audit = checked_call(calls, SOURCE_AUDIT, source_data(unit), SOURCE_SCHEMA, validate_source)
        audits.append({'claim_id': unit['claim_id'], 'result': audit, 'passed': source_passed(audit)})
        print(f'old-claim-audit {len(audits)}/{len(units)}', flush=True)
    for sid in sorted(selected):
        source = sources[sid]; parts = segments(source.text_original)
        if len(source.text_original) > 4000 or not parts or len(parts) > 80:
            records.append({'source_comment_id': sid, 'status': 'input_limit', 'claims': []})
            continue
        result = checked_call(calls, EXTRACT, {'COMMENT': parts}, extraction_schema(parts),
                              lambda v: validate_extraction(v, parts))
        claims = [] if result['errors'] else bind_claims(source, result['output'])
        records.append({'source_comment_id': sid, 'claims': claims, 'result': result,
                        'status': 'extraction_failed' if result['errors'] else result['output']['status']})
        print(f'new-extraction {len(records)}/{len(selected)}', flush=True)
    report = {**manifest, 'source_audits': audits, 'extractions': records,
              'summary': {'old_assigned_claims': len(units), 'source_gate_passed': sum(a['passed'] for a in audits),
                          'new_extraction_statuses': dict(Counter(r['status'] for r in records)),
                          'new_claims': sum(len(r['claims']) for r in records)}}
    write_json_exclusive(args.run_dir/'report.json', report)
    print(report['summary'], flush=True)


if __name__ == '__main__': main()
