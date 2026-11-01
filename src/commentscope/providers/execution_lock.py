"""Cross-platform, process-owned execution lock; file existence is not liveness."""
from contextlib import contextmanager
import os
try:
    import fcntl
except ImportError:
    fcntl = None
    import msvcrt


@contextmanager
def experiment_lock(directory):
    # Existence is not liveness. The OS advisory lock, not this empty file, owns
    # a running attempt; opening a stale file after a crash is safe.
    with (directory/'execution.lock').open('a+b') as stream:
        if fcntl is None and os.fstat(stream.fileno()).st_size == 0:
            stream.write(b'\0'); stream.flush()
        stream.seek(0)
        try:
            if fcntl is not None:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            else:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            import errno
            if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK): raise
            raise RuntimeError('This experiment already has a live executor') from None
        try: yield
        finally:
            if fcntl is not None:
                fcntl.flock(stream, fcntl.LOCK_UN)
            else:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
