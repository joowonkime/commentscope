"""Plan-bound resource observation for the current owned executor only."""
from contextlib import contextmanager
from datetime import datetime, timezone
import math
import os
from pathlib import Path
import signal
import threading

from commentscope.storage import write_json_exclusive as write

POLICY = {'version': 'host-headroom-0.1', 'minimum_available_mb': 1536,
          'minimum_commit_headroom_bytes': 1024**3, 'minimum_disk_free_bytes': 6*1024**3,
          'poll_seconds': 10, 'maximum_observation_failures': 2}


def validate(policy):
    if policy != POLICY:
        raise ValueError('Unknown host resource policy; freeze changes explicitly')


def reasons(observation, policy):
    validate(policy)
    for field in ('available_mb', 'committed_bytes', 'commit_limit', 'disk_free_bytes'):
        value = observation[field]
        if type(value) not in (float, int) or not math.isfinite(value) or value < 0:
            raise ValueError('Invalid host resource observation')
    if observation['commit_limit'] <= 0:
        raise ValueError('Invalid host commit limit')
    result = []
    if observation['available_mb'] < policy['minimum_available_mb']:
        result.append('low_host_available_memory')
    if observation['commit_limit']-observation['committed_bytes'] < policy['minimum_commit_headroom_bytes']:
        result.append('low_host_commit_headroom')
    if observation['disk_free_bytes'] < policy['minimum_disk_free_bytes']:
        result.append('low_host_disk')
    return result


class Observer:
    def __init__(self, directory, policy, observe):
        validate(policy)
        self.directory, self.policy, self.observe = Path(directory), dict(policy), observe
        self.sequence = 0; self.failures = 0

    def sample(self):
        self.sequence += 1
        row = {'at': datetime.now(timezone.utc).isoformat(), 'executor_pid': os.getpid()}
        try:
            value = self.observe()
            row['stop_reasons'] = reasons(value, self.policy)
            row['observation'] = value
            self.failures = 0
        except Exception as exc:
            self.failures += 1
            row['observation_error'] = type(exc).__name__
            row['stop_reasons'] = ['resource_observation_unavailable'] if self.failures >= self.policy['maximum_observation_failures'] else []
        write(self.directory/f'{self.sequence:06}.json', row)
        return row


@contextmanager
def watch(directory, policy, observe, *, interrupt=None):
    """A daemon observer interrupts this executor, never an unrelated PID.

    The caller owns its model-server cleanup in an outer finally block. No
    monitoring failure grants permission to run indefinitely unobserved.
    """
    observer = Observer(directory, policy, observe)
    stop = threading.Event()
    interrupt = interrupt or (lambda: os.kill(os.getpid(), signal.SIGINT))
    write(Path(directory)/'started.json', {'executor_pid': os.getpid(), 'policy': policy})
    first = observer.sample()
    if first.get('observation_error') or first['stop_reasons']:
        write(Path(directory)/'stop-requested.json', first)
        raise RuntimeError('Host resources unavailable at deployment startup')

    def monitor():
        while not stop.wait(policy['poll_seconds']):
            try:
                row = observer.sample()
                if not row['stop_reasons']:
                    continue
                write(Path(directory)/'stop-requested.json', row)
            except Exception:
                # Disk/write failure must also stop this owned executor even if
                # an observation cannot be durably published.
                pass
            if not stop.is_set():
                interrupt()
            return

    thread = threading.Thread(target=monitor, name='commentscope-host-resources', daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        # The Windows reader has a 20-second subprocess timeout.
        thread.join(25)
        write(Path(directory)/'finished.json', {'observer_stopped': not thread.is_alive(),
              'samples': observer.sequence, 'at': datetime.now(timezone.utc).isoformat()})
