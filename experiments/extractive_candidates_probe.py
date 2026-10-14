"""Frozen extractive baseline: no generated proposals or manual selection at runtime."""
import argparse
from collections import Counter
import html
import json
from pathlib import Path
import time

from commentscope.factory import extractive_candidates as e, positional_support as p
from commentscope.factory.automatic import Calls, local_provider
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha, embed, MODEL, REVISION
from commentscope.providers.schema_visible import SchemaVisibleCalls
from commentscope.providers.local_nli import LocalNLI
from commentscope.providers.raw_nli import score_full
from commentscope.storage import write_json_exclusive
from experiments import component_isolation_probe as prior
from experiments.raw_support_probe import source
from experiments.grounded_core_probe import check_inputs, no_model
from experiments.claim_support_probe import CachedScores

ORIGIN = Path('runs/component-isolation-20261012')
POSITIONAL = Path('runs/positional-support-20261012')
CODE = [*prior.CODE, 'src/commentscope/factory/extractive_candidates.py',
        'experiments/extractive_candidates_probe.py']


def make_plan():
    old = read_json(ORIGIN/'plan.json'); check_inputs(old)
    pos = read_json(POSITIONAL/'report.json')
    refs = {c['id']:c for c in old['cases']}
    cases = []
    for c in pos['pair_controls']:
        cases.append({'id':c['id'],'kind':'synthetic_development','sources':[
            source(c['id']+':a',c['left']),source(c['id']+':b',c['right'])],
            'evaluation_only':{'pair_expected':c['expected'],
                               'reference_spans':refs[c['id']]['reference_spans'] if c['id'] in refs else [],
                               'confidence':refs[c['id']]['reference_confidence'] if c['id'] in refs else 'existing_negative_pair'}})
    for c in old['cases']:
        if c['kind'] == 'real_development':
            cases.append({'id':c['id'],'kind':c['kind'],'sources':c['sources'],
                          'evaluation_only':{'pair_expected':True,'reference_spans':c['reference_spans'],
                                             'confidence':c['reference_confidence']}})
    if len(cases) != 15: raise ValueError('Expected12 synthetic+3 real pairs')
    unique = {}
    for case in cases:
        for s in case['sources']:
            if s['source_id'] in unique and unique[s['source_id']] != s: raise ValueError('Source collision')
            unique[s['source_id']] = s
    sources = [unique[k] for k in sorted(unique)]
    return {'artifact_kind':'extractive-candidates-probe-0.1','expires_at':old['expires_at'],
            'inputs':{**old['inputs'],str(ORIGIN/'plan.json'):sha(ORIGIN/'plan.json')},
            'code_sha256':{f:sha(f) for f in dict.fromkeys(CODE)},
            'model':old['model'],'nli':old['nli'],'embedding':{'model':MODEL,'revision':REVISION},
            'sources':sources,'inventory':e.inventory(sources),'cases':cases,
            'policy':{**e.POLICY,'max_llm_calls':160,'max_nli_calls':200},
            'criteria':'All targets bind literally; reference exposure is reported separately from support; inspect every model-passed target and every negative pair pass. No default or agent promotion.',
            'limitations':['Known development cases, not independent gold or unseen accuracy.',
                           'Literal sentences can contain conditions, unresolved referents, jokes or multiple claims.',
                           'Single sentences only; context-dependent or longer-than249 candidates are not rewritten.',
                           'More than one candidate per pair changes the decision budget; not a matched-cost comparison.',
                           'Pair compatibility labels are not per-target fidelity labels.'],
            'quality_gate_passed':False,'independent_gold':False}


def vector_contract(plan):
    return {'embedding':plan['embedding'],
            'candidate_ids':[c['candidate_id'] for c in plan['inventory'] if c['eligible']],
            'texts':[c['text'] for c in plan['inventory'] if c['eligible']]}


def validate_vectors(stored, contract):
    from commentscope.factory.raw_candidates import normalized_vectors
    if stored['input'] != contract or stored['vectors_sha256'] != digest(stored['vectors']):
        raise ValueError('Vector input/result changed')
    normalized_vectors(stored['vectors'],len(contract['texts']))


def rank_case(sources, vectors):
    candidates = e.inventory(sources)
    return e.rank(sources,candidates,{c['candidate_id']:vectors[c['candidate_id']] for c in candidates if c['eligible']})


def exposure(case, selection):
    refs = case['evaluation_only']['reference_spans']
    rows = selection['inventory']
    matched = []
    for source, ref in zip(case['sources'],refs):
        matches = [r for r in rows if r['source_id']==source['source_id'] and
                   r['start']==ref['start'] and r['end']==ref['end'] and r['text']==ref['text']]
        matched.append({'source_id':source['source_id'],'present':bool(matches),
                        'selected':any(r['status']=='selected' for r in matches)})
    return {'available':len(refs)==2,'endpoints':matched,
            'both_selected':len(matched)==2 and all(r['selected'] for r in matched)}


def summarize(plan, records):
    result = {'sources':len(plan['sources']),'sentence_inventory':len(plan['inventory']),
              'eligible_sentences':sum(c['eligible'] for c in plan['inventory']),
              'input_deferred_reasons':dict(Counter(c['deferred_reason'] for c in plan['inventory'] if not c['eligible'])),
              'selected_targets':sum(len(r['assessments']) for r in records),
              'model_passed_targets':sum(a['model_pair_passed'] for r in records for a in r['assessments']),
              'source_check_states':dict(Counter(c['state'] for r in records for a in r['assessments'] for c in a['checks'])),
              'proposal_calls':0,'agents':0,'support_count':None,'quality_gate_passed':False}
    for kind in ['synthetic_development','real_development']:
        rows = [(c,r) for c,r in zip(plan['cases'],records) if c['kind']==kind]
        passed = lambda r:any(a['model_pair_passed'] for a in r['assessments'])
        result[kind] = {
            'positive_pairs':sum(c['evaluation_only']['pair_expected'] for c,r in rows),
            'positive_pairs_with_model_pass':sum(c['evaluation_only']['pair_expected'] and passed(r) for c,r in rows),
            'negative_pairs':sum(not c['evaluation_only']['pair_expected'] for c,r in rows),
            'negative_pairs_with_model_pass':[c['id'] for c,r in rows if not c['evaluation_only']['pair_expected'] and passed(r)],
            'reference_pairs':sum(r['reference_exposure']['available'] for c,r in rows),
            'reference_pairs_both_selected':sum(r['reference_exposure']['both_selected'] for c,r in rows)}
    return result


def render(plan, report):
    esc = lambda x:html.escape(str(x),quote=True)
    page = ['<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
            '<title>원문 문장 후보와 지지 판정</title><style>body{font:16px/1.7 system-ui;max-width:1100px;margin:auto;padding:24px}pre,blockquote{white-space:pre-wrap;overflow-wrap:anywhere}article{border-top:1px solid #aaa}</style>',
            '<h1>원문 문장 후보와 지지 판정</h1><p>원문 문장만 후보로 선택했습니다. 유사도는 지지 수가 아니며 모델 통과도 품질 승인이 아닙니다. 새 agent0.</p>',
            '<pre>'+esc(json.dumps(report['summary'],ensure_ascii=False,indent=2))+'</pre>']
    for case,row in zip(plan['cases'],report['records']):
        page.append('<article><h2>'+esc(case['id'])+'</h2><details><summary>전체 두 원문</summary>')
        page += ['<blockquote>'+esc(s['text'])+'</blockquote>' for s in case['sources']]
        page.append('</details>')
        for a in row['assessments']:
            page.append('<blockquote>'+esc(a['core'])+'</blockquote><p>양쪽 모델 통과: '+esc(a['model_pair_passed'])+
                        ' / '+esc([(d['state'],d['reason']) for d in a['checks']])+'</p>')
        page.append('<details><summary>전체 후보·보류·판정 trace</summary><pre>'+
                    esc(json.dumps(row,ensure_ascii=False,indent=2))+'</pre></details></article>')
    return '\n'.join(page+['</html>'])


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--run-dir',type=Path,required=True)
    ap.add_argument('--phase',choices=['plan','run','verify'],required=True)
    ap.add_argument('--diagnostic-only',action='store_true',required=True)
    args=ap.parse_args();directory=args.run_dir;path=directory/'plan.json'
    if args.phase=='plan':
        plan=make_plan();check_inputs(plan);write_json_exclusive(path,plan)
        print({'pairs':len(plan['cases']),'sentences':len(plan['inventory']),'plan_sha256':sha(path)});return
    plan=read_json(path);check_inputs(plan);replay=args.phase=='verify'
    if plan['inventory']!=e.inventory(plan['sources']) or plan['embedding']!={'model':MODEL,'revision':REVISION}:
        raise ValueError('Inventory or embedding changed')
    if not replay and (directory/'report.json').exists():ap.error('Completed output exists')
    started=time.perf_counter();contract=vector_contract(plan);vp=directory/'vectors.json'
    embedding_started=time.perf_counter();new_embeddings=0
    if vp.exists():
        stored=read_json(vp);validate_vectors(stored,contract)
    else:
        if replay:raise RuntimeError('Replay cannot embed')
        vectors=embed(contract['texts']);new_embeddings=1
        stored={'input':contract,'vectors':vectors,'vectors_sha256':digest(vectors)}
        validate_vectors(stored,contract);write_json_exclusive(vp,stored)
    embedding_seconds=time.perf_counter()-embedding_started
    vm=dict(zip(contract['candidate_ids'],stored['vectors']))
    rank_started=time.perf_counter()
    selections=[rank_case(c['sources'],vm) for c in plan['cases']]
    ranking_seconds=time.perf_counter()-rank_started
    prior_llm=len(list((directory/'llm').glob('call-*.json')))
    prior_nli=len(list((directory/'nli').glob('score-*.json')))
    def provider(*args):
        if prior_llm+raw.new_calls>=plan['policy']['max_llm_calls']:raise RuntimeError('LLM budget')
        return local_provider(*args)
    raw=Calls(directory/'llm',plan,no_model if replay else provider)
    calls=SchemaVisibleCalls(raw,[p.AUDIT])
    model=None;new_nli=0
    def score(a,b):
        nonlocal model,new_nli
        if prior_nli+new_nli>=plan['policy']['max_nli_calls']:raise RuntimeError('NLI budget')
        if model is None:model=LocalNLI()
        new_nli+=1;return score_full(model,a,b)
    scores=CachedScores(directory/'nli',plan,no_model if replay else score)
    records=[]
    for case,selection in zip(plan['cases'],selections):
        assessments=[e.assess(case['sources'],c,calls,scores) for c in selection['selected']]
        row={'id':case['id'],'selection':selection,'reference_exposure':exposure(case,selection),'assessments':assessments}
        records.append(row)
        if not replay:print(json.dumps({'pair':case['id'],'targets':len(assessments),
            'model_passed':sum(a['model_pair_passed'] for a in assessments),'reference_exposure':row['reference_exposure']}),flush=True)
    report={'plan_sha256':sha(path),'vectors_sha256':sha(vp),'records':records,'summary':summarize(plan,records)}
    check_inputs(plan)
    if replay:
        if read_json(directory/'report.json')!=report:raise ValueError('Replay changed')
        print({'verified':True,'new_llm_calls':raw.new_calls,'new_nli_calls':new_nli,'new_embeddings':new_embeddings});return
    write_json_exclusive(directory/'report.json',report)
    write_json_exclusive(directory/'measurements.json',{'total_seconds':time.perf_counter()-started,
        'embedding_seconds':embedding_seconds,'ranking_seconds':ranking_seconds,'new_embedding_invocations':new_embeddings,
        'new_llm_calls':raw.new_calls,'new_nli_calls':new_nli,'nli_runtime':model.metadata if model else None,
        'scope':'15-pair development diagnostic including embedding load; not full service latency'})
    with (directory/'overview.html').open('x',encoding='utf-8') as f:f.write(render(plan,report))
    print(json.dumps(report['summary']),flush=True)


if __name__=='__main__':main()

