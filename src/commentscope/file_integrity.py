"""Exact SHA256 with bounded reads and best-effort large-file cache release.

Cache advice is not deletion and does not guarantee host memory reclamation in
WSL. Hash verification remains mandatory when advice is unavailable or fails.
"""
import hashlib
import os
from pathlib import Path

CHUNK_BYTES = 1024 * 1024
CACHE_RELEASE_BYTES = 8 * CHUNK_BYTES
LARGE_FILE_BYTES = 64 * CHUNK_BYTES


def file_sha256(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        advice = getattr(os, 'posix_fadvise', None)
        mode = getattr(os, 'POSIX_FADV_DONTNEED', None)
        release = (callable(advice) and mode is not None
                   and os.fstat(stream.fileno()).st_size >= LARGE_FILE_BYTES)
        offset = pending = 0
        while block := stream.read(CHUNK_BYTES):
            result.update(block)
            pending += len(block)
            if pending >= CACHE_RELEASE_BYTES:
                if release:
                    try:
                        advice(stream.fileno(), offset, pending, mode)
                    except OSError:
                        release = False
                offset += pending
                pending = 0
        if release and pending:
            try:
                advice(stream.fileno(), offset, pending, mode)
            except OSError:
                pass
    return result.hexdigest()
