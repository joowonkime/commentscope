"""Replay the frozen eight fact cases with the already-cached 8B deployment.

No changed claims, evidence, prompts, labels, sampling or acceptance criteria.
This is a deployment comparison, not a parameter-count-only ablation.
"""
import argparse
from copy import deepcopy
from pathlib import Path

from commentscope.factory import fact_checks as facts
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.storage import write_json_exclusive as write
from experiments.audit_model_compare import CANDIDATE, file_hash
from experiments import fact_evidence_probe as base


def deployment_plan(original, candidate):
    plan = deepcopy(original)
    plan['models'] = {'baseline': deepcopy(candidate)}
    plan['model'] = {'name': candidate['name'], 'revision': candidate['revision'],
                     'weights_sha256': candidate['sha256'],
                     'runtime_sha256': plan['server']['sha256']}
    for row in plan['rows']:
        row['request_sha256'] = digest(facts.invocation(row['packet'], plan['model']))
    plan['comparison'] = 'Same frozen cases and requests; different cached model and native chat template.'
    return plan


def prepare(directory, original_directory):
    if directory.exists():
        raise ValueError('Never overwrite an attempt')
    base.verify(original_directory)
    original = read_json(original_directory/'plan.json')
    if file_hash(CANDIDATE['path']) != CANDIDATE['sha256']:
        raise ValueError('Cached candidate model changed')
    plan = deployment_plan(original, CANDIDATE)
    plan['inputs'].update({str(original_directory/name): sha(original_directory/name)
                          for name in ['plan.json', 'completed.json', 'report.json']})
    plan['code_sha256'] = {str(p): sha(p) for root in ['src/commentscope', 'experiments']
                          for p in sorted(Path(root).rglob('*.py'))}
    write(directory/'plan.json', plan)
    print({'prepared': True, 'cases': 8, 'new_model_calls': 0,
           'plan_sha256': sha(directory/'plan.json')}, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--original-dir', type=Path,
                        default=Path('runs/fact-evidence-development-20261013'))
    parser.add_argument('--phase', choices=['prepare', 'run', 'verify'], required=True)
    args = parser.parse_args()
    if args.phase == 'prepare': prepare(args.run_dir, args.original_dir)
    elif args.phase == 'run': base.execute(args.run_dir, base.DEFAULT_BUDGET)
    else: base.verify(args.run_dir)


if __name__ == '__main__': main()
