"""Fixed-anchor local relation comparison; no automatic approvals or threshold search."""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import html
import hashlib
import json
import os
from pathlib import Path

from commentscope.factory.claim_clusters import read_json, sha
from commentscope.factory.extractive_keypoints import anchors_for, assemble, judge, render, RELATIONS, SYSTEM, SCHEMA
from commentscope.factory.perspective_drafts import inputs_for, load_candidates
from commentscope.providers.local_nli import LocalNLI, MODEL, REVISION, THRESHOLD
from commentscope.storage import write_json_exclusive


def validate_cases(cases, real=False, pairs=None):
    seen = set()
    if not isinstance(cases, list) or not 1 <= len(cases) <= 100:
        raise ValueError('Invalid evaluation size')
    for c in cases:
        if c['id'] in seen or not c['category'] or not c['allowed'] or not set(c['allowed']) <= set(RELATIONS):
            raise ValueError('Invalid evaluation case')
        seen.add(c['id'])
        if real:
            if c['id'] not in pairs or pairs[c['id']]['origin'] == 'identity_text_only':
                raise ValueError('Unknown or identity evaluation pair')
        elif not all(isinstance(c[k], str) and 0 < len(c[k].strip()) and len(c[k]) <= 500
                     for k in ('source', 'representative')):
            raise ValueError('Invalid synthetic text')


def evaluate(cases, records):
    result = {}
    for case in cases:
        row = result.setdefault(case['category'], {'total': 0, 'matches': 0, 'errors': 0,
                                                  'supports': 0, 'unclear': 0, 'mismatch_ids': []})
        record = records[case['id']]
        row['total'] += 1
        row['errors'] += bool(record['errors'])
        row['supports'] += not record['errors'] and record['relation'] == 'supports'
        row['unclear'] += not record['errors'] and record['relation'] == 'unclear'
        if not record['errors'] and record['relation'] in case['allowed']:
            row['matches'] += 1
        else:
            row['mismatch_ids'].append(case['id'])
    return result


def check_baseline(baseline, prepared, members, anchors, candidates_path):
    expected = {'snapshot_sha256': prepared['snapshot_sha256'],
                'extraction_sha256': prepared['extraction_sha256'], 'candidate_sha256': sha(candidates_path),
                'expires_at': prepared['expires_at'], 'members': members, 'anchors': anchors}
    if any(baseline.get(k) != v for k, v in expected.items()):
        raise ValueError('Baseline provenance or original inputs changed')
    if (baseline.get('prompt_sha256') != hashlib.sha256(SYSTEM.encode()).hexdigest()
            or baseline.get('generation_schema') != SCHEMA
            or baseline.get('request_settings') != {'temperature': 0, 'seed': 407, 'max_tokens': 3000}):
        raise ValueError('Baseline Qwen decision contract changed')
    # Revalidate matrix and assembly instead of trusting serialized groups.
    if baseline['assembly'] != assemble(members, anchors, baseline['pairs']):
        raise ValueError('Baseline assembly does not match fixed algorithm')


def render_comparison(report, nli_report):
    esc = lambda value: html.escape(str(value), quote=True)
    parts = ['<!doctype html><html lang="ko"><meta charset="utf-8"><title>로컬 판정기 비교</title>',
        '<style>body{font:16px system-ui;max-width:1400px;margin:30px auto}table{border-collapse:collapse}td,th{border:1px solid #bbb;padding:8px}pre{white-space:pre-wrap}</style>',
        '<h1>고정 원문·대표·배정 코드 / 관계 판정기 비교</h1>',
        '<p>개발용 assistant 평가 초안. 독립 gold/사람 승인/일반 정확도가 아닙니다. NLI softmax는 보정된 신뢰도가 아닙니다. 실제 긍정 pair 평가가 부족합니다.</p>',
        '<pre>'+esc(json.dumps(report['summary'], ensure_ascii=False, indent=2))+'</pre>']
    for name, cases, records in [('실제 댓글 회귀', report['real_cases'], report['real']),
                                  ('합성 개발 사례', report['synthetic_cases'], report['synthetic'])]:
        parts.append('<h2>'+name+'</h2><table><tr><th>ID / 기준</th><th>원문 → 대표</th><th>Qwen</th><th>NLI</th></tr>')
        for c in cases:
            if name == '실제 댓글 회귀':
                source, anchor = c['id'].split('->')
                texts = [nli_report['members'][source]['target'], nli_report['anchors'][anchor]['text']]
            else:
                texts = [c['source'], c['representative']]
            parts.append('<tr><td>'+esc(c['id'])+'<br>'+esc(c['allowed'])+'</td><td>'+
                         '<hr>'.join(esc(t) for t in texts)+'</td>')
            for model in ['qwen', 'nli']:
                r = records[model][c['id']]
                parts.append('<td>'+esc(r['relation'])+'<br>'+esc(r.get('scores', r['errors']))+'</td>')
            parts.append('</tr>')
        parts.append('</table>')
    parts.append('<h2>NLI 전체 72쌍으로 재배정한 미승인 결과</h2>')
    # Embed only body content of the existing escaped diagnostic renderer.
    body = render(nli_report)
    parts.append(body[body.index('<h1>'):body.rindex('</html>')])
    return '\n'.join(parts+['</html>'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['snapshot', 'extraction', 'candidates', 'baseline', 'plan']:
        parser.add_argument(name)
    parser.add_argument('--suite', default='tests/fixtures/synthetic-support-cases.json')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    baseline, plan, suite = read_json(args.baseline), read_json(args.plan), read_json(args.suite)
    prepared, clusters = load_candidates(args.snapshot, args.extraction, args.candidates)
    members, _ = inputs_for(prepared, clusters[baseline['cluster_id']], 'v2')
    anchors = anchors_for(members)
    check_baseline(baseline, prepared, members, anchors, args.candidates)
    if (plan['baseline_sha256'] != sha(args.baseline) or plan['expires_at'] != prepared['expires_at']
            or plan['nli_model'] != MODEL or plan['revision'] != REVISION or plan['threshold'] != THRESHOLD):
        raise ValueError('Pre-run plan mismatch')
    validate_cases(plan['real_cases'], real=True, pairs=baseline['pairs'])
    validate_cases(suite['cases'])
    files = [args.output, Path(str(args.output)+'.html'), Path(str(args.output)+'.manifest.json'),
             Path(str(args.output)+'.nli.json')]
    keys = [('real', 'nli', k) for k in baseline['pairs'] if k.split('->')[0] != k.split('->')[1]]
    keys += [('synthetic', model, c['id']) for model in ['qwen', 'nli'] for c in suite['cases']]
    # Index filenames, never interpolate untrusted case IDs into paths.
    checkpoints = {key: Path(str(args.output)+f'.pair-{i:03d}.json') for i, key in enumerate(keys)}
    if any(os.path.lexists(p) for p in [*files, *checkpoints.values()]):
        parser.error('Output exists; select new paths')
    manifest = {'artifact_kind': 'local-nli-comparison-0.1', 'created_at': datetime.now(timezone.utc).isoformat(),
                'baseline_sha256': sha(args.baseline), 'plan_sha256': sha(args.plan), 'suite_sha256': sha(args.suite),
                'assembly_code_sha256': sha(Path(__file__).parents[1]/'src/commentscope/factory/extractive_keypoints.py'),
                'expires_at': prepared['expires_at'], 'human_approved': False, 'independent_gold': False,
                'accepted_perspectives': 0, 'threshold': THRESHOLD}
    # Persist hashes/threshold before any new inference.
    write_json_exclusive(files[2], manifest)
    nli = LocalNLI()
    real = {'qwen': baseline['pairs'], 'nli': {}}
    for key, old in baseline['pairs'].items():
        source, anchor = key.split('->')
        if source == anchor:
            real['nli'][key] = deepcopy(old)
        else:
            record = {'source': source, 'anchor': anchor, **nli.score(members[source]['target'], anchors[anchor]['text'])}
            real['nli'][key] = record
            write_json_exclusive(checkpoints[('real', 'nli', key)], {**manifest, 'pair': record})
        if anchor == list(anchors)[-1]:
            print(json.dumps({'nli_source_completed': source}), flush=True)
    synthetic = {'qwen': {}, 'nli': {}}
    for c in suite['cases']:
        for model, score in [('qwen', judge), ('nli', nli.score)]:
            record = score(c['source'], c['representative'])
            synthetic[model][c['id']] = record
            write_json_exclusive(checkpoints[('synthetic', model, c['id'])], {**manifest, 'case': c, 'result': record})
        print(json.dumps({'synthetic_completed': c['id']}), flush=True)
    nli_assembly = assemble(members, anchors, real['nli'])
    summary = {'real_regressions': {m: evaluate(plan['real_cases'], r) for m, r in real.items()},
               'synthetic': {m: evaluate(suite['cases'], r) for m, r in synthetic.items()},
               'groups': {m: {'groups': len(a['groups']), 'assigned': sum(len(g['member_ids']) for g in a['groups']),
                             'unassigned': len(a['unassigned'])}
                          for m, a in [('qwen', baseline['assembly']), ('nli', nli_assembly)]},
               'real_pair_seconds': {m: sum(p['seconds'] for p in r.values()) for m, r in real.items()},
               'accepted_perspectives': 0}
    nli_report = {**manifest, 'model_metadata': nli.metadata, 'members': members, 'anchors': anchors,
                  'pairs': real['nli'], 'assembly': nli_assembly, 'summary': summary['groups']['nli']}
    report = {**manifest, 'nli_metadata': nli.metadata,
              'qwen_metadata': {k: baseline[k] for k in ['model', 'model_revision', 'runtime', 'prompt_sha256', 'request_settings']},
              'qwen_metadata_source': 'operator_supplied_not_attested; real outputs reused, synthetic calls fresh',
              'real_cases': plan['real_cases'], 'synthetic_cases': suite['cases'], 'real': real,
              'synthetic': synthetic, 'summary': summary,
              'limitations': ['English-only NLI', 'Threshold not calibrated or tuned', 'Synthetic is not real positive recall',
                              'Known development cases, not independent gold', 'No unseen real evaluation',
                              'Comparing decision mechanisms, not model-weights-only effect', 'All groups unapproved']}
    write_json_exclusive(files[3], nli_report)
    write_json_exclusive(args.output, report)
    with files[1].open('x', encoding='utf-8') as stream:
        stream.write(render_comparison(report, nli_report))
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
