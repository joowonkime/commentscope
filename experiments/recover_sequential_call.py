"""Preserve a proven interrupted LLM call in the frozen sequential execution.

This separate adapter leaves its already-pinned predecessor unchanged. It does
not retry, refund, repair a response, alter labels, or weaken startup guards.
Normal model/input validation runs here and again on actual same-plan resume.
"""
import argparse
import json
from pathlib import Path
import re
import sqlite3
from contextlib import closing

from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.providers.checkpoint_calls import VERSION as CHECKPOINT_VERSION
from commentscope.storage import write_json_exclusive as write
from experiments import sequential_corpus_pipeline as pipeline
from experiments.recover_interrupted_call import require_dead

VERSION = 'sequential-terminal-interrupted-call-reconciliation-0.1'


def stopped_models(directory, attempt, plan):
    """All recorded owned models must have completed cleanup, not just the last."""
    root = directory/'models'/attempt; paths = []
    owned = sorted(p for p in root.iterdir() if p.is_dir())
    if not owned or not any(p.name.startswith('llm-') for p in owned):
        raise ValueError('Owned sequential server shutdown evidence required')
    for target in owned:
        if re.fullmatch(r'llm-[0-9]{4}', target.name):
            files = [target/'runtime.json', target/'stopped.json', target/'resources/finished.json']
            runtime, stopped, finished = [read_json(p) for p in files]
            if (stopped['returncode'] != 0 or stopped['pid'] != runtime['pid']
                    or runtime['command'] != pipeline.command(plan['deployment'], 'baseline')
                    or finished['observer_stopped'] is not True):
                raise ValueError('Sequential server or resource observer shutdown unproven')
            require_dead(stopped['pid']); paths.extend(files)
        elif re.fullmatch(r'auxiliary-[0-9]{4}', target.name):
            path = target/'finished.json'
            if read_json(path)['observer_stopped'] is not True:
                raise ValueError('Auxiliary observer shutdown unproven')
            paths.append(path)
        else:
            raise ValueError('Unknown owned model lifecycle')
    return paths


def reconcile(directory, key, *, apply=False):
    directory = Path(directory); pipeline.private(directory)
    if not isinstance(key, str) or not re.fullmatch('[0-9a-f]{64}', key):
        raise ValueError('Exact checkpoint key required')
    with pipeline.experiment_lock(directory):
        plan_path = directory/'plan.json'; plan = read_json(plan_path)
        pipeline.validate(plan); plan_hash = sha(plan_path)
        if (directory/'completed.json').exists(): raise ValueError('Cannot reconcile a completed execution')
        origin_path = directory/'started.json'
        if read_json(origin_path)['plan_sha256'] != plan_hash: raise ValueError('Original plan identity changed')
        attempts = sorted((directory/'attempts').glob('*.started.json'))
        if not attempts: raise ValueError('Missing sequential attempt')
        start_path = attempts[-1]; attempt = start_path.name.split('.', 1)[0]
        failed_path = directory/'attempts'/(attempt+'.failed.json')
        start, failed = read_json(start_path), read_json(failed_path)
        if start['plan_sha256'] != plan_hash or failed['exception_type'] != 'KeyboardInterrupt':
            raise ValueError('Matching interrupted sequential attempt required')
        require_dead(start['pid'])
        model_paths = stopped_models(directory, attempt, plan)
        intent_path = directory/'checkpoints'/(key+'.intent.json')
        done_path = directory/'checkpoints'/(key+'.result.json')
        identity = read_json(intent_path)
        if (set(identity) != {'artifact_kind', 'plan_sha256', 'stage', 'request_sha256', 'provider'}
                or identity['artifact_kind'] != CHECKPOINT_VERSION or digest(identity) != key
                or identity['plan_sha256'] != plan_hash or identity['provider'] != 'local_llama'
                or not re.fullmatch('[A-Za-z0-9_-]{1,160}', identity['stage'])):
            raise ValueError('Unsupported or changed sequential checkpoint identity')
        transitions = sorted((directory/'transitions'/attempt).glob('*.started.json'))
        if not transitions: raise ValueError('Sequential transition evidence required')
        transition_path = transitions[-1]
        transition_failed = transition_path.with_name(transition_path.name.replace('.started.json', '.failed.json'))
        transition_finished = transition_path.with_name(transition_path.name.replace('.started.json', '.finished.json'))
        transition = read_json(transition_path)
        if (transition_finished.exists() or transition['kind'] != 'llm'
                or any(transition[k] != identity[k] for k in ('stage', 'plan_sha256', 'request_sha256'))
                or read_json(transition_failed) != {'exception_type': 'KeyboardInterrupt', 'stage': identity['stage']}):
            raise ValueError('Final interrupted LLM transition differs from checkpoint')
        requests = sorted((directory/'calls').glob('*.request.json'))
        matches = [p for p in requests if p.name.split('-', 1)[-1] == identity['stage']+'.request.json']
        if len(matches) != 1 or matches[0] != requests[-1]:
            raise ValueError('Unique final request of interrupted attempt required')
        request_path = matches[0]; logged = read_json(request_path)
        if (logged['plan_sha256'] != plan_hash or logged['request_sha256'] != identity['request_sha256']
                or digest(logged['request']) != identity['request_sha256']
                or logged['timeout_seconds'] != plan['limits']['call_seconds']):
            raise ValueError('Interrupted request identity or finite timeout changed')
        ledger_path = Path(plan['budget']['ledger']).resolve()
        with closing(sqlite3.connect(ledger_path.as_uri()+'?mode=ro', uri=True)) as db:
            db.row_factory = sqlite3.Row
            policy = db.execute('SELECT cycle,limit_seconds FROM policy WHERE id=1').fetchone()
            if policy['cycle'] != plan['budget']['cycle_id'] or policy['limit_seconds'] is not None:
                raise ValueError('Unexpected ledger policy')
            if db.execute("SELECT count(*) FROM calls WHERE plan_sha=? AND state='reserved'", (plan_hash,)).fetchone()[0]:
                raise ValueError('Unfinished reservation; terminal state is unproven')
            rows = db.execute('SELECT * FROM calls WHERE plan_sha=? AND request_sha=?',
                              (plan_hash, identity['request_sha256'])).fetchall()
        if len(rows) != 1: raise ValueError('Missing or ambiguous ledger call')
        row = dict(rows[0])
        if (row['state'] != 'interrupted' or row['error'] != 'KeyboardInterrupt'
                or row['response_json'] is not None or json.loads(row['request_json']) != logged['request']
                or row['started_at'] < start['started_at'] or row['elapsed'] is None
                or row['reserved'] != logged['timeout_seconds']+3
                or row['charged'] < max(row['reserved'], row['elapsed'])):
            raise ValueError('Ledger does not prove this interrupted request')
        expected_row = dict(zip(
            ['id', 'plan_sha256', 'request_sha256', 'reserved_seconds', 'charged_seconds', 'elapsed_seconds', 'state', 'error'],
            [row[k] for k in ('id', 'plan_sha', 'request_sha', 'reserved', 'charged', 'elapsed', 'state', 'error')]))
        if [r for r in failed['budget_after']['calls'] if r['id'] == row['id']] != [expected_row]:
            raise ValueError('Failed attempt and ledger disagree')
        result = {'raw': None, 'output': None, 'errors': ['bounded_call_interrupted'], 'seconds': None, 'usage': None}
        done = {'identity': identity, 'result': result, 'result_sha256': digest(result)}
        paths = [plan_path, origin_path, start_path, failed_path, *model_paths,
                 transition_path, transition_failed, intent_path, request_path]
        report = {'artifact_kind': VERSION, 'plan_sha256': plan_hash, 'checkpoint_key': key,
            'ledger': str(ledger_path), 'ledger_call': expected_row, 'ledger_row_sha256': digest(row),
            'inputs_sha256': {str(p): sha(p) for p in paths},
            'recovery_code_sha256': {str(Path(__file__)): sha(__file__),
                'experiments/recover_interrupted_call.py': sha('experiments/recover_interrupted_call.py')},
            'result_sha256': digest(result), 'model_calls': 0, 'ledger_modified': False,
            'semantic_result_reconstructed': False, 'action': 'preserve_terminal_interruption'}
        result_path = request_path.with_name(request_path.name.replace('.request.json', '.result.json'))
        publications = [(directory/'recoveries'/(key+'.json'), report), (result_path, result), (done_path, done)]
        for path, value in publications:
            if path.exists() and read_json(path) != value:
                raise ValueError('Existing recovery/result differs; never overwrite')
        if apply:
            for path, value in publications:
                if not path.exists(): write(path, value)
        return {'applied': apply, 'report': report, 'checkpoint_published': done_path.exists()}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--checkpoint', required=True)
    parser.add_argument('--apply', action='store_true', help='Publish only the proven failure; default is inspect')
    args = parser.parse_args()
    print(json.dumps(reconcile(args.directory, args.checkpoint, apply=args.apply), ensure_ascii=False, indent=2))
