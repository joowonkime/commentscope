"""Local snapshot validation/normalization commands. No model or network calls."""

import argparse
import json
import sys
import uuid
from dataclasses import asdict
from datetime import datetime, timezone

from commentscope import __version__
from commentscope.errors import PipelineError
from commentscope.ingestion import load_snapshot, normalize_snapshot
from commentscope.ingestion.normalize import NORMALIZATION_VERSION
from commentscope.storage import write_json_exclusive


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="commentscope", description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "normalize"):
        command = commands.add_parser(name)
        command.add_argument("snapshot", help="prepared UTF-8 snapshot JSON file")
        if name == "normalize":
            command.add_argument("--output", required=True, help="new JSON output path (never overwritten)")
    args = parser.parse_args(argv)
    try:
        loaded = load_snapshot(args.snapshot)
        snapshot = loaded.snapshot
        result = {
            "status": "valid", "snapshot_id": snapshot.snapshot_id,
            "source_kind": snapshot.source_kind, "snapshot_sha256": loaded.sha256,
            "counts": snapshot.counts(),
        }
        if args.command == "normalize":
            normalized = normalize_snapshot(snapshot)
            aliases = sum(c.duplicate_of is not None for c in normalized)
            result["counts"].update({
                "canonical_comment_count": len(normalized) - aliases,
                "duplicate_alias_count": aliases,
                "empty_analysis_count": sum(not c.text_analysis for c in normalized),
            })
            artifact = {
                "schema_version": snapshot.schema_version,
                "artifact_kind": "snapshot_normalization",
                "run_id": str(uuid.uuid4()), "snapshot_id": snapshot.snapshot_id,
                "snapshot_sha256": loaded.sha256, "pipeline_version": __version__,
                "normalization_version": NORMALIZATION_VERSION,
                "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "counts": result["counts"], "snapshot": snapshot.to_dict(),
                "normalized_comments": [asdict(c) for c in normalized],
            }
            write_json_exclusive(args.output, artifact)
            result.update(status="normalized", run_id=artifact["run_id"], output=args.output)
        print(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2))
        return 0
    except PipelineError as exc:
        print(json.dumps({"error": exc.to_dict()}, ensure_ascii=False), file=sys.stderr)
        return 1 if exc.code in {"INPUT_READ_ERROR", "OUTPUT_EXISTS", "OUTPUT_WRITE_ERROR"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
