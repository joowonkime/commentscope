"""Verify completed checkpoints before dispatch checks; misses use original guards.

This supplemental control keeps the complete original pipeline and all its
semantic binders. It never calls a checkpoint's provider on a local cache read.
"""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
for item in (ROOT, ROOT/'src'):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from tools import wide_mining_recovery as recovery
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.providers.checkpoint_calls import VERSION as CHECKPOINT_VERSION, PendingCallError
from commentscope.providers.generation_limits import allocate
from commentscope.storage import write_json_exclusive as write

VERSION = 'verified-wide-checkpoint-fast-read-20261111-v1'
TOOL = Path(__file__).resolve()
wide = recovery.wide
trial = recovery.trial
executor = recovery.executor


def completed_read(checkpoint, stage, request, *, provider=None):
    """Return only an exact completed successful record; never invoke base.call."""
    actual = allocate(request, checkpoint.runtime) if provider is None else deepcopy(request)
    identity = {'artifact_kind': CHECKPOINT_VERSION, 'plan_sha256': checkpoint.base.plan_sha,
                'stage': stage, 'request_sha256': digest(actual),
                'provider': getattr(type(checkpoint.base), 'provider_identity', 'local_llama') if provider is None
                else provider.__module__+':'+provider.__qualname__}
    key = digest(identity)
    intent = checkpoint.directory/(key+'.intent.json')
    done = checkpoint.directory/(key+'.result.json')
    if not done.exists():
        if intent.exists():
            raise PendingCallError('Pending original request cannot become a fresh paid call')
        return False, None
    saved = read_json(done)
    if (read_json(intent) != identity or set(saved) != {'identity', 'result', 'result_sha256'}
            or saved['identity'] != identity or saved['result_sha256'] != digest(saved['result'])):
        raise ValueError('Completed checkpoint identity or result changed')
    result = saved['result']
    if result.get('errors') or not isinstance(result.get('usage'), dict) or result['usage'].get('cost') is None:
        return False, None  # Terminal failures still require the audited recovery control.
    return True, deepcopy(result)


class CachedReads:
    """Mixin: only locally completed reads bypass repeated paid-dispatch checks."""
    def _read_guard(self):
        self.dispatch.check()
        authority = self.plan['authorization']['authorization']
        start = datetime.fromisoformat(authority['started_at'])
        end = datetime.fromisoformat(authority['deadline'])
        if not start <= datetime.now(timezone.utc) < end:
            raise TimeoutError('Original phase window expired; no further checkpoint processing')

    def inspect(self, request):
        self._read_guard()
        return self.clients['generation'].measure(request)

    def _completed_call(self, stage, request):
        self._read_guard()
        mapped = trial.mapped_stage(stage)
        role = executor.remote.role(mapped)
        key = 'generation' if role == 'interaction' else role
        hit, result = completed_read(self.checkpoints[key], key+'-'+mapped, request)
        if not hit:
            return super().call(stage, request)
        self.storage.check()
        measured = self.clients[key].measure(request)
        if not measured['fits']:
            raise ValueError('Cached request exceeds original capacity')
        limits = getattr(self, 'cost_limits', None)
        if limits is not None:
            limits.admit(key+'-'+mapped, allocate(request, self.checkpoints[key].runtime))
        executor.remote.parsed_receipt(result, request, self.clients[key].deployment)
        count = (result.get('usage') or {}).get('prompt_tokens')
        if (type(count) is not int
                or not 0 <= count <= measured['input_upper_bound_tokens']+measured['provider_margin']):
            raise ValueError('Cached actual input exceeds its original bound')
        self.cached_reads += 1
        if self.cached_reads % 250 == 0:
            print('Verified original cached responses:', self.cached_reads, flush=True)
        return result

    def call(self, stage, request):
        if sha(self.fast_manifest_file) != self.fast_manifest_sha256 or sha(TOOL) != self.fast_launcher_sha256:
            raise ValueError('Supplemental cache control changed')
        return recovery.guarded_call(self.directory, self.plan, self.recovery_manifest_file,
            stage, request, lambda: self._completed_call(stage, request), _binding=self.recovery_binding)

    def decide(self, stage, payload):
        self._read_guard()
        if (not self.plan.get('membership_judge_protocol')
                or stage != 'membership-jev-'+trial.decisions.wire_sha256(payload, trial.decisions.DEPLOYMENT)[:20]):
            raise ValueError('Original typed membership route required')
        hit, result = completed_read(self.membership_checkpoint, stage, payload,
                                     provider=self.membership_client.generate)
        if not hit:
            return super().decide(stage, payload)
        if not trial.jev_membership.measure(payload)['fits']:
            raise ValueError('Cached typed request exceeds capacity')
        limits = getattr(self, 'cost_limits', None)
        if limits is not None:
            limits.admit(stage, payload)
        self.storage.check()
        trial.decisions.answers(payload, result, trial.decisions.DEPLOYMENT)
        self.cached_reads += 1
        if self.cached_reads % 250 == 0:
            print('Verified original cached responses:', self.cached_reads, flush=True)
        return result


def prepare(directory, manifest_file, recovery_manifest, *, user_request):
    directory, manifest_file, recovery_manifest = [Path(p).resolve() for p in
                                                  (directory, manifest_file, recovery_manifest)]
    executor.private(manifest_file)
    if (manifest_file.exists() or not user_request.strip()
            or not manifest_file.is_relative_to(directory/'recoveries')):
        raise ValueError('Fresh explicit supplemental cache manifest required')
    with executor.experiment_lock(directory):
        plan = wide.validate(directory)
        recovery.validate(directory, recovery_manifest, plan)
        archive = manifest_file.parent/'launcher.py'
        archive.parent.mkdir(parents=True, exist_ok=True)
        with archive.open('xb') as stream:
            stream.write(TOOL.read_bytes())
        body = {'version': VERSION, 'plan_sha256': sha(directory/'plan.json'), 'run_directory': str(directory),
                'recovery_manifest': str(recovery_manifest), 'recovery_sha256': sha(recovery_manifest),
                'launcher_sha256': sha(TOOL), 'launcher_archive': str(archive),
                'user_request': user_request, 'created_at': datetime.now(timezone.utc).isoformat(),
                'provider_retries': 0, 'formal_admission_eligible': False}
        write(manifest_file, {**body, 'integrity_sha256': digest(body)})
        validate(directory, manifest_file, plan)
        return {'manifest': str(manifest_file), 'new_paid_calls': 0}


def validate(directory, manifest_file, plan):
    directory, manifest_file = Path(directory).resolve(), Path(manifest_file).resolve()
    value = read_json(manifest_file)
    body = {k: v for k, v in value.items() if k != 'integrity_sha256'}
    if (not manifest_file.is_relative_to(directory/'recoveries')
            or value.get('version') != VERSION or value['integrity_sha256'] != digest(body)
            or value.get('plan_sha256') != sha(directory/'plan.json')
            or value.get('run_directory') != str(directory) or value.get('provider_retries') != 0
            or value.get('formal_admission_eligible') is not False or not value.get('user_request', '').strip()
            or value.get('launcher_sha256') != sha(TOOL) or sha(value['launcher_archive']) != sha(TOOL)
            or sha(value['recovery_manifest']) != value['recovery_sha256']):
        raise ValueError('Supplemental cache control changed')
    recovery.validate(directory, value['recovery_manifest'], plan)
    return value


def run(directory, manifest_file):
    directory, manifest_file = Path(directory).resolve(), Path(manifest_file).resolve()
    plan = wide.validate(directory)
    manifest = validate(directory, manifest_file, plan)
    original_manifest = Path(manifest['recovery_manifest'])
    original_binding = recovery.dispatch_binding(directory, original_manifest, plan)
    sessions = []
    class Session(CachedReads, wide.Session):
        def __init__(self, *args):
            super().__init__(*args)
            self.fast_manifest_file = manifest_file
            self.fast_manifest_sha256 = sha(manifest_file)
            self.fast_launcher_sha256 = sha(TOOL)
            self.recovery_manifest_file = original_manifest
            self.recovery_binding = original_binding
            self.cached_reads = 0
            sessions.append(self)
    done = trial.run(directory, _validate=wide.validate, _kind=wide.VERSION, _session=Session)
    binding = {'version': VERSION+'-completion', 'completed_sha256': sha(directory/'completed.json'),
               'manifest_sha256': sha(manifest_file), 'parent_recovery_sha256': manifest['recovery_sha256'],
               'cached_reads': sum(s.cached_reads for s in sessions), 'provider_retries': 0,
               'formal_admission_eligible': False}
    path = manifest_file.parent/'completed-binding.json'
    if path.exists():
        existing = read_json(path)
        if not sessions:
            binding['cached_reads'] = existing.get('cached_reads')
        if existing != binding or type(binding['cached_reads']) is not int or binding['cached_reads'] < 0:
            raise ValueError('Cached recovery completion binding changed')
    else:
        write(path, binding)
    return done


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    command = sub.add_parser('prepare')
    command.add_argument('directory', type=Path)
    command.add_argument('manifest', type=Path)
    command.add_argument('--recovery-manifest', type=Path, required=True)
    command.add_argument('--user-request', required=True)
    command = sub.add_parser('run')
    command.add_argument('directory', type=Path)
    command.add_argument('manifest', type=Path)
    command.add_argument('--live', action='store_true')
    command.add_argument('--key-file', type=Path)
    args = parser.parse_args()
    if args.action == 'prepare':
        result = prepare(args.directory, args.manifest, args.recovery_manifest, user_request=args.user_request)
    else:
        if not args.live or not args.key_file:
            parser.error('Explicit live flag and private key file required')
        os.environ['OPENROUTER_API_KEY'] = args.key_file.read_text().strip()
        result = run(args.directory, args.manifest)
    import json
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
