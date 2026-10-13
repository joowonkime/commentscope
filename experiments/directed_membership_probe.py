"""Final bounded 8B directionality clarification, not another 4B auditor loop.

Matched reasoning deployment, fixed100 targets/references and acceptance gates.
First requires all eight binary direction/scope controls. Known-case development
comparison, not held-out or independent validation. No threshold/label repairs.
"""
import argparse
from copy import deepcopy
from pathlib import Path
from commentscope.factory import scoped_discovery as core
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json,sha
from commentscope.storage import write_json_exclusive as write
from experiments.scoped_discovery_probe import code_hashes,validate
from experiments.reasoning_membership_probe import execute

FIXTURE=Path('tests/fixtures/directed-entailment-cases.json')
OLD='A narrower faithful\nparaphrase is allowed; shared vocabulary alone is not.'
NEW='''The direction is SOURCE entails TARGET, not the reverse. TARGET may be a
logically weaker faithful claim: an asserted specific activity also establishes
its broader activity, and an asserted conjunction establishes either conjunct.
Not repeating an incidental occupation, example, or quantity is not by itself a
missing part of TARGET. Do not require TARGET to reproduce every SOURCE detail.
This never permits changing the actor or population, dropping a necessary
condition, inventing an unstated cause, changing modality or strengthening a
quantifier. Shared vocabulary alone does not establish entailment.'''


def directed(req):
    out=deepcopy(req)
    if out['system'].count(OLD)!=1:raise ValueError('Expected original directionality instruction')
    out['system']=out['system'].replace(OLD,NEW)
    return out


def prepare(directory,source,controls=None):
    if directory.exists():raise ValueError('Never overwrite an attempt')
    parent=read_json(source/'plan.json')
    if parent['runtime'].get('reasoning_budget')!=256 or parent['runtime'].get('reasoning')!='on':
        raise ValueError('Matched 256-token reasoning deployment required')
    plan=deepcopy(parent);plan.pop('reused_records',None);plan.pop('continuation_of',None)
    plan['inputs']={str(source/'plan.json'):sha(source/'plan.json'),str(FIXTURE):sha(FIXTURE),
                    **{p:h for p,h in parent['inputs'].items() if p.endswith('references.json') or p.endswith('reference-frozen.json')}}
    plan['directionality_variant']='asymmetric-entailment-clarification-0.1'
    plan['comparison']='Only clarify logical entailment direction; unchanged data/schema/model/256-token reasoning deployment and fixed100 gate.'
    plan['stop_on_impossible']=True
    plan['plumbing_only']=controls is None
    if controls is None:
        fixture=read_json(FIXTURE)
        if fixture['runtime_input_labels'] is not False:raise ValueError('References must be offline')
        rows=[]
        for c in fixture['cases']:
            claim={'id':'C','text':c['target'],'kind':'fact','scope':{'entity':'','time':'','conditions':''},'requires':[]}
            req=core.judge_request(c['source'],claim);req['max_tokens']=512
            rows.append({'id':c['id'],'text':c['source'],'claim':claim,'request':req,'expected':c['expected']})
        plan['rows']=rows;plan['evaluation_ids']=[r['id'] for r in rows]
    else:
        control_plan=read_json(controls/'plan.json');validate(control_plan)
        complete=read_json(controls/'completed.json');report=read_json(controls/'report.json')
        if complete['plan_sha256']!=sha(controls/'plan.json') or complete['report_sha256']!=sha(controls/'report.json'):
            raise ValueError('Control completion changed')
        if (control_plan.get('directionality_variant')!=plan['directionality_variant'] or len(control_plan['rows'])!=8
                or report['precision']!=1 or report['positive_retention']!=1 or report['errors']):
            raise ValueError('Directionality controls failed; no full trial')
        for row in control_plan['rows']:
            record=read_json(controls/(row['id']+'.json'))
            if complete['records'][row['id']]!=sha(controls/(row['id']+'.json')) or record['request_sha256']!=row['request_sha256']:
                raise ValueError('Control record changed')
            if core.verdict(record['result'])!=report['actual'][row['id']]:raise ValueError('Control report does not replay')
        if len(plan['evaluation_ids'])!=100:raise ValueError('Original fixed100 required')
        plan['inputs'].update({str(controls/name):sha(controls/name) for name in ['plan.json','report.json','completed.json']})
    for row in plan['rows']:
        row['request']=directed(row['request']);row['request_sha256']=digest(row['request'])
    plan['code_sha256']=code_hashes();validate(plan)
    write(directory/'plan.json',plan)
    print({'prepared':True,'controls_only':plan['plumbing_only'],'requests':len(plan['rows']),'semantic_target_changes':False},flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('phase',choices=['prepare','run']);p.add_argument('directory',type=Path)
    p.add_argument('--source',type=Path,default=Path('runs/reasoning-membership-on-20261013'));p.add_argument('--controls',type=Path)
    a=p.parse_args()
    if a.phase=='prepare':prepare(a.directory,a.source,a.controls)
    else:execute(a.directory)
