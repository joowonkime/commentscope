"""Offline existing-unit NLI ranking worker; no LLM prompt or membership decision."""
import os
from commentscope.factory.automatic_contract import digest
from commentscope.providers.local_nli import LocalNLI

VERSION = 'bounded-target-ranking-nli-0.1'


def generate(system,data,schema,max_tokens):
    if (system!=VERSION or schema!={} or max_tokens!=1 or set(data)!={'pairs'}
            or not isinstance(data['pairs'],list) or len(data['pairs'])>1000
            or len({p['id'] for p in data['pairs']})!=len(data['pairs'])):
        raise ValueError('Invalid bounded ranking request')
    os.environ['HF_HUB_OFFLINE']='1';os.environ['TRANSFORMERS_OFFLINE']='1'
    nli=LocalNLI() if data['pairs'] else None
    rows=[]
    for pair in data['pairs']:
        record=nli.score(pair['premise'],pair['hypothesis'])
        rows.append({'id':pair['id'],'pair_sha256':digest(pair),**record})
    return {'metadata':nli.metadata if nli else None,'rows':rows,
            'membership_approval':False,'quality_gate_passed':False}
