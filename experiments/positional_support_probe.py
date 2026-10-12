"""Bounded post-retrieval contract comparison; no corpus expansion or agents."""
import argparse
from collections import Counter
import html
import json
from pathlib import Path
import time

from commentscope.factory import positional_support as p, raw_support
from commentscope.factory.automatic import Calls,local_provider
from commentscope.factory.claim_clusters import read_json,sha
from commentscope.factory.automatic_contract import digest
from commentscope.providers.schema_visible import SchemaVisibleCalls
from commentscope.providers.local_nli import LocalNLI
from commentscope.providers.raw_nli import score_full
from commentscope.storage import write_json_exclusive
from experiments import raw_support_probe as old
from experiments.claim_support_probe import CachedScores
from experiments.grounded_core_probe import check_inputs,no_model

ORIGIN=Path('runs/raw-support-20261012')
CODE=[*old.CODE,'experiments/positional_support_probe.py','src/commentscope/factory/positional_support.py']


def make_plan():
    prior=read_json(ORIGIN/'plan.json');old.check_plan(prior)
    report=read_json(ORIGIN/'report.json');review=read_json(ORIGIN/'assistant-review.json')
    if report['plan_sha256']!=sha(ORIGIN/'plan.json') or review['report_sha256']!=sha(ORIGIN/'report.json'):
        raise ValueError('Prior review/report changed')
    exact=[{**c,'old_decision':c['decision']} for c in report['exact_controls']]
    sources={s['source_id']:s for s in prior['registry']['sources']}
    by_pair={r['id']:r['trace'] for r in report['records']}
    excluded=[]
    for finding in review['findings']:
        if finding['verdict']=='needs_review':excluded.append(finding);continue
        trace=by_pair[finding['pair_id']];core=trace['proposal']['output']['core']
        decision=next(c for c in trace['checks'] if c['source_id']==finding['source_id'])
        if decision['state']!='support':raise ValueError('Reviewed decision changed')
        exact.append({'id':finding['pair_id']+':'+finding['source_id'],'source':sources[finding['source_id']]['text'],
                      'target':core,'expected':finding['verdict']=='faithful_standalone',
                      'split':'representative_regression','old_decision':decision,'label_origin':'prior_assistant_review'})
    known={tuple(sorted(c['source_ids'])) for c in prior['known_pairs_evaluation_only']}
    pairs=[pair for pair in prior['pairs'] if tuple(sorted(pair['source_ids'])) in known]
    if len(pairs)!=3:raise ValueError('Expected frozen3 development pairs')
    inputs={**prior['inputs'],**{str(ORIGIN/f):sha(ORIGIN/f) for f in ['plan.json','report.json','assistant-review.json']}}
    return {'artifact_kind':'positional-support-probe-0.1','expires_at':prior['expires_at'],
            'inputs':inputs,'code_sha256':{f:sha(f) for f in dict.fromkeys(CODE)},
            'model':prior['model'],'nli':prior['nli'],'registry':prior['registry'],'pairs':pairs,
            'exact_controls':exact,'pair_controls':prior['pair_controls'],'excluded_ambiguous':excluded,
            'policy':{'max_llm_calls':400,'alignment_ranges':1,'full64':False,'agents':False},
            'criteria':'All frozen positives kept, no false accepts or errors/deferred; known3 source pairs yield faithful independently reviewed cores before expansion. Never tune after outputs.',
            'quality_gate_passed':False,'independent_gold':False,
            'limitations':['Known development controls only; no independent or unseen quality estimate',
                           'Eligibility is newly explicit; fidelity-only positives may be rejected for a different task',
                           'Alignment/projection/evidence/schema/prompts change together; not single-factor causal evidence',
                           'One ambiguous prior review excluded before inference and listed explicitly; not silently counted as correct']}


def pair_error(trace):
    return trace['status'] in ('error','unchecked') or any(c['state'] in ('error','unchecked') for c in trace['checks'])


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--run-dir',type=Path,required=True)
    ap.add_argument('--phase',choices=['plan','run','verify'],required=True)
    ap.add_argument('--diagnostic-only',action='store_true',required=True)
    args=ap.parse_args();directory=args.run_dir;path=directory/'plan.json'
    if args.phase=='plan':
        plan=make_plan();check_inputs(plan);write_json_exclusive(path,plan)
        print({'exact_controls':len(plan['exact_controls']),'synthetic_pairs':len(plan['pair_controls']),
               'real_pairs':len(plan['pairs']),'plan_sha256':sha(path)});return
    plan=read_json(path);check_inputs(plan);replay=args.phase=='verify'
    if not replay and (directory/'report.json').exists():ap.error('Completed output exists')
    started=time.perf_counter();prior_calls=len(list((directory/'llm').glob('call-*.json')))
    def provider(system,data,schema):
        if prior_calls+raw.new_calls>=plan['policy']['max_llm_calls']:raise RuntimeError('LLM budget')
        return local_provider(system,data,schema)
    raw=Calls(directory/'llm',plan,no_model if replay else provider)
    calls=SchemaVisibleCalls(raw,[p.ALIGN,p.AUDIT,raw_support.PROPOSE])
    model=None;new_scores=0
    def score(a,b):
        nonlocal model,new_scores
        if model is None:model=LocalNLI()
        new_scores+=1;return score_full(model,a,b)
    scores=CachedScores(directory/'nli',plan,no_model if replay else score)
    exact=[]
    for c in plan['exact_controls']:
        d=p.check(old.source(c['id'],c['source']),c['target'],calls,scores)
        exact.append({**c,'decision':d})
        if not replay:print(json.dumps({'exact':c['id'],'state':d['state'],'reason':d['reason']}),flush=True)
    controls=[]
    for c in plan['pair_controls']:
        sources=[old.source(c['id']+':a',c['left']),old.source(c['id']+':b',c['right'])]
        pair={'source_ids':[s['source_id'] for s in sources],
              'pair_id':'R'+digest([[s['source_id'],s['source_digest']] for s in sources])[:20]}
        controls.append({**c,'trace':p.discover({'sources':sources},pair,calls,scores)})
    records=[]
    for pair in plan['pairs']:
        trace=p.discover(plan['registry'],pair,calls,scores)
        records.append({'id':pair['pair_id'],'trace':trace})
        if not replay:print(json.dumps({'pair':pair['pair_id'],'status':trace['status'],'core':trace['selected_core']}),flush=True)
    summary={split:old.metrics([r for r in exact if r['split']==split],lambda r:r['decision']['state']=='support',
                               lambda r:r['decision']['state'] in ('error','unchecked')) for split in sorted({r['split'] for r in exact})}
    summary['synthetic_pairs']=old.metrics(controls,lambda r:bool(r['trace']['selected_core']),lambda r:pair_error(r['trace']))
    summary['known_real_pairs']={'total':len(records),'model_passed':sum(bool(r['trace']['selected_core']) for r in records)}
    summary['exact_states']=dict(Counter(r['decision']['state'] for r in exact))
    summary['agents']=0;summary['quality_gate_passed']=False
    report={'plan_sha256':sha(path),'registry':plan['registry'],'exact_controls':exact,
            'pair_controls':controls,'records':records,'ledgers':[],'summary':summary}
    check_inputs(plan)
    if replay:
        if read_json(directory/'report.json')!=report:raise ValueError('Replay changed')
        print({'verified':True,'new_llm_calls':raw.new_calls,'new_nli_calls':new_scores});return
    write_json_exclusive(directory/'report.json',report)
    write_json_exclusive(directory/'measurements.json',{'total_seconds':time.perf_counter()-started,
        'new_llm_calls':raw.new_calls,'new_nli_calls':new_scores,'nli_runtime':model.metadata if model else None,
        'scope':'Development controls+3 real pairs, includes NLI loading/cache IO; not service latency'})
    page=old.render(report).replace('</html>','')+'<h2>고정 주장 판정</h2>'
    for row in exact:
        page+='<article><h3>'+html.escape(row['id'])+'</h3><blockquote>'+html.escape(row['source'])+'</blockquote><p>'+html.escape(row['target'])+'</p><pre>'+html.escape(json.dumps(row['decision'],ensure_ascii=False,indent=2))+'</pre></article>'
    with (directory/'overview.html').open('x',encoding='utf-8') as f:f.write(page+'</html>')
    print(json.dumps(summary),flush=True)


if __name__=='__main__':main()
