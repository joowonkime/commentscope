"""Prepared snapshot tools and explicit, bounded official YouTube collection."""

import argparse
import getpass
import json
import os
import sys
import uuid
from dataclasses import asdict
from datetime import datetime, timezone

from commentscope import __version__
from commentscope.errors import PipelineError
from commentscope.ingestion import load_snapshot, normalize_snapshot
from commentscope.ingestion.normalize import NORMALIZATION_VERSION
from commentscope.ingestion.youtube import CollectionConfig, collect_youtube, video_id_from_input
from commentscope.ingestion.youtube_client import YouTubeClient, api_error
from commentscope.storage import write_json_exclusive


def _collect(args) -> int:
    video_id = video_id_from_input(args.video)
    config = CollectionConfig(args.max_comments, args.top_level_limit, args.replies_per_thread,
                              args.retention_days, args.primary_language, args.usage_basis)
    config.validate()
    if os.path.lexists(args.output):
        raise PipelineError("OUTPUT_EXISTS", "storage", None, "output exists; choose a new output path")
    key = getpass.getpass("YouTube API key (hidden): ") if args.prompt_key else os.environ.get("YOUTUBE_API_KEY", "")
    client = YouTubeClient(key, max_requests=args.max_requests)
    collected = collect_youtube(video_id, client, config)
    write_json_exclusive(args.output, collected.snapshot.to_dict())
    print(json.dumps({
        "status": "collected", "snapshot_id": collected.snapshot.snapshot_id,
        "output": args.output, "counts": collected.snapshot.counts(),
        "partial_reply_threads": sum(c.parent_status == "root" and c.replies_status == "partial"
                                     for c in collected.snapshot.comments),
        "expires_at": collected.snapshot.usage.expires_at, "collection": collected.report,
    }, ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="commentscope", description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "normalize"):
        command = commands.add_parser(name)
        command.add_argument("snapshot", help="prepared UTF-8 snapshot JSON file")
        if name == "normalize":
            command.add_argument("--output", required=True, help="new JSON output path (never overwritten)")
    collect = commands.add_parser("collect-youtube", help="collect one video's public comments via the official API")
    collect.add_argument("video", help="YouTube video URL or video ID")
    collect.add_argument("--output", required=True, help="new snapshot path, preferably under data/")
    collect.add_argument("--prompt-key", action="store_true", help="ask for a hidden API key instead of YOUTUBE_API_KEY")
    collect.add_argument("--max-comments", type=int, default=1000, help="total comments including replies (default: 1000)")
    collect.add_argument("--top-level-limit", type=int, default=400, help="ranking entries before ID deduplication (default: 400)")
    collect.add_argument("--replies-per-thread", type=int, default=100)
    collect.add_argument("--max-requests", type=int, default=100, help="includes video metadata and retry attempts")
    collect.add_argument("--retention-days", type=int, default=30, help="expiry metadata from 1 to 30 days; no auto-deletion")
    collect.add_argument("--primary-language", default="und", help="corpus description only; individual languages remain unknown")
    collect.add_argument("--usage-basis", default=CollectionConfig.usage_basis)
    args = parser.parse_args(argv)
    try:
        if args.command == "collect-youtube":
            return _collect(args)
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
        return 1 if exc.code.startswith("YOUTUBE_") or exc.code in {
            "INPUT_READ_ERROR", "OUTPUT_EXISTS", "OUTPUT_WRITE_ERROR", "COMMENTS_DISABLED", "INVALID_API_RESPONSE"
        } else 2
    except (EOFError, KeyboardInterrupt):
        error = api_error("COLLECTION_CANCELLED", "collection cancelled; no completed snapshot was published")
        print(json.dumps({"error": error.to_dict()}), file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
