"""Bounded real-source V0/V1/V2 development comparison; never promotes agents.

Prepare before inference. V2 filters the exact V1 cards, without regeneration.
Assistant evaluation files are not accepted as runtime input.
"""
import argparse
from collections import Counter
from copy import deepcopy
import html
import json
import os
from pathlib import Path
import time

from commentscope.agents.profiles import require_live
from commentscope.agents.runtime import request
from commentscope.contracts import perspective_assignment as assignment
from commentscope.contracts.perspective_draft import bind
from commentscope.factory import automatic_contract as ac
from commentscope.factory.claim_clusters import average_linkage, embed, read_json, sha
from commentscope.factory.draft_audit import audit_pairs
from commentscope import perspective_prompt_v3
from commentscope.providers.local_llama import generate
from commentscope.storage import write_json_exclusive as write
from experiments import factory_evaluation_kit as kit
from experiments.audit_model_compare import owned_server, file_hash

VERSION = 'matched-factory-0.1'
LIMITS = {'extract_calls':64, 'V0_draft_calls':32, 'V1_draft_calls':32,
          'audit_calls':192, 'generation_seconds':1800, 'members_per_candidate':20,
          'request_utf8_bytes':30000, 'extract_tokens':900, 'draft_tokens':1800,
          'audit_tokens':300, 'minimum_candidate_sources':2, 'minimum_agent_sources':3}


def visible_system(system, schema):
    return system+'\n\nRequired JSON output schema:\n'+json.dumps(schema, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def make_plan(kit_dir, model_plan):
    old = read_json(kit_dir/'plan.json')
    require_live(old['expires_at'])
    if any(sha(p)!=h for field in ['inputs','code_sha256'] for p,h in old[field].items()):
        raise ValueError('Evaluation preparation changed')
    prepared, baseline, calibration = kit.prepare(old['snapshot'], old['development_plan'], old['vectors'], len(old['split']['reserve_ids']))
    if prepared!=old or baseline!=read_json(kit_dir/'baseline.json') or calibration!=read_json(kit_dir/'calibration.json'):
        raise ValueError('Evaluation preparation does not replay')
    model = read_json(model_plan)
    paths = [kit_dir/'plan.json', kit_dir/'baseline.json', model_plan,
             Path(old['snapshot']), Path(old['development_plan']), Path(old['vectors'])]
    code = sorted({str(p) for base in ['src/commentscope','experiments'] for p in Path(base).rglob('*.py')})
    sources = read_json(old['development_plan'])['registry']['sources']
    if len(sources)!=64 or sorted(s['source_id'] for s in sources)!=old['split']['development_ids']:
        raise ValueError('Requires the frozen 64-source development pool')
    return {'artifact_kind':VERSION, 'expires_at':old['expires_at'],
            'inputs':{str(p):sha(p) for p in paths}, 'code_sha256':{p:sha(p) for p in code},
            'server':model['server'], 'models':{'baseline':model['models']['baseline']},
            'runtime':{**model['runtime'], 'context':8192, 'max_seconds_per_model':1800},
            'limits':LIMITS, 'sources':sources, 'raw_clusters':baseline['clusters'],
            'embedding':old['embedding'], 'threshold':kit.THRESHOLD,
            'variant_order':['V0','extract','V1','V2'],
            'context_policy':old['context_policy'],
            'card_contract':{'wire':assignment.VERSION, 'prompt':perspective_prompt_v3.VERSION,
                'scope_quote':'List of exact original spans: full comment for V0; selected spans for V1.',
                'common':'Every assigned source must support the whole fixed assertion.',
                'details':'Only cited sources support a detail; not attributed to all members.',
                'support_count':None, 'candidate_count':'Distinct canonical source IDs, not claim units.'},
            'V1':'Fresh source-only extraction; embed English statement only; same average linkage/threshold as V0; no modality prefilter.',
            'V2':'Reuse exact V1 cards; audit each distinct statement/source independently. Keep whole card only if every common/detail citation is supported. No repair or rewriting.',
            'policy_calibration':'Assistant development readings only, not individually user-confirmed or independent gold; mixed-source assertions may be retained; truth != fidelity.',
            'criteria':{'assistant_valid_ge3_cards_min':1, 'assistant_bad_bindings_in_ge3_cards_max':0,
                'assistant_bad_detail_bindings_in_ge3_cards_max':0, 'V2_must_remove_bad_binding':True,
                'V2_must_keep_all_valid_V1_ge3_cards':True, 'V2_additional_seconds_max':300,
                'zero_transport_or_contract_errors':True,
                'decision':'Development candidate for reserve trial only. No winner if no valid >=3-source card. No global recall claim.'},
            'quality_gate_passed':False, 'agents':[], 'independent_gold':False}


def check(plan, *, model_files=False):
    require_live(plan['expires_at'])
    if plan['artifact_kind']!=VERSION or plan['limits']!=LIMITS:
        raise ValueError('Unknown or modified configuration')
    for field in ['inputs','code_sha256']:
        if any(sha(p)!=h for p,h in plan[field].items()):raise ValueError('Frozen inputs/code changed')
    if model_files:
        for info in [plan['server'], *plan['models'].values()]:
            if file_hash(info['path'])!=info['sha256']:raise ValueError('Model/server checksum changed')


class Calls:
    """Fresh-only, append-only calls. Budget deferrals are not negative judgments."""
    def __init__(self, plan, root, provider=generate):
        self.plan, self.root, self.provider = plan, root, provider
        self.counts = Counter(); self.records = []; self.seconds = 0.

    def invoke(self, stage, system, data, schema):
        require_live(self.plan['expires_at'])
        system = visible_system(system, schema)
        tokens = LIMITS['extract_tokens' if stage=='extract' else 'audit_tokens' if stage=='audit' else 'draft_tokens']
        req = {'system':system, 'data':data, 'schema':schema, 'max_tokens':tokens}
        deferred = None
        if self.counts[stage]>=LIMITS[stage+'_calls']:deferred='call_budget'
        elif self.seconds>=LIMITS['generation_seconds']:deferred='time_budget'
        elif len(json.dumps(req,ensure_ascii=False).encode())>LIMITS['request_utf8_bytes']:deferred='request_size_budget'
        raw_response = None
        def provider(s,d,c):
            nonlocal raw_response
            self.counts[stage]+=1
            raw_response=self.provider(s,d,c,max_tokens=tokens)
            return raw_response
        result = ({'output':None,'raw':None,'errors':[deferred],'seconds':0,'usage':None}
                  if deferred else request(system,data,schema,provider))
        self.seconds+=result['seconds']
        record = {'id':f'R{len(self.records)+1:04d}', 'stage':stage, 'request':req,
                  'request_sha256':ac.digest(req), 'response':raw_response, 'result':result,
                  'deferred':deferred, 'fresh_call':deferred is None}
        write(self.root/'calls'/(record['id']+'.json'), record)
        self.records.append(record)
        return record


def extract_sources(plan, calls):
    rows=[]; units=[]
    for source in plan['sources']:
        parts=ac.segments(source['text'])
        if not parts:
            rows.append({'source_id':source['source_id'],'status':'empty','claims':[]});continue
        rec=calls.invoke('extract',ac.EXTRACT,{'COMMENT':parts},ac.extraction_schema(parts))
        result=rec['result'];errors=list(result['errors'])
        if not errors:errors.extend(ac.validate_extraction(result['output'],parts))
        claims=[]
        if not errors:
            for i,c in enumerate(result['output']['claims']):
                claims.append({'id':'U'+ac.digest([source['source_id'],i])[:20],
                    'source_id':source['source_id'],'statement':c['statement'],'mode':c['mode'],
                    'spans':[p for p in parts if p['id'] in c['segment_ids']]})
        units.extend(claims)
        rows.append({'source_id':source['source_id'],'request_id':rec['id'],'errors':errors,
                     'status':'error' if errors else result['output']['status'],'claims':claims})
        print(json.dumps({'stage':'extract','done':len(rows),'claims':len(units),'errors':errors}),flush=True)
    return {'rows':rows,'units':units,'source_count':len(plan['sources'])}


def candidates(units, vectors, threshold):
    if len(units)!=len(vectors) or len({u['id'] for u in units})!=len(units):
        raise ValueError('Vector/unit identity mismatch')
    groups,_=average_linkage(vectors,threshold)
    return [{'id':f'V1-C{i:03d}','unit_ids':[units[j]['id'] for j in group],
             'source_ids':sorted({units[j]['source_id'] for j in group})} for i,group in enumerate(groups,1)]


def draft_candidates(plan, variant, groups, units, calls):
    lookup={s['source_id']:s for s in plan['sources']}; by_unit={u['id']:u for u in units}
    records=[]; cards=[]
    for g in groups:
        ids=g['members'] if variant=='V0' else g['unit_ids']
        source_ids=sorted(set(ids)) if variant=='V0' else g['source_ids']
        reason=('singleton_source' if len(source_ids)<LIMITS['minimum_candidate_sources'] else
                'member_budget' if len(ids)>LIMITS['members_per_candidate'] else None)
        if reason:
            records.append({'candidate_id':g['id'],'status':reason,'unit_ids':ids,'source_ids':source_ids});continue
        members={}
        for i,uid in enumerate(ids,1):
            sid=uid if variant=='V0' else by_unit[uid]['source_id'];source=lookup[sid]
            spans=[source['text']] if variant=='V0' else [p['text'] for p in by_unit[uid]['spans']]
            if any(text not in source['text'] for text in spans):raise ValueError('Non-source span')
            members[f'M{i:02d}']={'claim_id':uid,'source_comment_id':sid,'target':source['text'],'scope_quote':spans}
        payload={'members':[{'member_id':mid,'target':m['target'],'scope_quote':m['scope_quote']} for mid,m in members.items()]}
        rec=calls.invoke(variant+'_draft',perspective_prompt_v3.SYSTEM,payload,assignment.schema(members))
        errors=list(rec['result']['errors']);canonical=None
        if not errors:
            try:canonical=assignment.canonicalize(rec['result']['output'],members)
            except (ValueError,TypeError,KeyError) as exc:errors.append('assignment:'+str(exc))
        row={'candidate_id':g['id'],'status':'error' if errors else 'drafted','request_id':rec['id'],
             'members':members,'errors':errors,'canonical':canonical,'source_ids':source_ids}
        records.append(row)
        if not errors:
            for group in bind(canonical,members)['groups']:
                cards.append({'id':g['id']+'-'+group['draft_id'],'candidate_id':g['id'],**group,
                              'candidate_source_count':len(group['source_ids']),'support_count':None})
        print(json.dumps({'stage':variant,'candidate':g['id'],'errors':errors,'cards':len(cards)}),flush=True)
    return {'variant':variant,'candidates':groups,'records':records,'cards':cards,
            'quality_gate_passed':False,'agents':[]}


def audit_cards(plan, v1, calls):
    rows=[]; cards=[]; cache={}
    for card in v1['cards']:
        pair_records=[]
        for statement_index,statement in enumerate([card['common'],*card['details']]):
            for citation in statement['evidence']:
                key=ac.digest([citation['source_comment_id'],citation['quote'],statement['text']])
                if key not in cache:
                    pair={'P01':{'text':statement['text'],'member_id':'M01'}}
                    member={'M01':{'target':citation['quote']}}
                    def provider(system,data,schema):
                        record=calls.invoke('audit',system,data,schema)
                        cache[key]={'request_id':record['id'],'call_errors':record['result']['errors']}
                        # Existing strict audit validator handles all errors, including deferrals.
                        return record['response'] or {}
                    result=audit_pairs(pair,member,provider,prompt_revision='v2')
                    cache[key].update({'verdict':None if result['errors'] else result['output']['P01']['verdict'],
                                       'reason':None if result['errors'] else result['output']['P01']['reason'],
                                       'errors':cache[key]['call_errors']+result['errors']})
                pair_records.append({'statement_index':statement_index,'source_id':citation['source_comment_id'],
                                     'pair_key':key,**cache[key]})
        retained=bool(pair_records) and all(not p['errors'] and p['verdict']=='supported' for p in pair_records)
        rows.append({'card_id':card['id'],'retained':retained,'pairs':pair_records})
        if retained:cards.append(deepcopy(card))
        print(json.dumps({'stage':'V2','card':card['id'],'retained':retained}),flush=True)
    return {'variant':'V2','base_cards_sha256':ac.digest(v1['cards']),'records':rows,'cards':cards,
            'distinct_audit_pairs':len(cache),'quality_gate_passed':False,'agents':[]}


def summarize(plan, extraction, v0, v1, v2, calls, embedding_seconds):
    def card_summary(variant):
        big=[c for c in variant['cards'] if c['candidate_source_count']>=3]
        return {'cards':len(variant['cards']),'cards_ge3':len(big),
                'proposed_source_coverage_ge3':len({sid for c in big for sid in c['source_ids']}),
                'semantic_precision':None,'validated_coverage':None}
    return {'source_denominator':len(plan['sources']),
            'extraction_statuses':dict(Counter(r['status'] for r in extraction['rows'])),
            'extracted_claims':len(extraction['units']),
            'variants':{v['variant']:card_summary(v) for v in [v0,v1,v2]},
            'fresh_calls':dict(calls.counts),'generation_seconds':calls.seconds,
            'seconds_by_stage':{s:sum(r['result']['seconds'] for r in calls.records if r['stage']==s) for s in calls.counts},
            'embedding_seconds':embedding_seconds,'V0_vectors':'reused; fresh embedding latency not measured',
            'transport_or_response_errors':sum(bool(r['result']['errors']) and not r['deferred'] for r in calls.records),
            'extraction_contract_or_call_errors':sum(bool(r.get('errors')) for r in extraction['rows']),
            'draft_contract_or_call_errors':{v['variant']:sum(bool(r.get('errors')) for r in v['records']) for v in [v0,v1]},
            'audit_pair_errors':sum(bool(p['errors']) for r in v2['records'] for p in r['pairs']),
            'deferrals':dict(Counter(r['deferred'] for r in calls.records if r['deferred'])),
            'quality_gate_passed':False,'agents':[],'semantic_review':'pending_assistant_development_review'}


def render(report):
    esc=lambda x:html.escape(str(x),quote=True)
    out=['<!doctype html><html lang="ko"><meta charset="utf-8"><title>실제 V0/V1/V2 비교</title>',
         '<style>body{font:16px/1.65 system-ui;max-width:1100px;margin:auto;padding:24px}article{border-top:1px solid #aaa}pre,blockquote{white-space:pre-wrap;overflow-wrap:anywhere}</style>',
         '<h1>실제64개 V0/V1/V2 — 개발 진단</h1><p>카드 수와 모델 감사 통과는 검증된 관점/agent 수가 아닙니다. V2는 V1 원본 카드를 그대로 필터링합니다.</p>',
         '<p><a href="assistant-review.html">별도 assistant 검토</a></p><pre>'+esc(json.dumps(report['summary'],ensure_ascii=False,indent=2))+'</pre>']
    retained={c['id'] for c in report['V2']['cards']}
    audit={r['card_id']:r for r in report['V2']['records']}
    for variant in ['V0','V1']:
        out.append('<h2>'+variant+'</h2>')
        for card in report[variant]['cards']:
            out+=['<article id="'+esc(card['id'])+'"><h3>'+esc(card['id'])+' · 후보 원문 '+str(card['candidate_source_count'])+'</h3>']
            for s in [card['common'],*card['details']]:
                out.append('<p><strong>'+esc(s['text'])+'</strong></p>')
                for c in s['evidence']:out.append('<blockquote>'+esc(c['source_comment_id'])+'\n'+esc(c['quote'])+'</blockquote>')
            if variant=='V1':out.append('<pre>'+esc(json.dumps({'V2_kept':card['id'] in retained,'audit':audit[card['id']]},ensure_ascii=False,indent=2))+'</pre>')
            out.append('</article>')
    return '\n'.join(out+['</html>'])


def execute(plan, root):
    check(plan,model_files=True)
    write(root/'started.json',{'plan_sha256':sha(root/'plan.json')})
    calls=Calls(plan,root)
    os.environ['HF_HUB_OFFLINE']='1';os.environ['TRANSFORMERS_OFFLINE']='1'
    with owned_server(plan,'baseline',root/'server'):
        v0=draft_candidates(plan,'V0',plan['raw_clusters'],[],calls);write(root/'V0.json',v0)
        extraction=extract_sources(plan,calls);write(root/'extraction.json',extraction)
        texts=[u['statement'] for u in extraction['units']]
        started=time.perf_counter();vectors=embed(texts);embedding_seconds=time.perf_counter()-started
        write(root/'claim-vectors.json',{'texts':texts,'vectors':vectors,'embedding':plan['embedding'],'seconds':embedding_seconds})
        groups=candidates(extraction['units'],vectors,plan['threshold'])
        v1=draft_candidates(plan,'V1',groups,extraction['units'],calls);write(root/'V1.json',v1)
        v2=audit_cards(plan,v1,calls);write(root/'V2.json',v2)
    summary=summarize(plan,extraction,v0,v1,v2,calls,embedding_seconds)
    report={'artifact_kind':VERSION,'plan_sha256':sha(root/'plan.json'),'summary':summary,'V0':v0,'V1':v1,'V2':v2}
    write(root/'report.json',report)
    with (root/'overview.html').open('x',encoding='utf-8') as f:f.write(render(report))
    write(root/'completed.json',{'plan_sha256':sha(root/'plan.json'),'artifact_sha256':{
        str(p.relative_to(root)):sha(p) for p in sorted(root.rglob('*')) if p.is_file()}})
    print(json.dumps(summary,ensure_ascii=False,indent=2),flush=True)


def verify(root):
    plan=read_json(root/'plan.json');check(plan)
    manifest=read_json(root/'completed.json')
    if manifest['plan_sha256']!=sha(root/'plan.json'):raise ValueError('Plan changed')
    if any(sha(root/p)!=h for p,h in manifest['artifact_sha256'].items()):raise ValueError('Run artifact changed')
    v1=read_json(root/'V1.json');v2=read_json(root/'V2.json')
    if ac.digest(v1['cards'])!=v2['base_cards_sha256']:raise ValueError('V1 identity changed')
    kept={r['card_id'] for r in v2['records'] if r['retained']}
    if v2['cards']!=[c for c in v1['cards'] if c['id'] in kept]:raise ValueError('V2 regenerated cards')
    print({'verified':True,'fresh_calls':0,'plan_sha256':sha(root/'plan.json')})


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--run-dir',type=Path,required=True)
    ap.add_argument('--phase',choices=['prepare','run','verify'],required=True)
    ap.add_argument('--kit-dir',type=Path,default=Path('runs/factory-evaluation-reset-20261013'))
    ap.add_argument('--model-plan',type=Path,default=Path('runs/audit-model-comparison-20261012/plan.json'))
    args=ap.parse_args()
    if args.phase=='prepare':
        plan=make_plan(args.kit_dir,args.model_plan);check(plan,model_files=True)
        write(args.run_dir/'plan.json',plan);print({'plan_sha256':sha(args.run_dir/'plan.json'),'limits':LIMITS})
    elif args.phase=='run':execute(read_json(args.run_dir/'plan.json'),args.run_dir)
    else:verify(args.run_dir)


if __name__=='__main__':main()
