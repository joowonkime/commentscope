"""Offline fixed-case NLI ablation. No production gate changes or threshold search."""
import argparse
import html
from importlib.metadata import version
import json
from pathlib import Path

from commentscope.agents.profiles import require_live
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.providers.local_nli import LocalNLI, MODEL, REVISION, THRESHOLD, decide
from commentscope.storage import write_json_exclusive
from experiments.claim_frame_probe import prepare_cases

POLICIES = {
    'directional': ['anchor_fidelity', 'member_fidelity', 'common_from_source'],
    'mutual_claims': ['anchor_fidelity', 'member_fidelity', 'common_from_source',
                      'claim_to_common', 'common_to_claim'],
}


def checks_for(anchor, member):
    # Newlines preserve selected segment boundaries; never add parent/context or reference labels.
    source = lambda u: '\n'.join(s['text'] for s in u['spans'])
    return {
        'anchor_fidelity': (source(anchor), anchor['statement']),
        'member_fidelity': (source(member), member['statement']),
        'common_from_source': (source(member), anchor['statement']),
        'claim_to_common': (member['statement'], anchor['statement']),
        'common_to_claim': (anchor['statement'], member['statement']),
    }


def accepted(record):
    if record['errors']:
        return False
    # Never trust a cached relation label independently of its numerical scores.
    relation = decide(record['scores'])
    if record['relation'] != relation:
        raise ValueError('NLI relation changed')
    return relation == 'supports'


def evaluate_pair(anchor, member, score):
    checks = {key: {'premise': pair[0], 'hypothesis': pair[1], 'result': score(*pair)}
              for key, pair in checks_for(anchor, member).items()}
    supported = {key: accepted(row['result']) for key, row in checks.items()}
    return {'checks': checks, 'policies': {
        policy: {'allowed': all(supported[k] for k in keys),
                 'blocked_checks': [k for k in keys if not supported[k]]}
        for policy, keys in POLICIES.items()}}


def summarize(rows):
    result = {}
    for kind in ['synthetic', 'real_development']:
        selected = [r for r in rows if r['kind'] == kind]
        result[kind] = {}
        for policy in POLICIES:
            positives = [r for r in selected if r['expected']]
            negatives = [r for r in selected if not r['expected']]
            allowed = lambda r: r['nli']['policies'][policy]['allowed']
            result[kind][policy] = {
                'positive_total': len(positives), 'positive_kept': sum(allowed(r) for r in positives),
                'negative_total': len(negatives), 'negative_blocked': sum(not allowed(r) for r in negatives),
                'false_rejection_ids': [r['id'] for r in positives if not allowed(r)],
                'false_acceptance_ids': [r['id'] for r in negatives if allowed(r)],
                'cases_with_errors': sum(any(c['result']['errors'] for c in r['nli']['checks'].values()) for r in selected),
            }
    return result


class CachedScores:
    def __init__(self, directory, manifest, score):
        self.directory, self.expiry, self.score = Path(directory), manifest['expires_at'], score
        path = self.directory / 'manifest.json'
        if path.exists():
            if read_json(path) != manifest: raise ValueError('Manifest changed; choose a new run directory')
        else:
            write_json_exclusive(path, manifest)
        self.records = {}

    def __call__(self, premise, hypothesis):
        require_live(self.expiry)
        request = {'premise': premise, 'hypothesis': hypothesis}
        key = digest(request)
        if key in self.records: return self.records[key]
        path = self.directory / ('score-' + key + '.json')
        if path.exists():
            stored = read_json(path)
            if stored['request'] != request or digest(stored['result']) != stored['result_sha256']:
                raise ValueError('NLI checkpoint changed')
            record = stored['result']
        else:
            record = self.score(premise, hypothesis)
            accepted(record)
            write_json_exclusive(path, {'request': request, 'result': record, 'result_sha256': digest(record)})
        accepted(record)
        self.records[key] = record
        return record


def render(report):
    esc = lambda v: html.escape(str(v), quote=True)
    parts = ['<!doctype html><html lang="ko"><meta charset="utf-8">',
             '<meta name="viewport" content="width=device-width,initial-scale=1">',
             '<title>고정 사례 원문 지지 판정 비교</title>',
             '<style>body{font:16px/1.6 system-ui;max-width:1100px;margin:auto;padding:20px}pre,blockquote{white-space:pre-wrap;overflow-wrap:anywhere}article{border-top:1px solid #999;padding:12px}</style>',
             '<h1>고정 사례 원문 지지 판정 비교</h1>',
             '<p>비공개 개발 평가입니다. 이전 assistant 기대값이며 독립 gold/서비스 승인/새 agent 생성이 아닙니다. 영어 전용 모델의 한국어 사례는 범위 밖 스트레스 검사입니다.</p>',
             '<pre>'+esc(json.dumps(report['summary'], ensure_ascii=False, indent=2))+'</pre>']
    for row in report['results']:
        parts.append('<article><h2>'+esc(row['id'])+'</h2><p>기대 허용: '+esc(row['expected'])+'</p>')
        parts.append('<pre>'+esc(json.dumps(row['nli']['policies'], ensure_ascii=False, indent=2))+'</pre>')
        for key, check in row['nli']['checks'].items():
            parts.append('<details><summary>'+esc(key)+' · '+esc(check['result']['relation'])+'</summary>')
            parts.append('<blockquote>'+esc(check['premise'])+'</blockquote><p>→ '+esc(check['hypothesis'])+'</p>')
            parts.append('<pre>'+esc(json.dumps(check['result']['scores']))+'</pre></details>')
        parts.append('</article>')
    return '\n'.join(parts+['</html>'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['snapshot', 'baseline_report', 'reference_evaluation', 'frame_report']:
        parser.add_argument(name)
    parser.add_argument('--fixtures', default='tests/fixtures/claim-frame-cases.json')
    parser.add_argument('--run-dir', type=Path, required=True)
    args = parser.parse_args()
    if any((args.run_dir/name).exists() for name in ['report.json', 'overview.html']):
        parser.error('Completed output exists')
    baseline, cases = prepare_cases(args.snapshot, args.baseline_report, args.reference_evaluation, args.fixtures)
    frames = read_json(args.frame_report)
    if (frames['cases'] != cases or frames['baseline_sha256'] != sha(args.baseline_report)
            or frames['reference_sha256'] != sha(args.reference_evaluation)
            or frames['fixture_sha256'] != sha(args.fixtures)):
        parser.error('Frozen frame cases changed')
    require_live(baseline['expires_at'])
    manifest = {'artifact_kind': 'claim-support-diagnostic-0.1', 'expires_at': baseline['expires_at'],
                'snapshot_sha256': sha(args.snapshot), 'baseline_sha256': sha(args.baseline_report),
                'reference_sha256': sha(args.reference_evaluation), 'fixture_sha256': sha(args.fixtures),
                'frame_report_sha256': sha(args.frame_report), 'cases': cases, 'policies': POLICIES,
                'model': MODEL, 'revision': REVISION, 'threshold': THRESHOLD,
                'runtime_config': {'device': 'cpu', 'dtype': 'float32', 'threads': 6,
                                   'torch': version('torch'), 'transformers': version('transformers')},
                'next_stage_criterion': 'All fixed positive and negative cases correct in BOTH sets; no errors. Not quality certification.',
                'language_scope': 'English only; Korean fixture retained as out-of-scope stress case',
                'code_sha256': {p: sha(p) for p in [__file__, 'experiments/claim_frame_probe.py',
                    'src/commentscope/providers/local_nli.py']},
                'independent_gold': False, 'human_handling': False, 'service_time_input': False,
                'accepted_perspectives': 0}
    # Persist criteria/code/data identities before loading the local model or making predictions.
    model = None
    def score(premise, hypothesis):
        nonlocal model
        if model is None: model = LocalNLI()
        return model.score(premise, hypothesis)
    cached = CachedScores(args.run_dir, manifest, score)
    results = []
    for case in cases:
        result = evaluate_pair(case['anchor'], case['member'], cached)
        results.append({**case, 'nli': result})
        print(json.dumps({'id': case['id'], 'policies': result['policies']}), flush=True)
    summary = summarize(results)
    ready = {p: all(s[p]['positive_kept'] == s[p]['positive_total']
                   and s[p]['negative_blocked'] == s[p]['negative_total']
                   and not s[p]['cases_with_errors'] for s in summary.values()) for p in POLICIES}
    report = {**manifest, 'results': results, 'summary': summary, 'next_stage_eligible': ready,
              'unique_requests': len(cached.records),
              'inference_seconds': sum(r['seconds'] for r in cached.records.values()),
              'runtime': model.metadata if model is not None else {'cache_only': True},
              'limitations': ['Known development sample, not independent gold',
                  'Directional support permits weakening; mutual claims may reject valid common cores with different details',
                  'Invalid shared anchor blocks multiple members, not independent successes',
                  'NLI scores uncalibrated; no threshold tuning; Korean outside model scope',
                  'Different decision mechanisms, not model-weights-only comparison',
                  'No factory integration or agent creation in this experiment']}
    require_live(baseline['expires_at'])
    write_json_exclusive(args.run_dir/'report.json', report)
    with (args.run_dir/'overview.html').open('x', encoding='utf-8') as out:
        out.write(render(report))
    print(json.dumps({'summary': summary, 'next_stage_eligible': ready}, ensure_ascii=False), flush=True)


if __name__ == '__main__': main()
