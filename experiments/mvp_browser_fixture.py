"""Local product preview with synthetic provider outputs and no paid calls."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import time

from commentscope.agents.grounded_web import GroundedApp
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
    def __init__(self,directory):self.directory=Path(directory);self.calls=0
    def __call__(self,stage,request):
        self.calls+=1
        (self.directory/'metrics.json').write_text(json.dumps({'synthetic_provider_calls':self.calls,'paid_calls':0}),encoding='utf-8')
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
        else:
            entries=data['PERSPECTIVE']['allowed_entries'];core=data['PERSPECTIVE']['core_claim_id']
            chosen=core if core in {e['claim_id'] for e in entries} else entries[0]['claim_id'] if entries else None
            output={'answerability':'grounded' if chosen else 'not_in_evidence',
                    'claim_ids':[chosen] if chosen else [],'limitation':'none' if chosen else 'missing_evidence'}
        return {'output':output,'errors':[],'usage':{'cost':0},'new_cost_usd':'0'}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('directory',type=Path)
    args=parser.parse_args();args.directory.mkdir(parents=True,exist_ok=False)
    generated=bundle();analysis=Analysis(generated,{'synthetic_browser_fixture':True})
    model=SyntheticModel(args.directory)
    product=ProductApp(args.directory/'app.sqlite',[analysis],model,session_ttl_seconds=3600,
                       room_maximum_usd='1',reservation=lambda request:'0')
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
