"""One matched non-thinking deployment of the frozen directed membership policy.

No prompt, source, target, schema or reference changes. First run the same eight
synthetic controls; only a complete binary pass permits the frozen100 trial.
This is the final cached-8B deployment check, not a new prompt search.
"""
import argparse
from copy import deepcopy
from pathlib import Path

from commentscope.factory import membership_policy, scoped_discovery as core
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.storage import write_json_exclusive as write
from experiments.directed_membership_probe import FIXTURE
from experiments.reasoning_membership_probe import execute
from experiments.scoped_discovery_probe import code_hashes, validate


def control_rows(policy):
    fixture=read_json(FIXTURE)
    if fixture['runtime_input_labels'] is not False:raise ValueError('Offline controls required')
    rows=[]
    for case in fixture['cases']:
        claim={'id':'C','text':case['target'],'kind':'fact',
               'scope':{'entity':'','time':'','conditions':''},'requires':[]}
        req=membership_policy.invocation(policy,case['source'],claim)
        rows.append({'id':case['id'],'text':case['source'],'claim':claim,'request':req,
                     'request_sha256':digest(req),'expected':case['expected']})
    return rows


def verify_controls(directory,plan):
    prior=read_json(directory/'plan.json');validate(prior)
    done=read_json(directory/'completed.json');report=read_json(directory/'report.json')
    policy=membership_policy.from_rows(plan['rows'])
    if (not prior.get('plumbing_only') or prior['rows']!=control_rows(policy)
            or any(prior[k]!=plan[k] for k in ('models','server','runtime'))
            or done['plan_sha256']!=sha(directory/'plan.json')
            or done['report_sha256']!=sha(directory/'report.json')):
        raise ValueError('Control configuration or completion changed')
    if report['precision']!=1 or report['positive_retention']!=1 or report['errors']:
        raise ValueError('Controls failed; no full trial')
    for row in prior['rows']:
        record=read_json(directory/(row['id']+'.json'))
        if (done['records'][row['id']]!=sha(directory/(row['id']+'.json'))
                or record['request_sha256']!=row['request_sha256']
                or core.verdict(record['result'])!=report['actual'][row['id']]
                or (core.verdict(record['result'])=='supported')!=(row['expected']=='supported')):
            raise ValueError('Control decisions do not replay')


def prepare(directory,source,controls=None):
    if directory.exists():raise ValueError('Never overwrite an attempt')
    parent=read_json(source/'plan.json')
    for path,expected in parent['inputs'].items():
        if sha(path)!=expected:raise ValueError('Original inputs changed')
    policy=membership_policy.from_rows(parent['rows'])
    if parent.get('directionality_variant')!='asymmetric-entailment-clarification-0.1':
        raise ValueError('Existing directed policy required')
    if len(parent['evaluation_ids'])!=100:raise ValueError('Same fixed100 required')
    plan=deepcopy(parent);plan.pop('continuation_of',None);plan.pop('reused_records',None)
    plan['runtime'].update(reasoning='off',reasoning_budget=0,
                           template_kwargs={'enable_thinking':False},max_tokens=180)
    plan['budget'].update(reasoning_tokens=0,repairs=0,retries=0)
    policy['max_tokens']=180
    plan['rows']=membership_policy.bind_rows(policy,plan['rows'])
    plan['inputs']={str(source/'plan.json'):sha(source/'plan.json'),str(FIXTURE):sha(FIXTURE),
                   **{p:h for p,h in parent['inputs'].items() if p.endswith(('references.json','reference-frozen.json'))}}
    plan['comparison']='Final cached8B non-thinking deployment; unchanged directed system, sources, targets, schema, fixed100 references. No prompt iteration.'
    plan['stop_on_impossible']=True;plan['plumbing_only']=controls is None
    if controls is None:
        plan['rows']=control_rows(policy);plan['evaluation_ids']=[r['id'] for r in plan['rows']]
    else:
        verify_controls(controls,plan)
        plan['inputs'].update({str(controls/n):sha(controls/n) for n in ('plan.json','report.json','completed.json')})
    plan['code_sha256']=code_hashes();validate(plan)
    write(directory/'plan.json',plan)
    print({'prepared':True,'controls_only':plan['plumbing_only'],'rows':len(plan['rows']),'reasoning':'off'},flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('phase',choices=['prepare','run']);p.add_argument('directory',type=Path)
    p.add_argument('--source',type=Path,default=Path('runs/atomic8b-directed-membership-20261013'));p.add_argument('--controls',type=Path)
    a=p.parse_args()
    if a.phase=='prepare':prepare(a.directory,a.source,a.controls)
    else:execute(a.directory)
