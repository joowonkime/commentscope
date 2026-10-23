"""One frozen development comparison of fixed-core membership vs matched V1/V2.

Reuses extraction, embeddings and candidates. No new prompt, generated details,
human labels as runtime input, agent publication, or reserved-pool access.
"""
import argparse
from collections import Counter
import html
import json
from pathlib import Path

from commentscope.agents.profiles import require_live
from commentscope.factory import fixed_core as core
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.factory.draft_audit import audit_pairs
from commentscope.storage import write_json_exclusive as write
from experiments import matched_factory_probe as prior
from experiments.audit_model_compare import owned_server, file_hash

VERSION = 'fixed-core-probe-0.1'
POLICY = {'cores_per_candidate': 3, 'minimum_sources': 3,
          'max_calls': 96, 'max_generation_seconds': 600,
          'audit_prompt_revision': 'v2', 'max_tokens': 300,
          'request_utf8_bytes': 30000, 'retries': 0, 'repairs': 0}


def make_plan(origin):
    prior.verify(origin)
    previous = read_json(origin/'plan.json')
    extraction = read_json(origin/'extraction.json')
    vectors = read_json(origin/'claim-vectors.json')
    v1 = read_json(origin/'V1.json')
    if vectors['texts'] != [u['statement'] for u in extraction['units']]:
        raise ValueError('Embedding text alignment mismatch')
    groups = prior.candidates(extraction['units'], vectors['vectors'], previous['threshold'])
    if groups != v1['candidates']:
        raise ValueError('Candidate replay mismatch')
    selection = core.select_cores(extraction['units'], vectors['vectors'], groups, previous['sources'], POLICY['cores_per_candidate'])
    paths = [origin/name for name in ['plan.json','extraction.json','claim-vectors.json','V1.json','V2.json','completed.json']]
    paths += [Path(p) for p in previous['inputs']]
    files = sorted({str(p) for base in ['src/commentscope','experiments'] for p in Path(base).rglob('*.py')})
    return {'artifact_kind': VERSION, 'expires_at': previous['expires_at'],
            'inputs': {str(p): sha(p) for p in paths}, 'code_sha256': {p: sha(p) for p in files},
            'origin': str(origin), 'policy': POLICY, 'sources': previous['sources'],
            'selection': selection, 'server': previous['server'], 'models': previous['models'],
            'runtime': {**previous['runtime'], 'max_tokens': 300, 'max_seconds_per_model': 600},
            'expected_relations': sum(len(c['source_ids']) for c in selection['cores']),
            'criteria': {'faithful_ge3_cards_min': 1, 'bad_bindings_in_ge3_cards_max': 0,
                         'inflation_three_source_core_retained': True,
                         'contradicting_work_source_not_joined_to_no_work_claim': True,
                         'errors_max': 0, 'deferrals_max': 0,
                         'on_failure': 'Stop this 4B prompt/auditor iteration family; no reserve or 1000 expansion.',
                         'on_pass': 'Eligible for one reserved development comparison; not service approval.'},
            'comparison': 'Package comparison to saved matched V1/V2, not isolated causal ablation; cached extraction/retrieval costs excluded.',
            'new_boundary': 'Immutable extracted target, independent overlapping membership, original quotations instead of generated details.',
            'not_new': 'Fixed targets already exist in raw_support/grounded_core. This removes the joint assignment/draft stage from matched V1 without their NLI/guard cascade.',
            'quality_gate_passed': False, 'agents': [], 'independent_gold': False}


def check(plan, model_files=False):
    require_live(plan['expires_at'])
    if plan['artifact_kind'] != VERSION or plan['policy'] != POLICY:
        raise ValueError('Unknown configuration')
    for field in ['inputs', 'code_sha256']:
        if any(sha(p) != h for p,h in plan[field].items()):
            raise ValueError('Frozen inputs/code changed')
    if model_files:
        for info in [plan['server'], *plan['models'].values()]:
            if file_hash(info['path']) != info['sha256']:
                raise ValueError('Model/server changed')


class Judge:
    def __init__(self, plan, root, provider=prior.generate):
        self.calls = prior.Calls(plan, root, provider)
        self.cache = {}

    def __call__(self, candidate, source):
        require_live(self.calls.plan['expires_at'])
        key = digest([candidate['text'], source['source_id'], source['text']])
        if key in self.cache:
            return self.cache[key]
        if sum(self.calls.counts.values()) >= POLICY['max_calls'] or self.calls.seconds >= POLICY['max_generation_seconds']:
            return {'verdict': None, 'reason': None, 'errors': ['budget_deferred'], 'request_id': None}
        records = []
        def provider(system, data, schema):
            record = self.calls.invoke('audit', system, data, schema)
            records.append(record)
            return record['response'] or {}
        result = audit_pairs({'P01': {'text': candidate['text'], 'member_id': 'M01'}},
                             {'M01': {'target': source['text']}}, provider, prompt_revision='v2')
        record = records[0]
        errors = record['result']['errors'] + result['errors']
        self.cache[key] = {'request_id': record['id'], 'request_sha256': record['request_sha256'],
                           'verdict': None if errors else result['output']['P01']['verdict'],
                           'reason': None if errors else result['output']['P01']['reason'], 'errors': errors}
        return self.cache[key]


def render(report, sources):
    esc = lambda x: html.escape(str(x), quote=True)
    originals = {s['source_id']: s['text'] for s in sources}
    out = ['<!doctype html><html lang="ko"><meta charset="utf-8"><title>고정 주장 · 독립 가입 비교</title>',
           '<style>body{font:16px/1.65 system-ui;max-width:1100px;margin:auto;padding:24px}article{border-top:2px solid #888}blockquote,pre{white-space:pre-wrap;overflow-wrap:anywhere}.model_supported{border-left:4px solid #397;padding-left:12px}</style>',
           '<h1>고정 주장 → 원문별 가입 → 지지 집계</h1><p>개발 비교입니다. 모델 지지는 검증된 관점/agent가 아닙니다. 상세 주장을 새로 생성하지 않았습니다.</p>',
           '<pre>'+esc(json.dumps(report['summary'], ensure_ascii=False, indent=2))+'</pre>']
    for card in report['membership']['cards']:
        target = card['core']
        out += ['<article id="'+esc(target['id'])+'"><h2>'+esc(target['candidate_id'])+' / '+esc(target['text'])+'</h2>',
                '<p>모델 잠정 지지: '+str(card['model_support_count'])+' · '+esc(card['status'])+'</p>']
        for relation in card['relations']:
            sid = relation['source_id']
            out += ['<section class="'+esc(relation['state'])+'"><h3>'+esc(sid)+' · '+esc(relation['state'])+'</h3>',
                    '<blockquote>'+esc(originals[sid])+'</blockquote><pre>'+esc(json.dumps(relation['judgment'], ensure_ascii=False, indent=2))+'</pre></section>']
        out.append('</article>')
    return '\n'.join(out+['</html>'])


def execute(plan, root):
    check(plan, True)
    write(root/'started.json', {'plan_sha256': sha(root/'plan.json')})
    judge = Judge(plan, root)
    with owned_server(plan, 'baseline', root/'server'):
        membership = core.memberships(plan['selection'], plan['sources'], judge, POLICY['minimum_sources'])
    relations = [r for c in membership['cards'] for r in c['relations']]
    summary = {'source_denominator': len(plan['sources']), 'cores': len(membership['cards']),
               'relations': len(relations), 'states': dict(Counter(r['state'] for r in relations)),
               'cards_ge3': sum(c['model_support_count'] >= 3 for c in membership['cards']),
               'fresh_calls': sum(judge.calls.counts.values()), 'generation_seconds': judge.calls.seconds,
               'cached_extraction_and_embedding': True, 'generated_details': 0,
               'errors': sum(r['state'] == 'error' for r in relations),
               'deferrals': sum('budget_deferred' in r['judgment']['errors'] for r in relations),
               'quality_gate_passed': False, 'agents': [], 'semantic_review': 'pending_offline_assistant_review'}
    report = {'artifact_kind': VERSION, 'plan_sha256': sha(root/'plan.json'), 'summary': summary, 'membership': membership}
    write(root/'report.json', report)
    with (root/'overview.html').open('x', encoding='utf-8') as f:
        f.write(render(report, plan['sources']))
    write(root/'completed.json', {'plan_sha256': sha(root/'plan.json'), 'artifact_sha256': {
        str(p.relative_to(root)): sha(p) for p in sorted(root.rglob('*')) if p.is_file()}})
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


def verify(root):
    plan = read_json(root/'plan.json'); check(plan)
    manifest = read_json(root/'completed.json')
    if manifest['plan_sha256'] != sha(root/'plan.json') or any(sha(root/p) != h for p,h in manifest['artifact_sha256'].items()):
        raise ValueError('Artifact identity changed')
    report = read_json(root/'report.json')
    records = {read_json(p)['id']: read_json(p) for p in sorted((root/'calls').glob('*.json'))}
    def replay(candidate, source):
        saved = next(r['judgment'] for c in report['membership']['cards'] if c['core']['id'] == candidate['id']
                     for r in c['relations'] if r['source_id'] == source['source_id'])
        if saved['request_id'] is None:
            return saved
        record = records[saved['request_id']]
        def provider(system, data, schema):
            expected = {'system': prior.visible_system(system, schema), 'data': data, 'schema': schema, 'max_tokens': POLICY['max_tokens']}
            if record['request'] != expected or record['request_sha256'] != digest(expected):
                raise ValueError('Source/target request changed')
            return record['response'] or {}
        result = audit_pairs({'P01': {'text': candidate['text'], 'member_id': 'M01'}}, {'M01': {'target': source['text']}}, provider, prompt_revision='v2')
        errors = record['result']['errors'] + result['errors']
        expected = {'request_id': record['id'], 'request_sha256': record['request_sha256'],
                    'verdict': None if errors else result['output']['P01']['verdict'],
                    'reason': None if errors else result['output']['P01']['reason'], 'errors': errors}
        if saved != expected:
            raise ValueError('Saved judgment changed')
        return expected
    if core.memberships(plan['selection'], plan['sources'], replay) != report['membership']:
        raise ValueError('Membership replay mismatch')
    print({'verified': True, 'fresh_calls': 0, 'plan_sha256': sha(root/'plan.json')})


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--run-dir', type=Path, required=True)
    ap.add_argument('--origin', type=Path, default=Path('runs/matched-factory-20261013'))
    ap.add_argument('--phase', choices=['prepare','run','verify'], required=True)
    args = ap.parse_args()
    if args.phase == 'prepare':
        plan = make_plan(args.origin); check(plan, True)
        if plan['expected_relations'] > POLICY['max_calls']:
            raise ValueError('Selection exceeds frozen call budget')
        write(args.run_dir/'plan.json', plan)
        print({'plan_sha256': sha(args.run_dir/'plan.json'), 'cores': len(plan['selection']['cores']), 'relations': plan['expected_relations']})
    elif args.phase == 'run':
        execute(read_json(args.run_dir/'plan.json'), args.run_dir)
    else:
        verify(args.run_dir)


if __name__ == '__main__':
    main()
