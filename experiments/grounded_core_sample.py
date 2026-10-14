"""New offline evaluation slice: source-only extraction and directional fidelity.

Selection is frozen independently of inference. Offline expectations never enter
model payloads. These comments appeared in the older full1000 run, so this is not
an untouched dataset or an independent gold evaluation.
"""
import argparse
import hashlib
import json
from pathlib import Path
from importlib.metadata import version

from commentscope.agents.profiles import require_live
from commentscope.factory import grounded_core
from commentscope.factory.automatic import Calls, bind_claims, checked_call, local_provider, build_bundle
from commentscope.factory.automatic_contract import EXTRACT, segments, extraction_schema, validate_extraction
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.ingestion import load_snapshot
from commentscope.providers.local_nli import LocalNLI, MODEL, REVISION, THRESHOLD
from commentscope.storage import write_json_exclusive
from experiments.claim_support_probe import CachedScores
from experiments.grounded_core_probe import CODE, no_model, check_inputs


def select(snapshot, baseline, full):
    excluded = {r['source_comment_id'] for r in baseline['records']}
    assigned = {uid for g in full['groups'] for uid in g['member_ids']}
    excluded.update(u['source_comment_id'] for u in full['units'] if u['claim_id'] in assigned)
    return sorted((c for c in snapshot.comments if c.comment_id not in excluded),
                  key=lambda c: hashlib.sha256(('grounded-core-evaluation-20261012:'+c.comment_id).encode()).hexdigest())[:12]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['snapshot', 'baseline64', 'baseline_full', 'evaluation_plan']: parser.add_argument(name)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--verify', action='store_true')
    args = parser.parse_args()
    baseline, full = read_json(args.baseline64), read_json(args.baseline_full)
    build_bundle(args.snapshot, baseline); build_bundle(args.snapshot, full)
    snapshot = load_snapshot(args.snapshot).snapshot
    selected = select(snapshot, baseline, full)
    plan = read_json(args.evaluation_plan)
    if [r['comment_id'] for r in plan['expectations']] != [s.comment_id for s in selected]:
        parser.error('Frozen selection changed')
    manifest = {'artifact_kind': 'grounded-core-new-sample-0.1', 'expires_at': snapshot.usage.expires_at,
                'inputs': {p: sha(p) for p in [args.snapshot, args.baseline64, args.baseline_full, args.evaluation_plan]},
                'code_sha256': {p: sha(p) for p in [*CODE, __file__]}, 'model': baseline['model'],
                'nli': {'model': MODEL, 'revision': REVISION, 'threshold': THRESHOLD},
                'runtime': {'torch': version('torch'), 'transformers': version('transformers'),
                            'device': 'cpu', 'threads': 6, 'temperature': 0, 'seed': 407, 'max_tokens': 900},
                'source_ids': [s.comment_id for s in selected], 'human_handling': False,
                'independent_gold': False, 'untouched_corpus': False, 'quality_gate_passed': False}
    require_live(manifest['expires_at'])
    if args.verify and (not (args.run_dir/'llm'/'manifest.json').exists() or not (args.run_dir/'nli'/'manifest.json').exists()):
        parser.error('Missing replay cache')
    if not args.verify and (args.run_dir/'report.json').exists(): parser.error('Completed output exists')
    calls = Calls(args.run_dir/'llm', manifest, no_model if args.verify else local_provider)
    model = None
    def score(a, b):
        nonlocal model
        if model is None: model = LocalNLI()
        return model.score(a, b)
    scores = CachedScores(args.run_dir/'nli', manifest, no_model if args.verify else score)
    rows = []
    for s in selected:
        parts = segments(s.text_original)
        if len(s.text_original) > 4000 or not parts or len(parts) > 80:
            rows.append({'source_id': s.comment_id, 'source': s.text_original, 'status': 'input_budget', 'units': [], 'checks': []})
            continue
        extracted = checked_call(calls, EXTRACT, {'COMMENT': parts}, extraction_schema(parts),
                                 lambda v: validate_extraction(v, parts))
        units = [] if extracted['errors'] else bind_claims(s, extracted['output'])
        checks = [grounded_core.prepare(u, calls, scores) for u in units]
        row = {'source_id': s.comment_id, 'source': s.text_original, 'extraction': extracted,
               'status': 'failed' if extracted['errors'] else extracted['output']['status'], 'units': units, 'checks': checks}
        rows.append(row)
        print(json.dumps({'source': s.comment_id, 'status': row['status'], 'claims': len(units),
                          'passed': sum(c['allowed'] for c in checks)}), flush=True)
    summary = {'sources': len(rows), 'claims': sum(len(r['units']) for r in rows),
               'passing_claims': sum(c['allowed'] for r in rows for c in r['checks']),
               'zero_claim_sources': sum(not r['units'] for r in rows),
               'claim_sources': sum(bool(r['units']) for r in rows)}
    report = {**manifest, 'summary': summary, 'records': rows}
    check_inputs(manifest)
    if args.verify:
        if read_json(args.run_dir/'report.json') != report: raise ValueError('New sample replay changed')
        print(json.dumps({'verified': summary, 'new_model_calls': calls.new_calls}), flush=True)
    else:
        write_json_exclusive(args.run_dir/'report.json', report)
        print(json.dumps(summary), flush=True)


if __name__ == '__main__': main()
