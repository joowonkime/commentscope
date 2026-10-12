"""Frozen local NLI/eligibility comparator; no factory or clustering mutations."""
import argparse
import html
from importlib.metadata import version
import json
from pathlib import Path
import statistics

from commentscope.agents.profiles import require_live
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.ingestion import load_snapshot
from commentscope.providers import local_nli, local_openjev
from commentscope.storage import write_json_exclusive
from experiments.claim_support_probe import CachedScores, accepted

INPUTS = ['data/ubi-research-20261010.json', 'runs/grounded-core-new-sample-20261012/report.json',
          'artifacts/grounded-core-evaluation-20261012.json',
          'tests/fixtures/core-fidelity-cases.json', 'tests/fixtures/openjev-transfer-cases.json',
          'tests/fixtures/evidence-unit-cases.json']
CODE = ['experiments/openjev_probe.py', 'src/commentscope/providers/local_openjev.py',
        'src/commentscope/providers/local_nli.py', 'experiments/claim_support_probe.py',
        'src/commentscope/factory/automatic_contract.py', 'src/commentscope/storage.py']
ELIGIBILITY_TARGET = ('The author makes at least one substantive assertion about an identifiable topic: '
                      'an opinion, experience, prediction, recommendation, or explanation. '
                      'Its references can be resolved within this comment; it is not merely a question, '
                      'joke, bare agreement, unendorsed quotation, or video-arrival chatter.')
REVIEW_LABELS = {'source_faithful': True, 'faithful_paraphrase_overrejected': True,
                 'unsupported_added_meaning': False, 'unsupported_reference_resolution': False,
                 'unsupported_causal_rewrite': False}


def make_plan():
    snapshot = load_snapshot(INPUTS[0]).snapshot
    require_live(snapshot.usage.expires_at)
    if len(snapshot.comments) > 1000: raise ValueError('Snapshot exceeds1000')
    prior, review = read_json(INPUTS[1]), read_json(INPUTS[2])
    if (review['artifacts']['new_sample']['sha256'] != sha(INPUTS[1]) or
            prior['inputs'][INPUTS[0]] != sha(INPUTS[0])): raise ValueError('Review/source binding changed')
    labels = {r['claim_id']: r for r in review['new_sample_claim_reviews']}
    sources = {s.comment_id: s.text_original for s in snapshot.comments}
    cases, excluded = [], []
    for path, split in [(INPUTS[3], 'fidelity_development'), (INPUTS[4], 'fidelity_transfer')]:
        for c in read_json(path)['cases']:
            cases.append({**c, 'split': split, 'task': 'fidelity', 'label_origin': path})
    seen = set()
    for row in prior['records']:
        if sources[row['source_id']] != row['source']: raise ValueError('Original source changed')
        for u in row['units']:
            seen.add(u['claim_id'])
            for span in u['spans']:
                if row['source'][span['start']:span['end']] != span['text']: raise ValueError('Span changed')
            label = labels[u['claim_id']]
            if label['assessment'] not in REVIEW_LABELS:
                excluded.append({'id': u['claim_id'], 'reason': label['assessment']})
                continue
            cases.append({'id': u['claim_id'], 'split': 'fidelity_real_development', 'task': 'fidelity',
                          'source': '\n'.join(s['text'] for s in u['spans']), 'target': u['statement'],
                          'expected': REVIEW_LABELS[label['assessment']], 'label_origin': INPUTS[2],
                          'source_id': row['source_id'], 'assessment': label['assessment']})
    if seen != set(labels): raise ValueError('Review inventory changed')
    for c in read_json(INPUTS[5])['cases']:
        cases.append({'id': 'eligibility:'+c['id'], 'split': 'eligibility_'+c['split'], 'task': 'eligibility',
                      'source': c['source'], 'target': ELIGIBILITY_TARGET, 'expected': c['expected'],
                      'label_origin': INPUTS[5]})
    validate_cases(cases)
    return {'artifact_kind': 'openjev-diagnostic-plan-0.1', 'expires_at': snapshot.usage.expires_at,
            'inputs': {p: sha(p) for p in INPUTS}, 'code_sha256': {p: sha(p) for p in CODE},
            'cases': cases, 'excluded': excluded,
            'models': {'deberta': {'model': local_nli.MODEL, 'revision': local_nli.REVISION, 'device': 'cpu'},
                       'openjev': {'model': local_openjev.MODEL, 'revision': local_openjev.REVISION,
                                   'subfolder': local_openjev.SUBFOLDER, 'device': 'cpu'}},
            'policy': {'threshold': .8, 'threshold_tuning': False, 'max_chars': 500, 'max_tokens': 512,
                       'batch_size': 1, 'parent_context': False, 'generation': False},
            'quality_gate_passed': False, 'independent_gold': False, 'service_time_input': False,
            'promotion_criterion': 'No false approvals or lost positives on frozen fidelity and transfer controls, improved known errors, followed by independent real evaluation; this experiment alone cannot promote.',
            'limitations': ['Known assistant development labels, not independent gold',
                            'Real nuance/context-missing/eligibility-only labels excluded BEFORE inference',
                            'NLI support and substantive eligibility are separate tasks',
                            'Equal threshold does not imply calibrated or equally conservative models',
                            'Same CPU/threads/float32, different tokenizers and transformers versions: operational latency, not a universal speed claim',
                            'OpenJev2B is not commercial Jev or OpenJev4B; English only',
                            'No claim extraction, cluster assembly, new agents or full1000 rerun']}


def validate_cases(cases):
    if not cases or len({c['id'] for c in cases}) != len(cases): raise ValueError('Invalid case inventory')
    for c in cases:
        if type(c['expected']) is not bool or c['task'] not in ('fidelity', 'eligibility'):
            raise ValueError('Invalid case label')
        local_openjev.format_pair(c['source'], c['target'])


def check_plan(plan):
    require_live(plan['expires_at'])
    for field in ['inputs', 'code_sha256']:
        if any(sha(p) != h for p, h in plan[field].items()): raise ValueError('Frozen inputs/code changed')
    validate_cases(plan['cases'])


def summarize(cases, records):
    result = {}
    for split in sorted({c['split'] for c in cases}):
        rows = [c for c in cases if c['split'] == split]
        def ok(c): return not records[c['id']]['errors']
        def allowed(c): return accepted(records[c['id']])
        result[split] = {'positive_total': sum(c['expected'] for c in rows),
                         'positive_kept': sum(c['expected'] and ok(c) and allowed(c) for c in rows),
                         'negative_total': sum(not c['expected'] for c in rows),
                         'negative_blocked': sum(not c['expected'] and ok(c) and not allowed(c) for c in rows),
                         'errors': sum(not ok(c) for c in rows),
                         'unclear': sum(ok(c) and records[c['id']]['relation'] == 'unclear' for c in rows),
                         'false_acceptance_ids': [c['id'] for c in rows if not c['expected'] and ok(c) and allowed(c)],
                         'false_rejection_ids': [c['id'] for c in rows if c['expected'] and ok(c) and not allowed(c)]}
    return result


def render(report):
    esc = lambda v: html.escape(str(v), quote=True)
    p = ['<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
         '<title>OpenJev 로컬 판정 비교</title><style>body{font:16px/1.7 system-ui;max-width:1100px;margin:auto;padding:20px}pre,blockquote{white-space:pre-wrap;overflow-wrap:anywhere}td,th{border:1px solid #aaa;padding:8px}table{border-collapse:collapse}article{border-top:1px solid #aaa;margin-top:20px}</style>',
         '<h1>OpenJev 로컬 판정 비교</h1><p>진단 전용. TypeSafe Jev의 시험이 아니며 독립 gold/품질 승인/새 agent 생성이 아닙니다.</p>',
         '<p>원문 지지와 독립 주장 여부를 따로 평가합니다. 실행 오류는 올바른 거절로 세지 않습니다. 같은 CPU이지만 tokenizer와 라이브러리가 달라 보편적 속도 우열로 일반화하지 않습니다.</p>',
         '<table><tr><th>표본</th><th>DeBERTa 정상/제외</th><th>OpenJev 정상/제외</th></tr>']
    for split in report['summaries']['deberta']:
        p.append('<tr><td>'+esc(split)+'</td>')
        for name in ['deberta', 'openjev']:
            s = report['summaries'][name][split]
            p.append('<td>'+esc(f"{s['positive_kept']}/{s['positive_total']} · {s['negative_blocked']}/{s['negative_total']} (errors {s['errors']})")+'</td>')
        p.append('</tr>')
    p.append('</table>')
    for c in report['cases']:
        p += ['<article><h2>'+esc(c['id'])+'</h2><p>'+esc(c['task'])+' / 기대 승인 '+esc(c['expected'])+'</p>',
              '<blockquote>'+esc(c['source'])+'</blockquote><p>검사 대상: '+esc(c['target'])+'</p>']
        for name in ['deberta', 'openjev']:
            r = report['records'][name][c['id']]
            p += ['<p>'+esc(name)+': '+esc(r['relation'])+' · entailment '+esc((r['scores'] or {}).get('entailment'))+'</p>']
        p.append('</article>')
    p += ['<h2>런타임 및 한계</h2><pre>'+esc(json.dumps(report['performance'], ensure_ascii=False, indent=2))+'</pre>',
          '<pre>'+esc(json.dumps(report['limitations'], ensure_ascii=False, indent=2))+'</pre></html>']
    return '\n'.join(p)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run-dir', type=Path, required=True)
    p.add_argument('--phase', choices=['plan', 'deberta', 'openjev', 'report', 'verify'], required=True)
    p.add_argument('--diagnostic-only', action='store_true', required=True)
    args = p.parse_args()
    path = args.run_dir/'plan.json'
    if args.phase == 'plan':
        plan = make_plan(); write_json_exclusive(path, plan)
        print(json.dumps({'cases': len(plan['cases']), 'excluded': len(plan['excluded']), 'plan_sha256': sha(path)})); return
    plan = read_json(path); check_plan(plan)
    if args.phase in ['deberta', 'openjev']:
        name = args.phase; directory = args.run_dir/name
        if (directory/'report.json').exists(): p.error('Completed model output exists')
        manifest = {'expires_at': plan['expires_at'], 'plan_sha256': sha(path), 'model': plan['models'][name],
                    'runtime': {'torch': version('torch'), 'transformers': version('transformers'),
                                'dtype': 'float32', 'threads': 6}}
        model = None
        def score(a, b):
            nonlocal model
            if model is None:
                model = local_nli.LocalNLI() if name == 'deberta' else local_openjev.LocalOpenJev(device='cpu')
                if not (directory/'runtime.json').exists(): write_json_exclusive(directory/'runtime.json', model.metadata)
            return model.score(a, b)
        cached = CachedScores(directory, manifest, score)
        records = {}
        for c in plan['cases']:
            # The only model arguments: original premise and fixed hypothesis. No labels, IDs, or other judge results.
            records[c['id']] = cached(c['source'], c['target'])
            print(json.dumps({'case': c['id'], 'relation': records[c['id']]['relation'],
                              'errors': records[c['id']]['errors']}), flush=True)
        check_plan(plan)
        times = sorted(r['seconds'] for r in cached.records.values())
        performance = {'unique_requests': len(times), 'sum_request_seconds': sum(times),
                       'p50_request_seconds': statistics.median(times),
                       'p95_request_seconds': times[min(len(times)-1, int(.95*len(times)))],
                       'peak_allocated_bytes': max((r.get('peak_allocated_bytes', 0) for r in records.values()), default=0),
                       'runtime': read_json(directory/'runtime.json'),
                       'note': 'Includes cold first scoring call; model loading is separate. Same CPU/threads/float32, different libraries/tokenizers. Cached timings retained; no universal speed claim.'}
        try:
            import resource
            performance['process_peak_rss_kib'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        except ImportError:
            performance['process_peak_rss_kib'] = None
        write_json_exclusive(directory/'report.json', {'manifest': manifest, 'records': records,
                             'summary': summarize(plan['cases'], records), 'performance': performance})
    else:
        models = {name: read_json(args.run_dir/name/'report.json') for name in ['deberta', 'openjev']}
        for name, stored in models.items():
            if stored['manifest']['plan_sha256'] != sha(path): raise ValueError('Model plan changed')
            if stored['manifest']['model'] != plan['models'][name]: raise ValueError('Model identity changed')
            def forbidden(*unused): raise RuntimeError('Replay attempted model inference')
            cached = CachedScores(args.run_dir/name, stored['manifest'], forbidden)
            records = {c['id']: cached(c['source'], c['target']) for c in plan['cases']}
            if records != stored['records'] or summarize(plan['cases'], records) != stored['summary']:
                raise ValueError('Model replay changed')
        report = {**plan, 'plan_sha256': sha(path),
                  'records': {n: m['records'] for n, m in models.items()},
                  'summaries': {n: m['summary'] for n, m in models.items()},
                  'performance': {n: m['performance'] for n, m in models.items()}}
        if args.phase == 'verify':
            if read_json(args.run_dir/'report.json') != report: raise ValueError('Comparison changed')
            print(json.dumps({'verified': True, 'new_model_calls': 0}))
        else:
            write_json_exclusive(args.run_dir/'report.json', report)
            with (args.run_dir/'overview.html').open('x', encoding='utf-8') as f: f.write(render(report))
            print(json.dumps(report['summaries']), flush=True)


if __name__ == '__main__': main()
