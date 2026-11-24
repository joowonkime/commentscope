import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from filter_comments import (batches, filter_source, load_source, local_decision,
                             make_items, save_results, validate_decisions)
from llm_client import read_settings


def comment(cid, text, parent=""):
    return {"comment_id": cid, "text": text, "parent_id": parent,
            "author": "원작성자", "like_count": 10, "is_reply": bool(parent)}


def decision(cid, status="keep", confidence=0.95):
    category = {"keep": "opinion", "exclude": "pure_joke", "review": "uncertain"}[status]
    return {"comment_id": cid, "status": status, "category": category,
            "confidence": confidence, "reason": "테스트 분류 근거"}


class StubClient:
    def __init__(self, decisions):
        self.decisions = decisions
        self.calls = []

    def structured(self, system, payload, schema, name):
        self.calls.append(copy.deepcopy(payload))
        return {"data": {"decisions": [self.decisions[x["comment_id"]] for x in payload["comments"]]},
                "model": "test/model", "usage": {"prompt_tokens": 100}}


class FilterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.output = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def run_filter(self, source, client=None, **kwargs):
        return filter_source(source, client, self.output, topic="근무시간 단축", model="test/model", **kwargs)

    def test_rules_do_not_drop_short_sarcastic_or_unpopular_views(self):
        for text in ["주4일 반대", "10-5해줘", "ㅋㅋ 임금은 누가 줌?", "찬성", "동의합니다", "최저임금 폐지하자"]:
            with self.subTest(text=text):
                self.assertIsNone(local_decision(comment("x", text)))
        for text in ["", "  ", "ㅋㅋㅋㅋ", "ㅠㅠ", "😂😂", "!!!"]:
            with self.subTest(text=text):
                self.assertEqual(local_decision(comment("x", text))["status"], "exclude")

    def test_reply_has_parent_context_even_outside_preview(self):
        source = {"comments": [comment("r", "맞아요", "p"), comment("p", "임금 유지가 중요합니다")]}
        client = StubClient({"r": decision("r")})
        result = self.run_filter(source, client, max_comments=1)
        self.assertEqual(client.calls[0]["comments"][0]["parent_context"], "임금 유지가 중요합니다")
        self.assertEqual(result["meta"]["processed_count"], 1)
        self.assertTrue(result["meta"]["is_partial"])

    def test_missing_parent_is_explicit_and_author_not_sent(self):
        items = make_items([comment("r", "맞아요", "missing")], [])
        self.assertIsNone(items[0]["parent_context"])
        self.assertTrue(items[0]["is_reply"])
        self.assertNotIn("author", items[0])
        self.assertNotIn("like_count", items[0])

    def test_each_source_row_preserved_once_with_metadata(self):
        source = {"meta": {"title": "영상", "video_id": "123"}, "comments": [
            comment("a", "ㅋㅋ 임금은?"), comment("b", "ㅋㅋ"),
            comment("c", "농담뿐"), comment("d", "모호한 반응")]}
        original = copy.deepcopy(source)
        client = StubClient({"a": decision("a"), "c": decision("c", "exclude"),
                             "d": decision("d", "review")})
        result = self.run_filter(source, client)
        save_results(self.output, result)
        self.assertEqual(source, original)
        self.assertEqual(result["meta"]["counts"], {"keep": 1, "exclude": 2, "review": 1})
        rows = []
        for file in ["filtered.json", "review.json", "excluded.json"]:
            rows.extend(json.loads((self.output / file).read_text())["comments"])
        self.assertCountEqual(rows, original["comments"])
        self.assertEqual(result["meta"]["source_meta"], source["meta"])

    def test_low_confidence_exclusion_is_reviewed(self):
        source = {"comments": [comment("a", "애매한 비꼼")]}
        client = StubClient({"a": decision("a", "exclude", 0.6)})
        result = self.run_filter(source, client)
        d = result["decisions"][0]["classification"]
        self.assertEqual(d["status"], "review")
        self.assertEqual(d["proposed_status"], "exclude")

    def test_exclusion_audit_can_rescue_a_viewpoint_and_preserves_first_pass(self):
        class ReconsideringClient(StubClient):
            def structured(self, system, payload, schema, name):
                if name == "exclusion_review":
                    self.decisions["a"] = decision("a", "keep")
                return super().structured(system, payload, schema, name)
        source = {"comments": [comment("a", "농담처럼 표현된 의견")]}
        client = ReconsideringClient({"a": decision("a", "exclude")})
        result = self.run_filter(source, client)
        d = result["decisions"][0]["classification"]
        self.assertEqual(d["status"], "keep")
        self.assertEqual(d["first_pass"]["status"], "exclude")
        self.assertEqual(result["meta"]["exclusion_review_count"], 1)
        self.assertEqual(len(client.calls), 2)
        # Re-running uses both cached passes, including the original exclusion.
        result = self.run_filter(source, client)
        self.assertEqual(result["meta"]["cached_batches"], 2)
        self.assertEqual(len(client.calls), 2)

    def test_offline_does_not_fake_semantic_classifications(self):
        source = {"comments": [comment("a", "주4일 찬성"), comment("b", "ㅋㅋ")]}
        result = self.run_filter(source, offline=True)
        self.assertEqual(result["meta"]["counts"], {"keep": 0, "exclude": 1, "review": 1})
        self.assertEqual(result["meta"]["new_model_batches"], 0)

    def test_resume_uses_validated_cache_and_topic_change_invalidates_it(self):
        source = {"comments": [comment("a", "주4일 찬성")]}
        client = StubClient({"a": decision("a")})
        self.run_filter(source, client)
        result = self.run_filter(source, client)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(result["meta"]["cached_batches"], 1)
        # Threshold is applied again, without another paid request.
        result = self.run_filter(source, client, review_threshold=0.99)
        self.assertEqual(result["meta"]["counts"]["review"], 1)
        self.assertEqual(len(client.calls), 1)
        filter_source(source, client, self.output, topic="다른 영상", model="test/model")
        self.assertEqual(len(client.calls), 2)

    def test_provider_and_reasoning_changes_do_not_reuse_other_results(self):
        source = {"comments": [comment("a", "주4일 찬성")]}
        client = StubClient({"a": decision("a")})
        client.provider = "openrouter"
        self.run_filter(source, client)
        client.provider = "openai"
        client.reasoning_effort = "medium"
        self.run_filter(source, client)
        client.reasoning_effort = "high"
        self.run_filter(source, client)
        self.assertEqual(len(client.calls), 3)

    def test_failure_can_resume_completed_batches(self):
        source = {"comments": [comment("a", "찬성"), comment("b", "반대")]}
        client = StubClient({"a": decision("a")})
        with self.assertRaises(KeyError):
            self.run_filter(source, client, batch_size=1)
        self.assertEqual(len(list((self.output / ".cache").glob("*.json"))), 1)
        client.decisions["b"] = decision("b")
        result = self.run_filter(source, client, batch_size=1)
        self.assertEqual(result["meta"]["cached_batches"], 1)
        self.assertEqual(result["meta"]["counts"]["keep"], 2)

    def test_incomplete_extra_duplicate_and_bad_confidence_rejected(self):
        good = decision("a")
        bad_lists = [[], [good, good], [decision("b")], [dict(good, confidence=True)],
                     [dict(good, confidence=float("nan"))], [dict(good, confidence=1.1)],
                     [dict(good, category="spam")], [dict(good, reason="")]]
        for ds in bad_lists:
            with self.subTest(ds=ds), self.assertRaises(ValueError):
                validate_decisions({"decisions": ds}, ["a"])

    def test_bad_response_never_becomes_cache(self):
        source = {"comments": [comment("a", "찬성")]}
        client = StubClient({"a": decision("wrong")})
        with self.assertRaises(ValueError):
            self.run_filter(source, client)
        self.assertFalse((self.output / ".cache").exists())

    def test_invalid_cache_is_refetched(self):
        source = {"comments": [comment("a", "찬성")]}
        client = StubClient({"a": decision("a")})
        self.run_filter(source, client)
        next((self.output / ".cache").glob("*.json")).write_text("invalid")
        result = self.run_filter(source, client)
        self.assertEqual(result["meta"]["new_model_batches"], 1)
        self.assertEqual(len(client.calls), 2)

    def test_oversized_comments_reviewed_without_truncation(self):
        source = {"comments": [comment("a", "장문" * 10000)]}
        result = self.run_filter(source)
        self.assertEqual(result["meta"]["counts"]["review"], 1)
        self.assertEqual(result["decisions"][0]["comment"]["text"], source["comments"][0]["text"])

    def test_duplicate_text_is_not_deduplicated(self):
        source = {"comments": [comment("a", "주4일 찬성"), comment("b", "주4일 찬성")]}
        client = StubClient({"a": decision("a"), "b": decision("b")})
        result = self.run_filter(source, client)
        self.assertEqual(result["meta"]["counts"]["keep"], 2)

    def test_concurrent_batches_preserve_source_order_and_all_decisions(self):
        source = {"comments": [comment(str(i), f"주4일 의견 {i}") for i in range(17)]}
        client = StubClient({str(i): decision(str(i)) for i in range(17)})
        result = self.run_filter(source, client, batch_size=3, workers=3)
        self.assertEqual([x["comment"] for x in result["decisions"]], source["comments"])
        self.assertEqual(result["meta"]["counts"], {"keep": 17, "exclude": 0, "review": 0})
        self.assertEqual(result["meta"]["new_model_batches"], 6)
        again = self.run_filter(source, client, batch_size=3, workers=3)
        self.assertEqual(again["meta"]["cached_batches"], 6)
        self.assertEqual(len(client.calls), 6)

    def test_model_aliases_restore_exact_long_source_ids(self):
        class AliasClient:
            use_local_comment_ids = True
            provider = "openai"
            def structured(self, system, payload, schema, name):
                ids=[x['comment_id'] for x in payload['comments']]
                self.asserted_ids=ids
                assert ids==schema['properties']['decisions']['items']['properties']['comment_id']['enum']
                return {'data':{'decisions':[decision(cid) for cid in reversed(ids)]},'model':'test/model','usage':{}}
        source={'comments':[comment('long-original-id.with-Case_-123','주4일 찬성'),comment('another-ID.with-a-dot','반대')]}
        client=AliasClient()
        result=self.run_filter(source,client)
        self.assertEqual(client.asserted_ids,['c001','c002'])
        self.assertEqual([x['classification']['comment_id'] for x in result['decisions']],
                         [x['comment_id'] for x in source['comments']])

    def test_invalid_source_ids_rejected(self):
        file = self.output / "source.json"
        for rows in [[comment("a", "x"), comment("a", "y")], [comment("", "x")]]:
            file.write_text(json.dumps({"comments": rows}))
            with self.assertRaises(ValueError):
                load_source(file)

    def test_empty_source_and_all_noise_need_no_model(self):
        for rows in [[], [comment("a", "ㅋㅋ")]]:
            result = self.run_filter({"comments": rows})
            self.assertEqual(result["meta"]["processed_count"], len(rows))
            self.assertEqual(result["meta"]["new_model_batches"], 0)

    def test_batches_obey_both_count_and_character_limits(self):
        items = [{"text": "가" * 30} for _ in range(6)]
        split = list(batches(items, 2, max_chars=100))
        self.assertEqual(sum(map(len, split)), 6)
        self.assertTrue(all(len(b) <= 2 and sum(len(json.dumps(i, ensure_ascii=False)) for i in b) <= 100
                            for b in split))

    def test_dotenv_values_literal_and_environment_wins(self):
        env = self.output / ".env"
        env.write_text('export OPENROUTER_API_KEY="fake#test" # comment\nOPENROUTER_MODEL=test/model\n')
        with patch.dict("os.environ", {"OPENROUTER_MODEL": "override/model"}):
            values = read_settings(env)
        self.assertEqual(values["OPENROUTER_API_KEY"], "fake#test")
        self.assertEqual(values["OPENROUTER_MODEL"], "override/model")


if __name__ == "__main__":
    unittest.main()
