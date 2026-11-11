"""Audited terminal HTTP failures become unavailable tasks, never paid retries.

The original wide plan, execution files, checkpoints and money history stay
immutable. A separate manifest binds this additional control and its archive.
Only development-wide runs are supported; formal admission remains disabled.
"""
import argparse
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
for item in (ROOT, ROOT/'src'):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from tools import wide_mining_trial as wide
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.factory.shared_admission import PriorRequestUnavailable
from commentscope.providers.generation_limits import allocate
from commentscope.providers.checkpoint_calls import VERSION as CHECKPOINT_VERSION
from commentscope.storage import write_json_exclusive as write

VERSION = 'wide-terminal-unavailable-recovery-20261111-v1'
TOOL = Path(__file__).resolve()
TEMPORARY_HTTP = (429, 500, 502, 503, 504)
trial = wide.trial
executor = wide.executor


@contextmanager
def database(path):
    connection = sqlite3.connect('file:'+str(Path(path).resolve())+'?mode=ro', uri=True)
    try:
        yield connection
    finally:
        connection.close()


def terminal_evidence(directory, plan, request_file):
    """Inspect an exact terminal error, its checkpoint and its money owner."""
    directory = Path(directory).resolve()
    request_file = Path(request_file).resolve()
    if request_file.parent != directory/'calls' or not request_file.name.endswith('.request.json'):
        raise ValueError('Original call request required')
    saved = read_json(request_file)
    req_sha = digest(saved['request'])
    if saved['plan_sha256'] != sha(directory/'plan.json') or saved['request_sha256'] != req_sha:
        raise ValueError('Original request binding changed')
    result_file = request_file.with_name(request_file.name.replace('.request.json', '.result.json'))
    result = read_json(result_file)
    if (result.get('raw') is not None or result.get('output') is not None
            or result.get('usage') is not None or result.get('errors') != ['bounded_call_failed']):
        raise ValueError('Only a terminal unavailable transport result may be held')
    with database(directory/'inference.sqlite') as db:
        rows = db.execute('SELECT id,state,error FROM calls WHERE plan_sha=? AND request_sha=?',
                          (sha(directory/'plan.json'), req_sha)).fetchall()
    if len(rows) != 1 or rows[0][1] != 'error' or not rows[0][2]:
        raise ValueError('One original terminal inference error required')
    error = json.loads(rows[0][2])
    if error.get('type') != 'HTTPError' or error.get('http_status') not in TEMPORARY_HTTP:
        raise ValueError('Explicit temporary HTTP failure required; no ambiguous interruption')
    stage = re.sub(r'^\d+-', '', request_file.name.removesuffix('.request.json'))
    intents = []
    for path in (directory/'checkpoints').glob('*.intent.json'):
        identity = read_json(path)
        if identity.get('stage') == stage and identity.get('request_sha256') == req_sha:
            intents.append((path, identity))
    if len(intents) != 1:
        raise ValueError('Unique original checkpoint required')
    intent, identity = intents[0]
    checkpoint = intent.with_name(intent.name.replace('.intent.json', '.result.json'))
    completed = read_json(checkpoint)
    if (set(identity) != {'artifact_kind', 'plan_sha256', 'stage', 'request_sha256', 'provider'}
            or identity['artifact_kind'] != CHECKPOINT_VERSION
            or intent.name != digest(identity)+'.intent.json'
            or identity['plan_sha256'] != saved['plan_sha256']
            or identity['provider'] != executor.openrouter.Runner.provider_identity
            or completed != {'identity': identity, 'result': result, 'result_sha256': digest(result)}):
        raise ValueError('Terminal checkpoint provenance changed')
    with database(plan['spend_policy']['ledger']) as db:
        money = db.execute('SELECT id,reserved,charged,state FROM calls WHERE plan_sha=? AND request_sha=?',
                           (plan['spend_scope_sha256'], req_sha)).fetchall()
    if (len(money) != 1 or money[0][3] not in ('unknown', 'conservative')
            or money[0][1] != money[0][2] or money[0][1] <= 0):
        raise ValueError('Exact retained full reservation required; never refund or retry')
    return {'plan_sha256': saved['plan_sha256'], 'scope_sha256': plan['spend_scope_sha256'],
            'request_sha256': req_sha, 'stage': stage, 'inference_id': rows[0][0],
            'inference_error_sha256': digest(error), 'http_status': error['http_status'],
            'ledger_call_id': money[0][0], 'retained_units': money[0][1],
            'files': {str(p.relative_to(directory)): sha(p)
                      for p in (request_file, result_file, intent, checkpoint)}}


def settled(directory, plan, entry):
    proof = read_json(entry['proof_file'])
    if (proof.get('version') != VERSION+'-proof'
            or sha(entry['proof_file']) != entry['proof_sha256']):
        raise ValueError('Recovery proof changed')
    current = terminal_evidence(directory, plan, directory/entry['request_file'])
    if proof.get('evidence') != current:
        raise ValueError('Original terminal evidence changed')
    with database(plan['spend_policy']['ledger']) as db:
        row = db.execute('SELECT state FROM calls WHERE id=?', (current['ledger_call_id'],)).fetchone()
        resolution = db.execute('SELECT evidence_sha FROM resolutions WHERE call_id=?',
                                (current['ledger_call_id'],)).fetchone()
    if row != ('conservative',) or resolution != (entry['proof_sha256'],):
        raise ValueError('Full reservation must be conservatively reconciled before continuation')
    return current


def prepare(directory, manifest_file, *, user_request):
    directory = Path(directory).resolve()
    manifest_file = Path(manifest_file).resolve()
    executor.private(manifest_file)
    if not user_request.strip() or manifest_file.exists() or not manifest_file.is_relative_to(directory/'recoveries'):
        raise ValueError('Fresh explicit recovery manifest inside the original run required')
    with executor.experiment_lock(directory):
        plan = wide.validate(directory)
        failed = []
        for path in (directory/'calls').glob('*.result.json'):
            value = read_json(path)
            if value.get('raw') is None and value.get('errors') == ['bounded_call_failed']:
                request = path.with_name(path.name.replace('.result.json', '.request.json'))
                failed.append((request, terminal_evidence(directory, plan, request)))
        if not failed:
            raise ValueError('No original terminal transport failure to reconcile')
        money = executor.ledger(plan['spend_policy'])
        summary = money.summary()
        with database(plan['spend_policy']['ledger']) as db:
            unknown = {r[0] for r in db.execute("SELECT id FROM calls WHERE state='unknown'")}
        if summary['reserved_calls'] or not unknown <= {r['ledger_call_id'] for _, r in failed}:
            raise ValueError('Other active or uncertain calls block continuation')
        entries = []
        for request, evidence in sorted(failed):
            proof_file = manifest_file.parent/(str(evidence['ledger_call_id'])+'-proof.json')
            proof = {'version': VERSION+'-proof', 'evidence': evidence}
            if proof_file.exists():
                if read_json(proof_file) != proof:
                    raise ValueError('Existing recovery proof changed')
            else:
                write(proof_file, proof)
            with database(plan['spend_policy']['ledger']) as db:
                state = db.execute('SELECT state FROM calls WHERE id=?', (evidence['ledger_call_id'],)).fetchone()[0]
            if state == 'unknown':
                money.resolve_conservatively(evidence['ledger_call_id'],
                    plan_sha256=plan['spend_scope_sha256'], request_sha256=evidence['request_sha256'],
                    evidence_sha256=sha(proof_file),
                    reason='Audited terminal HTTP failure: retain full original reservation; no provider retry or actual zero-cost claim.')
            entry = {'request_file': str(request.relative_to(directory)),
                     'proof_file': str(proof_file), 'proof_sha256': sha(proof_file)}
            settled(directory, plan, entry)
            entries.append(entry)
        archive = manifest_file.parent/'launcher.py'
        archive.parent.mkdir(parents=True, exist_ok=True)
        if archive.exists():
            if sha(archive) != sha(TOOL):
                raise ValueError('Archived recovery launcher changed')
        else:
            with archive.open('xb') as stream:
                stream.write(TOOL.read_bytes())
        body = {'version': VERSION, 'user_request': user_request, 'plan_sha256': sha(directory/'plan.json'),
                'run_directory': str(directory), 'launcher_file': str(TOOL), 'launcher_sha256': sha(TOOL),
                'launcher_archive': str(archive), 'entries': entries,
                'created_at': datetime.now(timezone.utc).isoformat(),
                'provider_retries': 0, 'formal_admission_eligible': False,
                'original_models_prompts_inputs_limits_deadline_unchanged': True}
        write(manifest_file, {**body, 'integrity_sha256': digest(body)})
        validate(directory, manifest_file, plan)
        return {'manifest': str(manifest_file), 'unavailable_requests': len(entries),
                'retries': 0, 'spending': money.summary()}


def validate(directory, manifest_file, plan):
    directory = Path(directory).resolve()
    manifest_file = Path(manifest_file).resolve()
    value = read_json(manifest_file)
    body = {k: v for k, v in value.items() if k != 'integrity_sha256'}
    fields = {'version', 'user_request', 'plan_sha256', 'run_directory', 'launcher_file',
              'launcher_sha256', 'launcher_archive', 'entries', 'created_at', 'provider_retries',
              'formal_admission_eligible', 'original_models_prompts_inputs_limits_deadline_unchanged',
              'integrity_sha256'}
    if (set(value) != fields or not manifest_file.is_relative_to(directory/'recoveries')
            or value['integrity_sha256'] != digest(body) or value.get('version') != VERSION
            or value.get('plan_sha256') != sha(directory/'plan.json')
            or value.get('run_directory') != str(directory)
            or value.get('provider_retries') != 0 or value.get('formal_admission_eligible') is not False
            or value.get('original_models_prompts_inputs_limits_deadline_unchanged') is not True
            or not value.get('user_request', '').strip() or not value.get('entries')
            or value.get('launcher_file') != str(TOOL)
            or value.get('launcher_sha256') != sha(TOOL)
            or sha(value['launcher_archive']) != sha(TOOL)):
        raise ValueError('Closed immutable recovery control changed')
    seen = set()
    for entry in value['entries']:
        if (set(entry) != {'request_file', 'proof_file', 'proof_sha256'}
                or not Path(entry['proof_file']).resolve().is_relative_to(manifest_file.parent)):
            raise ValueError('Original run recovery proof required')
        row = settled(directory, plan, entry)
        key = (row['stage'], row['request_sha256'])
        if key in seen:
            raise ValueError('Duplicate unavailable request')
        seen.add(key)
    return value


def wire_identity(plan, stage, request):
    stage = trial.mapped_stage(stage)
    role = executor.remote.role(stage)
    key = 'generation' if role == 'interaction' else role
    field = 'deployment' if key == 'generation' else 'verification_deployment'
    actual = allocate(request, executor.openrouter.generation_allocation(plan[field], require_explicit=True))
    return key+'-'+stage, digest(actual)


def dispatch_binding(directory, manifest_file, plan):
    manifest = validate(directory, manifest_file, plan)
    entries = {}
    for entry in manifest['entries']:
        evidence = read_json(entry['proof_file'])['evidence']
        entries[(evidence['stage'], evidence['request_sha256'])] = deepcopy(entry)
    return {'manifest_sha256': sha(manifest_file), 'launcher_sha256': sha(TOOL), 'entries': entries}


def guarded_call(directory, plan, manifest_file, stage, request, original_call, *, _binding=None):
    binding = dispatch_binding(directory, manifest_file, plan) if _binding is None else _binding
    if sha(manifest_file) != binding['manifest_sha256'] or sha(TOOL) != binding['launcher_sha256']:
        raise ValueError('Recovery control changed during execution')
    key = wire_identity(plan, stage, request)
    if key in binding['entries']:
        settled(directory, plan, binding['entries'][key])
        raise PriorRequestUnavailable('Audited terminal HTTP failure retained as unavailable; no paid retry')
    return original_call()


def run(directory, manifest_file):
    directory = Path(directory).resolve()
    manifest_file = Path(manifest_file).resolve()
    plan = wide.validate(directory)
    manifest = validate(directory, manifest_file, plan)
    binding = dispatch_binding(directory, manifest_file, plan)
    class RecoverySession(wide.Session):
        def call(self, stage, request):
            parent_call = super().call
            return guarded_call(directory, self.plan, manifest_file, stage, request,
                                lambda: parent_call(stage, request), _binding=binding)
    done = trial.run(directory, _validate=wide.validate, _kind=wide.VERSION, _session=RecoverySession)
    binding = {'version': VERSION+'-completion', 'plan_sha256': manifest['plan_sha256'],
               'completed_sha256': sha(directory/'completed.json'),
               'recovery_manifest_file': str(manifest_file), 'recovery_manifest_sha256': sha(manifest_file),
               'unavailable_requests': len(manifest['entries']), 'provider_retries': 0,
               'formal_admission_eligible': False}
    path = manifest_file.parent/'completed-binding.json'
    if path.exists():
        if read_json(path) != binding:
            raise ValueError('Recovery completion binding changed')
    else:
        write(path, binding)
    return done


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    command = sub.add_parser('prepare')
    command.add_argument('directory', type=Path)
    command.add_argument('manifest', type=Path)
    command.add_argument('--user-request', required=True)
    command = sub.add_parser('run')
    command.add_argument('directory', type=Path)
    command.add_argument('manifest', type=Path)
    command.add_argument('--live', action='store_true')
    command.add_argument('--key-file', type=Path)
    args = parser.parse_args()
    if args.action == 'prepare':
        result = prepare(args.directory, args.manifest, user_request=args.user_request)
    else:
        if not args.live or not args.key_file:
            parser.error('Explicit live flag and private key file required')
        os.environ['OPENROUTER_API_KEY'] = args.key_file.read_text().strip()
        result = run(args.directory, args.manifest)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
