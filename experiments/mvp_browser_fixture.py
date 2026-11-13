"""Local product preview with synthetic provider outputs and no paid calls."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import time

from commentscope.agents.grounded_web import GroundedApp
from commentscope.agents import seed_policy
from commentscope.providers import openrouter_decisions as decisions
from commentscope.product.analysis import Analysis
from commentscope.product.app import ProductApp
from commentscope.product.web import ProductServer
from experiments.grounding_contract_demo import fixture,claim,source_relation


def bundle():
    value=fixture();other=claim('voluntary','Safety reviews should be voluntary.','value')
    sources=[{'id':'other'+str(i),'canonical_id':'other'+str(i),'text':other['text']} for i in range(3)]
    value['sources'].extend(sources);value['claims'].append(other)
    value['relations'].extend(source_relation(other,s) for s in sources)
    value['candidates'].append({'id':'P2','core_claim_id':'voluntary','reason_claim_ids':[],'major_fact_ids':[]})
    return value


class SyntheticModel:
    def __init__(self,directory):self.directory=Path(directory);self.calls=0;self.typed_calls=0
    def metrics(self):
        (self.directory/'metrics.json').write_text(json.dumps({'synthetic_provider_calls':self.calls,
            'synthetic_typed_calls':self.typed_calls,'paid_calls':0}),encoding='utf-8')

    def verify(self,stage,payload):
        self.typed_calls+=1;self.metrics()
        def choose(key):
            if key=='answer':return 'appropriate'
            index,kind=key[1:].split('_',1)
            if kind=='kind':return 'reasoning' if payload['state']['PARAGRAPHS']['P'+index.zfill(3)]['origin']=='ai_reasoning' else 'empirical'
            return {'attribution':'clean','scope':'preserved','basis':'supported'}[kind]
        return {'id':'synthetic-decision-'+str(self.typed_calls),'provider':decisions.DEPLOYMENT['provider_name'],
            'model':decisions.DEPLOYMENT['model'],'usage':{'cost':0},'new_cost_usd':'0',
            'answers':{key:{'type':'choice','choice':choose(key),'confidence':1,
                'probabilities':{option:int(option==choose(key)) for option in q['criteria']}}
                for key,q in payload['questions'].items()}}

    def __call__(self,stage,request):
        self.calls+=1
        self.metrics()
        time.sleep(.35 if stage=='room' else .02)
        data=request['data']
        if stage=='comparison':
            core=next(c for c in data['PERSPECTIVE_CLAIMS'] if c['role']=='core')
            output={'items':[{'relation':'agreement','user_span_ids':[data['INITIAL_SEGMENTS'][0]['id']],
                'perspective_claim_ids':[core['id']],'explanation':'Both statements support requiring safety reviews.',
                'consideration_question':'Which conditions would matter to you?'}]}
        elif stage=='reflection':
            output={k:[] for k in ('stayed','changed','newly_learned','worth_more_thought')}
            if data['INITIAL_SEGMENTS'] and data['CURRENT_SEGMENTS']:
                output['stayed']=[{'initial_span_ids':[data['INITIAL_SEGMENTS'][0]['id']],
                    'current_span_ids':[data['CURRENT_SEGMENTS'][0]['id']],
                    'related_message_ids':[data['CONVERSATION_CONTEXT'][0]['id']] if data['CONVERSATION_CONTEXT'] else [],
                    'explanation':'I still support safety reviews.'}]
        elif stage=='room' and 'REFERENCES' in data:
            core=data['PERSPECTIVE']['core_claim_id'];ref=next(iter(data['REFERENCES']))
            output={'answerability':'answered','limitation':'none','comment_ids':[core],
                'paragraphs':[{'origin':'ai_reasoning','text':'One possible argument is to weigh avoidable risks against the freedom to choose.',
                    'comment_ids':[core],'reference_ids':[]},
                    {'origin':'external_evidence','text':data['REFERENCES'][ref]['span']['text'],
                    'comment_ids':[core],'reference_ids':[ref]}]}
        else:
            entries=data['PERSPECTIVE']['allowed_entries'];core=data['PERSPECTIVE']['core_claim_id']
            chosen=core if core in {e['claim_id'] for e in entries} else entries[0]['claim_id'] if entries else None
            output={'answerability':'grounded' if chosen else 'not_in_evidence',
                    'claim_ids':[chosen] if chosen else [],'limitation':'none' if chosen else 'missing_evidence'}
        return {'output':output,'errors':[],'usage':{'cost':0},'new_cost_usd':'0'}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('directory',type=Path)
    parser.add_argument('--seeded',action='store_true',help='Synthetic seeded provenance UI, never a paid provider')
    args=parser.parse_args();args.directory.mkdir(parents=True,exist_ok=False)
    generated=bundle()
    if args.seeded:
        generated['admission_policy']=deepcopy(seed_policy.POLICY)
        doc=generated['documents'][0]
        generated['reference_selections']=[{'id':'prepared','document_id':doc['id'],
            'span':{'start':0,'end':len(doc['text']),'text':doc['text']}}]
    analysis=Analysis(generated,{'synthetic_browser_fixture':True})
    model=SyntheticModel(args.directory)
    product=ProductApp(args.directory/'app.sqlite',[analysis],model,session_ttl_seconds=3600,
                       room_maximum_usd='1',reservation=lambda request:'0',
                       decision=model.verify if args.seeded else None,
                       decision_reservation=(lambda:'0') if args.seeded else None)
    def legacy_provider(system,data,schema,*,max_tokens):
        result=model('legacy',{'system':system,'data':data,'schema':schema,'max_tokens':max_tokens})
        return {'choices':[{'finish_reason':'stop','message':{'content':json.dumps(result['output'])}}]}
    legacy=GroundedApp(generated,args.directory/'legacy',provider=legacy_provider)
    server=ProductServer(product,legacy,0)
    print(json.dumps({'origin':'http://127.0.0.1:'+str(server.server_address[1]),'paid_calls':0}),flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close();product.close()


if __name__=='__main__':main()
