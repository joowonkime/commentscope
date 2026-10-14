"""Synthetic UI fixture only. No model calls, corpus, or semantic quality score."""
import argparse
import json
from pathlib import Path
from experiments.grounding_contract_demo import fixture,response
from commentscope.agents.grounded_web import GroundedApp,GroundedServer
from commentscope.factory.grounded_factory import relation


def bundle():
    value=fixture()
    claim={'id':'voluntary','text':'Safety reviews should be voluntary.','kind':'value',
           'scope':{'entity':'safety reviews','time':'proposed policy','conditions':'as a normative preference'},'requires':[]}
    value['claims'].append(claim)
    for i in range(3):
        sid=f'voluntary-{i}';text=f'Synthetic commenter {i}: I prefer voluntary safety reviews.'
        value['sources'].append({'id':sid,'canonical_id':sid,'text':text})
        value['relations'].append(relation(claim,sid,text,'supported','0'*64))
    value['candidates'].append({'id':'P2','core_claim_id':'voluntary','reason_claim_ids':[],'major_fact_ids':[]})
    return value


def provider(system,data,schema,**kwargs):
    profile=data['PERSPECTIVE'];question=data['QUESTION'].lower()
    ids=[profile['core_claim_id']]
    if 'why' in question:
        ids=[e['claim_id'] for e in profile['allowed_entries'] if e['declared_role']=='reason'][:1]
    if 'amount' in question:ids=[]
    return response({'answerability':'grounded' if ids else 'not_in_evidence','claim_ids':ids,
                     'limitation':'none' if ids else 'missing_evidence'})


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('output',type=Path);a=p.parse_args()
    app=GroundedApp(bundle(),a.output,provider=provider)
    server=GroundedServer(app,0)
    print(json.dumps({'origin':f'http://127.0.0.1:{server.server_address[1]}','synthetic_only':True,'model_calls':0}),flush=True)
    try:server.serve_forever()
    finally:server.server_close()
