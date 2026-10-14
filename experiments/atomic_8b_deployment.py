"""Cached 8B core-only proposal comparison on the same frozen twenty groups.

No membership prompt iteration. Same proposal prompt/schema/source groups as
the previous 4B core-only run. New target outputs require a separately frozen
relation sample before judging; they cannot turn the old fixed100 failure into
a pass or be compared as identical-target accuracy.
"""
import argparse
from copy import deepcopy
from pathlib import Path
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json,sha
from commentscope.storage import write_json_exclusive as write
from experiments import atomic_discovery_probe as atomic
from experiments.scoped_discovery_probe import code_hashes,validate


def prepare(directory,source,deployment):
    if directory.exists():raise ValueError('Never overwrite an attempt')
    original=read_json(source/'plan.json');model=read_json(deployment/'plan.json')
    if len(original['rows'])!=20:raise ValueError('Same frozen twenty groups required')
    for path,expected in original['inputs'].items():
        if sha(path)!=expected:raise ValueError('Original proposal inputs changed')
    for row in original['rows']:
        if row['request']!=atomic.invocation(row['sources']) or digest(row['request'])!=row['request_sha256']:
            raise ValueError('Original proposal request changed')
    plan=deepcopy(original)
    plan.update(models=deepcopy(model['models']),server=deepcopy(model['server']),runtime=deepcopy(model['runtime']),model=deepcopy(model['model']))
    plan['runtime'].update(context=8192,gpu_layers='all',template_kwargs={'enable_thinking':False},
                           reasoning='off',reasoning_budget=0,max_tokens=350)
    plan['inputs'].update({str(source/'plan.json'):sha(source/'plan.json'),str(deployment/'plan.json'):sha(deployment/'plan.json')})
    plan['code_sha256']=code_hashes()
    plan['comparison']='Same core-only prompt/schema/20 groups, cached 8B instead of 4B. No source-auditor prompt change.'
    plan['new_relation_protocol']={'selection':'Interleave candidate queues by frozen group order, within each queue source-ID hash order, first100. Freeze labels before relation inference; if fewer than100 stop.',
          'references':'Assistant offline development references, not runtime inputs or independent gold.',
          'old_fixed100':'Preserve failed results unchanged. New target relation metrics are not identical-target improvement.',
          'criteria':{'precision_min':.95,'positive_retention_min':.8,'sample_size':100},
          'repairs':0,'retries':0}
    validate(plan);write(directory/'plan.json',plan)
    print({'prepared':True,'groups':20,'same_proposal_requests':True,'model':plan['models']['baseline']['name']},flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('phase',choices=['prepare','run']);p.add_argument('directory',type=Path)
    p.add_argument('--source',type=Path,default=Path('runs/atomic-discovery-20261013'))
    p.add_argument('--deployment',type=Path,default=Path('runs/reasoning-membership-on-20261013'))
    a=p.parse_args()
    if a.phase=='prepare':prepare(a.directory,a.source,a.deployment)
    else:atomic.discover(a.directory)
