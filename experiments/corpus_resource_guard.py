"""External WSL host-resource guard for one already-running corpus attempt.

Observes host memory and C: free space; only signals the pinned executor through
a Linux pidfd. Does not change the frozen runtime, restart jobs, alter the OS,
or modify inference records. Every observation and action stays private.
"""
import argparse
from datetime import datetime, timezone
import fcntl
import json
import math
import os
from pathlib import Path
import select
import shutil
import signal
import subprocess
import time

from commentscope.factory.claim_clusters import read_json, sha
from commentscope.storage import write_json_exclusive as write

PRIVATE_ROOT = Path('runs')
LIMITS = {'minimum_available_mb': 1024, 'maximum_commit_percent': 92,
          'minimum_disk_free_bytes': 4*1024**3, 'poll_seconds': 30,
          'maximum_observation_failures': 2}


def host_observation():
    result = subprocess.run([
        'powershell.exe', '-NoProfile', '-Command',
        'Get-CimInstance Win32_PerfFormattedData_PerfOS_Memory | '
        'Select-Object AvailableMBytes,CommittedBytes,CommitLimit,PercentCommittedBytesInUse | '
        'ConvertTo-Json -Compress'], capture_output=True, text=True, timeout=20, check=True)
    memory = json.loads(result.stdout)
    return {'available_mb': memory['AvailableMBytes'],
            'commit_percent': memory['PercentCommittedBytesInUse'],
            'committed_bytes': memory['CommittedBytes'], 'commit_limit': memory['CommitLimit'],
            'disk_free_bytes': shutil.disk_usage('/mnt/c').free}


def unsafe_reasons(observation):
    for field in ('available_mb', 'commit_percent', 'disk_free_bytes'):
        value = observation[field]
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError('Invalid host observation')
    reasons = []
    if observation['available_mb'] < LIMITS['minimum_available_mb']:
        reasons.append('low_host_available_memory')
    if observation['commit_percent'] >= LIMITS['maximum_commit_percent']:
        reasons.append('high_host_commit')
    if observation['disk_free_bytes'] < LIMITS['minimum_disk_free_bytes']:
        reasons.append('low_host_disk')
    return reasons


def guard(directory, attempt):
    directory = Path(directory)
    if not directory.resolve().is_relative_to(PRIVATE_ROOT.resolve()) or not 1 <= attempt <= 9999:
        raise ValueError('Private run and exact attempt required')
    started_path = directory/'attempts'/f'{attempt:04}.started.json'
    started = read_json(started_path)
    if started['plan_sha256'] != sha(directory/'plan.json'):
        raise ValueError('Attempt plan changed')
    pid = started['pid']
    if type(pid) is not int or pid <= 0:
        raise ValueError('Invalid executor PID')
    # pidfd prevents a PID recycled later from becoming the signal target.
    pidfd = os.pidfd_open(pid)
    try:
        args = Path(f'/proc/{pid}/cmdline').read_bytes().decode().split('\0')
        expected = ['-m', 'experiments.framed_corpus_pipeline', 'run', str(directory)]
        if args[1:5] != expected or Path(f'/proc/{pid}/cwd').resolve() != Path.cwd().resolve():
            raise ValueError('Not the expected owned corpus executor')
        outputs = directory/'resource-guard'/f'{attempt:04}'
        outputs.mkdir(parents=True, exist_ok=True)
        with (outputs/'execution.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if (outputs/'started.json').exists():
                raise ValueError('Guard already started; inspect its process before replacement')
            write(outputs/'started.json', {
                'pid': os.getpid(), 'target_pid': pid, 'attempt': attempt,
                'started_at': datetime.now(timezone.utc).isoformat(), 'limits': LIMITS,
                'plan_sha256': started['plan_sha256'], 'code_sha256': sha(__file__),
                'authority': 'resource protection of this owned executor only'})
            failures = 0; sequence = 0
            while True:
                if select.select([pidfd], [], [], 0)[0]:
                    write(outputs/'finished.json', {'target_terminal': True, 'signal_sent': False})
                    return
                sequence += 1
                row = {'observed_at': datetime.now(timezone.utc).isoformat(), 'target_pid': pid}
                try:
                    observation = host_observation()
                    reasons = unsafe_reasons(observation)
                    row['observation'] = observation
                    failures = 0
                except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError) as exc:
                    failures += 1
                    row['observation_error'] = type(exc).__name__
                    reasons = ['resource_observation_unavailable'] if failures >= LIMITS['maximum_observation_failures'] else []
                row['stop_reasons'] = reasons
                write(outputs/f'{sequence:06}.json', row)
                if reasons:
                    # Persist intent before signaling; never signal by a bare PID.
                    write(outputs/'stop-requested.json', row)
                    try:
                        signal.pidfd_send_signal(pidfd, signal.SIGINT)
                        signaled = True
                    except ProcessLookupError:
                        signaled = False
                    write(outputs/'signal-sent.json', {'target_pid': pid, 'signal_sent': signaled,
                          'signal': 'SIGINT', 'observed_at': datetime.now(timezone.utc).isoformat()})
                    print({'resource_guard_stopped_executor': signaled, 'reasons': reasons}, flush=True)
                    return
                time.sleep(LIMITS['poll_seconds'])
    finally:
        os.close(pidfd)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--attempt', type=int, required=True)
    args = parser.parse_args()
    guard(args.directory, args.attempt)
