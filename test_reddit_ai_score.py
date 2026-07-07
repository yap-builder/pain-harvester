"""Tests for the pure core of reddit_ai_score (no claude calls)."""
import unittest

import fetch_pain
import reddit_ai_score as r


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
        # title = headline + '\n\n' + body; the proof quote must come from the BODY (gate P0#3)
        self.cands = [
            {"title": "I keep losing customers\n\nonboarding is broken and users churn before activating.", "url": "u0", "score": 5},
            {"title": "Anyone else struggle here?\n\nwe copy numbers between spreadsheets every single day.", "url": "u1", "score": 4},
            {"title": "Just launched my new app, check it out!", "url": "u2", "score": 3},
        ]

    def test_keeps_only_validated_pains_and_attaches_source_url(self):
        verdicts = [
            {"id": 0, "keep": True, "ai_score": 5, "reason": "real churn pain", "evidence_quote": "onboarding is broken"},
            {"id": 1, "keep": True, "ai_score": 3, "reason": "mild", "evidence_quote": "copy numbers between spreadsheets"},
            {"id": 2, "keep": False, "ai_score": 1, "reason": "promo", "evidence_quote": ""},
        ]
        kept, counts = r.merge_verdicts(self.cands, verdicts)
        self.assertEqual(len(kept), 2)
        self.assertEqual(kept[0]["url"], "u0")        # url from the source, not from the model
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


class TestBodyQuoteGate(unittest.TestCase):
    FULL = "How do I sell my niche software\n\nI keep losing deals because buyers do not trust a one-man shop."

    def _verdict(self, quote):
        return [{"id": 0, "keep": True, "ai_score": 4, "reason": "x", "evidence_quote": quote}]

    def test_quote_equal_to_headline_rejected(self):
        kept, counts = r.merge_verdicts([{"title": self.FULL}], self._verdict("How do I sell my niche software"))
        self.assertEqual(kept, [])
        self.assertEqual(counts["dropped_title_echo"], 1)

    def test_quote_substring_of_headline_rejected(self):
        kept, counts = r.merge_verdicts([{"title": self.FULL}], self._verdict("sell my niche software"))
        self.assertEqual(kept, [])
        self.assertEqual(counts["dropped_title_echo"], 1)

    def test_quote_from_body_kept(self):
        kept, counts = r.merge_verdicts([{"title": self.FULL}], self._verdict("losing deals because buyers do not trust"))
        self.assertEqual(len(kept), 1)

    def test_headline_only_post_cannot_pass(self):
        kept, counts = r.merge_verdicts([{"title": "Ask HN: Why is hiring broken?"}],
                                        self._verdict("Why is hiring broken?"))
        self.assertEqual(kept, [])


class TestSplitHeadlineBody(unittest.TestCase):
    def test_splits_on_first_blank_line(self):
        self.assertEqual(r.split_headline_body("Head\n\nBody one\n\nBody two"), ("Head", "Body one\n\nBody two"))

    def test_no_body_returns_empty(self):
        self.assertEqual(r.split_headline_body("Only headline"), ("Only headline", ""))


class TestLooksPromo(unittest.TestCase):
    def test_show_hn_is_promo(self):
        self.assertTrue(r.looks_promo("Show HN: my new invoicing tool"))

    def test_i_built_is_promo(self):
        self.assertTrue(r.looks_promo("I built a smart shopping list \U0001F6D2"))

    def test_roast_my_is_promo(self):
        self.assertTrue(r.looks_promo("Roast my landing page please"))

    def test_launched_is_promo(self):
        self.assertTrue(r.looks_promo("Just launched our beta today"))

    def test_pain_question_is_not_promo(self):
        self.assertFalse(r.looks_promo("How do I stop losing deals as a one-man shop?"))

    def test_empty_is_not_promo(self):
        self.assertFalse(r.looks_promo(""))


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


class TestBuildPrompt(unittest.TestCase):
    def test_numbers_each_post_and_includes_its_text(self):
        batch = [
            {"title": "onboarding is broken and I am drowning", "url": "u0"},
            {"title": "manual data entry every day kills me", "url": "u1"},
        ]
        p = r.build_prompt(batch)
        self.assertIn("POST 0", p)
        self.assertIn("POST 1", p)
        self.assertIn("onboarding is broken", p)
        self.assertIn("manual data entry", p)
        # requires a verbatim quote + strict JSON
        self.assertIn("evidence_quote", p)

    def test_caps_long_post_text(self):
        batch = [{"title": "x" * 5000, "url": "u0"}]
        p = r.build_prompt(batch)
        self.assertLess(len(p), 4000)  # a long post is trimmed in the prompt


class TestScoreBatch(unittest.TestCase):
    def test_calls_runner_with_prompt_and_parses_result(self):
        seen = {}

        def fake_runner(prompt, model):
            seen["prompt"] = prompt
            seen["model"] = model
            return '[{"id":0,"keep":true,"ai_score":4,"reason":"r","evidence_quote":"q"}]'

        batch = [{"title": "some pain here", "url": "u0"}]
        out = r.score_batch(batch, runner=fake_runner, model="claude-haiku-4-5")
        self.assertEqual(out[0]["ai_score"], 4)
        self.assertIn("POST 0", seen["prompt"])
        self.assertEqual(seen["model"], "claude-haiku-4-5")


class TestRender(unittest.TestCase):
    def test_includes_quote_url_score_and_escapes_html(self):
        items = [{
            "url": "https://reddit.com/x",
            "ai_score": 5,
            "ai_reason": "real churn",
            "evidence_quote": 'I said <b>"stop"</b> & it broke',
            "sources": ["SaaS"],
        }]
        out = r.render(items, "t")
        self.assertIn("https://reddit.com/x", out)
        self.assertIn("&lt;b&gt;", out)               # escaped
        self.assertNotIn('<b>"stop"', out)            # no raw html from the data
        self.assertIn("real churn", out)

    def test_orders_higher_ai_score_first(self):
        items = [
            {"url": "u_low", "ai_score": 2, "ai_reason": "", "evidence_quote": "low pain", "sources": []},
            {"url": "u_high", "ai_score": 5, "ai_reason": "", "evidence_quote": "high pain", "sources": []},
        ]
        out = r.render(items, "t")
        self.assertLess(out.index("u_high"), out.index("u_low"))


class TestRunLog(unittest.TestCase):
    def test_new_run_is_running_with_fields(self):
        rec = r.new_run("r1", "manual", "abc", "2026-06-25T10:00")
        self.assertEqual(rec["status"], "running")
        self.assertEqual(rec["trigger"], "manual")
        self.assertEqual(rec["source_hash"], "abc")
        self.assertEqual(rec["started_at"], "2026-06-25T10:00")

    def test_finish_run_updates_matching(self):
        runs = [r.new_run("r1", "manual", "abc", "t0")]
        r.finish_run(runs, "r1", "done", "t1", counts={"kept": 3})
        self.assertEqual(runs[0]["status"], "done")
        self.assertEqual(runs[0]["finished_at"], "t1")
        self.assertEqual(runs[0]["counts"]["kept"], 3)

    def test_trim_runs_keeps_last_n(self):
        runs = [{"id": str(i)} for i in range(25)]
        out = r.trim_runs(runs, 20)
        self.assertEqual(len(out), 20)
        self.assertEqual(out[0]["id"], "5")


class TestIfChanged(unittest.TestCase):
    def test_should_run_true_when_hash_differs(self):
        self.assertTrue(r.should_run("a", "b"))

    def test_should_run_false_when_same(self):
        self.assertFalse(r.should_run("a", "a"))

    def test_last_run_hash_from_completed(self):
        runs = [r.new_run("r1", "cron", "h1", "t0")]
        r.finish_run(runs, "r1", "done", "t1", counts={})
        self.assertEqual(r.last_run_hash(runs), "h1")

    def test_last_run_hash_empty_when_none_completed(self):
        runs = [r.new_run("r1", "cron", "h1", "t0")]  # still running
        self.assertEqual(r.last_run_hash(runs), "")

    def test_source_hash_of_file(self):
        import os
        import tempfile
        fd, p = tempfile.mkstemp()
        os.write(fd, b"hello")
        os.close(fd)
        try:
            self.assertEqual(len(r.source_hash(p)), 64)
        finally:
            os.remove(p)

    def test_source_hash_missing_file_empty(self):
        self.assertEqual(r.source_hash("/no/such/file/xyz"), "")


class TestCardsHtml(unittest.TestCase):
    def test_card_leads_with_pain_then_proof_quote(self):
        items = [{"url": "u", "ai_score": 5, "ai_reason": "cannot identify ICP",
                  "evidence_quote": "our onboarding is broken", "sources": ["SaaS"]}]
        h = r.cards_html(items)
        self.assertIn("cannot identify ICP", h)            # the pain
        self.assertIn("onboarding", h)                     # the proof
        self.assertLess(h.index("cannot identify ICP"), h.index("onboarding"))  # pain before proof


class TestViewPage(unittest.TestCase):
    def test_has_run_link_source_link_and_pain(self):
        items = [{"url": "u", "ai_score": 5, "ai_reason": "pain X",
                  "evidence_quote": "quote Y here", "sources": []}]
        page = r.view_page(items, {"updated": "now", "n": 1, "running": False, "runs": []})
        self.assertIn('href="/run"', page)
        self.assertIn("reddit-pain.html", page)            # link to the source
        self.assertIn("pain X", page)

    def test_running_state_has_meta_refresh(self):
        page = r.view_page([], {"updated": "now", "n": 0, "running": True, "runs": []})
        self.assertIn("http-equiv", page.lower())          # meta refresh, no JS
        self.assertIn("in progress", page)

    def test_includes_hn_se_digest_link_when_present(self):
        page = r.view_page([], {"updated": "now", "n": 0, "running": False, "runs": [],
                                "digest": "2026-06-23-pain-core20.html"})
        self.assertIn('href="2026-06-23-pain-core20.html"', page)
        self.assertIn("HN+SE", page)

    def test_no_digest_link_when_absent(self):
        page = r.view_page([], {"updated": "now", "n": 0, "running": False, "runs": []})
        self.assertNotIn("HN+SE", page)


class TestParseHnse(unittest.TestCase):
    MD = (
        "# pain digest 2026-06-23\n\n"
        "## [HN] Manual data entry is killing my team\n"
        "> We spend hours every day copying numbers between spreadsheets.\n"
        "> Nobody wants to do it and errors creep in.\n"
        "— score 1280 · 2026-06-20 · matched `data entry` · @alice\n"
        "https://news.ycombinator.com/item?id=111\n\n"
        "## [SE/stackoverflow] How to stop losing customers at onboarding\n"
        "> Our onboarding flow is broken and users churn before activating.\n"
        "— matched `losing customers` · @bob\n"
        "https://stackoverflow.com/q/222\n"
    )

    def test_packs_title_and_quote_into_title_field(self):
        items = r.parse_hnse(self.MD)
        self.assertEqual(len(items), 2)
        self.assertIn("Manual data entry", items[0]["title"])
        self.assertIn("copying numbers between spreadsheets", items[0]["title"])  # quote made it in

    def test_score_parsed_from_meta(self):
        self.assertEqual(r.parse_hnse(self.MD)[0]["score"], 1280)

    def test_missing_score_defaults_zero(self):
        self.assertEqual(r.parse_hnse(self.MD)[1]["score"], 0)

    def test_origin_and_sources_tagged(self):
        items = r.parse_hnse(self.MD)
        self.assertEqual(items[0]["origin"], "hn")
        self.assertEqual(items[0]["sources"], ["HN"])
        self.assertEqual(items[1]["origin"], "se")
        self.assertEqual(items[1]["sources"], ["SE/stackoverflow"])

    def test_bucket_is_cand_for_selection(self):
        self.assertTrue(all(it["bucket"] == "cand" for it in r.parse_hnse(self.MD)))

    def test_url_carried_from_source(self):
        self.assertEqual(r.parse_hnse(self.MD)[0]["url"], "https://news.ycombinator.com/item?id=111")

    def test_quote_validates_against_packed_title(self):
        # gate: a verbatim piece of quote is present in the title field validated by merge_verdicts
        items = r.parse_hnse(self.MD)
        self.assertTrue(r.quote_in_source("onboarding flow is broken", items[1]["title"]))


class TestSelectHnse(unittest.TestCase):
    ITEMS = [
        {"origin": "hn", "bucket": "cand", "score": 300, "title": "Ask HN pain"},
        {"origin": "se", "bucket": "cand", "score": 9000, "title": "SO trivia"},
        {"origin": "hn", "bucket": "cand", "score": 100, "title": "another HN pain"},
    ]

    def test_hn_only_drops_se_by_default(self):
        out = r.select_hnse(self.ITEMS, top=10)
        self.assertEqual([x["origin"] for x in out], ["hn", "hn"])  # SE dropped

    def test_include_se_keeps_both(self):
        out = r.select_hnse(self.ITEMS, top=10, include_se=True)
        self.assertEqual(len(out), 3)
        self.assertEqual(out[0]["origin"], "se")  # SE score 9000 rises to the top in the shared ranking

    def test_top_caps_hn(self):
        self.assertEqual(len(r.select_hnse(self.ITEMS, top=1)), 1)


class TestSourceLabel(unittest.TestCase):
    def test_reddit_default_red_tag_with_r_prefix(self):
        self.assertEqual(r.source_label({"sources": ["SaaS", "startups"]}), "🔴 r/SaaS, r/startups")

    def test_hn_orange_tag_with_site(self):
        self.assertEqual(r.source_label({"origin": "hn", "sources": ["HN"]}), "🟠 HN")

    def test_se_orange_tag_with_site(self):
        self.assertEqual(r.source_label({"origin": "se", "sources": ["SE/stackoverflow"]}),
                         "🟠 SE/stackoverflow")

    def test_empty_sources_tag_only(self):
        self.assertEqual(r.source_label({"origin": "hn", "sources": []}), "🟠")


class TestCardsHtmlSourceTag(unittest.TestCase):
    def test_hn_card_shows_orange_tag_and_site_not_r_prefix(self):
        items = [{"url": "u", "ai_score": 4, "ai_reason": "pain",
                  "evidence_quote": "manual data entry", "sources": ["HN"], "origin": "hn"}]
        h = r.cards_html(items)
        self.assertIn("🟠", h)
        self.assertNotIn("r/HN", h)

    def test_reddit_card_shows_red_tag(self):
        items = [{"url": "u", "ai_score": 4, "ai_reason": "pain",
                  "evidence_quote": "x", "sources": ["SaaS"]}]
        h = r.cards_html(items)
        self.assertIn("🔴", h)
        self.assertIn("r/SaaS", h)


class TestSourcesHash(unittest.TestCase):
    def _tmp(self, content):
        import os
        import tempfile
        fd, p = tempfile.mkstemp()
        os.write(fd, content)
        os.close(fd)
        self.addCleanup(lambda: os.path.exists(p) and os.remove(p))
        return p

    def test_combined_hash_is_64_hex(self):
        a, b = self._tmp(b"aaa"), self._tmp(b"bbb")
        self.assertEqual(len(r.sources_hash([a, b])), 64)

    def test_changes_when_any_file_changes(self):
        a, b = self._tmp(b"aaa"), self._tmp(b"bbb")
        h1 = r.sources_hash([a, b])
        open(b, "wb").write(b"CHANGED")
        self.assertNotEqual(h1, r.sources_hash([a, b]))

    def test_same_when_unchanged(self):
        a, b = self._tmp(b"aaa"), self._tmp(b"bbb")
        self.assertEqual(r.sources_hash([a, b]), r.sources_hash([a, b]))

    def test_missing_file_does_not_raise(self):
        a = self._tmp(b"aaa")
        self.assertEqual(len(r.sources_hash([a, "/no/such/file/xyz"])), 64)

    def test_order_distinguishes_sources(self):
        a, b = self._tmp(b"aaa"), self._tmp(b"bbb")
        self.assertNotEqual(r.sources_hash([a, b]), r.sources_hash([b, a]))


class TestHnItemUrl(unittest.TestCase):
    def test_comment_links_to_story_with_anchor(self):
        hit = {"objectID": "46365561", "story_id": 46355165, "comment_text": "some pain"}
        self.assertEqual(fetch_pain.hn_item_url(hit),
                         "https://news.ycombinator.com/item?id=46355165#46365561")

    def test_story_links_plain(self):
        hit = {"objectID": "40714641", "story_id": 40714641, "story_text": "Ask HN body"}
        self.assertEqual(fetch_pain.hn_item_url(hit),
                         "https://news.ycombinator.com/item?id=40714641")

    def test_comment_without_story_id_falls_back(self):
        hit = {"objectID": "123", "comment_text": "x"}
        self.assertEqual(fetch_pain.hn_item_url(hit),
                         "https://news.ycombinator.com/item?id=123")


if __name__ == "__main__":
    unittest.main()
