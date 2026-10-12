"""Freeze 8B membership requests for any frozen proposal deployment."""
import argparse
from pathlib import Path
from commentscope.factory.claim_clusters import read_json,sha
from commentscope.storage import write_json_exclusive as write
from experiments.scoped_discovery_probe import prepare_judgments,code_hashes


def prepare(source,directory):
    if directory.exists():raise ValueError('Never overwrite an attempt')
    origin=directory/'proposal-origin'
    prepare_judgments(origin,source)
    plan=read_json(origin/'plan.json')
    deployment=read_json('runs/fact-evidence-8b-20261013/plan.json')
    plan.update(models=deployment['models'],model=deployment['model'],runtime=deployment['runtime'],server=deployment['server'])
    plan['inputs'][str(origin/'plan.json')]=sha(origin/'plan.json')
    plan['code_sha256']=code_hashes()
    plan['membership_deployment']='Cached 8B, independent full-source judgments; proposal model may differ.'
    write(directory/'plan.json',plan)
    write(directory/'evaluation-inputs.json',read_json(origin/'evaluation-inputs.json'))
    print({'prepared_membership':len(plan['rows']),'model':plan['model']['name']},flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('source',type=Path);p.add_argument('directory',type=Path)
    a=p.parse_args();prepare(a.source,a.directory)
