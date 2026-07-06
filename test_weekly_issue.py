"""Тесты чистой логики собирателя (без claude, без файлов)."""
import re
import unittest

import weekly_issue as w

P = [
    {"ai_reason": "PDF parsing for RAG is painful", "evidence_quote": "spent 3 weeks fighting PDF tables",
     "url": "https://a", "ai_score": 5, "score": 8, "sources": ["SaaS"]},
    {"ai_reason": "founders cannot sell", "evidence_quote": "I keep losing deals",
     "url": "https://b", "ai_score": 4, "score": 9, "sources": ["startups"]},
    {"ai_reason": "founders cannot sell 2", "evidence_quote": "no one replies to my cold emails",
     "url": "https://c", "ai_score": 3, "score": 2, "sources": ["SaaS"]},
]


class TestIdentityThemes(unittest.TestCase):
    def test_one_theme_per_pain_with_reason_label(self):
        ts = w.identity_themes(P)
        self.assertEqual(len(ts), 3)
        self.assertEqual(ts[0], {"label": "PDF parsing for RAG is painful", "members": [0]})


class TestRepresentative(unittest.TestCase):
    def test_picks_max_ai_score_then_heuristic(self):
        theme = {"label": "sales", "members": [1, 2]}
        self.assertEqual(w.representative(theme, P)["url"], "https://b")


class TestIssueData(unittest.TestCase):
    def test_sorts_by_count_then_score_and_caps_top_n(self):
        themes = [{"label": "solo", "members": [0]},
                  {"label": "sales", "members": [1, 2]}]
        issue = w.issue_data(P, themes, top_n=1, week="2026-W27")
        self.assertEqual(len(issue["themes"]), 1)
        self.assertEqual(issue["themes"][0]["label"], "sales")   # 2 человека > 1
        self.assertEqual(issue["themes"][0]["count"], 2)
        self.assertEqual(issue["themes"][0]["quote"], "I keep losing deals")

    def test_quote_and_url_come_from_source_item(self):
        issue = w.issue_data(P, w.identity_themes(P), top_n=5, week="2026-W27")
        urls = {t["url"] for t in issue["themes"]}
        self.assertTrue(urls <= {"https://a", "https://b", "https://c"})


class TestRenderTxt(unittest.TestCase):
    def test_no_first_person_and_has_quotes_urls(self):
        issue = w.issue_data(P, w.identity_themes(P), top_n=5, week="2026-W27")
        txt = w.render_txt(issue)
        self.assertIn("I keep losing deals", txt)      # цитата (её «I» — автора боли, ок)
        self.assertIn("https://b", txt)
        # рамка: сервис, не первое лицо. Гейт по ГРАНИЦЕ слова, а не подстроке:
        # наивное "я " ловит ложные срабатывания внутри слов ("каждаЯ ") — это не первое лицо.
        self.assertIsNone(re.search(r"(?i)\b(я|мой|моя|мою)\b", txt.replace("\n", " ")),
                          "рамка выпуска не должна содержать первого лица")


class TestValidateThemes(unittest.TestCase):
    def test_dedups_ids_across_themes_and_drops_out_of_range(self):
        raw = [{"theme": "sales", "members": [1, 2, 2, 99]},
               {"theme": "dup", "members": [1]},
               "мусор"]
        themes, uncovered = w.validate_themes(raw, n=3)
        self.assertEqual(themes, [{"label": "sales", "members": [1, 2]}])
        self.assertEqual(uncovered, [0])

    def test_empty_or_unlabeled_groups_dropped(self):
        themes, uncovered = w.validate_themes([{"theme": "", "members": [0]}], n=1)
        self.assertEqual(themes, [])
        self.assertEqual(uncovered, [0])


class TestBuildThemesFallback(unittest.TestCase):
    def test_runner_failure_falls_back_to_identity(self):
        def boom(prompt, model=None):
            raise RuntimeError("claude недоступен")
        ts = w.build_themes(P, use_ai=True, runner=boom)
        self.assertEqual(ts, w.identity_themes(P))


class TestRenderHtml(unittest.TestCase):
    def _issue(self, quote):
        themes = [{"label": "sales pain", "count": 2, "quote": quote,
                   "url": "https://x", "source": "🔴 r/SaaS", "ai_score": 5}]
        return {"week": "2026-W27", "pains_total": 2, "themes": themes}

    def test_quote_present_and_escaped_no_js(self):
        page = w.render_html(self._issue('he said <b>"ship"</b> & it broke'))
        self.assertIn("&lt;b&gt;", page)                 # опасный html экранирован
        self.assertNotIn('<b>"ship"', page)              # нет сырого html из данных
        self.assertNotIn("<script", page.lower())        # без JS (правило телефона)
        self.assertNotIn("http-equiv", page.lower())     # без meta-refresh
        self.assertIn("https://x", page)                 # ссылка из источника
        self.assertIn("2&times; reported", page)         # счётчик многолюдной темы (html-сущность)
        self.assertIn("<details", page)                  # легенда — нативный details (без JS)
        self.assertIn("how to read this page", page)   # свёрнутая легенда на месте

    def test_source_emoji_stripped(self):
        page = w.render_html(self._issue("real pain here"))
        self.assertIn("r/SaaS", page)
        self.assertNotIn("🔴", page)                      # цветной кружок снят в N2-скине


if __name__ == "__main__":
    unittest.main()
