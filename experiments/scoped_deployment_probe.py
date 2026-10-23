"""Same proposal requests on the existing non-thinking 4B Instruct deployment.

This changes proposal deployment only, not membership judging or reference
labels. It does not resume the stopped same-4B source-auditor prompt family.
"""
import argparse
from copy import deepcopy
from pathlib import Path
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.storage import write_json_exclusive as write
from experiments.scoped_discovery_probe import code_hashes, validate


def prepare(source,directory):
    if directory.exists(): raise ValueError('Never overwrite an attempt')
    original=read_json(source/'plan.json');validate(original)
    baseline=read_json('runs/fact-evidence-development-20261013/plan.json')
    plan=deepcopy(original)
    plan['models']=baseline['models'];plan['model']=baseline['model']
    plan['inputs'][str(source/'plan.json')]=sha(source/'plan.json')
    plan['code_sha256']=code_hashes()
    plan['comparison']='Identical proposal inputs, schema and prompt; cached 4B Instruct instead of cached 8B. Native templates/training differ.'
    write(directory/'plan.json',plan)
    print({'prepared':True,'model':plan['model']['name'],'groups':len(plan['rows'])},flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('source',type=Path);p.add_argument('directory',type=Path)
    a=p.parse_args();prepare(a.source,a.directory)
