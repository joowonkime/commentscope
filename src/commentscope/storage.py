"""Publish a complete JSON file atomically without replacing any existing path."""

import json
import os
import tempfile
from pathlib import Path

from commentscope.errors import PipelineError


def write_json_exclusive(path: str | Path, value: object) -> None:
    destination = Path(path)
    temporary = None
    try:
        encoded = (json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode("utf-8")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".commentscope-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        # Same-directory hard link is atomic and fails if the destination exists,
        # including symlinks and a file created by a concurrent writer.
        os.link(temporary, destination)
    except FileExistsError as exc:
        raise PipelineError("OUTPUT_EXISTS", "storage", None, "output exists; choose a new output path") from exc
    except (OSError, ValueError, TypeError) as exc:
        raise PipelineError("OUTPUT_WRITE_ERROR", "storage", None, "could not publish output; check path permissions and hard-link support") from exc
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                # Never remove the destination or an unrelated path on cleanup failure.
                pass
