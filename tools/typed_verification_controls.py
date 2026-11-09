"""Evaluate frozen synthetic type/world controls; no labels enter requests."""
from copy import deepcopy
from pathlib import Path

from commentscope.factory import argument_dependencies as deps,owner_observations as owners
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json
from commentscope.providers import remote_verification as remote

VERSION='typed-verification-controls-20261109-v1'
FIXTURE=Path('tests/fixtures/typed-verification-controls.json')


def selected(fixture,selection=None):
    graphs={r['id'] for r in fixture['graphs']};owners_set={r['id'] for r in fixture['owners']}
    if selection is None:return graphs,owners_set
    if (set(selection)!={'graph_ids','owner_ids'} or any(not isinstance(selection[k],list) for k in selection)
            or any(not isinstance(x,str) for k in selection for x in selection[k])
            or any(len(selection[k])!=len(set(selection[k])) for k in selection)
            or not set(selection['graph_ids'])<=graphs or not set(selection['owner_ids'])<=owners_set
            or not selection['graph_ids'] and not selection['owner_ids']):
        raise ValueError('Explicit unchanged control source IDs required')
    return set(selection['graph_ids']),set(selection['owner_ids'])


def requests(selection=None):
    fixture=read_json(FIXTURE);graphs,owner_ids=selected(fixture,selection);out=[]
    for row in fixture['graphs']:
        if row['id'] in graphs:
            try:tasks=deps.tasks(row['record'],row['cores'],typed=True)
            except ValueError:continue  # Host-only negative input, recorded before dispatch.
            out.extend(req for t in tasks for req in deps.chat_requests(t))
    out.extend(owners.request(r['task']) for r in fixture['owners'] if r['id'] in owner_ids)
    return out


def execute(session,save):
    fixture=read_json(FIXTURE)
    if fixture['version']!=VERSION:raise ValueError('Frozen typed controls required')
    selected_graphs,selected_owners=selected(fixture,getattr(session,'plan',{}).get('controls_selection'))
    graphs={};out=[];records=[]
    for row in fixture['graphs']:
        if row['id'] not in selected_graphs:continue
        checks=[]
        try:tasks=deps.tasks(row['record'],row['cores'],typed=True)
        except ValueError as exc:
            out.append({'id':row['id'],'expected_accepted':row['expected_accepted'],'accepted':False,
                        'guards':{'input':[str(exc)]},'kind':'graph_host_reject'});continue
        for task in tasks:
            responses=[session.call('argument-dependency-'+digest(req)[:20],req) for req in deps.chat_requests(task)]
            checks.append(deps.bind_chat(task,responses,remote.SOL))
        graphs[row['id']]=(row,checks);records.extend(checks)
        guards=deps.guards(row['record'],row['cores'],checks,typed=True)
        out.append({'id':row['id'],'expected_accepted':row['expected_accepted'],
                    'accepted':not any(guards.values()),'guards':guards,'kind':'graph'})
    for mutation in fixture['declaration_mutations']:
        if mutation['source'] not in graphs:continue
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
        if row['id'] not in selected_owners:continue
        task=row['task'];req=owners.request(task);result=session.call('argument-owner-'+digest(req)[:20],req)
        record=owners.bind(task,result);records.append(record)
        out.append({'id':row['id'],'expected_accepted':row['expected_accepted'],
                    'accepted':record['passed'],'observation':record['response'],'kind':'owner'})
    save('control-records',records)
    positives=[r for r in out if r['expected_accepted']];negatives=[r for r in out if not r['expected_accepted']]
    report={'artifact_kind':VERSION,'cases':out,'unique_graph_sources':len(selected_graphs),
            'observed_graph_sources':len(graphs),'owner_sources':len(selected_owners),
            'positive_kept':sum(r['accepted'] for r in positives),'positive_total':len(positives),
            'false_approval':sum(r['accepted'] for r in negatives),'negative_total':len(negatives),
            'all_expected':all(r['accepted']==r['expected_accepted'] for r in out),
            'independent_human_gold':False,'quality_gate_passed':False}
    save('controls-report',report);return report
