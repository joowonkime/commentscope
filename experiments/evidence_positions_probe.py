"""Frozen positional-topic ablation, final-window audit and source-level retrieval exposure."""
import argparse
from collections import Counter
import html
import json
from pathlib import Path

from commentscope.factory import evidence_positions as p, evidence_units as old, candidate_search
from commentscope.factory.automatic import Calls, local_provider
from commentscope.factory.automatic_contract import digest, segments
from commentscope.factory.claim_clusters import read_json, sha, embed, MODEL, REVISION
from commentscope.ingestion import load_snapshot
from commentscope.providers.schema_visible import SchemaVisibleCalls
from commentscope.storage import write_json_exclusive
from experiments.claim_frame_probe import prepare_cases
from experiments.grounded_core_probe import check_inputs, no_model

SNAPSHOT = 'data/ubi-research-20261010.json'
PRIOR = 'runs/evidence-units-20261012-visible/probe.json'
FULL = 'runs/automatic-factory-20261011-full1000/report.json'
REVIEW = 'artifacts/automatic-factory-20261011-assistant-evaluation.json'
UNIT_REVIEW = 'artifacts/evidence-units-evaluation-20261012.json'
FIXTURE = 'tests/fixtures/evidence-unit-cases.json'
INPUTS = [SNAPSHOT, PRIOR, FULL, REVIEW, UNIT_REVIEW, FIXTURE, 'tests/fixtures/claim-frame-cases.json']
CODE = ['experiments/evidence_positions_probe.py', 'src/commentscope/factory/evidence_positions.py',
        'src/commentscope/factory/evidence_units.py', 'src/commentscope/factory/candidate_search.py',
        'src/commentscope/factory/automatic.py', 'src/commentscope/factory/automatic_contract.py',
        'src/commentscope/providers/schema_visible.py', 'src/commentscope/providers/local_llama.py',
        'src/commentscope/factory/claim_clusters.py', 'src/commentscope/cluster_baseline.py',
        'experiments/claim_frame_probe.py']


def make_plan():
    snapshot = load_snapshot(SNAPSHOT).snapshot
    if len(snapshot.comments) > 1000: raise ValueError('Snapshot limit exceeded')
    sources = {s.comment_id: s.text_original for s in snapshot.comments}
    prior = read_json(PRIOR)
    if prior['inputs'][SNAPSHOT] != sha(SNAPSHOT): raise ValueError('Prior source hash changed')
    review = read_json(UNIT_REVIEW)
    if review['report_sha256'] != sha(PRIOR): raise ValueError('Review binding changed')
    _, pairs = prepare_cases(SNAPSHOT, FULL, REVIEW, INPUTS[-1])
    known = [c for c in pairs if c['kind'] == 'real_development' and c['expected'] and
             c['anchor']['source_comment_id'] != c['member']['source_comment_id']]
    rows = [{**c, 'split': 'fixed_'+c['split'], 'prior': c['result']} for c in prior['fixtures']]
    for split, key in [('real_development','records'), ('real_confirmation','confirmation')]:
        for c in prior[key]:
            if c['source'] != sources[c['source_id']]: raise ValueError('Source changed')
            rows.append({'id': c['source_id'], 'source': c['source'], 'split': split, 'prior': c['result']})
    included = {r['id'] for r in rows}
    for sid in sorted({c[k]['source_comment_id'] for c in known for k in ['anchor','member']} - included):
        rows.append({'id': sid, 'source': sources[sid], 'split': 'known_pair_endpoint', 'prior': None})
    return {'artifact_kind': 'evidence-positions-probe-0.1', 'expires_at': snapshot.usage.expires_at,
            'inputs': {f: sha(f) for f in INPUTS}, 'code_sha256': {f: sha(f) for f in CODE},
            'model': prior['model'], 'embedding': {'model': MODEL, 'revision': REVISION},
            'cases': rows, 'known_pairs': known, 'prior_unit_review': review['confirmation_review'],
            'policy': {'fixed_prior_selection': True, 'max_source_chars':4000, 'max_context_chars':500,
                       'parent_context':False, 'manual_runtime_decisions':False, 'new_agents':False},
            'quality_gate_passed':False, 'independent_gold':False,
            'criteria':'No text/offset mutation; preserve all8 fixed positives and reject all8 fixed negatives with no errors; inspect all confirmation units before any assembly.',
            'limitations':['Known development labels, no independent gold; prior confirmation is now regression data',
                           'Prior selection ranges are held fixed, so this is a downstream ablation not a fresh end-to-end extraction score',
                           'Topic prompt/schema/representation change together; not weights or temperature',
                           'Retrieval counts source exposure, NOT correct claim matching or membership; small nonrepresentative pool',
                           'No threshold tuning, new collection, full1000 rerun or default promotion']}


def failed(result):
    return bool((result['selection'] or {}).get('errors') or any(
        (c.get('topic') or {}).get('errors') or ((c.get('final') or {}).get('result') or {}).get('errors')
        for c in result['candidates']))


def summarize(rows):
    output = {}
    for split in sorted({r['split'] for r in rows}):
        group = [r for r in rows if r['split'] == split]
        s = {'sources':len(group), 'sources_with_errors':sum(failed(r['result']) for r in group),
             'position_units':sum(len(r['result']['position_units']) for r in group),
             'final_units':sum(len(r['result']['units']) for r in group),
             'reasons':dict(Counter(c['reason'] for r in group for c in r['result']['candidates'] if c['reason']))}
        if split.startswith('fixed_'):
            for policy in ['position_units', 'units']:
                s[policy+'_quality'] = {'positive_total':sum(r['expected'] for r in group),
                    'positive_kept':sum(bool(r['expected'] and r['result'][policy]) for r in group),
                    'negative_total':sum(not r['expected'] for r in group),
                    'negative_blocked':sum(not r['expected'] and not r['result'][policy] and not failed(r['result']) for r in group)}
        output[split] = s
    return output


def retrieval_summary(units, links, pairs):
    by_source = {}
    by_id = {u['claim_id']:u for u in units}
    for u in units: by_source.setdefault(u['source_comment_id'], []).append(u['claim_id'])
    records = []
    for c in pairs:
        a,b = [c[k]['source_comment_id'] for k in ['anchor','member']]
        hits = [{'anchor_unit': uid, 'member_unit': r['claim_id'], 'rank':i+1}
                for uid in by_source.get(a, []) for i,r in enumerate(links[uid])
                if by_id[r['claim_id']]['source_comment_id'] == b]
        records.append({'pair_id':c['id'], 'anchor_source':a, 'member_source':b,
                        'both_sources_retained':a in by_source and b in by_source,
                        'source_exposed':bool(hits), 'hits':hits})
    return {'known_pairs':len(records), 'both_sources_retained':sum(r['both_sources_retained'] for r in records),
            'source_exposed':sum(r['source_exposed'] for r in records), 'pairs':records,
            'funnel':candidate_search.funnel(units, links)}


def render(report):
    esc = lambda x:html.escape(str(x),quote=True)
    page = ['<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
            '<title>원문 위치와 최종 근거 검사</title><style>body{font:16px/1.7 system-ui;max-width:1100px;margin:auto;padding:20px}pre,blockquote{white-space:pre-wrap;overflow-wrap:anywhere}article{border-top:1px solid #aaa}</style>',
            '<h1>원문 위치와 최종 근거 검사</h1><p>개발 진단. 독립 gold/서비스 승인/새 agent 생성 아님. 검색은 상대 source 노출이지 의미 연결 성공이 아닙니다.</p>',
            '<pre>'+esc(json.dumps(report['summary'],ensure_ascii=False,indent=2))+'</pre>']
    for r in report.get('records',[]):
        page += ['<article><h2>'+esc(r['id'])+'</h2><blockquote>'+esc(r['source'])+'</blockquote>']
        for c in r['result']['candidates']:
            page += ['<p>선택: '+esc(c['focus'])+'</p><p>보류 이유: '+esc(c['reason'])+'</p>']
            if c['unit']:
                page += ['<p>주제: '+esc(c['unit']['topic_quote'])+'</p><blockquote>'+esc(''.join(s['text'] for s in c['unit']['spans']))+'</blockquote>']
        page += ['<details><summary>원시 판정 및 위치</summary><pre>'+esc(json.dumps(r['result'],ensure_ascii=False,indent=2))+'</pre></details></article>']
    return '\n'.join(page+['</html>'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir',type=Path,required=True)
    parser.add_argument('--phase',choices=['plan','extract','retrieval','verify'],required=True)
    parser.add_argument('--diagnostic-only',action='store_true',required=True)
    args = parser.parse_args(); path = args.run_dir/'plan.json'
    if args.phase == 'plan':
        plan = make_plan(); check_inputs(plan); write_json_exclusive(path,plan)
        print({'cases':len(plan['cases']),'known_pairs':len(plan['known_pairs']),'plan_sha256':sha(path)}); return
    plan = read_json(path); check_inputs(plan)
    replay = args.phase == 'verify'
    def save(name, report):
        check_inputs(plan)
        if replay:
            if read_json(args.run_dir/(name+'.json')) != report: raise ValueError('Replay changed: '+name)
        else:
            write_json_exclusive(args.run_dir/(name+'.json'),report)
            with (args.run_dir/(name+'.html')).open('x',encoding='utf-8') as f:f.write(render(report))
    if args.phase in ['extract','verify']:
        if not replay and (args.run_dir/'extract.json').exists(): parser.error('Completed output exists')
        raw = Calls(args.run_dir/'llm',plan,no_model if replay else local_provider)
        visible = SchemaVisibleCalls(raw,[old.SELECT_SYSTEM,p.TOPIC_SYSTEM,p.FINAL_SYSTEM])
        records = []
        for c in plan['cases']:
            def calls(system,data,schema):
                if system == old.SELECT_SYSTEM and c['prior'] is not None:
                    if data != {'COMMENT':segments(c['source'])}: raise ValueError('Selection input changed')
                    selection = c['prior']['selection']
                    return {'output':selection['output'], 'errors':selection['errors']}
                return visible(system,data,schema)
            result = p.extract(c['id'],c['source'],calls)
            for u in result['position_units']: p.validate_bound(u,c['source'])
            legacy = {u['claim_id']:p.final_check(u,visible) for u in (c['prior'] or {}).get('units',[])}
            records.append({**c,'result':result,'legacy_final':legacy})
            if not replay: print(json.dumps({'case':c['id'],'position':len(result['position_units']), 'final':len(result['units'])}),flush=True)
        report = {'plan_sha256':sha(path),'records':records,'summary':summarize(records)}
        save('extract',report)
        print(json.dumps(report['summary']),flush=True)
        if replay: print({'new_model_calls':raw.new_calls})
    if args.phase in ['retrieval','verify']:
        if not replay and (args.run_dir/'retrieval.json').exists(): parser.error('Completed output exists')
        extraction = read_json(args.run_dir/'extract.json')
        if extraction['plan_sha256'] != sha(path): raise ValueError('Extraction plan changed')
        real = [r for r in extraction['records'] if not r['split'].startswith('fixed_')]
        pools = {'raw_source':[{'claim_id':r['id'],'source_comment_id':r['id'],'statement':r['source'],'mode':'source_literal'} for r in real]}
        pools.update({key:[u for r in real for u in r['result'][key]] for key in ['position_units','units']})
        results = {}
        for name,units in pools.items():
            texts = [u['statement'] if name == 'raw_source' else u['topic_quote']+'\n'+u['statement'] for u in units]
            vp = args.run_dir/(name+'-vectors.json')
            if vp.exists():
                v = read_json(vp)
                if v['texts'] != texts or digest(v['vectors']) != v['vectors_sha256']: raise ValueError('Vectors changed')
                vectors = v['vectors']
            else:
                if replay: raise RuntimeError('Replay attempted embedding inference')
                vectors = embed(texts)
                write_json_exclusive(vp,{'texts':texts,'vectors':vectors,'vectors_sha256':digest(vectors)})
            results[name] = {}
            for policy in ['cross_mode','hybrid']:
                links = candidate_search.search(units,vectors,policy)
                results[name][policy] = {'summary':retrieval_summary(units,links,plan['known_pairs']),'links':links}
        report = {'plan_sha256':sha(path),'extraction_sha256':sha(args.run_dir/'extract.json'), 'results':results,
                  'summary':{k:{p:v['summary'] for p,v in m.items()} for k,m in results.items()}}
        save('retrieval',report); print(json.dumps(report['summary']),flush=True)
    if replay: print({'verified':True,'new_embedding_calls':0})


if __name__ == '__main__': main()
