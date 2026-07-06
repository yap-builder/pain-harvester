"""Unit tests for the verbatim-evidence gate core (no model call, pure functions)."""
import unittest

import gate as r


class TestNormalize(unittest.TestCase):
    def test_lowercases_and_collapses_whitespace(self):
        self.assertEqual(r.normalize("  Hello   World\n\tFoo "), "hello world foo")


class TestQuoteInSource(unittest.TestCase):
    SRC = "I keep losing customers because onboarding is broken."

    def test_verbatim_quote_found(self):
        self.assertTrue(r.quote_in_source("onboarding is broken", self.SRC))

    def test_whitespace_and_case_differences_still_match(self):
        src = "I  KEEP   losing\ncustomers because onboarding is broken."
        self.assertTrue(r.quote_in_source("Keep losing customers", src))

    def test_fabricated_quote_rejected(self):
        self.assertFalse(r.quote_in_source("our revenue dropped 40 percent", self.SRC))

    def test_empty_quote_rejected(self):
        self.assertFalse(r.quote_in_source("   ", "anything here"))


class TestParseBatch(unittest.TestCase):
    def test_parses_plain_json_array(self):
        raw = '[{"id":0,"keep":true,"ai_score":4,"reason":"x","evidence_quote":"y"}]'
        self.assertEqual(r.parse_batch(raw)[0]["id"], 0)

    def test_parses_json_inside_code_fence_and_prose(self):
        raw = ('Here you go:\n```json\n'
               '[{"id":1,"keep":false,"ai_score":1,"reason":"vague","evidence_quote":""}]\n'
               '```\nDone.')
        out = r.parse_batch(raw)
        self.assertEqual(len(out), 1)
        self.assertFalse(out[0]["keep"])

    def test_raises_on_no_json(self):
        with self.assertRaises(ValueError):
            r.parse_batch("sorry, I cannot help with that")


class TestMergeVerdicts(unittest.TestCase):
    def setUp(self):
        self.cands = [
            {"title": "I keep losing customers because onboarding is broken.", "url": "u0", "score": 5},
            {"title": "Anyone else hate manual data entry every single day?", "url": "u1", "score": 4},
            {"title": "Just launched my new app, check it out!", "url": "u2", "score": 3},
        ]

    def test_keeps_only_validated_pains_and_attaches_source_url(self):
        verdicts = [
            {"id": 0, "keep": True, "ai_score": 5, "reason": "real churn pain", "evidence_quote": "onboarding is broken"},
            {"id": 1, "keep": True, "ai_score": 3, "reason": "mild", "evidence_quote": "hate manual data entry"},
            {"id": 2, "keep": False, "ai_score": 1, "reason": "promo", "evidence_quote": ""},
        ]
        kept, counts = r.merge_verdicts(self.cands, verdicts)
        self.assertEqual(len(kept), 2)
        self.assertEqual(kept[0]["url"], "u0")        # url comes from the source, not the model
        self.assertEqual(kept[0]["ai_score"], 5)
        self.assertEqual(counts["kept"], 2)
        self.assertEqual(counts["dropped_ai_no"], 1)

    def test_drops_keep_true_with_fabricated_quote(self):
        verdicts = [
            {"id": 0, "keep": True, "ai_score": 5, "reason": "x", "evidence_quote": "we pay 500 a month"},
        ]
        kept, counts = r.merge_verdicts(self.cands, verdicts)
        self.assertEqual(kept, [])
        self.assertEqual(counts["dropped_no_quote"], 1)

    def test_ignores_out_of_range_id(self):
        verdicts = [{"id": 99, "keep": True, "ai_score": 5, "reason": "x", "evidence_quote": "onboarding is broken"}]
        kept, counts = r.merge_verdicts(self.cands, verdicts)
        self.assertEqual(kept, [])
        self.assertEqual(counts["malformed"], 1)


class TestSelectCandidates(unittest.TestCase):
    def test_filters_cand_sorts_by_score_desc_and_slices_top(self):
        items = [
            {"bucket": "cand", "score": 4, "title": "a"},
            {"bucket": "noise", "score": 9, "title": "b"},
            {"bucket": "cand", "score": 7, "title": "c"},
            {"bucket": "look", "score": 2, "title": "d"},
        ]
        out = r.select_candidates(items, top=1)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["title"], "c")

    def test_top_none_returns_all_cands(self):
        items = [{"bucket": "cand", "score": 4, "title": "a"}, {"bucket": "cand", "score": 7, "title": "c"}]
        self.assertEqual(len(r.select_candidates(items, top=None)), 2)


if __name__ == "__main__":
    unittest.main()
