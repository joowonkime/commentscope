"""Frozen source-selection, context ablation, confirmation and density-order diagnostics."""
import argparse
from collections import Counter
import html
from importlib.metadata import version
import json
from pathlib import Path

from commentscope.agents.profiles import require_live
from commentscope.factory import evidence_units, evidence_core, candidate_search, core_groups, grounded_core
from commentscope.factory.automatic import Calls, build_bundle, local_provider
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha, embed
from commentscope.ingestion import load_snapshot, normalize_snapshot
from commentscope.providers.local_nli import LocalNLI, MODEL, REVISION, THRESHOLD
from commentscope.storage import write_json_exclusive
from experiments.claim_support_probe import CachedScores
from experiments.grounded_core_probe import no_model, check_inputs
from experiments.shared_core_integration import profiles

FIXTURE = 'tests/fixtures/evidence-unit-cases.json'
CODE = [__file__, 'src/commentscope/factory/evidence_units.py', 'src/commentscope/factory/evidence_core.py',
        'src/commentscope/factory/candidate_search.py', 'src/commentscope/factory/core_groups.py',
        'src/commentscope/factory/grounded_core.py', 'src/commentscope/factory/qualification_guards.py',
        'src/commentscope/factory/shared_core.py', 'src/commentscope/factory/automatic.py',
        'src/commentscope/factory/automatic_contract.py', 'src/commentscope/factory/claim_clusters.py',
        'src/commentscope/cluster_baseline.py', 'src/commentscope/providers/local_nli.py',
        'src/commentscope/providers/local_llama.py', 'src/commentscope/agents/runtime.py',
        'experiments/claim_support_probe.py', 'experiments/shared_core_integration.py']


def source_plan(snapshot, baseline, full, prior):
    aliases = {r.comment_id: r.duplicate_of for r in normalize_snapshot(snapshot)}
    sources = {s.comment_id: s for s in snapshot.comments if not aliases[s.comment_id]}
    old64 = [r['source_comment_id'] for r in baseline['records']]
    dev = [r['source_id'] for r in prior['records']]
    assigned = {u for g in full['groups'] for u in g['member_ids']}
    excluded = set(old64+dev) | {u['source_comment_id'] for u in full['units'] if u['claim_id'] in assigned}
    confirmation = sorted((s for s in sources if s not in excluded),
                          key=lambda sid: (digest(['evidence-confirmation-20261012', sid]), sid))[:12]
    # Automatic density sampling of existing retrieval outputs, NOT membership labels.
    # Source-only extraction is redone; old generated claims never become new evidence.
    by_id = {u['claim_id']: u for u in full['units']}
    neighborhoods = []
    for uid, rows in full['candidates'].items():
        sid = by_id[uid]['source_comment_id']
        if sid not in sources or sid in confirmation: continue
        unique = {}
        for r in rows:
            other = by_id[r['claim_id']]['source_comment_id']
            if other in sources and other not in confirmation and other != sid:
                unique[other] = max(unique.get(other, -1), r['cosine'])
        ranked = sorted(unique, key=lambda x: (-unique[x], x))
        if len(ranked) >= 2: neighborhoods.append((unique[ranked[1]], uid, [sid, *ranked[:7]]))
    dense = []
    for _, _, group in sorted(neighborhoods, key=lambda x: (-x[0], x[1])):
        new = [sid for sid in group if sid not in dense]
        if len(new) < 3: continue
        dense.extend(new[:32-len(dense)])
        if len(dense) >= 32: break
    return {'development': dev, 'confirmation': confirmation, 'baseline64': old64, 'dense32': dense}


def render(report):
    esc = lambda v: html.escape(str(v), quote=True)
    p = ['<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
         '<title>원문 선택형 주장 생성 검증</title><style>body{font:16px/1.7 system-ui;max-width:1100px;margin:auto;padding:20px}pre,blockquote{white-space:pre-wrap;overflow-wrap:anywhere}article{border-top:1px solid #aaa;padding:12px}</style>',
         '<h1>원문 선택형 주장 생성 검증</h1><p>진단용. 원문 복사 불변조건과 의미 품질 검증은 별개이며 독립 gold가 아닙니다.</p>',
         '<pre>'+esc(json.dumps(report['summary'], ensure_ascii=False, indent=2))+'</pre>']
    for r in report.get('records', []):
        p += ['<article><h2>'+esc(r['source_id'])+'</h2><blockquote>'+esc(r['source'])+'</blockquote>']
        for u in r['result']['units']:
            p += ['<p>원문 선택 주장: '+esc(u['statement'])+'</p><p>주제 근거: '+esc(u['topic_quote'])+'</p>']
        p += ['<details><summary>선택·독립성·문맥 기록</summary><pre>'+esc(json.dumps(r['result'], ensure_ascii=False, indent=2))+'</pre></details></article>']
    for profile in report.get('profiles', []):
        p += ['<article><h2>'+esc(profile['title'])+'</h2>']
        for e in profile['evidence']: p += ['<blockquote>'+esc(e['original_text'])+'</blockquote>']
        p += ['</article>']
    return '\n'.join(p+['</html>'])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ['snapshot', 'baseline64', 'full_report', 'prior_sample']: p.add_argument(name)
    p.add_argument('--run-dir', type=Path, required=True)
    p.add_argument('--phase', choices=['probe', 'baseline64', 'dense32', 'verify'], required=True)
    p.add_argument('--diagnostic-only', action='store_true', required=True)
    args = p.parse_args()
    baseline, full, prior = map(read_json, [args.baseline64, args.full_report, args.prior_sample])
    build_bundle(args.snapshot, baseline); build_bundle(args.snapshot, full)
    snapshot = load_snapshot(args.snapshot).snapshot
    if len(snapshot.comments) > 1000: p.error('Snapshot limit1000')
    plan = source_plan(snapshot, baseline, full, prior)
    manifest = {'artifact_kind': 'evidence-units-probe-0.1', 'expires_at': snapshot.usage.expires_at,
                'inputs': {f: sha(f) for f in [args.snapshot, args.baseline64, args.full_report, args.prior_sample, FIXTURE]},
                'code_sha256': {f: sha(f) for f in CODE}, 'source_plan': plan, 'model': baseline['model'],
                'nli': {'model': MODEL, 'revision': REVISION, 'threshold': THRESHOLD},
                'runtime': {'torch': version('torch'), 'transformers': version('transformers'), 'device':'cpu',
                            'threads':6, 'temperature':0, 'seed':407, 'max_tokens':900},
                'policy': {'semantic_budget':64, 'seed_limit':2, 'min_sources':3, 'context_chars':500,
                           'selection_only':True, 'parent_context':False, 'manual_runtime_decisions':False},
                'quality_gate_passed':False, 'independent_gold':False,
                'confirmation_scope':'Source IDs withheld from this revision until code/fixtures frozen; not an untouched corpus (older full1000 used all sources).',
                'dense_scope':'Automatic nonrepresentative32-source functional sample from old retrieval geometry. Old claims/labels not given to the new extractor.',
                'criteria':'No invented unit text/source changes; content-free controls rejected; preserve positive assertions; inspect all emitted confirmation units and new profiles before any quality promotion.'}
    check_inputs(manifest)
    if args.phase == 'verify' and not (args.run_dir/'llm'/'manifest.json').exists(): p.error('Missing replay cache')
    calls = Calls(args.run_dir/'llm', manifest, no_model if args.phase == 'verify' else local_provider)
    nli_model = None
    def score(a, b):
        nonlocal nli_model
        if nli_model is None: nli_model = LocalNLI()
        return nli_model.score(a, b)
    scores = CachedScores(args.run_dir/'nli', manifest, no_model if args.phase == 'verify' else score)
    sources = {s.comment_id:s for s in snapshot.comments}
    def extract(ids):
        rows = []
        for sid in ids:
            text = sources[sid].text_original
            result = evidence_units.extract(sid, text, calls)
            for u in result['units']: evidence_units.validate_bound(u, text)
            rows.append({'source_id':sid, 'source':text, 'result':result})
            if args.phase != 'verify': print(json.dumps({'source':sid,'units':len(result['units'])}), flush=True)
        return rows
    def tally(rows):
        return {'sources':len(rows), 'units':sum(len(r['result']['units']) for r in rows),
                'represented_claim_sources':sum(bool(r['result']['units']) for r in rows),
                'rejected_candidates':dict(Counter(c['reason'] for r in rows for c in r['result']['candidates'] if c['reason']))}
    def store(name, report):
        check_inputs(manifest)
        report = {**manifest, **report}
        if args.phase == 'verify':
            if read_json(args.run_dir/(name+'.json')) != report: raise ValueError('Replay changed: '+name)
        else:
            write_json_exclusive(args.run_dir/(name+'.json'), report)
            with (args.run_dir/(name+'.html')).open('x',encoding='utf-8') as f: f.write(render(report))
    def probe():
        fixed = []
        for c in read_json(FIXTURE)['cases']:
            result = evidence_units.extract(c['id'], c['source'], calls)
            fixed.append({**c,'result':result})
        summary = {}
        for split in ['development','transfer']:
            subset = [r for r in fixed if r['split'] == split]
            summary[split] = {'positive_total':sum(r['expected'] for r in subset),
                              'positive_kept':sum(bool(r['expected'] and r['result']['units']) for r in subset),
                              'negative_total':sum(not r['expected'] for r in subset),
                              'negative_blocked':sum(bool(not r['expected'] and not r['result']['units']) for r in subset)}
        records = extract(plan['development'])
        summary['real_development'] = tally(records)
        confirmation = extract(plan['confirmation'])
        summary['real_confirmation'] = tally(confirmation)
        context = []
        for row in prior['records']:
            for u, before in zip(row['units'], row['checks']):
                # One controlled intervention: same proposed statement and same
                # checker, but include the complete OWN short comment as premise.
                after = grounded_core.verify(row['source'], u['statement'], calls, scores) if len(row['source']) <= 500 else None
                context.append({'claim_id':u['claim_id'], 'source_id':row['source_id'], 'statement':u['statement'],
                                'before':before, 'after':after})
        summary['context_ablation'] = {'claims':len(context), 'within_budget':sum(r['after'] is not None for r in context),
                                      'before_pass':sum(r['before']['allowed'] for r in context if r['after'] is not None),
                                      'after_pass':sum(r['after']['allowed'] for r in context if r['after'] is not None)}
        store('probe', {'summary':summary, 'fixtures':fixed, 'records':records,
                        'confirmation':confirmation, 'context_ablation':context})
        print(json.dumps(summary), flush=True)
    def integrate(split):
        records = extract(plan[split])
        units = [u for r in records for u in r['result']['units']]
        texts = [u['topic_quote']+'\n'+u['statement'] for u in units]
        vector_path = args.run_dir/(split+'-vectors.json')
        if vector_path.exists():
            v = read_json(vector_path)
            if v['texts'] != texts or v['vectors_sha256'] != digest(v['vectors']): raise ValueError('Embeddings changed')
            vectors = v['vectors']
        else:
            if args.phase == 'verify': raise RuntimeError('Missing embedding cache')
            vectors = embed(texts)
            write_json_exclusive(vector_path, {'texts':texts,'vectors':vectors,'vectors_sha256':digest(vectors)})
        candidates = candidate_search.search(units, vectors, 'cross_mode')
        def discover(a,b):
            result = evidence_core.discover(a,b,calls,scores)
            if args.phase != 'verify': print(json.dumps({'pair':a['claim_id'],'core':result['selected_core']}),flush=True)
            return result
        def attach(u, core): return evidence_core.check(u, core, calls, scores)
        assemblies = {}
        # Two seed orders, identical units/candidates/model/budget. Cache raw
        # requests so the second ordering does not reroll prior judgments.
        for order in ['degree','source_density']:
            assemblies[order] = core_groups.assemble(units,candidates,discover,attach,budget=64,
                                                    cross_mode=True,seed_order=order)
        assembly = assemblies['source_density']
        agents = profiles(snapshot,units,assembly)
        summary = {'extraction':tally(records),'retrieval':candidate_search.funnel(units,candidates),
                   'orders':{name:{'agents':len(a['groups']),'decisions':len(a['decisions']),
                                   'budget_exhausted':a['budget_exhausted'],
                                   'sources':len({u['source_comment_id'] for u in units if any(u['claim_id'] in g['member_ids'] for g in a['groups'])})}
                             for name,a in assemblies.items()}}
        store(split, {'summary':summary,'records':records,'units':units,'candidates':candidates,
                      'assemblies':assemblies,'profiles':agents})
        print(json.dumps(summary),flush=True)
    if args.phase == 'verify':
        probe()
        for split in ['baseline64','dense32']:
            if (args.run_dir/(split+'.json')).exists(): integrate(split)
        print(json.dumps({'verified':True,'new_model_calls':calls.new_calls}),flush=True)
    else:
        if (args.run_dir/(args.phase+'.json')).exists(): p.error('Completed output exists')
        if args.phase == 'probe': probe()
        else:
            if not (args.run_dir/'probe.json').exists(): p.error('Run fixed/confirmation probe first')
            integrate(args.phase)


if __name__ == '__main__': main()
