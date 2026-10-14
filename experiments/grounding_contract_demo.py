"""Synthetic, model-free demonstration of the fact-screened input contract.

All comments, documents and judgments are authored fixtures. This is NOT an
automatic clustering or fact-check accuracy experiment. No network is used.
"""
import argparse
from copy import deepcopy
import html
import json
from pathlib import Path

from commentscope.agents.grounded_inputs import compile_inputs, prompt_input
from commentscope.factory import fact_checks as f
from commentscope.factory.automatic_contract import digest
from commentscope.storage import write_json_exclusive as write

EXPIRY = '2099-01-01T00:00:00Z'
MODEL = {'name':'SYNTHETIC_STUB_NOT_A_MODEL','revision':'authored-fixture-1',
         'weights_sha256':'0'*64,'runtime_sha256':'0'*64}


def response(value, finish='stop'):
    return {'choices':[{'message':{'content':json.dumps(value)},'finish_reason':finish}]}


def verdict(state='supported', supporting=None, refuting=None):
    return {'verdict':state, 'supporting_ids':(['E1'] if state=='supported' else []) if supporting is None else supporting,
            'refuting_ids':(['E1'] if state=='refuted' else []) if refuting is None else refuting,
            'reason':'Authored fixture judgment; not model inference or a real-world fact.'}


def claim(cid, text, kind='fact', requires=None):
    return {'id':cid,'text':text,'kind':kind,
            'scope':{'entity':'Fictional Trial A','time':'2025','conditions':'Invented fixture, not real evidence'},
            'requires':requires or []}


def source_relation(c, source, verdict_value='supported'):
    return {'claim_id':c['id'],'claim_sha256':f.claim_identity(c),
            'source_id':source['id'],'source_sha256':digest(source['text']),
            'span':{'start':0,'end':len(source['text']),'text':source['text']},
            'verdict':verdict_value,'trace_id':'authored:'+c['id']+':'+source['id'],'origin':'synthetic_fixture'}


def add_check(bundle, cid, state='supported', *, selections=None):
    c = next(c for c in bundle['claims'] if c['id']==cid)
    doc = bundle['documents'][0]
    if selections is None:
        selections = [{'id':'E1','document_id':doc['id'],
                       'span':{'start':0,'end':len(doc['text']),'text':doc['text']}}]
    bound = f.packet(c,bundle['documents'],selections,bundle['expires_at'])
    record = f.check(bound,bundle['model'],lambda *a,**k:response(verdict(state)))
    bundle['checks'] = [x for x in bundle['checks'] if x['claim_id']!=cid]
    bundle['checks'].append({'claim_id':cid,'selections':deepcopy(selections),'record':record})
    return record


def fixture():
    core = claim('position','Safety reviews should be required.','value')
    good = claim('observed','In fictional Trial A, 12 of 100 devices failed.')
    bad = claim('eliminated','Fictional Trial A eliminated all accidents.')
    sources = [
        {'id':'c1','canonical_id':'c1','text':core['text']+' '+good['text']+' '+bad['text']},
        {'id':'c2','canonical_id':'c2','text':core['text']},
        {'id':'c3','canonical_id':'c3','text':core['text']}]
    document = {'id':'D1','text':'Fictional Trial A evaluated 100 devices in 2025. Twelve devices failed. Two accidents occurred.',
                'url':'https://example.invalid/fictional-trial-a','title':'Invented trial report',
                'publisher':'Synthetic fixture, not an institution','published_at':'2026-01-01',
                'retrieved_at':'2026-10-13T00:00:00Z','expires_at':EXPIRY,'source_kind':'synthetic'}
    bundle = {'expires_at':EXPIRY,'model':deepcopy(MODEL),'sources':sources,'documents':[document],
              'claims':[core,good,bad], 'relations':[source_relation(core,s) for s in sources]
                    +[source_relation(good,sources[0]),source_relation(bad,sources[0])],
              'checks':[], 'candidates':[{'id':'P1','core_claim_id':'position',
                    'reason_claim_ids':['observed','eliminated'],'major_fact_ids':['observed','eliminated']}]}
    add_check(bundle,'observed');add_check(bundle,'eliminated','refuted')
    return bundle


def scenarios():
    base = fixture(); cases = {'one_supported_one_refuted':base}
    missing = deepcopy(base);missing['checks']=[];cases['all_facts_unassessed']=missing
    refuted = deepcopy(base);add_check(refuted,'observed','refuted');cases['all_major_facts_refuted']=refuted
    dependency = deepcopy(base);dependency['claims'][0]['requires']=['eliminated']
    for r in dependency['relations']:
        if r['claim_id']=='position':r['claim_sha256']=f.claim_identity(dependency['claims'][0])
    cases['core_requires_refuted_fact']=dependency
    rare = deepcopy(base);rare['relations']=[r for r in rare['relations'] if r['source_id']!='c3']
    cases['two_core_sources']=rare
    return cases


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--output-dir',type=Path,required=True)
    args=ap.parse_args();reports=[]
    for name,bundle in scenarios().items():
        compiled=compile_inputs(bundle)
        prompts=[prompt_input(compiled,p['candidate_id'],bundle=bundle) for p in compiled['profiles']]
        write(args.output_dir/(name+'.json'),{'input':bundle,'compiled':compiled,'prompt_inputs':prompts})
        reports.append({'scenario':name,'profiles':len(compiled['profiles']),'deferred':compiled['deferred'],
                        'prompt_inputs':prompts,'agents':[]})
    summary={'artifact_kind':'synthetic-grounding-contract-demo-0.1','model_calls':0,'network_calls':0,
             'authored_judgments':True,'semantic_accuracy_measured':False,'quality_gate_passed':False,
             'scenarios':reports}
    write(args.output_dir/'summary.json',summary)
    esc=lambda x:html.escape(str(x),quote=True)
    rows=['<!doctype html><html lang="ko"><meta charset="utf-8"><title>팩트 근거 입력 계약 예제</title>',
          '<style>body{font:16px/1.6 system-ui;max-width:1000px;margin:auto;padding:24px}pre{white-space:pre-wrap;overflow-wrap:anywhere}article{border-top:1px solid #aaa}</style>',
          '<h1>팩트 근거 입력 계약 예제</h1><p>모든 댓글·문서·판정은 합성 예제입니다. 모델 호출 0, 네트워크 0. 실제 팩트체크 성능이나 자동 MVP 성공이 아닙니다.</p>']
    for report in reports:
        rows+=['<article><h2>'+esc(report['scenario'])+'</h2><pre>'+esc(json.dumps(report,ensure_ascii=False,indent=2))+'</pre></article>']
    with (args.output_dir/'overview.html').open('x',encoding='utf-8') as out:out.write('\n'.join(rows+['</html>']))
    print(json.dumps({'model_calls':0,'profiles_by_scenario':{r['scenario']:r['profiles'] for r in reports},'agents':[]},indent=2))


if __name__=='__main__':main()
