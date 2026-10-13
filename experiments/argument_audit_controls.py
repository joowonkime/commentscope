"""Fixed synthetic role/attitude/dependency controls, not independent gold."""
import argparse
from copy import deepcopy
from pathlib import Path
import time

from commentscope.factory import argument_graph as graph, candidate_completion as completion
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.factory.automatic_contract import digest
from commentscope.storage import write_json_exclusive as write
from commentscope.providers.budget import InferenceBudget
from experiments.argument_graph_probe import allocate
from experiments.fresh_grounded_pipeline import Runner
from experiments.audit_model_compare import owned_server, file_hash
from experiments.scoped_discovery_probe import code_hashes

VERSION = 'argument-role-fixed-controls-0.1'


def controls():
    cases = [
        ('A', True, 'Public transit should be free.', 'value',
         'Public transit should be free because mobility should not depend on income.',
         'Public transit should be free', 'mobility should not depend on income', 'value'),
        ('B', True, 'If I received a grant, I would keep volunteering.', 'prediction',
         'If I received a grant, I would keep volunteering because helping my neighbors matters to me.',
         'If I received a grant, I would keep volunteering', 'helping my neighbors matters to me', 'value'),
        ('C', False, 'Public transit should be free.', 'value',
         'Public transit should be free.', 'Public transit should be free.', 'Public transit should be free.', 'value'),
        ('D', False, 'A flood may close this road.', 'prediction',
         'A flood may close this road. We should plan another route in case that happens.',
         'A flood may close this road.', 'We should plan another route in case that happens.', 'value'),
        ('E', False, 'Robots will do my chores.', 'prediction',
         'I hope robots do my chores. Free time matters to me.',
         'I hope robots do my chores.', 'Free time matters to me.', 'value'),
        ('F', False, 'Helmets should be required.', 'value',
         "Last year's trial cut injuries in half. That is why helmets should be required.",
         'helmets should be required.', "Last year's trial cut injuries in half.", 'value'),
        ('G', False, 'Helmets should be required.', 'value',
         "Last year's trial cut injuries in half. Because it demonstrated that reduction, helmets should be required. Safety matters to me.",
         'helmets should be required.', 'Safety matters to me.', 'value'),
        ('H', False, 'Reviews should remain voluntary.', 'value',
         'Some people say mandatory tests improve safety. I disagree: reviews should remain voluntary because choice matters to me.',
         'reviews should remain voluntary', 'mandatory tests improve safety', 'fact')]
    result = []
    for cid, expected, core, core_kind, source, quote, reason, reason_kind in cases:
        sources = {'author': source}
        unit = {'claim_id': 'unit', 'source_comment_id': 'author', 'quote': quote, 'reason_quote': reason,
                'claim': core, 'condition': None, 'scope': 'as stated'}
        p = {'id': 'P', 'sources': sources, 'claims': {'C': {'id': 'C', 'text': core, 'kind': 'fact',
              'scope': {'entity': 'as stated', 'time': '', 'conditions': ''}, 'requires': []}}}
        inventory = graph.inventory([unit], sources)
        nid = next(k for k, v in inventory['nodes'].items() if v['text'] == reason)
        typed = graph.assemble(p, sources, [unit], core_kind,
            {'status': 'selected', 'node_ids': [nid], 'essential_node_ids': [nid]}, {nid: reason_kind})
        req = allocate(completion.audit_request(typed, sources, [unit]), 768)
        result.append({'id': cid, 'expected_pass': expected, 'typed': typed, 'request': req, 'request_sha256': digest(req)})
    return result


def prepare(directory, deployment_plan):
    if directory.exists(): raise ValueError('Never overwrite control attempt')
    source = read_json(deployment_plan); deployment = deepcopy(source['deployments']['profile'])
    for info in (deployment['server'], deployment['models']['baseline']):
        if file_hash(info['path']) != info['sha256']: raise ValueError('Deployment changed')
    plan = {'artifact_kind': VERSION, 'deployment': deployment, 'budget': source['budget'],
            'inputs': {str(deployment_plan): sha(deployment_plan)}, 'code_sha256': code_hashes(), 'controls': controls(),
            'limits': {'analysis_seconds': 600, 'call_seconds': 90},
            'criteria': {'positive_retained': 2, 'negative_false_approvals': 0},
            'synthetic': True, 'independent_gold': False, 'quality_gate_passed': False}
    write(directory/'plan.json', plan); print({'prepared': True, 'fixed_controls': 8}, flush=True)


def run(directory):
    started = time.monotonic(); plan = read_json(directory/'plan.json')
    if plan['artifact_kind'] != VERSION or plan['controls'] != controls(): raise ValueError('Frozen controls changed')
    for field in ('inputs', 'code_sha256'):
        if any(sha(p) != h for p, h in plan[field].items()): raise ValueError('Frozen file changed')
    for info in (plan['deployment']['server'], plan['deployment']['models']['baseline']):
        if file_hash(info['path']) != info['sha256']: raise ValueError('Deployment changed')
    budget = InferenceBudget(Path(plan['budget']['ledger']), plan['budget']['cycle_id'])
    runner = Runner(directory, plan, budget); runner.started = started
    write(directory/'started.json', {'plan_sha256': runner.plan_sha, 'budget_before': budget.summary()})
    rows = []
    try:
        with owned_server(plan['deployment'], 'baseline', directory/'audit-server'):
            for control in plan['controls']:
                result = runner.call('audit-'+control['id'], control['request'])
                passed = completion.audit_passed(control['typed'], result)
                rows.append({'id': control['id'], 'passed': passed, 'expected_pass': control['expected_pass'], 'errors': result['errors']})
        positive = sum(r['passed'] and r['expected_pass'] for r in rows)
        false = sum(r['passed'] and not r['expected_pass'] for r in rows)
        report = {'artifact_kind': VERSION, 'plan_sha256': runner.plan_sha, 'rows': rows,
                  'positive_retained': positive, 'negative_false_approvals': false,
                  'development_controls_passed': positive == 2 and false == 0 and not any(r['errors'] for r in rows),
                  'elapsed_seconds': time.monotonic()-started, 'quality_gate_passed': False,
                  'independent_gold': False, 'budget_after': budget.summary()}
        write(directory/'completed.json', report)
        print({k: v for k, v in report.items() if k != 'budget_after'}, flush=True)
    except BaseException as exc:
        write(directory/'failed.json', {'exception_type': type(exc).__name__, 'elapsed_seconds': time.monotonic()-started,
              'budget_after': budget.summary(), 'quality_gate_passed': False})
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); sub = parser.add_subparsers(dest='action', required=True)
    p = sub.add_parser('prepare'); p.add_argument('directory', type=Path); p.add_argument('--deployment-plan', type=Path, required=True)
    p = sub.add_parser('run'); p.add_argument('directory', type=Path)
    args = parser.parse_args()
    if args.action == 'prepare': prepare(args.directory, args.deployment_plan)
    else: run(args.directory)
