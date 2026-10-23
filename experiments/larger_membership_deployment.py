"""Authorized single14B deployment comparison, same frozen directed policy.

No new prompts, references, thresholds or repairs. The same eight controls must
pass before attempting the existing100 development relations. GPU offload is a
resource change, so timing is operational rather than isolated size causality.
"""
import argparse
from copy import deepcopy
from pathlib import Path

from commentscope.factory import membership_policy
from commentscope.factory.claim_clusters import read_json,sha
from commentscope.storage import write_json_exclusive as write
from experiments.directed_membership_probe import FIXTURE
from experiments.directed_off_deployment import control_rows,verify_controls
from experiments.reasoning_membership_probe import execute
from experiments.scoped_discovery_probe import code_hashes,validate

MODEL={'name':'Qwen3-14B-Q4_K_M','repository':'Qwen/Qwen3-14B-GGUF',
       'revision':'530227a7d994db8eca5ab5ced2fb692b614357fd',
       'path':'/home/taeng/.cache/commentscope-models/Qwen3-14B-Q4_K_M.gguf',
       'bytes':9001752960,'sha256':'500a8806e85ee9c83f3ae08420295592451379b4f8cf2d0f41c15dffeb6b81f0'}


def prepare(directory,source,controls=None):
    if directory.exists():raise ValueError('Never overwrite an attempt')
    original=read_json(source/'plan.json')
    for path,expected in original['inputs'].items():
        if sha(path)!=expected:raise ValueError('Original inputs changed')
    policy=membership_policy.from_rows(original['rows'])
    if (original.get('directionality_variant')!='asymmetric-entailment-clarification-0.1'
            or original['runtime'].get('reasoning_budget')!=256
            or original['runtime'].get('reasoning')!='on'
            or len(original['evaluation_ids'])!=100 or len(set(original['evaluation_ids']))!=100):
        raise ValueError('Frozen directed thinking deployment and fixed100 required')
    plan=deepcopy(original);plan.pop('reused_records',None);plan.pop('continuation_of',None)
    plan['models']={'baseline':deepcopy(MODEL)}
    plan['model'].update(name=MODEL['name'],revision=MODEL['revision'],weights_sha256=MODEL['sha256'])
    plan['runtime']['gpu_layers']=28
    plan['inputs']={str(source/'plan.json'):sha(source/'plan.json'),str(FIXTURE):sha(FIXTURE),
                   **{p:h for p,h in original['inputs'].items() if p.endswith(('references.json','reference-frozen.json'))}}
    plan['comparison']='Authorized14B instead of8B; same directed policy/schema/requests/references/256-token reasoning.28 GPU layers for8GiB device; operational deployment comparison.'
    plan['plumbing_only']=controls is None;plan['stop_on_impossible']=True
    if controls is None:
        plan['rows']=control_rows(policy);plan['evaluation_ids']=[r['id'] for r in plan['rows']]
    else:
        verify_controls(controls,plan)
        plan['inputs'].update({str(controls/name):sha(controls/name) for name in ['plan.json','completed.json','report.json']})
    plan['code_sha256']=code_hashes();validate(plan)
    write(directory/'plan.json',plan)
    print({'prepared':True,'controls_only':plan['plumbing_only'],'requests':len(plan['rows']),'model':MODEL['name']},flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('phase',choices=['prepare','run']);p.add_argument('directory',type=Path)
    p.add_argument('--source',type=Path,default=Path('runs/atomic8b-directed-membership-20261013'));p.add_argument('--controls',type=Path)
    a=p.parse_args()
    if a.phase=='prepare':prepare(a.directory,a.source,a.controls)
    else:execute(a.directory)
