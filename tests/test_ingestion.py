import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, asdict
from pathlib import Path
from unittest.mock import patch

from commentscope.contracts import parse_snapshot
from commentscope.errors import PipelineError
from commentscope.ingestion import load_snapshot, normalize_snapshot
from commentscope.storage import write_json_exclusive

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/synthetic-snapshot.json"


def fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


class SnapshotTests(unittest.TestCase):
    def test_s01_roundtrip_multilingual_provenance_and_immutable_contract(self):
        raw = fixture()
        snapshot = parse_snapshot(raw)
        self.assertEqual(json.loads(json.dumps(snapshot.to_dict())), raw)
        with self.assertRaises(FrozenInstanceError):
            snapshot.comments[0].text_original = "changed"
        raw["comments"][0]["text_original"] = "outside mutation"
        self.assertNotEqual(snapshot.comments[0].text_original, "outside mutation")
        self.assertEqual({c.language.tag for c in snapshot.comments}, {"en", "ko"})

    def test_s02_duplicate_ids_are_rejected(self):
        raw = fixture()
        raw["comments"].append(copy.deepcopy(raw["comments"][0]))
        with self.assertRaises(PipelineError) as caught:
            parse_snapshot(raw)
        self.assertEqual(caught.exception.code, "INVALID_SNAPSHOT")

    def test_s03_s05_invalid_parent_relations(self):
        cases = [("present", "absent"), ("present", "c1"), ("root", "c2"),
                 ("missing", "c2"), ("missing", None), ("present", None)]
        for status, parent in cases:
            with self.subTest(status=status, parent=parent):
                raw = fixture()
                raw["comments"][0].update(parent_status=status, parent_id=parent)
                with self.assertRaises(PipelineError) as caught:
                    parse_snapshot(raw)
                self.assertEqual(caught.exception.code, "INVALID_REFERENCE")

    def test_s03_multinode_cycle(self):
        raw = fixture()
        raw["comments"][0].update(parent_status="present", parent_id="c2")
        raw["comments"][1].update(parent_status="present", parent_id="c1")
        with self.assertRaises(PipelineError) as caught:
            parse_snapshot(raw)
        self.assertEqual(caught.exception.code, "INVALID_REFERENCE")

    def test_s04_explicit_missing_parent_is_retained(self):
        snapshot = parse_snapshot(fixture())
        orphan = next(c for c in snapshot.comments if c.comment_id == "c8")
        self.assertEqual((orphan.parent_status, orphan.parent_id), ("missing", "outside-snapshot"))
        self.assertNotIn(orphan.parent_id, {c.comment_id for c in snapshot.comments})

    def test_s09_invalid_fields_types_enums_and_numbers(self):
        cases = [
            (("extra",), "unknown"), (("schema_version",), "0.2"),
            (("source_kind",), "live"), (("snapshot_id",), "  "),
            (("comments",), {}), (("video", "extra"), 1),
            (("comments", 0, "likes"), True), (("comments", 0, "likes"), -1),
            (("comments", 0, "likes"), 1.5), (("comments", 0, "text_original"), None),
            (("comments", 0, "text_original"), "\ud800"),
            (("comments", 0, "parent_status"), "other"),
            (("comments", 0, "replies_status"), "other"),
            (("comments", 0, "sampling_origins", 0, "rank"), 0),
            (("comments", 0, "sampling_origins", 0, "rank"), -1),
            (("comments", 0, "sampling_origins", 0, "rank"), True),
            (("comments", 0, "language", "confidence"), float("nan")),
            (("comments", 0, "language", "confidence"), float("inf")),
            (("comments", 0, "language", "confidence"), True),
            (("comments", 0, "language", "confidence"), 1.1),
            (("comments", 0, "language", "confidence"), 10**400),
            (("comments", 0, "language", "tag"), "not a tag"),
            (("comments", 0, "language", "method"), "guessed"),
            (("sampling", "target_count"), False),
            (("usage", "basis"), ""), (("captured_at",), None),
        ]
        for path, value in cases:
            with self.subTest(path=path, value=repr(value)[:40]):
                raw = fixture()
                target = raw
                for part in path[:-1]:
                    target = target[part]
                target[path[-1]] = value
                with self.assertRaises(PipelineError) as caught:
                    parse_snapshot(raw)
                self.assertEqual(caught.exception.code, "INVALID_SNAPSHOT")

    def test_s09_missing_required_field_and_nonobject_root(self):
        raw = fixture()
        del raw["comments"][0]["likes"]
        for value in [raw, [], None, True, "snapshot"]:
            with self.subTest(value=type(value).__name__):
                with self.assertRaises(PipelineError):
                    parse_snapshot(value)

    def test_s09_timestamp_validation_and_utc_output(self):
        for invalid in ["2026-10-09", "2026-10-09T01:00:00", "2026-02-30T00:00:00Z",
                        "2026-10-09T25:00:00Z", "2026-10-09T01:00:00+01:99"]:
            with self.subTest(invalid=invalid):
                raw = fixture()
                raw["captured_at"] = invalid
                with self.assertRaises(PipelineError):
                    parse_snapshot(raw)
        raw = fixture()
        raw["captured_at"] = "2026-10-09T09:30:00+09:00"
        raw["comments"][0]["published_at"] = "2026-10-08T23:00:00-01:00"
        parsed = parse_snapshot(raw)
        self.assertEqual(parsed.captured_at, "2026-10-09T00:30:00Z")
        self.assertEqual(parsed.comments[0].published_at, "2026-10-09T00:00:00Z")

    def test_s09_url_validation_and_source_kind(self):
        for url in [None, "http://example.com/watch", "javascript:alert(1)",
                    "https:///watch", "https://user:secret@example.com/watch",
                    "https://example.com:wrong/", "https://exam ple.com", "https://example.com\\bad"]:
            with self.subTest(url=url):
                raw = fixture()
                raw["source_kind"] = "research"
                raw["video"]["url"] = url
                with self.assertRaises(PipelineError):
                    parse_snapshot(raw)
        raw = fixture()
        raw["source_kind"] = "research"
        raw["video"]["url"] = "https://example.com/video"
        self.assertEqual(parse_snapshot(raw).video.url, raw["video"]["url"])
        raw["source_kind"] = "synthetic"
        with self.assertRaises(PipelineError):
            parse_snapshot(raw)
        raw["video"]["url"] = None
        raw["comments"][0]["source_url"] = "https://example.com/comment"
        with self.assertRaises(PipelineError):
            parse_snapshot(raw)

    def test_s10_counts_do_not_use_target_or_conflate_replies(self):
        raw = fixture()
        raw["sampling"]["target_count"] = 1000
        counts = parse_snapshot(raw).counts()
        self.assertEqual(counts, {"source_count": 11, "top_level_count": 9,
                                 "reply_count": 2, "missing_parent_count": 1})

    def test_empty_snapshot_is_valid_and_explicit(self):
        raw = fixture()
        raw["comments"] = []
        snapshot = parse_snapshot(raw)
        self.assertEqual(snapshot.counts()["source_count"], 0)
        self.assertEqual(normalize_snapshot(snapshot), ())

    def test_long_reply_chain_does_not_recurse(self):
        raw = fixture()
        template = raw["comments"][0]
        raw["comments"] = []
        for i in range(2000):
            c = copy.deepcopy(template)
            c.update(comment_id=f"chain-{i}", parent_id=f"chain-{i-1}" if i else None,
                     parent_status="present" if i else "root")
            raw["comments"].append(c)
        self.assertEqual(parse_snapshot(raw).counts()["reply_count"], 1999)
        raw["comments"][0].update(parent_id="chain-1999", parent_status="present")
        with self.assertRaises(PipelineError):
            parse_snapshot(raw)


class NormalizationTests(unittest.TestCase):
    def test_s06_originals_case_urls_and_nfc(self):
        raw = fixture()
        original = "  Cafe\u0301\t🙂\n안녕  HTTPS://Example.com/A?x=1&y=2  "
        raw["comments"][0]["text_original"] = original
        snapshot = parse_snapshot(raw)
        normalized = normalize_snapshot(snapshot)
        self.assertEqual(normalized[0].text_analysis, "Café 🙂 안녕 HTTPS://Example.com/A?x=1&y=2")
        self.assertEqual(snapshot.comments[0].text_original, original)

    def test_s07_duplicate_aliases_preserve_originals_and_context(self):
        snapshot = parse_snapshot(fixture())
        records = {c.comment_id: c for c in normalize_snapshot(snapshot)}
        self.assertEqual(records["c9"].duplicate_of, "c3")
        self.assertIsNone(records["c3"].duplicate_of)
        self.assertEqual(len(records), len(snapshot.comments))
        raw = fixture()
        raw["comments"][0].update(text_original="Exactly.", parent_id="c2", parent_status="present")
        raw["comments"][1].update(text_original="Exactly.")
        records = {c.comment_id: c for c in normalize_snapshot(parse_snapshot(raw))}
        for cid in ["c1", "c2", "c7"]:
            self.assertIsNone(records[cid].duplicate_of)

    def test_s08_canonical_selection_is_order_independent(self):
        raw = fixture()
        expected = {c.comment_id: asdict(c) for c in normalize_snapshot(parse_snapshot(raw))}
        raw["comments"].reverse()
        actual = {c.comment_id: asdict(c) for c in normalize_snapshot(parse_snapshot(raw))}
        self.assertEqual(actual, expected)

    def test_s11_empty_analysis_texts_are_not_deduplicated(self):
        raw = fixture()
        for c, text in zip(raw["comments"], ["", " \n\t", "\u2003"]):
            c["text_original"] = text
        for c in normalize_snapshot(parse_snapshot(raw))[:3]:
            self.assertEqual(c.text_analysis, "")
            self.assertIsNone(c.duplicate_of)

    def test_parent_id_is_not_rewritten_to_duplicate_representative(self):
        raw = fixture()
        raw["comments"][6]["parent_id"] = "c9"
        snapshot = parse_snapshot(raw)
        normalize_snapshot(snapshot)
        self.assertEqual(snapshot.comments[6].parent_id, "c9")

    def test_design_example_and_test_fixture_remain_in_sync(self):
        design = ROOT / "docs/examples/synthetic-snapshot.json"
        self.assertEqual(fixture(), json.loads(design.read_text(encoding="utf-8")))
        trace = json.loads((ROOT / "docs/examples/synthetic-factory-trace.json").read_text(encoding="utf-8"))
        actual = [asdict(c) for c in normalize_snapshot(parse_snapshot(fixture()))]
        self.assertEqual(actual, trace["normalized_comments"])


class FileAndCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def cli(self, *args):
        return subprocess.run([sys.executable, "-m", "commentscope", *map(str, args)],
                              cwd=self.directory, capture_output=True, text=True, encoding="utf-8")

    def test_input_hash_uses_exact_bytes(self):
        loaded = load_snapshot(FIXTURE)
        self.assertEqual(loaded.sha256, hashlib.sha256(FIXTURE.read_bytes()).hexdigest())
        alternate = self.directory / "same-content.json"
        alternate.write_bytes(FIXTURE.read_bytes() + b"\n")
        changed = load_snapshot(alternate)
        self.assertEqual(loaded.snapshot, changed.snapshot)
        self.assertNotEqual(loaded.sha256, changed.sha256)

    def test_s09_rejects_invalid_json_duplicates_encoding_and_infinities(self):
        for raw in [b'{"a":1,"a":2}', b'{"a":{"b":1,"b":2}}', b'NaN', b'Infinity',
                    b'-Infinity', b'1e999', b'{broken', b'\xff', b'"\\ud800"']:
            with self.subTest(raw=raw):
                path = self.directory / "invalid.json"
                path.write_bytes(raw)
                with self.assertRaises(PipelineError) as caught:
                    load_snapshot(path)
                self.assertEqual(caught.exception.code, "INVALID_SNAPSHOT")

    def test_validate_module_from_outside_repository(self):
        result = self.cli("validate", FIXTURE)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        output = json.loads(result.stdout)
        self.assertEqual(output["status"], "valid")
        self.assertEqual(output["counts"]["source_count"], 11)
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_normalize_cli_preserves_source_and_records_provenance(self):
        source = self.directory / "input.json"
        original = FIXTURE.read_bytes()
        source.write_bytes(original)
        destination = self.directory / "nested" / "normalized.json"
        result = self.cli("normalize", source, "--output", destination)
        self.assertEqual(result.returncode, 0, result.stderr)
        artifact = json.loads(destination.read_text(encoding="utf-8"))
        self.assertEqual(artifact["artifact_kind"], "snapshot_normalization")
        self.assertEqual(artifact["snapshot"], fixture())
        self.assertEqual(artifact["snapshot_sha256"], hashlib.sha256(original).hexdigest())
        self.assertEqual(artifact["counts"]["canonical_comment_count"], 10)
        self.assertEqual(artifact["counts"]["duplicate_alias_count"], 1)
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual(json.loads(result.stdout)["run_id"], artifact["run_id"])

    def test_s12_existing_output_and_input_path_are_never_overwritten(self):
        source = self.directory / "input.json"
        source.write_bytes(FIXTURE.read_bytes())
        existing = self.directory / "existing.json"
        existing.write_bytes(b"keep this")
        for destination in [source, existing]:
            with self.subTest(destination=destination):
                before = destination.read_bytes()
                result = self.cli("normalize", source, "--output", destination)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(json.loads(result.stderr)["error"]["code"], "OUTPUT_EXISTS")
                self.assertEqual(result.stdout, "")
                self.assertEqual(destination.read_bytes(), before)
        self.assertFalse(list(self.directory.glob(".commentscope-*.tmp")))

    def test_s12_symlink_destination_is_not_followed_or_replaced(self):
        target = self.directory / "target.json"
        target.write_text("keep", encoding="utf-8")
        link = self.directory / "link.json"
        try:
            link.symlink_to(target)
        except OSError:
            self.skipTest("creating symlinks requires privileges on this platform")
        with self.assertRaises(PipelineError) as caught:
            write_json_exclusive(link, {"replacement": True})
        self.assertEqual(caught.exception.code, "OUTPUT_EXISTS")
        self.assertTrue(link.is_symlink())
        self.assertEqual(target.read_text(encoding="utf-8"), "keep")

    def test_s12_publish_failure_leaves_no_partial_output(self):
        output = self.directory / "result.json"
        with patch("commentscope.storage.os.link", side_effect=PermissionError("denied")):
            with self.assertRaises(PipelineError) as caught:
                write_json_exclusive(output, {"value": "🙂"})
        self.assertEqual(caught.exception.code, "OUTPUT_WRITE_ERROR")
        self.assertFalse(output.exists())
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_s12_write_failure_leaves_no_partial_output(self):
        output = self.directory / "result.json"
        with patch("commentscope.storage.os.fsync", side_effect=OSError("disk failure")):
            with self.assertRaises(PipelineError):
                write_json_exclusive(output, {"value": "🙂"})
        self.assertFalse(output.exists())
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_s12_competing_writers_publish_one_complete_file(self):
        output = self.directory / "result.json"

        def write(value):
            try:
                write_json_exclusive(output, {"writer": value})
                return "ok"
            except PipelineError as exc:
                return exc.code

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(write, [1, 2]))
        self.assertCountEqual(results, ["ok", "OUTPUT_EXISTS"])
        self.assertIn(json.loads(output.read_text())["writer"], [1, 2])

    def test_cli_invalid_input_and_missing_input_are_structured_errors(self):
        invalid = self.directory / "invalid.json"
        invalid.write_text("{}", encoding="utf-8")
        for path, code, status in [(invalid, "INVALID_SNAPSHOT", 2),
                                   (self.directory / "absent.json", "INPUT_READ_ERROR", 1)]:
            with self.subTest(code=code):
                result = self.cli("validate", path)
                self.assertEqual(result.returncode, status)
                self.assertEqual(result.stdout, "")
                error = json.loads(result.stderr)["error"]
                self.assertEqual(error["code"], code)
                self.assertEqual(set(error), {"code", "stage", "entity_id", "message", "retryable"})
                self.assertNotIn("Traceback", result.stderr)

    def test_invalid_input_does_not_create_normalization_output(self):
        invalid = self.directory / "invalid.json"
        invalid.write_text("{}", encoding="utf-8")
        output = self.directory / "nested" / "output.json"
        result = self.cli("normalize", invalid, "--output", output)
        self.assertEqual(result.returncode, 2)
        self.assertFalse(output.parent.exists())


if __name__ == "__main__":
    unittest.main()
