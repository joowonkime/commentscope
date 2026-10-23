"""Reconcile a proven interrupted LLM call without inference or ledger mutation.

This offline operation preserves the failure; it is not a retry, response repair,
or semantic approval. The frozen runtime remains unchanged. Publication can be
repeated after interruption only when every existing artifact still agrees.
"""
import argparse
import json
import os
from pathlib import Path
import re
import sqlite3

from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.providers.checkpoint_calls import VERSION as CHECKPOINT_VERSION
from commentscope.storage import write_json_exclusive as write
from experiments.audit_model_compare import command
from experiments.framed_corpus_pipeline import PRIVATE_ROOT, experiment_lock, validate

VERSION = 'terminal-interrupted-call-reconciliation-0.1'


def require_dead(pid):
    if type(pid) is not int or pid <= 0:
        raise ValueError('Invalid process identity')
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return
    # Permission errors also fail closed. A reused PID is not assumed safe.
    raise ValueError('Original process still exists; do not reconcile a live attempt')


def reconcile(directory, key, *, apply=False):
    directory = Path(directory)
    if not directory.resolve().is_relative_to(PRIVATE_ROOT.resolve()):
        raise ValueError('Recovery artifacts must remain private')
    if not isinstance(key, str) or not re.fullmatch('[0-9a-f]{64}', key):
        raise ValueError('Exact checkpoint key required')
    with experiment_lock(directory):
        plan_path = directory/'plan.json'
        plan = read_json(plan_path)
        validate(plan)
        plan_hash = sha(plan_path)
        if (directory/'completed.json').exists():
            raise ValueError('Cannot reconcile a completed experiment')
        origin_path = directory/'started.json'
        if read_json(origin_path)['plan_sha256'] != plan_hash:
            raise ValueError('Original plan identity changed')
        attempts = sorted((directory/'attempts').glob('*.started.json'))
        if not attempts:
            raise ValueError('Missing attempt')
        start_path = attempts[-1]
        attempt = start_path.name.split('.', 1)[0]
        failed_path = directory/'attempts'/(attempt+'.failed.json')
        start, failed = read_json(start_path), read_json(failed_path)
        if start['plan_sha256'] != plan_hash or failed['exception_type'] != 'KeyboardInterrupt':
            raise ValueError('Expected a matching interrupted attempt')
        require_dead(start['pid'])
        runtime_path = directory/'servers'/attempt/'runtime.json'
        stop_path = directory/'servers'/attempt/'stopped.json'
        runtime, stop = read_json(runtime_path), read_json(stop_path)
        if (stop['returncode'] != 0 or stop['pid'] != runtime['pid']
                or runtime['command'] != command(plan['deployment'], 'baseline')):
            raise ValueError('Server shutdown or deployment identity is unproven')
        require_dead(stop['pid'])
        intent_path = directory/'checkpoints'/(key+'.intent.json')
        done_path = directory/'checkpoints'/(key+'.result.json')
        identity = read_json(intent_path)
        if (set(identity) != {'artifact_kind', 'plan_sha256', 'stage', 'request_sha256', 'provider'}
                or identity['artifact_kind'] != CHECKPOINT_VERSION or digest(identity) != key
                or identity['plan_sha256'] != plan_hash or identity['provider'] != 'local_llama'
                or not re.fullmatch('[A-Za-z0-9_-]{1,160}', identity['stage'])):
            raise ValueError('Unsupported or changed checkpoint identity')
        requests = sorted((directory/'calls').glob('*.request.json'))
        matches = [p for p in requests if p.name.split('-', 1)[-1] == identity['stage']+'.request.json']
        if len(matches) != 1 or matches[0] != requests[-1]:
            raise ValueError('Expected the unique final request of the interrupted attempt')
        request_path = matches[0]
        logged = read_json(request_path)
        if (logged['plan_sha256'] != plan_hash or logged['request_sha256'] != identity['request_sha256']
                or digest(logged['request']) != identity['request_sha256']):
            raise ValueError('Request identity changed')
        ledger_path = Path(plan['budget']['ledger']).resolve()
        with sqlite3.connect(ledger_path.as_uri()+'?mode=ro', uri=True) as db:
            db.row_factory = sqlite3.Row
            policy = db.execute('SELECT cycle,limit_seconds FROM policy WHERE id=1').fetchone()
            if policy['cycle'] != plan['budget']['cycle_id'] or policy['limit_seconds'] is not None:
                raise ValueError('Unexpected ledger policy')
            if db.execute("SELECT count(*) FROM calls WHERE plan_sha=? AND state='reserved'", (plan_hash,)).fetchone()[0]:
                raise ValueError('Unfinished reservation; do not infer terminal state')
            rows = db.execute('SELECT * FROM calls WHERE plan_sha=? AND request_sha=?',
                              (plan_hash, identity['request_sha256'])).fetchall()
        if len(rows) != 1:
            raise ValueError('Missing or ambiguous ledger call')
        row = dict(rows[0])
        if (row['state'] != 'interrupted' or row['error'] != 'KeyboardInterrupt'
                or row['response_json'] is not None or json.loads(row['request_json']) != logged['request']
                or row['started_at'] < start['started_at'] or row['elapsed'] is None
                or row['reserved'] != logged['timeout_seconds']+3
                or row['charged'] < max(row['reserved'], row['elapsed'])):
            raise ValueError('Ledger does not prove this interrupted request')
        recorded = [r for r in failed['budget_after']['calls'] if r['id'] == row['id']]
        expected_row = dict(zip(
            ['id', 'plan_sha256', 'request_sha256', 'reserved_seconds', 'charged_seconds', 'elapsed_seconds', 'state', 'error'],
            [row[k] for k in ('id', 'plan_sha', 'request_sha', 'reserved', 'charged', 'elapsed', 'state', 'error')]))
        if recorded != [expected_row]:
            raise ValueError('Failed attempt and ledger disagree')
        result = {'raw': None, 'output': None, 'errors': ['bounded_call_interrupted'],
                  'seconds': None, 'usage': None}
        done = {'identity': identity, 'result': result, 'result_sha256': digest(result)}
        paths = [plan_path, origin_path, start_path, failed_path, runtime_path, stop_path, intent_path, request_path]
        report = {'artifact_kind': VERSION, 'plan_sha256': plan_hash, 'checkpoint_key': key,
                  'ledger': str(ledger_path), 'ledger_call': expected_row, 'ledger_row_sha256': digest(row),
                  'inputs_sha256': {str(p): sha(p) for p in paths}, 'recovery_code_sha256': sha(__file__),
                  'result_sha256': digest(result), 'model_calls': 0, 'ledger_modified': False,
                  'semantic_result_reconstructed': False, 'action': 'preserve_terminal_interruption'}
        report_path = directory/'recoveries'/(key+'.json')
        result_path = request_path.with_name(request_path.name.replace('.request.json', '.result.json'))
        publications = [(report_path, report), (result_path, result), (done_path, done)]
        # Validate all preexisting publications before making the first write.
        for path, value in publications:
            if path.exists() and read_json(path) != value:
                raise ValueError('Existing recovery/result differs; never overwrite')
        if apply:
            for path, value in publications:
                if not path.exists():
                    write(path, value)
        return {'applied': apply, 'report': report, 'checkpoint_published': done_path.exists()}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--checkpoint', required=True)
    parser.add_argument('--apply', action='store_true', help='Publish a proven failure; default is inspect only')
    args = parser.parse_args()
    print(json.dumps(reconcile(args.directory, args.checkpoint, apply=args.apply), ensure_ascii=False, indent=2))
