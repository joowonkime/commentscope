"""Evaluate frozen synthetic type/world controls; no labels enter requests."""
from copy import deepcopy
from pathlib import Path

from commentscope.factory import argument_dependencies as deps,owner_observations as owners
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json
from commentscope.providers import remote_verification as remote

VERSION='typed-verification-controls-20261109-v1'
FIXTURE=Path('tests/fixtures/typed-verification-controls.json')


def execute(session,save):
    fixture=read_json(FIXTURE)
    if fixture['version']!=VERSION:raise ValueError('Frozen typed controls required')
    graphs={};out=[];records=[]
    for row in fixture['graphs']:
        checks=[]
        for task in deps.tasks(row['record'],row['cores'],typed=True):
            responses=[session.call('argument-dependency-'+digest(req)[:20],req) for req in deps.chat_requests(task)]
            checks.append(deps.bind_chat(task,responses,remote.SOL))
        graphs[row['id']]=(row,checks);records.extend(checks)
        guards=deps.guards(row['record'],row['cores'],checks,typed=True)
        out.append({'id':row['id'],'expected_accepted':row['expected_accepted'],
                    'accepted':not any(guards.values()),'guards':guards,'kind':'graph'})
    for mutation in fixture['declaration_mutations']:
        original,checks=graphs[mutation['source']];record=deepcopy(original['record'])
        if mutation['field']=='core_requires_for':
            for u in record['units']:u['core_requires_for']=[]
            for local_id in mutation['units']:
                next(u for u in record['units'] if u['local_id']==local_id)['core_requires_for']=[original['cores'][0]['candidate']['id']]
        else:next(u for u in record['units'] if u['local_id']==mutation['target'])['requires']=mutation['units']
        guards=deps.guards(record,original['cores'],checks,typed=True)
        out.append({'id':mutation['id'],'expected_accepted':False,'accepted':not any(guards.values()),
                    'guards':guards,'kind':'declaration_mutation','reused_observation':mutation['source']})
    for row in fixture['owners']:
        task=row['task'];req=owners.request(task);result=session.call('argument-owner-'+digest(req)[:20],req)
        record=owners.bind(task,result);records.append(record)
        out.append({'id':row['id'],'expected_accepted':row['expected_accepted'],
                    'accepted':record['passed'],'observation':record['response'],'kind':'owner'})
    save('control-records',records)
    positives=[r for r in out if r['expected_accepted']];negatives=[r for r in out if not r['expected_accepted']]
    report={'artifact_kind':VERSION,'cases':out,'unique_graph_sources':len(graphs),'owner_sources':len(fixture['owners']),
            'positive_kept':sum(r['accepted'] for r in positives),'positive_total':len(positives),
            'false_approval':sum(r['accepted'] for r in negatives),'negative_total':len(negatives),
            'all_expected':all(r['accepted']==r['expected_accepted'] for r in out),
            'independent_human_gold':False,'quality_gate_passed':False}
    save('controls-report',report);return report
