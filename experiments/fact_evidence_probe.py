"""Eight frozen document-grounded development cases, not the 40-case MVP gate.

Claims and reference labels are authored before inference. The supplied source
is an actual Kela publication. No comment extraction, automatic search, cluster
promotion, or independently validated factual accuracy is claimed.
"""
import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import html
import json
from pathlib import Path

from commentscope.factory import fact_checks as facts
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.factory.evidence_fetch import capture
from commentscope.providers.budget import InferenceBudget
from commentscope.storage import write_json_exclusive as write
from experiments.audit_model_compare import owned_server, file_hash

VERSION = 'fact-evidence-development-probe-0.1'
URL = 'https://tietotarjotin.fi/en/information-package/158070/basic-income-experiment'
CYCLE = 'mvp-agreed-20261013'
DEFAULT_BUDGET = Path('runs/mvp-agreed-20261013/inference.sqlite')


def cases():
    # These references never enter invocation data or system prompts.
    rows = [
        ('participants','The Finnish basic income experiment included 2,000 unemployed people aged 25 to 58.','supported','Participant count, age and unemployment status are explicitly described.'),
        ('first-year','At group level, the basic income experiment had no employment effects in its first year.','supported','The first-year paragraph expressly qualifies the finding at group level.'),
        ('wellbeing','Survey respondents receiving basic income reported less mental strain than control respondents.','supported','This is self-reported wellbeing, not a diagnosis or a universal causal claim.'),
        ('amount','The Finnish experiment paid each recipient 1,000 euros per month.','refuted','The specified monthly amount is 560 euros, not 1,000.'),
        ('first-year-effect','The Finnish experiment increased employment by ten days at group level in its first year.','refuted','The first-year group-level report states no employment effect.'),
        ('age','All recipients in the Finnish experiment were between 18 and 24 years of age.','refuted','The reported participant age range is 25 to 58.'),
        ('inflation','The Finnish basic income experiment reduced the annual national inflation rate by two percentage points.','insufficient','The supplied passages contain no national inflation outcome.'),
        ('later-policy','Finland introduced permanent nationwide basic income for all citizens in 2025.','insufficient','The supplied study passages do not establish any 2025 policy adoption.')]
    return [{'id':cid,'claim':{'id':cid,'text':text,'kind':'fact',
                'scope':{'entity':'Finnish basic income experiment' if cid!='later-policy' else 'Finland national policy',
                         'time':'2025' if cid=='later-policy' else '2017 first year' if cid.startswith('first-year') else '2017–2018 experiment',
                         'conditions':'As scoped in the claim; no extrapolation to all populations'},'requires':[]},
             'expected':label,'reference_reason':reason,'reference_origin':'assistant_authored_development_not_independent_gold'}
            for cid,text,label,reason in rows]


def prepare(directory, model_plan):
    if directory.exists():
        raise ValueError('Choose a new probe directory; never overwrite an attempt')
    captured = capture(URL)
    expiry = (datetime.now(timezone.utc)+timedelta(days=30)).isoformat()
    doc = {'id':'kela-overview','text':captured['text'],'url':URL,'title':'Basic income experiment',
           'publisher':'Kela','published_at':captured['metadata']['published_at'],'retrieved_at':captured['retrieved_at'],
           'expires_at':expiry,'source_kind':'primary_document'}
    needles = ['received a monthly payment','During the first year','Survey respondents']
    selected = []
    for i,needle in enumerate(needles):
        matches = [p for p in captured['paragraphs'] if needle in p]
        if len(matches) != 1:
            raise ValueError('Source layout/content changed; inspect before freezing a plan')
        text=matches[0]; start=doc['text'].index(text)
        selected.append({'id':f'E{i+1}','document_id':doc['id'],
                         'span':{'start':start,'end':start+len(text),'text':text}})
    old = read_json(model_plan)
    deployment = old['models']['baseline']
    model = {'name':deployment['name'],'revision':deployment['revision'],
             'weights_sha256':deployment['sha256'],'runtime_sha256':old['server']['sha256']}
    for info in [deployment,old['server']]:
        if file_hash(info['path']) != info['sha256']:
            raise ValueError('Local model/runtime checksum changed')
    write(directory/'capture.json',captured)
    rows = cases()
    for row in rows:
        row['packet']=facts.packet(row['claim'],[doc],selected,expiry)
        row['request_sha256']=digest(facts.invocation(row['packet'],model))
    code = sorted(str(p) for base in ['src/commentscope','experiments'] for p in Path(base).rglob('*.py'))
    plan = {'artifact_kind':VERSION,'expires_at':expiry,'model':model,'document':doc,
            'inputs':{str(directory/'capture.json'):sha(directory/'capture.json'),str(model_plan):sha(model_plan)},
            'code_sha256':{p:sha(p) for p in code},'rows':rows,'selections':selected,
            'server':old['server'],'models':{'baseline':deployment},
            'runtime':{**old['runtime'],'context':8192,'max_tokens':500},
            'budget':{'cycle_id':CYCLE,'limit_seconds':28800,'max_calls':8,'timeout_seconds':90},
            'criteria':{'exact_verdicts':8,'unsupported_false_support_max':0,'supported_kept':3,'errors_max':0},
            'scope':'Development preflight only. Not the final 40-case fact gate or a real-comment trial.',
            'automatic_retrieval':False,'independent_gold':False,'quality_gate_passed':False,'agents':[]}
    write(directory/'plan.json',plan)
    print(json.dumps({'prepared':True,'cases':len(rows),'reference_counts':dict(Counter(r['expected'] for r in rows)),
                      'plan_sha256':sha(directory/'plan.json'),'new_model_calls':0}))


def check(plan, *, model_files=False):
    facts.live(plan['expires_at'])
    if plan['artifact_kind'] != VERSION or len(plan['rows']) != 8:
        raise ValueError('Unknown probe plan')
    if any(sha(p)!=h for field in ['inputs','code_sha256'] for p,h in plan[field].items()):
        raise ValueError('Frozen source or code changed')
    for row in plan['rows']:
        bound=facts.packet(row['claim'],[plan['document']],plan['selections'],plan['expires_at'])
        if bound != row['packet'] or digest(facts.invocation(bound,plan['model']))!=row['request_sha256']:
            raise ValueError('Frozen claim/evidence/request changed')
    if model_files:
        for info in [plan['server'],plan['models']['baseline']]:
            if file_hash(info['path'])!=info['sha256']: raise ValueError('Deployment changed')


def summarize(plan, records):
    rows = []
    for row, record in zip(plan['rows'],records,strict=True):
        facts.validate_record(record,row['packet'],plan['model'])
        rows.append({'id':row['id'],'expected':row['expected'],'actual':record['state'],
                     'matches':row['expected']==record['state'],'reason':record['result']['output'].get('reason') if record['result']['output'] else None})
    result = {'rows':rows,'exact_verdicts':sum(r['matches'] for r in rows),
              'unsupported_false_support':sum(r['expected']!='supported' and r['actual']=='supported' for r in rows),
              'supported_kept':sum(r['expected']=='supported' and r['actual']=='supported' for r in rows),
              'errors':sum(r['actual'] in {'error','unassessed'} for r in rows),
              'request_elapsed_seconds':sum(r['result']['seconds'] for r in records),
              'quality_gate_passed':False,'agents':[],'scope':plan['scope'],'independent_gold':False}
    result['development_preflight_passed']=(result['exact_verdicts']==8 and result['unsupported_false_support']==0 and result['supported_kept']==3 and result['errors']==0)
    return result


def render(plan, report):
    esc=lambda x:html.escape(str(x),quote=True)
    out=['<!doctype html><html lang="ko"><meta charset="utf-8"><title>공개 자료 기반 사실 판정 개발 시험</title>',
         '<style>body{font:16px/1.6 system-ui;max-width:1000px;margin:auto;padding:24px}pre{white-space:pre-wrap}article{border-top:1px solid #aaa}</style>',
         '<h1>공개 자료 기반 사실 판정 개발 시험</h1><p>실제 Kela 문서와 사전 작성한 평가 주장 8개. 실제 댓글 생성 시험·독립 gold·MVP 합격 판정이 아닙니다.</p>',
         '<p><a href="'+esc(plan['document']['url'])+'">근거 원문</a></p><pre>'+esc(json.dumps(report,ensure_ascii=False,indent=2))+'</pre>']
    for row in plan['rows']:
        out+=['<article><h2>'+esc(row['id'])+'</h2><p>'+esc(row['claim']['text'])+'</p><p>'+esc(row['reference_reason'])+'</p></article>']
    return '\n'.join(out+['</html>'])


def execute(directory, ledger):
    plan=read_json(directory/'plan.json');check(plan,model_files=True)
    plan_sha=sha(directory/'plan.json')
    budget=InferenceBudget(ledger,CYCLE)
    write(directory/'started.json',{'plan_sha256':plan_sha,'budget_path':str(ledger),'budget_before':budget.summary()})
    provider=budget.provider(plan_sha,timeout_seconds=plan['budget']['timeout_seconds'])
    records=[]
    with owned_server(plan,'baseline',directory/'server'):
        for row in plan['rows']:
            record=facts.check(row['packet'],plan['model'],provider)
            write(directory/(row['id']+'.json'),record); records.append(record)
            print(json.dumps({'case':row['id'],'state':record['state'],'seconds':round(record['result']['seconds'],2)}),flush=True)
    report=summarize(plan,records);report['budget_after']=budget.summary()
    write(directory/'report.json',report)
    with (directory/'overview.html').open('x',encoding='utf-8') as out: out.write(render(plan,report))
    write(directory/'completed.json',{'plan_sha256':plan_sha,'report_sha256':sha(directory/'report.json')})
    print(json.dumps({k:v for k,v in report.items() if k not in {'rows','budget_after'}},indent=2))


def verify(directory):
    plan=read_json(directory/'plan.json');check(plan)
    completed=read_json(directory/'completed.json')
    if completed!={'plan_sha256':sha(directory/'plan.json'),'report_sha256':sha(directory/'report.json')}:
        raise ValueError('Completion binding changed')
    if read_json(directory/'started.json')['plan_sha256']!=completed['plan_sha256']:
        raise ValueError('Started plan changed')
    records=[read_json(directory/(r['id']+'.json')) for r in plan['rows']]
    report=read_json(directory/'report.json')
    if any(report[k]!=v for k,v in summarize(plan,records).items()): raise ValueError('Report does not replay')
    if read_json(directory/'server/stopped.json')['returncode']!=0: raise ValueError('Unclean owned server exit')
    print(json.dumps({'verified':True,'new_model_calls':0,'cases':len(records)}))


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--run-dir',type=Path,required=True)
    ap.add_argument('--phase',choices=['prepare','run','verify'],required=True)
    ap.add_argument('--model-plan',type=Path,default=Path('runs/matched-factory-20261013/plan.json'))
    ap.add_argument('--budget-ledger',type=Path,default=DEFAULT_BUDGET)
    args=ap.parse_args()
    if args.phase=='prepare': prepare(args.run_dir,args.model_plan)
    elif args.phase=='run': execute(args.run_dir,args.budget_ledger)
    else: verify(args.run_dir)


if __name__=='__main__': main()
